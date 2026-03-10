import asyncio
import logging
from typing import Dict, Any, List
from datetime import datetime, time, date

from src.core.event_bus import EventBus
from src.core.config import settings
from src.core.resilience import CircuitBreaker

# Import Agents
from src.agents.sentiment import SentimentAgent
from src.agents.regime import RegimeAgent
from src.agents.scanner import ScannerAgent
from src.agents.strategy import StrategyAgent
from src.agents.risk import RiskAgent
from src.agents.execution import ExecutionAgent
from src.agents.portfolio import PortfolioAgent
from src.agents.init_agents import initialize_strategy_agent

# Options chain scanner (guarded — requires OPTIONS_ENABLED)
try:
    from src.agents.option_chain_scanner import OptionChainScannerAgent
    _OPTION_CHAIN_SCANNER_AVAILABLE = True
except Exception as _oce:
    OptionChainScannerAgent = None  # type: ignore
    _OPTION_CHAIN_SCANNER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning(f"OptionChainScannerAgent unavailable: {_oce}")

logger = logging.getLogger(__name__)

# ============================================================================
# NSE Market Calendar helpers
# ============================================================================

# NSE trading hours (IST)
NSE_MARKET_OPEN = time(9, 15)
NSE_MARKET_CLOSE = time(15, 30)

# Known NSE public holidays (add/update each year)
_NSE_HOLIDAYS_2026: set = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 19),  # Holi (approximate)
    date(2026, 4, 3),   # Good Friday (approximate)
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Gandhi Jayanti
    date(2026, 11, 4),  # Diwali Laxmi Puja (approximate)
    date(2026, 12, 25), # Christmas
}


def is_market_open(now: datetime | None = None) -> bool:
    """Return True only if NSE is currently open (weekday + trading hours)."""
    now = now or datetime.now()
    today = now.date()

    # Skip weekends
    if now.weekday() >= 5:
        return False

    # Skip declared holidays
    if today in _NSE_HOLIDAYS_2026:
        return False

    # Check trading hours
    current_time = now.time()
    return NSE_MARKET_OPEN <= current_time <= NSE_MARKET_CLOSE


def is_market_day(d: date | None = None) -> bool:
    """Return True if the given date is a trading day (ignores time)."""
    d = d or date.today()
    if d.weekday() >= 5:
        return False
    return d not in _NSE_HOLIDAYS_2026


class AgentManager:
    """
    Central Orchestrator for the Agentic System.
    Manages Agent Lifecycle and the 3-Minute Execution Loop.
    """
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.agents: Dict[str, Any] = {}
        self.is_running = False
        self._market_opened_today: date | None = None  # track SOD reset

    async def initialize_agents(self):
        """Initialize and Wire all agents."""
        logger.info("Initializing Agents...")

        # Circuit breakers for sensing agents (B23)
        self.breakers: Dict[str, CircuitBreaker] = {
            "sentiment":     CircuitBreaker("sentiment",     failure_threshold=3, recovery_timeout=120),
            "regime":        CircuitBreaker("regime",        failure_threshold=3, recovery_timeout=120),
            "scanner":       CircuitBreaker("scanner",       failure_threshold=3, recovery_timeout=120),
            "option_chain":  CircuitBreaker("option_chain",  failure_threshold=3, recovery_timeout=120),
        }

        # 1. Sensing Agents
        self.agents["sentiment"] = SentimentAgent("SentimentAgent")
        self.agents["regime"] = RegimeAgent("RegimeAgent")
        self.agents["scanner"] = ScannerAgent("ScannerAgent")

        # 1b. Options chain scanner (only if OPTIONS_ENABLED and package available)
        if settings.OPTIONS_ENABLED and _OPTION_CHAIN_SCANNER_AVAILABLE:
            self.agents["option_chain_scanner"] = OptionChainScannerAgent("OptionChainScannerAgent")
            logger.info("OptionChainScannerAgent registered")
        else:
            logger.info("OptionChainScannerAgent skipped (OPTIONS_ENABLED=False or unavailable)")
        
        # 2. Decision Agent (Special Factory Init)
        self.agents["strategy"] = await initialize_strategy_agent({})
        
        # 3. Risk Agent
        self.agents["risk"] = RiskAgent("RiskAgent")
        
        # 4. Execution Agent
        self.agents["execution"] = ExecutionAgent("ExecutionAgent")
        
        # 5. Portfolio Agent
        self.agents["portfolio"] = PortfolioAgent("PortfolioAgent")
        
        # Set Event Bus for all
        for name, agent in self.agents.items():
            agent.event_bus = self.event_bus
            
        # Wire Event Subscriptions
        # Risk Agent listens to Signals
        self.event_bus.subscribe("SIGNALS_GENERATED", self.agents["risk"].on_signals_received)
        
        # Execution Agent listens to Approved Orders
        self.event_bus.subscribe("SIGNALS_APPROVED", self.agents["execution"].on_orders_approved)
        
        # Portfolio Agent listens to Fills (equity + options)
        self.event_bus.subscribe("ORDER_FILLED", self.agents["portfolio"].on_order_filled)
        self.event_bus.subscribe("OPTIONS_ORDER_FILLED", self.agents["portfolio"].on_options_order_filled)

        # Position monitor exit events → Portfolio sync
        self.event_bus.subscribe("POSITION_EXITED", self.agents["portfolio"].on_position_exited)

        # Risk Agent syncs positions from Portfolio
        self.event_bus.subscribe("PORTFOLIO_UPDATED", self.agents["risk"].on_portfolio_updated)

        # ── Previously dead-letter sensing events — now wired ─────────────────
        # SCAN_COMPLETE → StrategyAgent caches indicator data (avoids re-fetch)
        self.event_bus.subscribe("SCAN_COMPLETE", self.agents["strategy"].on_scan_complete)

        # SENTIMENT_UPDATED → StrategyAgent (context) + RiskAgent (kelly adjustment)
        self.event_bus.subscribe("SENTIMENT_UPDATED", self.agents["strategy"].on_sentiment_updated)
        self.event_bus.subscribe("SENTIMENT_UPDATED", self.agents["risk"].on_sentiment_updated)

        # REGIME_UPDATED → StrategyAgent (regime-adaptive weight cache)
        self.event_bus.subscribe("REGIME_UPDATED", self.agents["strategy"].on_regime_updated)

        # OPTIONS_SCAN_COMPLETE → StrategyAgent caches option chain data
        if "option_chain_scanner" in self.agents:
            self.event_bus.subscribe(
                "OPTIONS_SCAN_COMPLETE", self.agents["strategy"].on_options_scan_complete
            )

        logger.info("Agents Initialized and Wired.")

    async def start_all(self):
        """Start all agents."""
        tasks = [agent.start() for agent in self.agents.values()]
        await asyncio.gather(*tasks)
        self.is_running = True
        logger.info("All Agents Started.")

    async def stop_all(self):
        """Stop all agents."""
        logger.info("Stopping Agents...")
        tasks = [agent.stop() for agent in self.agents.values()]
        await asyncio.gather(*tasks)
        self.is_running = False
        logger.info("All Agents Stopped.")

    async def run_cycle(self):
        """
        Execute one full 3-minute orchestration cycle.
        Skips automatically outside NSE trading hours.
        """
        if not self.is_running:
            logger.warning("AgentManager not running. Skipping cycle.")
            return

        now = datetime.now()

        # --- Market hours gate ---
        if not is_market_open(now):
            logger.info(
                f"Market closed (weekday={now.weekday()}, time={now.strftime('%H:%M')}). "
                "Orchestration skipped."
            )
            return

        # --- Start-of-day reset (runs once, first cycle after market opens) ---
        today = now.date()
        if self._market_opened_today != today:
            await self._start_of_day_reset()
            self._market_opened_today = today

        cycle_id = f"CYCLE_{now.strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"🔄 Starting Cycle: {cycle_id}")
        
        try:
            # === Phase 1: Sensing (Parallel) ===
            logger.info("--- Phase 1: Sensing ---")
            
            # Wrap each sensing call with its CircuitBreaker (B23)
            sentiment_task = asyncio.create_task(
                self.breakers["sentiment"].call(self.agents["sentiment"].analyze)
            )
            regime_task = asyncio.create_task(
                self.breakers["regime"].call(
                    self.agents["regime"].analyze_with_real_data, "NIFTY 50"
                )
            )
            scanner_task = asyncio.create_task(
                self.breakers["scanner"].call(self.agents["scanner"].scan_universe)
            )

            # 4th sensing task: options chain scanner (runs in parallel, non-blocking)
            if "option_chain_scanner" in self.agents:
                options_scan_task = asyncio.create_task(
                    self.breakers["option_chain"].call(
                        self.agents["option_chain_scanner"].scan_option_universe,
                        regime if 'regime' in dir() else "UNKNOWN",  # best-effort regime hint
                    )
                )
            else:
                options_scan_task = asyncio.create_task(asyncio.sleep(0))  # no-op placeholder

            results = await asyncio.gather(
                sentiment_task, regime_task, scanner_task, options_scan_task,
                return_exceptions=True,
            )

            # Provide safe defaults when a breaker trips
            sentiment_score = results[0] if not isinstance(results[0], BaseException) else 0.5
            regime = results[1] if not isinstance(results[1], BaseException) else "UNKNOWN"
            opportunities = results[2] if not isinstance(results[2], BaseException) else []
            # results[3] = options scan result (consumed via OPTIONS_SCAN_COMPLETE event)

            for idx, label in enumerate(["sentiment", "regime", "scanner", "option_chain"]):
                if isinstance(results[idx], BaseException):
                    logger.warning(f"Sensing {label} failed (breaker may be open): {results[idx]}")

            logger.info(
                f"Sensing Complete. Regime: {regime}, Sentiment: "
                f"{sentiment_score if isinstance(sentiment_score, str) else f'{sentiment_score:.2f}'}, "
                f"Opps: {len(opportunities)}"
            )

            # === Phase 2: Decision (Sequential) ===
            logger.info("--- Phase 2: Decision ---")
            await self.agents["strategy"].select_and_execute(
                regime=regime,
                sentiment=sentiment_score,
                opportunities=opportunities
            )

            # Phase 3 (Risk) and Phase 4 (Execution) are event-driven via EventBus.

            # === Phase 5: Monitoring ===
            logger.info("--- Phase 5: Monitoring ---")
            await self.agents["portfolio"].update_portfolio()

            # Position SL/TP monitor (equity)
            try:
                from src.services.position_monitor import position_monitor
                await position_monitor.check_all()
            except Exception as e:
                logger.warning(f"Position monitor error: {e}")

            # Options leg monitor + adjustment engine
            if settings.OPTIONS_ENABLED:
                try:
                    from src.services.leg_monitor import leg_monitor
                    from src.services.adjustment_engine import adjustment_engine
                    from src.services.options_position_manager import options_position_manager

                    # Refresh premiums & greeks for all open options positions
                    await options_position_manager.refresh_all()

                    # Check for adjustment triggers
                    adjustment_requests = leg_monitor.check_all()
                    if adjustment_requests:
                        logger.info(
                            f"Options adjustments triggered: {len(adjustment_requests)}"
                        )
                        await adjustment_engine.process_batch(adjustment_requests)

                    # Auto-close positions expiring today
                    expiring = options_position_manager.check_expiry()
                    for pos in expiring:
                        logger.info(f"Auto-closing expiring position: {pos.position_id}")
                        from src.models.options import AdjustmentRequest, AdjustmentType
                        await adjustment_engine.process(AdjustmentRequest(
                            position_id=pos.position_id,
                            adjustment_type=AdjustmentType.SURRENDER,
                            reason="DTE=0 auto-close",
                        ))
                except Exception as e:
                    logger.warning(f"Options monitor error: {e}")

            logger.info(f"✅ Cycle {cycle_id} Completed.")

        except Exception as e:
            logger.error(f"❌ Cycle Failed: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _start_of_day_reset(self):
        """Operations to run once at the first cycle after market opens."""
        try:
            logger.info("📅 Start-of-day reset triggered")

            # Reset daily PnL counter in RiskAgent
            if "risk" in self.agents:
                await self.agents["risk"].reset_daily()

            # Refresh win rate from recent trade history
            await self._refresh_kelly_win_rate()

            # Security master may need daily refresh
            try:
                from src.services.dhan_client import get_dhan_client
                dhan = get_dhan_client()
                # Only force-refresh once per day; TTL is 12h so this is safe
                dhan._load_security_master(force_refresh=False)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Start-of-day reset failed: {e}")

    async def _refresh_kelly_win_rate(self):
        """Update RiskAgent's Kelly win rate from last 30 days of closed trades."""
        try:
            from src.database.postgres import db
            if db.pool is None:
                return

            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT realized_pnl + unrealized_pnl AS pnl
                    FROM open_positions
                    WHERE status IN ('SL_HIT','TARGET_HIT','CLOSED')
                      AND updated_at >= NOW() - INTERVAL '30 days'
                    LIMIT 100
                    """
                )
            if rows and "risk" in self.agents:
                trades = [{"pnl": float(r["pnl"])} for r in rows]
                await self.agents["risk"].update_win_rate_from_trades(trades)
        except Exception as e:
            logger.debug(f"Kelly win rate refresh failed (non-critical): {e}")

