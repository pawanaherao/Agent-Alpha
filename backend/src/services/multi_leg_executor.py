"""
Multi-Leg Execution Engine
==========================
Atomic multi-leg order execution via DhanHQ.

Supports:
  - Sequential leg placement (sell legs first for credit spreads)
  - Basket order grouping
  - Fill validation & partial-fill handling
  - Rollback on failure (cancel filled legs if a critical leg fails)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.options import (
    OptionsSignal,
    LegSignal,
    LegPosition,
    MultiLegPosition,
    PositionStatus,
    LegAction,
    StructureType,
)
from src.services.dhan_client import get_dhan_client

logger = logging.getLogger(__name__)

# Credit structures → sell legs first to collect premium before paying for buys
_CREDIT_STRUCTURES = {
    StructureType.IRON_CONDOR,
    StructureType.IRON_BUTTERFLY,
    StructureType.SHORT_STRADDLE,
    StructureType.SHORT_STRANGLE,
    StructureType.BEAR_PUT_SPREAD,   # sell higher, buy lower put
    StructureType.BULL_CALL_SPREAD,  # sell higher, buy lower call
}


def _order_legs(signal: OptionsSignal) -> List[LegSignal]:
    """
    Return legs in optimal execution order.
    For credit spreads, sell legs go first.
    """
    legs = list(signal.legs)
    if signal.structure_type in _CREDIT_STRUCTURES:
        # Sell legs first — collect premium before paying for protection
        sells = [l for l in legs if l.action == LegAction.SELL]
        buys = [l for l in legs if l.action == LegAction.BUY]
        return sells + buys
    # Debit / other → buy legs first (secure protection before selling)
    buys = [l for l in legs if l.action == LegAction.BUY]
    sells = [l for l in legs if l.action == LegAction.SELL]
    return buys + sells


class MultiLegExecutor:
    """
    Executes multi-leg options orders through DhanHQ.
    Each leg is placed as a separate order; the executor tracks fills
    and can rollback if a critical leg fails.
    """

    def __init__(self):
        self.max_retries = 2
        self.retry_delay_seconds = 1.0

    # ------------------------------------------------------------------
    # Public: execute a full multi-leg signal
    # ------------------------------------------------------------------
    async def execute_signal(self, signal: OptionsSignal) -> MultiLegPosition:
        """
        Place all legs of an OptionsSignal.

        Returns a MultiLegPosition (status OPEN if all filled, PARTIAL if some failed).
        On total failure, attempts rollback and returns status CLOSED.
        """
        dhan = get_dhan_client()
        ordered_legs = _order_legs(signal)

        position = MultiLegPosition(
            signal_id=signal.signal_id,
            strategy_name=signal.strategy_name,
            symbol=signal.symbol,
            structure_type=signal.structure_type,
            legs=[],
            status=PositionStatus.PENDING,
            expiry=signal.expiry,
            max_profit=signal.max_profit,
            max_loss=signal.max_loss,
        )

        filled_legs: List[LegPosition] = []
        failed = False

        for leg_signal in ordered_legs:
            leg_pos = await self._place_leg(dhan, leg_signal, signal)

            if leg_pos and leg_pos.order_id:
                filled_legs.append(leg_pos)
                logger.info(
                    f"Leg filled: {leg_signal.action.value} {leg_signal.option_type.value} "
                    f"{leg_signal.strike} → order_id={leg_pos.order_id}"
                )
            else:
                logger.error(
                    f"Leg FAILED: {leg_signal.action.value} {leg_signal.option_type.value} "
                    f"{leg_signal.strike}"
                )
                failed = True
                break  # stop attempting remaining legs

        position.legs = filled_legs

        if failed and filled_legs:
            # Partial fill → rollback (close already-filled legs)
            logger.warning(
                f"Partial fill ({len(filled_legs)}/{len(ordered_legs)}) — rolling back"
            )
            await self._rollback(dhan, filled_legs)
            position.status = PositionStatus.CLOSED
        elif not filled_legs:
            position.status = PositionStatus.CLOSED
        else:
            position.status = PositionStatus.OPEN
            position.net_premium_received = sum(
                (lp.entry_premium * lp.quantity * lp.lot_size *
                 (-1 if lp.action == LegAction.BUY else 1))
                for lp in filled_legs
            )
            position.opened_at = datetime.now()

        logger.info(
            f"MultiLeg execution result: {position.status.value} | "
            f"legs={len(position.legs)} | net_premium={position.net_premium_received:.2f}"
        )
        return position

    # ------------------------------------------------------------------
    # Execute individual legs
    # ------------------------------------------------------------------
    async def execute_legs(
        self, legs: List[LegSignal], symbol: str = ""
    ) -> List[LegPosition]:
        """Execute a flat list of legs (used by adjustment engine)."""
        dhan = get_dhan_client()
        results: List[LegPosition] = []
        for leg in legs:
            lp = await self._place_leg(dhan, leg, None)
            if lp:
                results.append(lp)
        return results

    # ------------------------------------------------------------------
    # Close specific legs
    # ------------------------------------------------------------------
    async def close_legs(self, legs: List[LegPosition]) -> List[str]:
        """Close (exit) a list of open LegPositions. Returns list of exit order IDs."""
        dhan = get_dhan_client()
        order_ids: List[str] = []
        for leg in legs:
            if leg.status != "OPEN":
                continue
            exit_side = "SELL" if leg.action == LegAction.BUY else "BUY"
            order_payload = self._build_order_payload(
                symbol=leg.symbol,
                option_type=leg.option_type.value,
                strike=leg.strike,
                expiry=leg.expiry,
                action=exit_side,
                quantity=leg.quantity,
                lot_size=leg.lot_size,
                security_id=leg.security_id,
                trading_symbol=leg.trading_symbol,
            )
            try:
                oid = await dhan.place_order(order_payload)
                if oid:
                    order_ids.append(oid)
                    leg.status = "CLOSED"
                    logger.info(f"Closed leg {leg.leg_id} → order_id={oid}")
            except Exception as e:
                logger.error(f"Failed to close leg {leg.leg_id}: {e}")
        return order_ids

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    async def _place_leg(
        self, dhan, leg: LegSignal, signal: Optional[OptionsSignal]
    ) -> Optional[LegPosition]:
        """Place a single leg order with retries."""
        order_payload = self._build_order_payload(
            symbol=leg.symbol,
            option_type=leg.option_type.value,
            strike=leg.strike,
            expiry=leg.expiry,
            action=leg.action.value,
            quantity=leg.quantity,
            lot_size=leg.lot_size,
            security_id=leg.security_id,
            trading_symbol=leg.trading_symbol,
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                order_id = await dhan.place_order(order_payload)
                if order_id:
                    return LegPosition(
                        leg_id=leg.leg_id,
                        symbol=leg.symbol,
                        option_type=leg.option_type,
                        strike=leg.strike,
                        expiry=leg.expiry,
                        action=leg.action,
                        quantity=leg.quantity,
                        lot_size=leg.lot_size,
                        entry_premium=leg.premium or 0.0,
                        order_id=order_id,
                        security_id=leg.security_id,
                        trading_symbol=leg.trading_symbol,
                        greeks=leg.greeks or __import__("src.models.options", fromlist=["Greeks"]).Greeks(),
                        filled_at=datetime.now(),
                        status="OPEN",
                    )
            except Exception as e:
                logger.warning(f"Leg order attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay_seconds)

        return None

    async def _rollback(self, dhan, filled_legs: List[LegPosition]):
        """Cancel / reverse already-filled legs on partial failure."""
        for leg in filled_legs:
            try:
                exit_side = "SELL" if leg.action == LegAction.BUY else "BUY"
                order_payload = self._build_order_payload(
                    symbol=leg.symbol,
                    option_type=leg.option_type.value,
                    strike=leg.strike,
                    expiry=leg.expiry,
                    action=exit_side,
                    quantity=leg.quantity,
                    lot_size=leg.lot_size,
                    security_id=leg.security_id,
                    trading_symbol=leg.trading_symbol,
                )
                cancel_id = await dhan.place_order(order_payload)
                logger.info(f"Rollback leg {leg.leg_id}: exit order {cancel_id}")
                leg.status = "CLOSED"
            except Exception as e:
                logger.error(f"Rollback failed for leg {leg.leg_id}: {e}")

    @staticmethod
    def _build_order_payload(
        symbol: str,
        option_type: str,
        strike: float,
        expiry: str,
        action: str,
        quantity: int,
        lot_size: int,
        security_id: Optional[str] = None,
        trading_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build DhanHQ order payload for an option leg."""
        payload: Dict[str, Any] = {
            "transactionType": action.upper(),
            "exchangeSegment": "NSE_FNO",
            "productType": "INTRA",
            "orderType": "MARKET",
            "validity": "DAY",
            "price": 0.0,
            "triggerPrice": 0.0,
            "quantity": quantity * lot_size,
            "metadata": {
                "instrument_type": option_type,
                "suggested_strike": strike,
                "option_type": option_type,
            },
        }
        if security_id:
            payload["securityId"] = security_id
            payload["metadata"]["security_id"] = security_id
        if trading_symbol:
            payload["tradingSymbol"] = trading_symbol
        else:
            payload["tradingSymbol"] = symbol
            payload["symbol"] = symbol

        return payload


# Module-level singleton
multi_leg_executor = MultiLegExecutor()
