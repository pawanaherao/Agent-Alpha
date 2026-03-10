"""
Portfolio Agent — Phase 3 rebuild
Tracks open positions via DhanHQ API, computes real PnL, and persists to DB.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, date
import logging

from src.agents.base import BaseAgent
from src.core.config import settings

logger = logging.getLogger(__name__)


class PortfolioAgent(BaseAgent):
    """
    Agent responsible for real-time Portfolio Monitoring.

    Responsibilities:
    1. Sync open positions from DhanHQ broker API
    2. Compute unrealised + realised PnL
    3. Persist position state to PostgreSQL (open_positions, daily_pnl)
    4. Publish PORTFOLIO_UPDATED event with live state for RiskAgent
    5. Update kill-switch PnL counter for RiskAgent
    """

    def __init__(self, name: str = "PortfolioAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        # In-memory cache: symbol -> position dict
        self.positions: Dict[str, Dict[str, Any]] = {}
        # Paper-trading: track simulated fills that won't appear in broker API
        self.simulated_positions: Dict[str, Dict[str, Any]] = {}
        self.balance: float = float(
            (config or {}).get("initial_capital", settings.__dict__.get("INITIAL_CAPITAL", 1_000_000))
        )
        self.total_unrealized_pnl: float = 0.0
        self.total_realized_pnl: float = 0.0
        self._today: date = date.today()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def update_portfolio(self) -> Dict[str, Any]:
        """
        Main heartbeat method — fetches positions, computes PnL and publishes.
        Called every 3-minute orchestration cycle.
        In paper trading mode (PAPER_TRADING=True or broker disconnected),
        simulated positions are used instead of broker data.
        """
        try:
            from src.services.dhan_client import get_dhan_client
            dhan = get_dhan_client()

            # 1. Fetch live positions from broker
            live_positions = await dhan.get_positions()

            # 2. Rebuild in-memory map keyed by symbol
            new_map: Dict[str, Dict] = {}
            total_unrealized = 0.0
            total_realized = 0.0

            for pos in live_positions:
                sym = pos.get("symbol", "UNKNOWN")
                unrealized = pos.get("unrealized_pnl", 0.0)
                realized = pos.get("realized_pnl", 0.0)
                total_unrealized += unrealized
                total_realized += realized

                new_map[sym] = {
                    "symbol": sym,
                    "security_id": pos.get("security_id", ""),
                    "exchange_segment": pos.get("exchange_segment", ""),
                    "product_type": pos.get("product_type", ""),
                    "quantity": pos.get("quantity", 0),
                    "net_qty": pos.get("net_qty", 0),
                    "buy_avg": pos.get("buy_avg", 0.0),
                    "ltp": pos.get("ltp", 0.0),
                    "unrealized_pnl": unrealized,
                    "realized_pnl": realized,
                    "risk_amount": abs(pos.get("buy_avg", 0) * pos.get("net_qty", 0)) * 0.03,
                }

            # 2b. Paper-trading: merge simulated positions when broker returns nothing
            if not live_positions and self.simulated_positions:
                logger.info(
                    f"Paper mode: merging {len(self.simulated_positions)} simulated positions"
                )
                for sym, sim_pos in self.simulated_positions.items():
                    if sim_pos.get("status") == "OPEN":
                        new_map[sym] = sim_pos

            self.positions = new_map
            self.total_unrealized_pnl = total_unrealized
            self.total_realized_pnl = total_realized

            # 3. Persist to DB
            await self._persist_to_db(live_positions)

            # 4. Compute daily PnL (realized today)
            daily_pnl = total_realized  # Simplified; ideally delta from SOD
            await self._update_daily_pnl(daily_pnl)

            # 5. Publish event
            state = self._build_state()
            await self.publish_event("PORTFOLIO_UPDATED", state)

            logger.info(
                f"Portfolio synced: {len(self.positions)} positions | "
                f"Unrealized={total_unrealized:+.0f} | Realized={total_realized:+.0f}"
            )
            return state

        except Exception as e:
            self.logger.error(f"Portfolio update failed: {e}", exc_info=True)
            # Publish stale cached state so downstream agents still work
            await self.publish_event("PORTFOLIO_UPDATED", self._build_state())
            return self._build_state()

    async def record_new_position(self, order_id: str, signal: Dict[str, Any], quantity: int):
        """
        Called by ExecutionAgent when an order is filled.
        Upserts a row in open_positions.
        """
        try:
            from src.database.postgres import db
            if db.pool is None:
                return

            symbol = signal.get("symbol", "UNKNOWN")
            entry_price = signal.get("entry_price") or 0.0
            stop_loss = signal.get("stop_loss")
            target_price = signal.get("target_price")
            strategy_id = signal.get("strategy_name", "")
            signal_id = signal.get("signal_id", "")
            side = signal.get("signal_type", "BUY").upper()
            security_id = (signal.get("metadata") or {}).get("security_id", "")
            exchange_segment = (signal.get("metadata") or {}).get("exchange_segment", "NSE")
            product_type = (signal.get("metadata") or {}).get("product_type", "INTRA")

            async with db.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO open_positions
                        (symbol, security_id, exchange_segment, product_type,
                         strategy_id, signal_id, side, quantity,
                         entry_price, stop_loss, target_price, order_id, status)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'OPEN')
                    ON CONFLICT (order_id) DO UPDATE
                        SET quantity = EXCLUDED.quantity,
                            updated_at = NOW()
                    """,
                    symbol, security_id, exchange_segment, product_type,
                    strategy_id, signal_id, side, quantity,
                    entry_price, stop_loss, target_price, order_id,
                )
            logger.info(f"Recorded new position: {side} {quantity} {symbol} @ {entry_price}")
        except Exception as e:
            logger.error(f"Failed to record position: {e}")

    async def close_position(self, symbol: str, order_id: str, reason: str = "MANUAL"):
        """Mark a position as closed in the DB."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return

            status_map = {
                "SL_HIT": "SL_HIT",
                "TARGET_HIT": "TARGET_HIT",
                "TIME_EXIT": "CLOSED",
                "MANUAL": "CLOSED",
            }
            status = status_map.get(reason, "CLOSED")

            async with db.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE open_positions
                    SET status=$1, updated_at=NOW()
                    WHERE order_id=$2 OR symbol=$3 AND status='OPEN'
                    """,
                    status, order_id, symbol,
                )
            # Remove from in-memory map
            self.positions.pop(symbol, None)
        except Exception as e:
            logger.error(f"Failed to close position: {e}")

    async def get_open_positions_from_db(self) -> List[Dict[str, Any]]:
        """Load OPEN positions from PostgreSQL for RiskAgent heat check."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return list(self.positions.values())

            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM open_positions WHERE status='OPEN'"
                )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to load positions from DB: {e}")
            return list(self.positions.values())

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    async def on_order_filled(self, payload: Dict[str, Any]):
        """Called by ExecutionAgent when an equity order is fully filled."""
        order_id = payload.get("order_id", "")
        signal = payload.get("signal", {})
        quantity = payload.get("quantity", 1)
        self.logger.info(f"Order filled: {order_id}")

        # Track simulated fills in memory for paper trading
        if str(order_id).startswith("SIM_"):
            symbol = signal.get("symbol", "UNKNOWN")
            entry_price = float(signal.get("entry_price", 0) or 0)
            side = signal.get("signal_type", "BUY").upper()
            self.simulated_positions[symbol] = {
                "symbol": symbol,
                "order_id": order_id,
                "security_id": (signal.get("metadata") or {}).get("security_id", ""),
                "exchange_segment": (signal.get("metadata") or {}).get("exchange_segment", "NSE"),
                "product_type": (signal.get("metadata") or {}).get("product_type", "INTRA"),
                "quantity": quantity,
                "net_qty": quantity if side == "BUY" else -quantity,
                "buy_avg": entry_price,
                "ltp": entry_price,  # will be updated with real LTP on next scan
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "risk_amount": abs(entry_price * quantity) * 0.03,
                "side": side,
                "strategy_name": signal.get("strategy_name", ""),
                "entry_time": datetime.now().isoformat(),
                "status": "OPEN",
                "simulated": True,
            }
            self.logger.info(
                f"Paper trade tracked: {side} {quantity} {symbol} @ {entry_price} | ID={order_id}"
            )

        await self.record_new_position(order_id, signal, quantity)
        await self.update_portfolio()

    async def on_options_order_filled(self, payload: Dict[str, Any]):
        """Called by ExecutionAgent when a multi-leg options position opens."""
        position_id = payload.get("position_id", "")
        symbol = payload.get("symbol", "")
        structure = payload.get("structure_type", "")
        legs = payload.get("legs", 0)
        self.logger.info(
            f"Options position opened: {position_id} | {structure} | "
            f"{symbol} | legs={legs}"
        )
        # Trigger a portfolio refresh so downstream (RiskAgent) sees the new exposure
        await self.update_portfolio()

    async def on_position_exited(self, payload: Dict[str, Any]):
        """Called by PositionMonitor when a SL/TP/time-exit fires."""
        symbol = payload.get("symbol", "")
        reason = payload.get("reason", "CLOSED")
        self.logger.info(f"Position exited event: {symbol} ({reason})")
        # Mark simulated position as closed
        if symbol in self.simulated_positions:
            self.simulated_positions[symbol]["status"] = "CLOSED"
            self.logger.info(f"Paper position closed: {symbol} ({reason})")
        await self.update_portfolio()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _persist_to_db(self, live_positions: list):
        """Update ltp / unrealized_pnl in open_positions from broker state."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return

            async with db.pool.acquire() as conn:
                for pos in live_positions:
                    sym = pos.get("symbol", "")
                    ltp = pos.get("ltp", 0.0)
                    upnl = pos.get("unrealized_pnl", 0.0)
                    rpnl = pos.get("realized_pnl", 0.0)
                    await conn.execute(
                        """
                        UPDATE open_positions
                        SET ltp=$1, unrealized_pnl=$2, realized_pnl=$3, updated_at=NOW()
                        WHERE symbol=$4 AND status='OPEN'
                        """,
                        ltp, upnl, rpnl, sym,
                    )
        except Exception as e:
            logger.error(f"DB persist failed: {e}")

    async def _update_daily_pnl(self, realized_pnl: float):
        """Upsert today's PnL summary in daily_pnl table."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return

            today = date.today()
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO daily_pnl (trade_date, realized_pnl, unrealized_pnl, updated_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (trade_date) DO UPDATE
                        SET realized_pnl = EXCLUDED.realized_pnl,
                            unrealized_pnl = EXCLUDED.unrealized_pnl,
                            updated_at = NOW()
                    """,
                    today, realized_pnl, self.total_unrealized_pnl,
                )
        except Exception as e:
            logger.error(f"Failed to update daily PnL: {e}")

    def _build_state(self) -> Dict[str, Any]:
        return {
            "balance": self.balance,
            "positions_count": len(self.positions),
            "positions": list(self.positions.values()),
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "total_realized_pnl": self.total_realized_pnl,
            "timestamp": datetime.now().isoformat(),
        }
