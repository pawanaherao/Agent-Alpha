"""
Options Position Manager
========================
Persistent tracking of open multi-leg positions with real-time P&L.

Responsibilities:
  - Store / retrieve MultiLegPosition objects (DB + in-memory cache)
  - Record new positions from OptionsSignal execution
  - Update leg premiums and Greeks in real-time
  - Aggregate portfolio-level Greeks
  - Generate portfolio summary / risk snapshot
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from src.models.options import (
    Greeks,
    LegPosition,
    MultiLegPosition,
    OptionsSignal,
    PositionStatus,
    LegAction,
)
from src.services.greeks import greeks_engine

logger = logging.getLogger(__name__)


class OptionsPositionManager:
    """
    Central registry for all open multi-leg option positions.
    Backed by in-memory dict (synced to Postgres when available).
    """

    def __init__(self):
        self._positions: Dict[str, MultiLegPosition] = {}  # position_id → position

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def add_position(self, position: MultiLegPosition) -> None:
        """Register a newly executed multi-leg position."""
        self._positions[position.position_id] = position
        logger.info(
            f"Position added: {position.position_id} | {position.structure_type.value} "
            f"| {position.symbol} | legs={len(position.legs)}"
        )
        # Async DB persist (fire-and-forget)
        asyncio.ensure_future(self._persist_to_db(position))

    def get_position(self, position_id: str) -> Optional[MultiLegPosition]:
        return self._positions.get(position_id)

    def get_open_positions(self) -> List[MultiLegPosition]:
        """All positions with status OPEN or PARTIAL."""
        return [
            p for p in self._positions.values()
            if p.status in (PositionStatus.OPEN, PositionStatus.PARTIAL, PositionStatus.ADJUSTING)
        ]

    def get_positions_by_symbol(self, symbol: str) -> List[MultiLegPosition]:
        return [p for p in self._positions.values() if p.symbol.upper() == symbol.upper()]

    def close_position(self, position_id: str, realized_pnl: float = 0.0) -> None:
        """Mark a position as closed."""
        pos = self._positions.get(position_id)
        if not pos:
            return
        pos.status = PositionStatus.CLOSED
        pos.closed_at = datetime.now()
        pos.realized_pnl = realized_pnl
        for leg in pos.legs:
            leg.status = "CLOSED"
        logger.info(f"Position closed: {position_id} | realized_pnl={realized_pnl:+.2f}")
        asyncio.ensure_future(self._persist_to_db(pos))

    # ------------------------------------------------------------------
    # Real-time P&L update
    # ------------------------------------------------------------------
    async def refresh_all(self, spot_prices: Optional[Dict[str, float]] = None):
        """
        Update premiums, Greeks, and P&L for all open positions.
        Called by LegMonitor on each tick.
        """
        for pos in self.get_open_positions():
            await self.refresh_position(pos, spot_prices)

    async def refresh_position(
        self,
        pos: MultiLegPosition,
        spot_prices: Optional[Dict[str, float]] = None,
    ):
        """Update a single position's legs with current market data."""
        spot = (spot_prices or {}).get(pos.symbol.upper(), 0)
        if spot <= 0:
            spot = await self._fetch_spot(pos.symbol)

        if spot <= 0:
            return  # can't update without spot

        for leg in pos.open_legs:
            # Refresh current premium
            ltp = await self._fetch_leg_ltp(leg)
            if ltp > 0:
                leg.current_premium = ltp

            # Refresh Greeks
            from src.services.option_chain import _time_to_expiry_years
            T = _time_to_expiry_years(leg.expiry)
            greeks_engine.refresh_leg_greeks(leg, spot, T)

        # Aggregate portfolio Greeks
        pos.greeks = greeks_engine.portfolio_greeks(pos.legs, spot)

    # ------------------------------------------------------------------
    # Portfolio summary
    # ------------------------------------------------------------------
    def portfolio_summary(self) -> Dict[str, Any]:
        """
        Aggregate summary across all open positions.
        Returns portfolio-level Greeks, P&L, and position count.
        """
        open_positions = self.get_open_positions()
        total_unrealized = sum(p.unrealized_pnl for p in open_positions)
        total_realized = sum(p.realized_pnl for p in self._positions.values())

        # Aggregate Greeks
        agg = Greeks()
        for p in open_positions:
            agg.delta += p.greeks.delta
            agg.gamma += p.greeks.gamma
            agg.theta += p.greeks.theta
            agg.vega += p.greeks.vega

        return {
            "open_positions": len(open_positions),
            "total_positions": len(self._positions),
            "unrealized_pnl": round(total_unrealized, 2),
            "realized_pnl": round(total_realized, 2),
            "portfolio_greeks": {
                "delta": round(agg.delta, 4),
                "gamma": round(agg.gamma, 6),
                "theta": round(agg.theta, 2),
                "vega": round(agg.vega, 2),
            },
            "positions": [
                {
                    "position_id": p.position_id,
                    "symbol": p.symbol,
                    "structure": p.structure_type.value,
                    "legs": len(p.legs),
                    "status": p.status.value,
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "greeks": {
                        "delta": round(p.greeks.delta, 4),
                        "gamma": round(p.greeks.gamma, 6),
                        "theta": round(p.greeks.theta, 2),
                        "vega": round(p.greeks.vega, 2),
                    },
                }
                for p in open_positions
            ],
        }

    # ------------------------------------------------------------------
    # Expiry management
    # ------------------------------------------------------------------
    def check_expiry(self) -> List[MultiLegPosition]:
        """Find positions expiring today."""
        today_str = date.today().isoformat()
        expiring = []
        for pos in self.get_open_positions():
            if pos.expiry and pos.expiry[:10] == today_str:
                expiring.append(pos)
            # Also check individual legs
            for leg in pos.open_legs:
                if leg.expiry[:10] == today_str and pos not in expiring:
                    expiring.append(pos)
        return expiring

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------
    async def _persist_to_db(self, pos: MultiLegPosition):
        """Persist position to Postgres (best-effort)."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO options_positions
                        (position_id, signal_id, symbol, structure_type, status,
                         legs_json, net_premium, max_profit, max_loss,
                         realized_pnl, greeks_json, opened_at, closed_at, expiry)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    ON CONFLICT (position_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        legs_json = EXCLUDED.legs_json,
                        realized_pnl = EXCLUDED.realized_pnl,
                        greeks_json = EXCLUDED.greeks_json,
                        closed_at = EXCLUDED.closed_at
                    """,
                    pos.position_id,
                    pos.signal_id,
                    pos.symbol,
                    pos.structure_type.value,
                    pos.status.value,
                    pos.model_dump_json(),  # full JSON
                    pos.net_premium_received,
                    pos.max_profit,
                    pos.max_loss,
                    pos.realized_pnl,
                    pos.greeks.model_dump_json(),
                    pos.opened_at,
                    pos.closed_at,
                    pos.expiry,
                )
        except Exception as e:
            logger.debug(f"DB persist failed (non-critical): {e}")

    async def load_from_db(self):
        """Hydrate in-memory positions from Postgres on startup."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT legs_json FROM options_positions WHERE status IN ('OPEN','PARTIAL','ADJUSTING')"
                )
            for row in rows:
                try:
                    pos = MultiLegPosition.model_validate_json(row["legs_json"])
                    self._positions[pos.position_id] = pos
                except Exception:
                    pass
            logger.info(f"Loaded {len(rows)} options positions from DB")
        except Exception as e:
            logger.debug(f"DB load failed: {e}")

    # ------------------------------------------------------------------
    # Market data helpers
    # ------------------------------------------------------------------
    @staticmethod
    async def _fetch_spot(symbol: str) -> float:
        try:
            from src.services.nse_data import nse_data_service
            df = await nse_data_service.get_stock_ohlc(symbol, period="1D")
            if not df.empty and "close" in df.columns:
                return float(df["close"].iloc[-1])
        except Exception:
            pass
        return 0.0

    @staticmethod
    async def _fetch_leg_ltp(leg: LegPosition) -> float:
        """Fetch current premium for an option leg."""
        try:
            from src.services.dhan_client import get_dhan_client
            dhan = get_dhan_client()
            if leg.security_id:
                data = await dhan.fetch_market_data(leg.security_id, "NSE_FNO")
                ltp = float(data.get("ltp", 0))
                if ltp > 0:
                    return ltp
        except Exception:
            pass
        return 0.0


# Module-level singleton
options_position_manager = OptionsPositionManager()
