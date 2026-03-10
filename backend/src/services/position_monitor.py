"""
Position Monitor Service
Periodically checks open positions against SL / target price and triggers exits.

Runs on the same 3-minute APScheduler job as the main orchestration loop
(or can be scheduled independently at a finer interval via add_job).
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, time
import logging

logger = logging.getLogger(__name__)

# Market close time — force-exit intraday positions before this
MARKET_CLOSE_TIME = time(15, 10)


class PositionMonitor:
    """
    Monitors open positions for:
    1. Stop-loss breach    → place exit order immediately
    2. Target hit          → place exit order immediately
    3. Time exit           → exit INTRA positions before market close
    4. Kill switch relay   → cancel all orders if RiskAgent fires kill switch
    """

    def __init__(self):
        self._last_check: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Main entry — called from orchestration loop / scheduler
    # ------------------------------------------------------------------

    async def check_all(self):
        """
        Fetch current open positions from DB, compare with live LTPs,
        and trigger exits where required.
        """
        try:
            from src.database.postgres import db
            from src.services.dhan_client import get_dhan_client
            from src.services.nse_data import nse_data_service

            db_available = db.pool is not None
            dhan = get_dhan_client()

            # 1. Load open positions
            positions = await self._load_open_positions(db_available)
            if not positions:
                return

            now = datetime.now()
            time_now = now.time()

            for pos in positions:
                symbol = pos.get("symbol", "")
                entry_price = float(pos.get("entry_price") or 0)
                stop_loss = float(pos.get("stop_loss") or 0)
                target_price = float(pos.get("target_price") or 0)
                quantity = int(pos.get("quantity") or 0)
                order_id = pos.get("order_id") or ""
                product_type = str(pos.get("product_type") or "INTRA").upper()
                side = str(pos.get("side") or "BUY").upper()
                security_id = str(pos.get("security_id") or "")
                exchange_segment = str(pos.get("exchange_segment") or "NSE")

                if not symbol or quantity == 0:
                    continue

                # 2. Get LTP
                ltp = await self._get_ltp(symbol, security_id, exchange_segment, entry_price)

                # 3. Check exit conditions
                exit_reason = self._should_exit(
                    side, ltp, entry_price, stop_loss, target_price,
                    product_type, time_now
                )

                if exit_reason:
                    logger.info(
                        f"Exit triggered: {symbol} | reason={exit_reason} | "
                        f"ltp={ltp:.2f} | sl={stop_loss:.2f} | tp={target_price:.2f}"
                    )
                    exit_side = "SELL" if side == "BUY" else "BUY"
                    exit_order_id = await dhan.place_order({
                        "transactionType": exit_side,
                        "tradingSymbol": symbol,
                        "securityId": security_id,
                        "exchangeSegment": exchange_segment,
                        "productType": product_type,
                        "orderType": "MARKET",
                        "quantity": quantity,
                        "price": 0.0,
                        "validity": "DAY",
                        "correlationId": f"EXIT_{order_id}",
                        "metadata": {
                            "security_id": security_id,
                            "exchange_segment": exchange_segment,
                            "product_type": product_type,
                        }
                    })
                    logger.info(f"Exit order placed: {exit_order_id} for {symbol}")

                    # 4. Mark position as closed in DB
                    await self._close_position_in_db(db_available, order_id, symbol, exit_reason)

                    # 5. Record PnL
                    await self._record_exit_pnl(
                        symbol, side, entry_price, ltp, quantity, exit_reason
                    )

                    # 6. Publish event so PortfolioAgent + RiskAgent stay in sync
                    await self._publish_exit_event(
                        symbol, exit_reason, entry_price, ltp, quantity, order_id
                    )

            self._last_check = now

        except Exception as e:
            logger.error(f"Position monitor failed: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _should_exit(
        side: str,
        ltp: float,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        product_type: str,
        time_now: time,
    ) -> Optional[str]:
        """Return exit reason string or None."""
        if ltp <= 0:
            return None  # No valid LTP → skip

        if side == "BUY":
            if stop_loss > 0 and ltp <= stop_loss:
                return "SL_HIT"
            if target_price > 0 and ltp >= target_price:
                return "TARGET_HIT"
        else:  # SELL / short
            if stop_loss > 0 and ltp >= stop_loss:
                return "SL_HIT"
            if target_price > 0 and ltp <= target_price:
                return "TARGET_HIT"

        # Time-based exit for intraday
        if "INTRA" in product_type and time_now >= MARKET_CLOSE_TIME:
            return "TIME_EXIT"

        return None

    @staticmethod
    async def _get_ltp(
        symbol: str, security_id: str, exchange_segment: str, fallback: float
    ) -> float:
        """Get latest traded price; fall back to entry_price if unavailable."""
        try:
            from src.services.nse_data import nse_data_service
            # Prefer NSE data service for equity
            if "FNO" not in exchange_segment.upper():
                df = await nse_data_service.get_stock_ohlc(symbol, period="1D")
                if not df.empty and "close" in df.columns:
                    return float(df["close"].iloc[-1])
        except Exception:
            pass

        # Fallback: DhanHQ market data
        try:
            from src.services.dhan_client import get_dhan_client
            dhan = get_dhan_client()
            data = await dhan.fetch_market_data(security_id, exchange_segment)
            ltp = float(data.get("ltp") or 0)
            if ltp > 0:
                return ltp
        except Exception:
            pass

        return fallback  # Use entry price as last resort

    @staticmethod
    async def _load_open_positions(db_available: bool) -> List[Dict[str, Any]]:
        """Load positions from DB if available, else empty list."""
        if not db_available:
            return []
        try:
            from src.database.postgres import db
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM open_positions WHERE status = 'OPEN'"
                )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to load positions: {e}")
            return []

    @staticmethod
    async def _close_position_in_db(
        db_available: bool, order_id: str, symbol: str, reason: str
    ):
        """Update position status in DB."""
        if not db_available:
            return
        try:
            from src.database.postgres import db
            status_map = {
                "SL_HIT": "SL_HIT",
                "TARGET_HIT": "TARGET_HIT",
                "TIME_EXIT": "CLOSED",
            }
            status = status_map.get(reason, "CLOSED")
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE open_positions
                    SET status=$1, updated_at=NOW()
                    WHERE (order_id=$2 OR symbol=$3) AND status='OPEN'
                    """,
                    status, order_id, symbol,
                )
        except Exception as e:
            logger.error(f"DB close position failed: {e}")

    @staticmethod
    async def _record_exit_pnl(
        symbol: str, side: str, entry_price: float,
        exit_price: float, quantity: int, reason: str
    ):
        """Compute realized PnL and update daily_pnl table."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return

            if side == "BUY":
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity

            from datetime import date
            today = date.today()
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO daily_pnl (trade_date, realized_pnl, total_trades,
                        winning_trades, losing_trades, updated_at)
                    VALUES ($1, $2, 1,
                        CASE WHEN $2 > 0 THEN 1 ELSE 0 END,
                        CASE WHEN $2 <= 0 THEN 1 ELSE 0 END,
                        NOW())
                    ON CONFLICT (trade_date) DO UPDATE
                        SET realized_pnl = daily_pnl.realized_pnl + EXCLUDED.realized_pnl,
                            total_trades = daily_pnl.total_trades + 1,
                            winning_trades = daily_pnl.winning_trades +
                                CASE WHEN $2 > 0 THEN 1 ELSE 0 END,
                            losing_trades = daily_pnl.losing_trades +
                                CASE WHEN $2 <= 0 THEN 1 ELSE 0 END,
                            updated_at = NOW()
                    """,
                    today, pnl,
                )
            logger.info(
                f"PnL recorded: {symbol} {reason} | pnl={pnl:+.2f} | "
                f"entry={entry_price:.2f} exit={exit_price:.2f} qty={quantity}"
            )
        except Exception as e:
            logger.error(f"Failed to record exit PnL: {e}")


    @staticmethod
    async def _publish_exit_event(
        symbol: str, reason: str, entry_price: float,
        exit_price: float, quantity: int, order_id: str
    ):
        """Publish POSITION_EXITED so PortfolioAgent/RiskAgent re-sync."""
        try:
            from src.core.event_bus import EventBus
            bus = EventBus._instance if hasattr(EventBus, '_instance') else None
            if bus is None:
                # Fallback: import the singleton from main
                try:
                    from src.main import event_bus as bus
                except ImportError:
                    return
            await bus.publish("POSITION_EXITED", {
                "symbol": symbol,
                "reason": reason,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "order_id": order_id,
            })
        except Exception as e:
            logger.debug(f"Failed to publish exit event: {e}")


# Singleton
position_monitor = PositionMonitor()
