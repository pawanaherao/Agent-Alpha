"""
Leg Monitor Service
===================
Continuous monitoring loop for open multi-leg option positions.

Checks each leg's:
  - P&L vs stop-loss / target thresholds
  - Greeks drift (delta breach, gamma risk)
  - Time decay (DTE-based auto-close)
  - Expiry auto-close

When thresholds are breached, triggers adjustment via the AdjustmentEngine.
Designed to be called from the 3-minute orchestration loop or a dedicated
sub-scheduler.
"""
from __future__ import annotations

import logging
from datetime import datetime, date, time
from typing import Any, Dict, List, Optional

from src.models.options import (
    AdjustmentRequest,
    AdjustmentType,
    Greeks,
    LegAction,
    LegPosition,
    MultiLegPosition,
    PositionStatus,
)
from src.services.options_position_manager import options_position_manager
from src.services.greeks import greeks_engine

logger = logging.getLogger(__name__)

# Default thresholds (can be overridden per-position via metadata)
DEFAULT_MAX_LOSS_PCT = 2.0        # max loss as % of margin → trigger adjustment
DEFAULT_DELTA_BREACH = 0.30       # if abs(portfolio delta) > this → hedge
DEFAULT_GAMMA_RISK = 0.05         # high gamma near ATM → warning
DEFAULT_DTE_AUTO_CLOSE = 0        # close on expiry day (0 DTE)
DEFAULT_PROFIT_TARGET_PCT = 50.0  # take profit at 50% of max profit
MARKET_CLOSE_TIME = time(15, 10)  # force-close intraday before this


class LegMonitor:
    """
    Monitors all open multi-leg positions and triggers adjustments
    when risk thresholds are breached.
    """

    def __init__(self):
        self._last_check: Optional[datetime] = None
        # Thresholds (sensible defaults, configurable via env or config)
        self.max_loss_pct = DEFAULT_MAX_LOSS_PCT
        self.delta_breach = DEFAULT_DELTA_BREACH
        self.gamma_risk = DEFAULT_GAMMA_RISK
        self.dte_auto_close = DEFAULT_DTE_AUTO_CLOSE
        self.profit_target_pct = DEFAULT_PROFIT_TARGET_PCT

    # ------------------------------------------------------------------
    # Main monitoring loop (called every 3 minutes from orchestrator)
    # ------------------------------------------------------------------
    async def check_all(self) -> List[AdjustmentRequest]:
        """
        Scan all open positions, refresh P&L / Greeks, and generate
        adjustment requests for any that breach thresholds.
        """
        adjustments: List[AdjustmentRequest] = []
        try:
            # 1. Refresh all positions (premiums + Greeks)
            await options_position_manager.refresh_all()

            open_positions = options_position_manager.get_open_positions()
            if not open_positions:
                return adjustments

            now = datetime.now()
            time_now = now.time()

            for pos in open_positions:
                pos_adjustments = self._evaluate_position(pos, time_now)
                adjustments.extend(pos_adjustments)

            self._last_check = now

            if adjustments:
                logger.info(f"Leg monitor: {len(adjustments)} adjustments triggered")

        except Exception as e:
            logger.error(f"Leg monitor check failed: {e}", exc_info=True)

        return adjustments

    # ------------------------------------------------------------------
    # Per-position evaluation
    # ------------------------------------------------------------------
    def _evaluate_position(
        self, pos: MultiLegPosition, time_now: time
    ) -> List[AdjustmentRequest]:
        """Check a single position against all thresholds."""
        adjustments: List[AdjustmentRequest] = []

        # 1. P&L check — max loss breach
        adj = self._check_max_loss(pos)
        if adj:
            adjustments.append(adj)
            return adjustments  # surrender overrides other checks

        # 2. Profit target
        adj = self._check_profit_target(pos)
        if adj:
            adjustments.append(adj)
            return adjustments

        # 3. Delta breach
        adj = self._check_delta_breach(pos)
        if adj:
            adjustments.append(adj)

        # 4. Gamma risk
        adj = self._check_gamma_risk(pos)
        if adj:
            adjustments.append(adj)

        # 5. Expiry / DTE auto-close
        adj = self._check_expiry(pos)
        if adj:
            adjustments.append(adj)

        # 6. Time-based intraday close
        adj = self._check_time_exit(pos, time_now)
        if adj:
            adjustments.append(adj)

        # 7. Per-leg breach (individual leg SL)
        leg_adjs = self._check_individual_legs(pos)
        adjustments.extend(leg_adjs)

        return adjustments

    # ------------------------------------------------------------------
    # Threshold checks
    # ------------------------------------------------------------------
    def _check_max_loss(self, pos: MultiLegPosition) -> Optional[AdjustmentRequest]:
        """If unrealized loss exceeds max_loss, surrender the position."""
        if pos.max_loss is None or pos.max_loss == 0:
            return None
        unrealized = pos.unrealized_pnl
        if unrealized < 0 and abs(unrealized) > abs(pos.max_loss) * (self.max_loss_pct / 100.0 + 1):
            return AdjustmentRequest(
                position_id=pos.position_id,
                adjustment_type=AdjustmentType.SURRENDER,
                reason=f"Max loss breached: unrealized={unrealized:.2f}, max_loss={pos.max_loss:.2f}",
                legs_to_close=[leg.leg_id for leg in pos.open_legs],
            )
        return None

    def _check_profit_target(self, pos: MultiLegPosition) -> Optional[AdjustmentRequest]:
        """Take profit when unrealized hits target % of max profit."""
        if pos.max_profit is None or pos.max_profit <= 0:
            return None
        unrealized = pos.unrealized_pnl
        target = pos.max_profit * (self.profit_target_pct / 100.0)
        if unrealized >= target:
            return AdjustmentRequest(
                position_id=pos.position_id,
                adjustment_type=AdjustmentType.SURRENDER,
                reason=f"Profit target hit: unrealized={unrealized:.2f} >= target={target:.2f}",
                legs_to_close=[leg.leg_id for leg in pos.open_legs],
            )
        return None

    def _check_delta_breach(self, pos: MultiLegPosition) -> Optional[AdjustmentRequest]:
        """If portfolio delta exceeds threshold, flag for hedging."""
        if abs(pos.greeks.delta) > self.delta_breach:
            # Determine roll direction based on delta sign
            adj_type = AdjustmentType.ROLL_DOWN if pos.greeks.delta > 0 else AdjustmentType.ROLL_UP
            return AdjustmentRequest(
                position_id=pos.position_id,
                adjustment_type=adj_type,
                reason=f"Delta breach: {pos.greeks.delta:.4f} (threshold ±{self.delta_breach})",
                metadata={"current_delta": pos.greeks.delta},
            )
        return None

    def _check_gamma_risk(self, pos: MultiLegPosition) -> Optional[AdjustmentRequest]:
        """Warn / adjust when gamma is dangerously high (near-ATM short options)."""
        if abs(pos.greeks.gamma) > self.gamma_risk:
            return AdjustmentRequest(
                position_id=pos.position_id,
                adjustment_type=AdjustmentType.WIDEN_WINGS,
                reason=f"High gamma risk: {pos.greeks.gamma:.6f} (threshold {self.gamma_risk})",
                metadata={"current_gamma": pos.greeks.gamma},
            )
        return None

    def _check_expiry(self, pos: MultiLegPosition) -> Optional[AdjustmentRequest]:
        """Auto-close or roll positions at DTE threshold."""
        if not pos.expiry:
            return None
        try:
            exp_date = datetime.strptime(pos.expiry[:10], "%Y-%m-%d").date()
            dte = (exp_date - date.today()).days
            if dte <= self.dte_auto_close:
                return AdjustmentRequest(
                    position_id=pos.position_id,
                    adjustment_type=AdjustmentType.SURRENDER,
                    reason=f"Expiry auto-close: DTE={dte} (threshold={self.dte_auto_close})",
                    legs_to_close=[leg.leg_id for leg in pos.open_legs],
                )
        except Exception:
            pass
        return None

    def _check_time_exit(self, pos: MultiLegPosition, time_now: time) -> Optional[AdjustmentRequest]:
        """Force exit INTRA positions before market close."""
        if time_now >= MARKET_CLOSE_TIME:
            return AdjustmentRequest(
                position_id=pos.position_id,
                adjustment_type=AdjustmentType.SURRENDER,
                reason="Time-based exit: approaching market close",
                legs_to_close=[leg.leg_id for leg in pos.open_legs],
            )
        return None

    def _check_individual_legs(self, pos: MultiLegPosition) -> List[AdjustmentRequest]:
        """
        Check each leg independently for anomalies:
        - Short leg premium doubled (SL breach)
        - Long leg lost >80% value (consider surrender)
        """
        adjustments: List[AdjustmentRequest] = []
        for leg in pos.open_legs:
            if leg.action == LegAction.SELL and leg.entry_premium > 0:
                # Short leg: if current premium > 2x entry, it's a loss
                if leg.current_premium > leg.entry_premium * 2.0:
                    adjustments.append(AdjustmentRequest(
                        position_id=pos.position_id,
                        adjustment_type=AdjustmentType.ROLL_OUT,
                        reason=(
                            f"Short leg {leg.leg_id} breached 2x premium: "
                            f"entry={leg.entry_premium:.2f} current={leg.current_premium:.2f}"
                        ),
                        legs_to_close=[leg.leg_id],
                        metadata={"breached_leg": leg.leg_id, "leg_strike": leg.strike},
                    ))
        return adjustments


# Module-level singleton
leg_monitor = LegMonitor()
