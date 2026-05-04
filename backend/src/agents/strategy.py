"""
Enhanced Strategy Agent with Real NSE Data and GenAI Integration
SEBI Compliant: Whitebox decision logic with AI augmentation

Features:
1. Real NSE data flow to all strategies
2. Regime-based strategy filtering
3. GenAI signal validation (Vertex AI)
4. Dynamic position sizing based on conviction
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import asyncio
import pandas as pd
import polars as pl
import logging

from src.agents.base import BaseAgent
from src.core.config import settings
from src.core.messages import AgentMessage
from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service
from src.database.redis import cache as _redis_cache
from src.services.ai_cost_tracker import ai_cost_tracker
from src.intelligence.alpha_intelligence import (
    expected_return_score,
    regime_weighted_strategy_scores,
    get_kelly_win_rate,
    gemini_should_override,
)

# ── In-process signal store ──────────────────────────────────────────────────
# Single source of truth for /api/signals/recent when Redis is unavailable.
# Written on every cycle alongside Redis so either path always has latest data.
_SIGNAL_STORE: dict = {"signals": [], "count": 0, "generated_at": None}

logger = logging.getLogger(__name__)


class StrategyAgent(BaseAgent):
    """
    Enhanced Strategy Agent with real data flow and GenAI augmentation.
    
    DECISION FLOW:
    1. Filter strategies by regime suitability
    2. Fetch real NSE data for each opportunity
    3. Generate signals from qualified strategies
    4. Validate signals with GenAI (optional)
    5. Apply dynamic position sizing
    """
    
    def __init__(self, name: str = "StrategyAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.strategies: Dict[str, BaseStrategy] = {}

        # ── Intra-cycle caches (refreshed on each sensing event) ──────────────
        # Keyed by symbol → full scan result from ScannerAgent (avoids re-fetch)
        self._scan_cache: Dict[str, Any] = {}
        # Keyed by symbol → scored options chain opportunity from OptionChainScannerAgent
        self._options_chain_cache: Dict[str, Any] = {}
        # FIX-AUDIT-D20-H7: Track when chain cache was last updated
        self._options_chain_cache_ts: Optional[datetime] = None
        self._options_chain_max_age_sec: int = 7200  # 2h — matches Redis TTL
        # Latest sentiment/regime pushed from sensing events
        self._latest_sentiment: float = 0.0
        self._latest_sentiment_at: Optional[datetime] = None
        self._sentiment_max_age_sec = int((config or {}).get("sentiment_max_age_sec", 900))
        self._latest_regime: str = "SIDEWAYS"       # intraday regime (daily bars)
        self._latest_swing_regime: str = "SIDEWAYS"  # swing regime (weekly view, 6M data)
        # Improvement #3 — Regime transition metadata
        self._latest_regime_transition: str = "STABLE"
        self._latest_regime_transition_confidence: float = 0.0
        self.nse_service = nse_data_service
        
        # Strategy weights by regime
        # Mar 9 2026: Rebalanced for wider funnel — floor raised from 0.3→0.6
        # to support 20-30 trades/day target.  Preferred types still boosted
        # but non-preferred types no longer crushed below threshold.
        self.regime_weights = {
            "BULL": {
                "momentum": 1.5,
                "trend": 1.3,
                "mean_reversion": 1.0,
                "theta": 0.7,
                "hedge": 0.6
            },
            "BEAR": {
                "momentum": 0.7,
                "trend": 0.8,
                "mean_reversion": 1.3,
                "theta": 1.0,
                "hedge": 1.5
            },
            "SIDEWAYS": {
                "momentum": 0.8,
                "trend": 0.7,
                "mean_reversion": 1.6,
                "theta": 1.4,
                "hedge": 0.8
            },
            "VOLATILE": {
                "momentum": 1.2,
                "trend": 0.8,
                "mean_reversion": 0.9,
                "theta": 0.6,
                "hedge": 1.2
            }
        }
        
        # GenAI model for signal validation — lazy-loaded on first use
        self.genai_model = None
        self._genai_init_attempted = False
        
        self.signal_history: List[StrategySignal] = []
        # ── AI: Cross-cycle signal consistency tracking ───────────────────────
        # Tracks how many consecutive orchestration cycles each (symbol, signal_type)
        # pair has generated a signal.  Consistent signals get SQS boost;
        # brand-new signals are dampened until they confirm over 2+ cycles.
        self._signal_streak: Dict[tuple, int] = {}   # (symbol, signal_type) → count
        self._prev_cycle_signals: set = set()        # keys from previous cycle

        # ── Session performance ledger (updated by orchestrator from RiskAgent) ──
        # Gemini receives this so it can downgrade/reject signals from strategies
        # that are misfiring today (e.g. PFTH: 5 losses / 0 wins today).
        # Schema: strategy_name → {trades: int, wins: int, losses: int,
        #                           consecutive_losses: int, session_pnl_inr: float}
        self._strategy_session_perf: Dict[str, dict] = {}

    # ── Strategy → category keyword map ──────────────────────────────────────
    # Patterns matched against strategy.name (case-sensitive prefix/substring)
    _CATEGORY_KEYWORDS: Dict[str, List[str]] = {
        "MOMENTUM"     : ["ORB", "EMA_Cross", "Momentum", "Earnings", "ATR_Break",
                           "OFI", "ALPHA_OFI", "ALPHA_SENTIMENT", "ALPHA_TREND",
                           "Sector_Rot", "Gap_Fill", "PowerFirstHour", "PFTH",
                           "ORBVWAPFusion"],
        "MEAN_REVERSION": ["VWAP", "BB_Squeeze", "RSI_Div", "Mean_Rev",
                            "MeanReversion", "Scalper"],
        "SWING"        : ["Swing", "Pullback", "Breakout", "Sector_Rot",
                           "ALPHA_TREND", "Trend_Pull", "TrendFollowing",
                           "Wave2"],
        "OPTIONS"      : ["Condor", "Spread", "Straddle", "Strangle", "Butterfly",
                           "Calendar", "Volatility_Crush", "DELTA", "BEARPUT",
                           "BUTTERFLY", "STRADDLE", "STRANGLE", "CALENDAR",
                           "Universal", "Iron", "Theta", "Diagonal",
                           "IndexOptions"],
        "INTRADAY"     : ["ORB", "VWAP", "Gap_Fill", "Scalper", "PowerFirstHour",
                           "PFTH"],
        "QUANT"        : ["Statistical", "Arbitrage", "CrossSectional", "Pair",
                           "Factor", "ML_Ensemble", "RSPair"],
        "VOLATILITY"   : ["VIX", "Vol_Crush", "VolatilityCrush", "Volatility",
                           "Delta_Hedg", "DeltaHedging", "Gamma"],
        "SECTOR"       : ["Sector_Rot", "SectorRotation", "Sentiment"],
        "HEDGING"      : ["Hedge", "Delta_Neutral", "DeltaHedging", "Gamma",
                           "Portfolio_Hedge", "PortfolioHedge"],
    }

    async def _get_category_filter(self) -> str:
        """
        Read the user-selected strategy category from Redis.
        Returns 'AUTO' if nothing selected or Redis unavailable.
        """
        try:
            return await _redis_cache.get("strategy_category_filter") or "AUTO"
        except Exception:
            return "AUTO"

    def _strategy_matches_category(self, strategy_name: str, category: str) -> bool:
        """Return True if strategy_name contains any keyword for the given category."""
        if category == "AUTO":
            return True
        keywords = self._CATEGORY_KEYWORDS.get(category, [])
        return any(kw.lower() in strategy_name.lower() for kw in keywords)

    # ── Module filter (Equity vs Options) ─────────────────────────────────────
    # Source of truth: order_type_router._STRATEGY_MODULE_MAP (explicit map, no keyword guessing).
    # Keyword list kept ONLY as a last-resort fallback for unregistered strategy names.
    _OPTIONS_MODULE_KEYWORDS: List[str] = [
        "Condor", "Spread", "Straddle", "Strangle", "Butterfly", "Calendar",
        "Volatility_Crush", "VIX", "Delta", "Gamma", "Iron", "Theta",
        "Diagonal", "DELTA", "BEARPUT", "BUTTERFLY", "STRADDLE", "STRANGLE",
        "CALENDAR", "Options",
    ]

    async def _get_module_filter(self) -> str:
        """Read the user-selected strategy module from Redis. Returns 'ALL' if unset."""
        try:
            return await _redis_cache.get("strategy_module_filter") or "ALL"
        except Exception:
            return "ALL"

    def _strategy_matches_module(self, strategy_name: str, module: str) -> bool:
        """Return True if strategy belongs to the given module (EQUITY or OPTIONS).
        Uses explicit map from order_type_router — no keyword fragility."""
        if module == "ALL":
            return True
        from src.services.order_type_router import get_strategy_module
        strat_module = get_strategy_module(strategy_name).upper()
        if module == "OPTIONS":
            return strat_module in {"OPTIONS", "FNO"}
        # EQUITY = anything not OPTIONS/FNO
        return strat_module == "EQUITY"

    # ── Trading Style filter (Intraday vs Swing) ──────────────────────────────
    # Source of truth: order_type_router._STRATEGY_TRADING_STYLE_MAP (deterministic).
    # Keyword list kept ONLY as a last-resort fallback for unregistered strategies.
    _INTRADAY_KEYWORDS: List[str] = [
        "ORB", "VWAP", "Gap_Fill", "MR_Scalp", "OFI",
        "Order_Flow", "First_Hour", "Power_First",
    ]

    async def _get_trading_style_filter(self) -> str:
        """Read the user-selected trading style from Redis. Returns 'ALL' if unset."""
        try:
            return await _redis_cache.get("trading_style_filter") or "ALL"
        except Exception:
            return "ALL"

    def _strategy_matches_style(self, strategy_name: str, style: str) -> bool:
        """Return True if strategy matches the given trading style (INTRADAY or SWING).
        Uses explicit map first; keyword fallback only for unregistered strategies."""
        if style == "ALL":
            return True
        from src.services.order_type_router import get_strategy_trading_style
        strat_style = get_strategy_trading_style(strategy_name)  # "INTRADAY" | "SWING"
        if style == "INTRADAY":
            return strat_style == "INTRADAY"
        return strat_style == "SWING"

    async def start(self):
        """Initialize Vertex AI for intelligence-layer signal validation."""
        await super().start()

        # Warm up regime from last known value in Redis so the first cycle
        # doesn't default to SIDEWAYS when the market opened BULL/BEAR.
        try:
            _cached_regime = await _redis_cache.get("current_regime")
            if _cached_regime:
                import json as _json_r
                _raw = _cached_regime.decode() if isinstance(_cached_regime, bytes) else str(_cached_regime)
                _obj = _json_r.loads(_raw)
                _r = _obj.get("regime", _obj) if isinstance(_obj, dict) else str(_obj)
                if _r in ("BULL", "BEAR", "SIDEWAYS", "VOLATILE"):
                    self._latest_regime = _r
                    logger.info(f"StrategyAgent: regime warm-up from Redis → {self._latest_regime}")
        except Exception as _re:
            logger.debug(f"StrategyAgent: regime warm-up skipped ({_re}); defaulting to SIDEWAYS")

        # Warm up options chain cache from Redis so step 5b runs on first cycle after restart.
        # Written by OptionChainScannerAgent after each scan; TTL=2h, survives intraday restarts.
        try:
            _raw_oc = await _redis_cache.get("options_chain_results")
            if _raw_oc:
                import json as _json_oc
                _oc_str = _raw_oc.decode() if isinstance(_raw_oc, bytes) else str(_raw_oc)
                _oc_data = _json_oc.loads(_oc_str)
                _chains = _oc_data.get("chains", [])
                if _chains:
                    self._options_chain_cache = {opp["symbol"]: opp for opp in _chains if "symbol" in opp}
                    logger.info(
                        f"StrategyAgent: options chain cache warmed from Redis — "
                        f"{len(self._options_chain_cache)} symbols "
                        f"(top={next(iter(self._options_chain_cache), 'none')})"
                    )
        except Exception as _oc_err:
            logger.debug(f"StrategyAgent: options chain warm-up skipped ({_oc_err})")

        # AI lazy-init: defer model loading to first use (_ensure_genai_model)
        # so Vertex AI client is guaranteed to be fully initialized.

    def _ensure_genai_model(self):
        """Enable GenAI validation via the shared ai_router on first use."""
        if self._genai_init_attempted:
            return self.genai_model
        try:
            from src.services.ai_router import ai_router

            self._genai_init_attempted = True
            self.genai_model = ai_router
            logger.info("StrategyAgent: GenAI signal validation active via ai_router")
        except Exception as e:
            self._genai_init_attempted = True
            logger.warning(f"StrategyAgent: AI router init failed ({e}) — skipping GenAI validation")
            self.genai_model = None
        return self.genai_model

    async def register_strategy(self, strategy: BaseStrategy):
        """Register a strategy instance."""
        self.strategies[strategy.name] = strategy
        logger.info(f"Registered strategy: {strategy.name}")

    # ── Sensing-event subscribers ──────────────────────────────────────────────

    async def on_scan_complete(self, data: Dict[str, Any]):
        """
        Cache full scanner results so select_and_execute() can skip the
        duplicate get_stock_with_indicators() call for each symbol.
        This is the primary fix for the 10-trades/second bottleneck: the
        scanner already fetched OHLCV + computed all 12 indicators; we
        inject those scalar values into the DataFrame instead of re-fetching.
        """
        scanned: list = data.get("scanned", [])
        self._scan_cache = {s["symbol"]: s for s in scanned if "symbol" in s}
        # Propagate regime hint from scanner
        if data.get("regime"):
            self._latest_regime = data["regime"]
        logger.debug(f"StrategyAgent: scan cache updated — {len(self._scan_cache)} symbols")

    async def on_sentiment_updated(self, data: Dict[str, Any]):
        """Cache latest sentiment score published by SentimentAgent.

        Stores both the global index score and the per-stock sentiment dict.
        When computing signals for a specific symbol, per-stock score is used
        if available; otherwise falls back to the global score.
        """
        self._latest_sentiment = float(data.get("score", self._latest_sentiment))
        self._latest_sentiment_at = datetime.now()
        # Cache per-stock sentiments (populated when SentimentAgent analyzes open positions)
        per_stock: dict = data.get("stock_sentiments", {})
        if per_stock:
            if not hasattr(self, "_stock_sentiments"):
                self._stock_sentiments: dict = {}
            self._stock_sentiments.update(per_stock)
        logger.debug(
            f"StrategyAgent: sentiment → {self._latest_sentiment:.2f} "
            f"({data.get('classification', '')}) | per-stock enriched: {len(per_stock)} symbols"
        )

    async def on_regime_updated(self, data: Dict[str, Any]):
        """Cache latest regime published by RegimeAgent."""
        _prev_regime = self._latest_regime
        self._latest_regime = data.get("regime", self._latest_regime)
        # Swing regime: slower-moving weekly view (published by RegimeAgent.analyze_swing_regime)
        if data.get("swing_regime"):
            self._latest_swing_regime = data["swing_regime"]
        # Improvement #3: cache transition metadata for suitability adjustments
        self._latest_regime_transition = data.get("transition", "STABLE")
        self._latest_regime_transition_confidence = float(data.get("transition_confidence", 0.0))
        self.logger.debug(
            f"StrategyAgent: intraday_regime={self._latest_regime} "
            f"swing_regime={self._latest_swing_regime} "
            f"(stat={data.get('statistical_regime', '')}, vix={data.get('vix', '')}, "
            f"transition={self._latest_regime_transition})"
        )

        # FIX-AUDIT-D20-C5: On regime TRANSITION, notify RiskAgent so it can
        # re-evaluate open positions entered under the previous regime.
        # E.g., TrendFollowing positions opened in BULL must be flagged when
        # regime flips to BEAR mid-day.
        if _prev_regime != self._latest_regime and _prev_regime:
            self.logger.warning(
                f"[REGIME-TRANSITION] {_prev_regime} → {self._latest_regime} "
                f"(transition={self._latest_regime_transition}) — "
                f"publishing REGIME_TRANSITION_ACTIVE event for position review"
            )
            try:
                await self.publish_event("REGIME_TRANSITION_ACTIVE", {
                    "previous_regime": _prev_regime,
                    "new_regime": self._latest_regime,
                    "transition_type": self._latest_regime_transition,
                    "confidence": self._latest_regime_transition_confidence,
                    "timestamp": __import__('datetime').datetime.now().isoformat(),
                })
            except Exception as _rt_err:
                self.logger.debug(f"Regime transition event publish failed: {_rt_err}")
    async def on_options_scan_complete(self, data: Dict[str, Any]):
        """
        Cache option chain scan results published by OptionChainScannerAgent.

        Payload structure (per OPTIONS_SCAN_COMPLETE event):
          {
            "chains": [
              {"symbol": str, "structure": str, "score": float,
               "iv_rank": float, "atm_iv": float, "oi_pcr": float,
               "atm_strike": float, "spot_price": float, "expiry": str,
               "lot_size": int, "legs": [...]},
              ...
            ],
            "regime": str, "count": int, "timestamp": str
          }
        Update _latest_regime from the scan's regime hint as well.
        """
        chains: list = data.get("chains", [])
        self._options_chain_cache = {opp["symbol"]: opp for opp in chains if "symbol" in opp}
        # FIX-AUDIT-D20-H7: Record cache population timestamp
        self._options_chain_cache_ts = datetime.now()
        if data.get("regime"):
            self._latest_regime = data["regime"]
        logger.info(
            f"StrategyAgent: options chain cache updated \u2014 "
            f"{len(self._options_chain_cache)} symbols, "
            f"top={next(iter(self._options_chain_cache), 'none')}"
        )    
    async def select_and_execute(
        self, 
        regime: str, 
        sentiment: float, 
        opportunities: List[str]
    ):
        """
        Enhanced strategy execution with parallel data fetch + scanner cache.

        PERFORMANCE PATH (10-trade/s target):
        ┌──────────────┐   SCAN_COMPLETE   ┌────────────────────┐
        │  ScannerAgent │ ──────────────── ▶│  _scan_cache       │
        └──────────────┘  (indicators pre- │  {symbol: scan_row}│
                           computed)        └────────┬───────────┘
                                                     │ inject scalars
                                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │  asyncio.gather(*fetch_tasks)  ← PARALLEL DATA FETCH    │
        │  For each symbol:                                        │
        │    cache hit  → get_stock_ohlc() + inject scan scalars  │
        │    cache miss → get_stock_with_indicators()  (fallback) │
        └────────────────────────┬─────────────────────────────────┘
                                 ▼
        ┌──────────────────────────────────────────────────────────┐
        │  asyncio.gather(*signal_tasks) ← PARALLEL SIGNAL GEN    │
        │  top-3 strategies × each symbol                         │
        └──────────────────────────────────────────────────────────┘

        WHITEBOX LOGIC:
        1. Filter strategies by regime suitability
        2. Pre-filter symbols: skip scanner score < 50 to reduce load
        3. Parallel OHLCV fetch (inject pre-computed scanner indicators)
        4. Parallel signal generation
        5. Validate with GenAI (if enabled)
        6. Publish approved signals
        """
        logger.info(f"Strategy selection: Regime={regime}, Sentiment={sentiment:.1f}, "
                    f"Opps={len(opportunities)}")

        # FIX-SCANNER-SA1: Move options chain staleness check to beginning of select_and_execute
        # (was only inside options injection block — stale cache persisted if no options strategy selected)
        if self._options_chain_cache_ts is not None:
            _chain_age = (datetime.now() - self._options_chain_cache_ts).total_seconds()
            if _chain_age > self._options_chain_max_age_sec:
                logger.warning(
                    f"[SA1-CHAIN-STALE] Options chain cache is {_chain_age:.0f}s old "
                    f"(max={self._options_chain_max_age_sec}s) — clearing stale data"
                )
                self._options_chain_cache.clear()
                self._options_chain_cache_ts = None

        # FIX-SCANNER-SA2: Prune _signal_streak entries not seen in last 5 cycles
        # (dict grows unbounded with 200+ symbols × strategy types)
        if hasattr(self, '_signal_streak_prune_counter'):
            self._signal_streak_prune_counter += 1
        else:
            self._signal_streak_prune_counter = 0
        if self._signal_streak_prune_counter >= 5:
            _before = len(self._signal_streak)
            self._signal_streak = {k: v for k, v in self._signal_streak.items() if v > 0}
            _pruned = _before - len(self._signal_streak)
            if _pruned > 0:
                logger.debug(f"SA2: Pruned {_pruned} stale signal streak entries")
            self._signal_streak_prune_counter = 0

        # Allow callers that pass raw string lists (legacy) as well as dicts
        def _sym(opp) -> str:
            return opp["symbol"] if isinstance(opp, dict) else str(opp)

        # 0. Paper mode: set _paper_mode flag on ALL strategies BEFORE filtering
        #    so calculate_suitability() can skip time-of-day penalties.
        _is_paper = getattr(settings, "PAPER_TRADING", False) or \
                    getattr(settings, "MODE", "") in ("PAPER", "LOCAL")
        if _is_paper:
            for strategy in self.strategies.values():
                strategy._paper_mode = True

        # 1. Filter strategies by regime suitability (dual-regime: intraday + swing)
        suitable_strategies = await self._filter_by_regime(
            regime, swing_regime=self._latest_swing_regime
        )
        if not suitable_strategies:
            logger.warning("No suitable strategies for current regime")
            return

        # 1b. Apply user-selected category filter (AUTO = no filter)
        category_filter = await self._get_category_filter()
        if category_filter != "AUTO":
            before = len(suitable_strategies)
            suitable_strategies = [
                (s, score) for s, score in suitable_strategies
                if self._strategy_matches_category(s.name, category_filter)
            ]
            logger.info(
                f"Category filter '{category_filter}': {before} → {len(suitable_strategies)} strategies"
            )
            if not suitable_strategies:
                logger.warning(
                    f"No strategies match category '{category_filter}' — "
                    f"falling back to full regime set"
                )
                suitable_strategies = await self._filter_by_regime(
                    regime, swing_regime=self._latest_swing_regime
                )

        # 1c. Apply module filter (ALL / EQUITY / OPTIONS)
        module_filter = await self._get_module_filter()
        if module_filter != "ALL":
            before = len(suitable_strategies)
            suitable_strategies = [
                (s, score) for s, score in suitable_strategies
                if self._strategy_matches_module(s.name, module_filter)
            ]
            logger.info(
                f"Module filter '{module_filter}': {before} → {len(suitable_strategies)} strategies"
            )
            if not suitable_strategies:
                logger.warning(
                    f"No strategies match module '{module_filter}' — "
                    f"falling back to full regime set"
                )
                suitable_strategies = await self._filter_by_regime(
                    regime, swing_regime=self._latest_swing_regime
                )

        # 1d. Apply trading style filter (ALL / INTRADAY / SWING)
        style_filter = await self._get_trading_style_filter()
        if style_filter != "ALL":
            before = len(suitable_strategies)
            suitable_strategies = [
                (s, score) for s, score in suitable_strategies
                if self._strategy_matches_style(s.name, style_filter)
            ]
            logger.info(
                f"Trading style filter '{style_filter}': {before} → {len(suitable_strategies)} strategies"
            )
            if not suitable_strategies:
                logger.warning(
                    f"No strategies match trading style '{style_filter}' — "
                    f"falling back to full regime set"
                )
                suitable_strategies = await self._filter_by_regime(
                    regime, swing_regime=self._latest_swing_regime
                )

        logger.info(f"Suitable strategies: {[s[0].name for s in suitable_strategies]}")

        # 1e. AUTO-RETIRE: Remove strategies flagged RED by alpha-decay monitor.
        #     Previously retire_flag was informational only — now enforced.
        try:
            from src.services.alpha_decay_monitor import get_alpha_decay_monitor
            _adm = get_alpha_decay_monitor()
            _dashboard = await _adm.get_decay_dashboard()
            _retire_set = set(_dashboard.get("summary", {}).get("retire_candidates", []))
            if _retire_set:
                _before_retire = len(suitable_strategies)
                suitable_strategies = [
                    (s, score) for s, score in suitable_strategies
                    if s.name not in _retire_set
                ]
                _removed = _before_retire - len(suitable_strategies)
                if _removed > 0:
                    logger.warning(
                        f"🛑 AUTO-RETIRE: Blocked {_removed} RED strategies from execution: "
                        f"{_retire_set & {s[0].name for s in suitable_strategies} | _retire_set}"
                    )
        except Exception as _ad_err:
            logger.debug(f"Alpha-decay retire filter skipped: {_ad_err}")

        # Cache the top-N selected strategy names so the dashboard can display
        # "Recommended This Cycle" without waiting for signals to appear.
        _top_n = self._dynamic_top_n(suitable_strategies)
        from src.services.order_type_router import get_strategy_module as _get_strategy_module

        # Options strategies have a dedicated chain-driven execution path later in
        # this method. Running them here once per equity opportunity explodes
        # decision latency and creates duplicate index-option signals.
        _per_symbol_strategies = [
            (strategy, score)
            for strategy, score in suitable_strategies
            if getattr(strategy, "config", {}).get("mode") != "options"
            and _get_strategy_module(strategy.name) != "Options"
        ]
        _per_symbol_top_n = min(_top_n, len(_per_symbol_strategies))
        try:
            _topN_names = [s[0].name for s in suitable_strategies[:_top_n]]
            await _redis_cache.set(
                "selected_strategies_this_cycle",
                __import__("json").dumps({
                    "strategies": _topN_names,
                    "regime": regime,
                    "top_n": _top_n,
                    "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }),
                ttl=300,
            )
        except Exception as _ce:
            logger.debug(f"Could not cache selected_strategies_this_cycle: {_ce}")

        # 1d. Paper mode flag already set at step 0 (before filtering).
        #     No additional action needed here.

        # 2. Pre-filter using scanner scores — avoid fetching data for weak setups
        #    Also apply symbol selection filter (per-strategy historical Sharpe ranking)
        try:
            from src.services.symbol_filter import symbol_filter
            if not symbol_filter._last_refresh:
                symbol_filter.initialize()
        except Exception as _sf_err:
            logger.debug(f"Symbol filter init skipped: {_sf_err}")
            symbol_filter = None

        # Regime-aware minimum scanner score (mirrors scanner._scan_one threshold).
        # Paper mode: very low floor — let ALL scanner-approved stocks through.
        # Quality control is handled by RiskAgent (R:R, Kelly, kill switch) and
        # SQS ranking, NOT by the pre-filter.  Target: 100-500 raw signals
        # so 20-30 trades survive risk filtering.
        _is_paper = getattr(settings, "PAPER_TRADING", False) or \
                    getattr(settings, "MODE", "") in ("PAPER", "LOCAL")
        if _is_paper:
            _strat_min_score = 10   # paper: let everything through
            _max_symbols = 50       # paper: process up to 50 stocks
        else:
            _regime_strategy_min = {
                "BULL": 35, "BEAR": 35, "SIDEWAYS": 25, "VOLATILE": 35,
            }
            _strat_min_score = _regime_strategy_min.get(regime, 30)
            _max_symbols = 15

        # Fallback: if scan_cache is empty, try loading from Redis
        if not self._scan_cache:
            try:
                import json as _j
                _raw = await _redis_cache.get("scanner_results")
                if _raw:
                    _parsed = _j.loads(_raw)
                    for item in _parsed.get("results", []):
                        if isinstance(item, dict) and "symbol" in item:
                            self._scan_cache[item["symbol"]] = item
                    logger.info(f"Loaded {len(self._scan_cache)} scanner results from Redis cache")
            except Exception as _e:
                logger.debug(f"Scanner Redis fallback failed: {_e}")

        qualified: list = []
        _seen_symbols: set[str] = set()
        _duplicate_opportunity_symbols = 0
        for opp in opportunities[:_max_symbols]:
            symbol = _sym(opp)
            if symbol in _seen_symbols:
                _duplicate_opportunity_symbols += 1
                continue
            _seen_symbols.add(symbol)
            cached = self._scan_cache.get(symbol)
            scanner_score = cached.get("score", 100) if cached else 100
            if scanner_score >= _strat_min_score:
                # Check symbol filter — only in LIVE mode (paper needs max coverage)
                if not _is_paper and symbol_filter and symbol_filter.enabled:
                    approved_for_any = any(
                        symbol_filter.is_symbol_approved(s.name, symbol)
                        for s, _ in suitable_strategies[:_top_n]
                    )
                    if not approved_for_any:
                        logger.debug(f"Symbol filter: skipping {symbol} (not in top-N for any strategy)")
                        continue
                qualified.append((symbol, cached))
            else:
                logger.debug(f"Pre-filter: skipping {symbol} (scan_score={scanner_score:.0f} < min={_strat_min_score})")

        if _duplicate_opportunity_symbols > 0:
            logger.info(
                "Strategy pre-filter deduped %s duplicate opportunity symbols before data fetch",
                _duplicate_opportunity_symbols,
            )

        if not qualified:
            logger.info("No qualified opportunities after scanner pre-filter")
            return

        # Pre-compute intraday/options need OUTSIDE the per-symbol loop (saves
        # re-evaluating for every symbol and avoids unnecessary API calls).
        try:
            from src.services.order_type_router import get_strategy_trading_style as _gts
            _need_intraday_global = any(
                _gts(s.name) == "INTRADAY"
                for s, _ in _per_symbol_strategies[:_per_symbol_top_n]
            )
        except Exception:
            _need_intraday_global = False
        generated_signals: list = []
        signal_batches: list = []
        if _per_symbol_strategies:
            # 3. PARALLEL data fetch — scanner cache hit avoids redundant indicator recalc
            async def _fetch(symbol: str, cached: Optional[Any]) -> tuple:
                try:
                    if cached:
                        # Fast path: fetch OHLCV only (indicators already in cache)
                        market_data = await self.nse_service.get_stock_ohlc(
                            symbol, period="1Y"
                        )
                        if not market_data.empty:
                            # Inject pre-computed scanner indicators as extra columns.
                            # Booleans (ema_aligned, ema_partial_aligned, obv_rising, vpt_rising)
                            # are converted to 1.0/0.0 so _derive_stock_local_regime() can read them.
                            for k, v in cached.get("indicators", {}).items():
                                if isinstance(v, bool):
                                    market_data[f"scan_{k}"] = 1.0 if v else 0.0
                                elif isinstance(v, (int, float)):
                                    market_data[f"scan_{k}"] = float(v)
                                elif isinstance(v, str) and k in ("stock_regime", "vp_zone"):
                                    market_data[f"scan_{k}"] = v
                            # Also inject scores breakdown (ema_score, rs_nifty_score, etc.)
                            # so per-stock regime derivation can use the pre-computed graded values.
                            for _sk, _sv in cached.get("indicators", {}).get("scores_breakdown", {}).items():
                                if isinstance(_sv, (int, float)) and not isinstance(_sv, bool):
                                    market_data[f"scan_score_{_sk}"] = float(_sv)
                            market_data["scanner_score"] = cached.get("score", 0)

                            # Improvement #6: inject indicator series from scanner
                            # Strategies can read these instead of recomputing
                            _series = cached.get("indicators", {}).get("series", {})
                            if _series:
                                for s_key, s_vals in _series.items():
                                    if isinstance(s_vals, list) and len(s_vals) > 0:
                                        # Store as the last N rows column
                                        market_data[f"scan_series_{s_key}"] = [s_vals] * len(market_data)
                    else:
                        # Slow path: full fetch + indicator computation (cache miss)
                        market_data = await self.nse_service.get_stock_with_indicators(
                            symbol, period="1Y"
                        )

                    if market_data.empty:
                        return symbol, pd.DataFrame()

                    market_data["symbol"] = symbol
                    # Inject sentiment score: use per-stock score when available (from open-position
                    # analysis in SentimentAgent), fall back to global index score.
                    _per_stock_map: dict = getattr(self, "_stock_sentiments", {})
                    _sentiment_fresh = False
                    if self._latest_sentiment_at is not None:
                        _sentiment_age = (datetime.now() - self._latest_sentiment_at).total_seconds()
                        _sentiment_fresh = _sentiment_age <= self._sentiment_max_age_sec
                    market_data["sentiment_score"] = _per_stock_map.get(
                        symbol,
                        self._latest_sentiment if _sentiment_fresh else 0.0,
                    )

                    # ── MTF: inject intraday_df for INTRADAY-style strategies ────────
                    # INTRADAY strategies (ORB, VWAP, MR Scalper, etc.) need 15-minute
                    # bars for real signal computation.  We attach them as a per-row
                    # column (same DataFrame object repeated) — strategies read:
                    #   intraday_df = market_data["intraday_df"].iloc[0]
                    try:
                        if _need_intraday_global:
                            intraday_df = await self.nse_service.get_intraday_ohlc(
                                symbol, days=5, interval_minutes=15
                            )
                            if intraday_df is not None and not intraday_df.empty:
                                # Attach as a scalar object reference in a new column;
                                # strategies pull it via .iloc[0] on that column.
                                market_data["intraday_df"] = [intraday_df] * len(market_data)
                            else:
                                market_data["intraday_df"] = [pd.DataFrame()] * len(market_data)
                    except Exception as _mte:
                        logger.debug(f"MTF intraday fetch skipped for {symbol}: {_mte}")
                        market_data["intraday_df"] = [pd.DataFrame()] * len(market_data)
                    # ── END MTF inject ────────────────────────────────────────────────

                    # ── OPTIONS: inject chain cache for options-module strategies ──────
                    # Options strategies use a dedicated chain-driven path later in the
                    # cycle, so the per-symbol equity loop never needs option-chain data.
                    market_data["options_chain"] = [{}] * len(market_data)
                    # ── END OPTIONS chain inject ──────────────────────────────────────

                    # Hurst exponent — fractality check (Phase 5, non-blocking)
                    try:
                        from src.utils.fast_math import calculate_hurst_exponent
                        close = market_data["close"].values
                        market_data["hurst"] = (
                            calculate_hurst_exponent(close) if len(close) > 30 else 0.5
                        )
                    except Exception:
                        market_data["hurst"] = 0.5

                    try:
                        pl.from_pandas(market_data)  # type-check via polars (fast)
                    except Exception:
                        pass

                    return symbol, market_data
                except Exception as e:
                    logger.error(f"Data fetch failed for {symbol}: {e}")
                    return symbol, pd.DataFrame()

            fetch_results: list = await asyncio.gather(
                *[_fetch(sym, cached) for sym, cached in qualified]
            )

            # 4. PARALLEL signal generation (symbol × strategy)
            async def _gen(symbol: str, market_data: pd.DataFrame) -> list:
                if market_data.empty:
                    return []
                signals = []
                for strategy, score in _per_symbol_strategies[:_per_symbol_top_n]:
                    try:
                        # Per-stock regime: directional strategies (momentum/trend/mean_reversion)
                        # use the stock's own technical character rather than the macro regime.
                        # Hedge/theta strategies always use macro regime (portfolio-level decisions).
                        _strat_type = self._classify_strategy(strategy.name)
                        _stock_regime = self._derive_stock_local_regime(
                            symbol, market_data, regime, _strat_type
                        )
                        # Inject swing regime so multi-day options strategies can use it
                        strategy._swing_regime = self._latest_swing_regime
                        signal = await strategy.generate_signal(market_data, _stock_regime)
                        if signal:
                            # Day22 fix: suppress directional signals when stock is SIDEWAYS
                            # but strategy requires a trending regime (momentum/trend).
                            # Mean-reversion strategies are OK in SIDEWAYS.
                            if _stock_regime == "SIDEWAYS" and _strat_type in ("momentum", "trend"):
                                logger.debug(
                                    f"Suppressed {strategy.name} {signal.signal_type} {symbol}: "
                                    f"stock_regime=SIDEWAYS incompatible with {_strat_type}"
                                )
                                continue
                            signal.metadata["suitability_score"] = score
                            signal.metadata["sentiment_score"] = sentiment
                            signal.metadata["regime"] = regime          # macro regime
                            signal.metadata["stock_regime"] = _stock_regime  # per-stock override
                            signal.metadata["data_rows"] = len(market_data)
                            signal.metadata["position_weight"] = (
                                self._calculate_position_weight(score, sentiment, signal.strength)
                            )
                            signals.append(signal)
                            logger.info(
                                f"Signal: {signal.signal_type} {signal.symbol} "
                                f"from {signal.strategy_name} "
                                f"(strength={signal.strength:.2f} "
                                f"macro={regime} stock={_stock_regime})"
                            )
                    except Exception as e:
                        logger.error(f"Signal generation failed for {strategy.name}: {e}")
                return signals

            signal_batches = await asyncio.gather(
                *[_gen(sym, data) for sym, data in fetch_results
                  if not isinstance(data, BaseException)]
            )
            generated_signals = [s for batch in signal_batches for s in batch]
        else:
            logger.info("Per-symbol strategy path skipped: only options strategies qualified this cycle")

        # ── Deduplicate signals: same (strategy, symbol, signal_type) = keep highest strength ──
        _seen: dict = {}  # key → signal
        for sig in generated_signals:
            key = (sig.strategy_name, sig.symbol, sig.signal_type)
            if key not in _seen or sig.strength > _seen[key].strength:
                _seen[key] = sig
        if len(_seen) < len(generated_signals):
            logger.info(
                f"Dedup: {len(generated_signals)} raw → {len(_seen)} unique signals "
                f"(removed {len(generated_signals) - len(_seen)} duplicates)"
            )
        generated_signals = list(_seen.values())

        # ── One-signal-per-symbol rule (Medallion CEO Fix #10) ──────────────────
        # Across all strategies, keep only the SINGLE highest-strength signal
        # per (symbol, direction) combination.  Prevents capital double-counting
        # when e.g. ORB + VWAP_Reversion + EMA_Crossover all trigger on RELIANCE BUY.
        _sym_dir: dict = {}  # (symbol, signal_type) → best signal
        for sig in generated_signals:
            _key = (sig.symbol, sig.signal_type)
            if _key not in _sym_dir or sig.strength > _sym_dir[_key].strength:
                _sym_dir[_key] = sig
        if len(_sym_dir) < len(generated_signals):
            logger.info(
                f"One-signal-per-symbol: {len(generated_signals)} → {len(_sym_dir)} "
                f"(collapsed {len(generated_signals) - len(_sym_dir)} duplicate symbol/direction signals; "
                f"best-strength strategy retained per slot)"
            )
        generated_signals = list(_sym_dir.values())
        # ── End one-signal-per-symbol ────────────────────────────────────────────

        # ── Signal Quality Score (MFT Mar 2026) ───────────────────────────
        # Composite ranking so capital goes to highest-quality signals first.
        # SQS = 0.25×strength + 0.25×(suitability/100) + 0.25×grade_mult + 0.25×expected_return
        for sig in generated_signals:
            _suit = sig.metadata.get("suitability_score", 50) / 100.0
            _grade_m = 1.0
            try:
                _gc = await self._get_grade_cache()
                _grade_m = self._grade_multiplier(sig.strategy_name, _gc)
            except Exception:
                pass

            # F1.3: Expected return scoring — real edge estimation
            _er_component = 0.0
            try:
                _kelly_wr, _kelly_aw, _kelly_al = await get_kelly_win_rate(
                    _redis_cache, sig.strategy_name,
                    self._latest_regime, default=0.55, min_trades=3,
                )
                _er_result = expected_return_score(
                    win_rate=_kelly_wr,
                    avg_win=_kelly_aw,
                    avg_loss=_kelly_al,
                    entry_price=float(sig.entry_price or 100),
                )
                sig.metadata["expected_return"] = _er_result
                sig.metadata["should_trade"] = _er_result["should_trade"]
                # Normalize ER to 0-1 range for SQS composition
                _edge_bps = _er_result.get("edge_bps", 0)
                _er_component = max(0, min(1.0, _edge_bps / 100.0))  # 100bps = perfect score
            except Exception as _er_err:
                logger.debug(f"Expected return calc failed for {sig.strategy_name}: {_er_err}")
                sig.metadata["should_trade"] = False  # Day22 fix: default to REJECT when ER unknown

            sig.metadata["signal_quality_score"] = round(
                0.25 * sig.strength + 0.25 * _suit
                + 0.25 * (_grade_m / 1.3) + 0.25 * _er_component, 4
            )
        # Sort highest SQS first so RiskAgent processes best signals first
        generated_signals.sort(
            key=lambda s: s.metadata.get("signal_quality_score", 0), reverse=True
        )

        # ── F1.3: Expected return gate — reject negative-edge signals ─────
        # Hard gate in ALL modes (paper + live). When the quant model says
        # should_trade=false (negative edge, profit_factor < 1), the signal
        # is removed. GenAI cannot override this — it's the last quantitative
        # safety net. Day22 fix: was paper-only, now universal.
        _pre_er = len(generated_signals)
        generated_signals = [
            s for s in generated_signals
            if s.metadata.get("should_trade", True)
        ]
        if len(generated_signals) < _pre_er:
            logger.info(
                f"F1.3 ER-GATE: {_pre_er} → {len(generated_signals)} "
                f"(rejected {_pre_er - len(generated_signals)} negative-edge signals)"
            )

        # ── Strategy diversity cap ────────────────────────────────────────
        # Prevents a single high-suitability strategy (e.g. CROSS_MOM in BEAR
        # at 80.0) from monopolising the entire published batch.
        # Rule: max 3 signals per strategy in the final published set.
        # Signals beyond the cap are still passed to the risk agent — they
        # are just deprioritised after the first 3 slots are filled.
        # This forces at least 3-4 different strategies per cycle when 10+
        # signals are being published (10 signals ÷ 3-per-strategy = minimum
        # 4 strategies represented).
        _MAX_PER_STRATEGY = 3
        _strat_count: dict = {}
        _diverse: list = []
        _overflow: list = []
        for _sig in generated_signals:
            _sname = _sig.strategy_name
            if _strat_count.get(_sname, 0) < _MAX_PER_STRATEGY:
                _diverse.append(_sig)
                _strat_count[_sname] = _strat_count.get(_sname, 0) + 1
            else:
                _overflow.append(_sig)
        # Append overflow at end so they can still be approved if no better signal
        generated_signals = _diverse + _overflow
        if _overflow:
            _unique_strats_pre  = len(set(s.strategy_name for s in _diverse + _overflow))
            _unique_strats_post = len(set(s.strategy_name for s in _diverse))
            logger.info(
                f"Strategy diversity cap (max {_MAX_PER_STRATEGY}/strategy): "
                f"{len(_diverse + _overflow)} → {len(_diverse)} priority, "
                f"{len(_overflow)} queued | "
                f"strategies in priority set: {_unique_strats_post} "
                f"(was {_unique_strats_pre} pre-cap)"
            )
        # ── End diversity cap ─────────────────────────────────────────────

        # ── Live LTP normalisation (system-wide entry price fix) ─────────────
        # Strategies compute entry_price from historical OHLCV closes which can
        # be days or weeks stale (Tier-3 fallback, in-process cache hits, yfinance
        # adjusted prices, etc.).  OHLCV data is only correct for *scoring* —
        # momentum rank, RSI, ATR etc.  The actual fill price must be live LTP.
        #
        # A SINGLE batch call resolves up to 100 symbols in one API round-trip
        # so there is no per-signal latency overhead.  Entry price, stop loss and
        # target price are updated while preserving SL/TGT as the same % offset
        # from entry.  The original OHLCV close is saved to metadata so charts
        # and scoring are unaffected.
        _ltp_symbols = list({s.symbol for s in generated_signals if s.symbol})
        if _ltp_symbols:
            try:
                # Always use DhanHQ DATA client for price lookups — never the
                # execution broker (Kotak Neo's token mapping returns scrambled
                # LTPs via search_scrip, causing wrong entry prices).
                from src.services.broker_factory import get_data_client as _get_data_client
                _dhan_dc = _get_data_client()
                _raw_quotes = await _dhan_dc.get_batch_quotes(_ltp_symbols, mode="ticker")
                _ltp_map = {
                    sym: float((_raw_quotes.get(sym) or {}).get("ltp") or 0)
                    for sym in _ltp_symbols
                }
                _corrected = 0
                _skipped_sanity = 0
                for _sig in generated_signals:
                    _live_ltp = float(_ltp_map.get(_sig.symbol) or 0)
                    _old_ep   = float(_sig.entry_price or 0)
                    if _live_ltp > 0 and _old_ep > 0:
                        _pct_diff = abs(_live_ltp - _old_ep) / _old_ep
                        # Sanity cap: reject DhanHQ LTP if it deviates >50% from
                        # OHLCV close — indicates a wrong security_id mapping
                        # (e.g. SBIN resolved to wrong instrument returning ₹2145
                        # instead of actual ₹~800). Keep OHLCV close in that case.
                        if _pct_diff > 0.50:
                            logger.warning(
                                f"[LTP-SANITY] {_sig.symbol}: DhanHQ returned "
                                f"₹{_live_ltp} ({_pct_diff*100:.0f}% from OHLCV ₹{_old_ep}) — "
                                f"likely wrong security_id; trying NSE/Kotak fallback"
                            )
                            _sig.metadata["ltp_sanity_failed"] = _live_ltp
                            # ── Translation-layer fallback ────────────────────
                            # DhanHQ security_id may be stale/wrong for this symbol.
                            # Use nse_data.get_live_quote() which tries:
                            #   1. Kotak Neo search_scrip (by symbol name, not sec_id)
                            #   2. DhanHQ ohlc_data
                            #   3. NSElib snapshot
                            # This avoids cascading the bad security_id into the price.
                            _fallback_ltp = 0.0
                            try:
                                from src.services.nse_data import nse_data_service as _nse_svc
                                _fb_result = await _nse_svc.get_live_quote(_sig.symbol)
                                _fallback_ltp = float(_fb_result.get("ltp") or 0)
                                if _fallback_ltp > 0:
                                    _fb_pct = abs(_fallback_ltp - _old_ep) / _old_ep if _old_ep > 0 else 1.0
                                    if _fb_pct < 2.0:  # sanity: fallback within 200% of OHLCV
                                        _sl_pct  = (((_sig.stop_loss    or _old_ep) - _old_ep) / _old_ep) if _old_ep > 0 else -0.03
                                        _tgt_pct = (((_sig.target_price or _old_ep) - _old_ep) / _old_ep) if _old_ep > 0 else 0.06
                                        _sig.entry_price  = round(_fallback_ltp, 2)
                                        _sig.stop_loss    = round(_fallback_ltp * (1.0 + _sl_pct),  2)
                                        _sig.target_price = round(_fallback_ltp * (1.0 + _tgt_pct), 2)
                                        _sig.ltp_source   = f"fallback_{_fb_result.get('source', 'nse')}"
                                        _sig.metadata["ohlcv_close_price"] = _old_ep
                                        _corrected += 1
                                        logger.info(
                                            f"[LTP-FALLBACK] {_sig.symbol}: ₹{_fallback_ltp} "
                                            f"from {_fb_result.get('source','?')} "
                                            f"(DhanHQ bad sec_id ₹{_live_ltp} overridden)"
                                        )
                                        continue  # skip _skipped_sanity count
                            except Exception as _fb_err:
                                logger.debug(f"[LTP-FALLBACK] {_sig.symbol} fallback failed: {_fb_err}")
                            _skipped_sanity += 1
                        elif _pct_diff > 0.005:  # >0.5% drift → normalise
                            _sl_pct  = (((_sig.stop_loss    or _old_ep) - _old_ep) / _old_ep)
                            _tgt_pct = (((_sig.target_price or _old_ep) - _old_ep) / _old_ep)
                            _sig.entry_price  = round(_live_ltp, 2)
                            _sig.stop_loss    = round(_live_ltp * (1.0 + _sl_pct),  2)
                            _sig.target_price = round(_live_ltp * (1.0 + _tgt_pct), 2)
                            _sig.ltp_source   = "broker_live"
                            _sig.metadata["ohlcv_close_price"] = _old_ep  # preserve for charts
                            _corrected += 1
                    elif _live_ltp > 0 and _old_ep <= 0:
                        # No entry_price at all — use LTP with ATR-proxy SL/TGT
                        _sig.entry_price  = round(_live_ltp, 2)
                        _sig.stop_loss    = round(_live_ltp * 0.97, 2)
                        _sig.target_price = round(_live_ltp * 1.06, 2)
                        _sig.ltp_source   = "broker_live"
                        _corrected += 1
                if _corrected or _skipped_sanity:
                    logger.info(
                        f"[LTP-CORRECT] Normalised {_corrected}/{len(_ltp_symbols)} signals "
                        f"to live LTP | {_skipped_sanity} sanity-blocked (>50% deviation = bad security_id)"
                    )
            except Exception as _ltp_ex:
                logger.warning(
                    f"[LTP-CORRECT] Batch LTP fetch failed — signals retain OHLCV prices: {_ltp_ex}"
                )
        # ── End LTP normalisation ─────────────────────────────────────────────

        # ── AUDIT Layer-5: 5-Factor Confluence Gate ───────────────────────
        # Every signal must score ≥3/5 on (regime, IV, OFI, sector, MTF)
        # to survive. This is the single biggest filter for 90% WR target.
        if generated_signals:
            try:
                from src.services.confluence_scorer import confluence_scorer as _cs
                _pre_confl = len(generated_signals)
                _confluent = []
                # Build market context once (shared across all signals)
                _day_posture = {}
                try:
                    from src.core.agent_manager import agent_manager as _am_cs
                    if _am_cs:
                        _day_posture = getattr(_am_cs, "_day_posture", {}) or {}
                except Exception:
                    pass
                _iv_regime_str = ""
                try:
                    from src.services.iv_regime import iv_regime_classifier
                    _iv_r = await iv_regime_classifier.classify()
                    _iv_regime_str = _iv_r.value
                except Exception:
                    pass
                _confl_context = {
                    "regime": regime,
                    "iv_regime": _iv_regime_str,
                    "day_posture": _day_posture,
                    "ofi_data": {},  # populated per-signal from scan cache
                    "mtf_trend": {},
                }
                # R4: Feed regime probabilities into confluence for weighted scoring
                try:
                    from src.database.redis import cache as _rcache_confl
                    import json as _json_confl
                    _raw_rp_confl = await _rcache_confl.get("current_regime")
                    if _raw_rp_confl:
                        _rp_confl = _json_confl.loads(_raw_rp_confl)
                        _confl_context["regime_probabilities"] = _rp_confl.get("regime_probabilities", {})
                except Exception:
                    pass
                # F6: Feed sentiment + smart money data into confluence
                try:
                    from src.core.agent_manager import agent_manager as _am_sent
                    _sa = _am_sent.agents.get("sentiment") if _am_sent else None
                    if _sa:
                        _confl_context["sentiment_score"] = float(getattr(_sa, "global_sentiment", 0.0) or 0.0)
                        _confl_context["sentiment_label"] = getattr(_sa, "sentiment_classification", "NEUTRAL")
                except Exception:
                    pass
                for _sig in generated_signals:
                    # Per-signal OFI from scan cache
                    _sig_ctx = dict(_confl_context)
                    _scan_data = self._scan_cache.get(_sig.symbol, {})
                    if _scan_data:
                        _sig_ctx["ofi_data"] = {
                            "net_ofi": float(_scan_data.get("ofi", {}).get("net_ofi", 0) if isinstance(_scan_data.get("ofi"), dict) else 0),
                        }
                        _sig_ctx["sector_rs"] = float(_scan_data.get("sector_rs", 0)) if "sector_rs" in _scan_data else None
                    _sig.metadata["strategy_category"] = self._classify_strategy(_sig.strategy_name).upper() if hasattr(self, '_classify_strategy') else ""
                    _result = await _cs.score(_sig.__dict__ if hasattr(_sig, '__dict__') else {"symbol": _sig.symbol, "signal_type": _sig.signal_type, "strength": _sig.strength, "strategy_name": _sig.strategy_name, "metadata": _sig.metadata}, _sig_ctx)
                    _sig.metadata["confluence_score"] = _result["score"]
                    _sig.metadata["confluence_tier"] = _result["conviction_tier"]
                    _sig.metadata["confluence_factors"] = {k: v["confirms"] for k, v in _result["factors"].items()}
                    if _result["pass"]:
                        # Store confluence size_multiplier as metadata — risk agent
                        # uses it for position sizing (Kelly * confluence_mult).
                        # DO NOT modify _sig.strength here: downstream G8 gate evaluates
                        # strength as a quality measure; applying the size_mult here
                        # cascades with Gemini's adj_str and kills options signals below
                        # the G8 threshold (e.g. 0.64 × 0.80 = 0.512 < 0.60 → rejected).
                        _sig.metadata["confluence_size_mult"] = _result["size_multiplier"]
                        _confluent.append(_sig)
                    else:
                        logger.info(
                            f"AUDIT-L5: {_sig.symbol} {_sig.signal_type} REJECTED "
                            f"(confluence {_result['score']}/6 < min)"
                        )
                if len(_confluent) < _pre_confl:
                    logger.info(
                        f"AUDIT-L5 Confluence Gate: {_pre_confl} → {len(_confluent)} signals "
                        f"(rejected {_pre_confl - len(_confluent)} weak-confluence)"
                    )
                generated_signals = _confluent
            except Exception as _confl_err:
                logger.debug(f"AUDIT-L5: Confluence scoring failed ({_confl_err}), passing all signals")
        # ── End AUDIT Layer-5 ─────────────────────────────────────────────

        # 5a. Confluence filter — resolve conflicting multi-strategy signals
        if generated_signals and len(generated_signals) > 1:
            generated_signals = await self._apply_confluence_filter(generated_signals)

        # 5b. Options path — run options-mode strategies against cached chain data
        if self._options_chain_cache:
            options_signals = await self._run_options_strategies(regime, sentiment)
            if options_signals:
                generated_signals.extend(options_signals)
                logger.info(f"Options path added {len(options_signals)} signals")

        # 5c. GenAI validation — validate the merged equity/options batch once.
        # This preserves portfolio-level coherence while avoiding a second
        # large prompt round-trip when both paths produce signals.
        if generated_signals and self._ensure_genai_model() and ai_cost_tracker.should_use_ai("strategy"):
            generated_signals = await self._validate_with_genai(
                generated_signals, regime, sentiment,
                session_perf=self._strategy_session_perf
            )

        # 5d. AI Consistency multiplier — reward confirmed signals, dampen new ones
        # Applied AFTER all signal sources (equity + options) are merged so that
        # each signal’s streak reflects cross-cycle persistence, not just intra-cycle dupes.
        if generated_signals:
            _new_count = _confirmed_count = 0
            for _sig in generated_signals:
                _sk = (_sig.symbol, _sig.signal_type)
                _streak = self._signal_streak.get(_sk, 0)
                # Multiplier tiers: new=0.80, seen-once=1.00, seen-twice=1.10, seen-3+=1.25
                if _streak >= 3:
                    _cmult = 1.25
                elif _streak == 2:
                    _cmult = 1.10
                elif _streak == 1:
                    _cmult = 1.00
                else:
                    # First-time signal: BULL regime BUY signals are not dampened
                    if regime == "BULL" and _sig.signal_type in ("BUY", "LONG"):
                        _cmult = 1.00   # Bull rally — trust first-time breakout buy
                    elif regime == "BULL":
                        _cmult = 0.90   # Bull day — mild dampening for non-BUY signals
                    else:
                        _cmult = 0.80   # Standard: need at least one confirmation
                    _new_count += 1
                if _cmult > 1.0:
                    _confirmed_count += 1
                if _cmult != 1.0:
                    _sig.metadata["signal_quality_score"] = round(
                        _sig.metadata.get("signal_quality_score", 0) * _cmult, 4
                    )
                _sig.metadata["signal_streak"]    = _streak
                _sig.metadata["is_new_signal"]    = (_streak == 0)
                _sig.metadata["consistency_mult"] = _cmult
            # Re-sort after consistency adjustment so confirmed signals rise
            generated_signals.sort(
                key=lambda s: s.metadata.get("signal_quality_score", 0), reverse=True
            )
            if _new_count or _confirmed_count:
                logger.info(
                    f"[AI-STREAK] {_confirmed_count} confirmed signals boosted | "
                    f"{_new_count} new signals (streak=0; regime={regime}; bull_buy_exempt)"
                )

        # 5e. Update streak tracker for NEXT cycle
        _this_cycle_keys: set = set()
        for _sig in generated_signals:
            _sk = (_sig.symbol, _sig.signal_type)
            _this_cycle_keys.add(_sk)
            if _sk in self._prev_cycle_signals:
                self._signal_streak[_sk] = min(self._signal_streak.get(_sk, 0) + 1, 5)
            else:
                self._signal_streak[_sk] = 1          # first appearance
        # Decay: remove entries for symbols that didn’t fire this cycle
        for _sk in list(self._signal_streak.keys()):
            if _sk not in _this_cycle_keys:
                del self._signal_streak[_sk]
        self._prev_cycle_signals = _this_cycle_keys
        # ── End AI streak tracking ─────────────────────────────────────────────

        # ── AUDIT: Dynamic Intraday→Swing Strategy Switching ─────────────────
        # When an intraday position is in significant profit (>2% with trailing SL
        # protecting gains), evaluate whether the signal has swing-grade conviction.
        # If regime, sentiment, and MTF all support continuation, generate a
        # parallel SWING signal (CNC) while the intraday (MIS) continues.
        # This captures multi-day moves that intraday SL would otherwise cut.
        try:
            from src.core.agent_manager import agent_manager as _am_sw
            if _am_sw:
                _port_sw = _am_sw.agents.get("portfolio")
                _sim_pos = {**getattr(_port_sw, "simulated_positions", {}), **getattr(_port_sw, "positions", {})} if _port_sw else {}
                _swing_candidates = []
                for _psym, _pdata in _sim_pos.items():
                    if _pdata.get("status") != "OPEN":
                        continue
                    _product = str(_pdata.get("product_type", "MIS")).upper()
                    if _product not in ("MIS", "INTRA"):
                        continue
                    _entry = float(_pdata.get("entry_price", 0) or 0)
                    _ltp = float(_pdata.get("ltp", 0) or 0)
                    if _entry <= 0 or _ltp <= 0:
                        continue
                    _pnl_pct = (_ltp - _entry) / _entry if str(_pdata.get("side", "BUY")).upper() == "BUY" else (_entry - _ltp) / _entry
                    # Require >2% unrealized profit + swing regime alignment
                    if _pnl_pct >= 0.02:
                        _swing_regime = self._latest_swing_regime
                        _side = str(_pdata.get("side", "BUY")).upper()
                        _regime_supports = (
                            (_side == "BUY" and _swing_regime in ("BULL", "SIDEWAYS"))
                            or (_side == "SELL" and _swing_regime in ("BEAR", "VOLATILE"))
                        )
                        if _regime_supports:
                            _swing_candidates.append((_psym, _pdata, _pnl_pct, _side))
                            logger.info(
                                f"AUDIT SWING-SWITCH: {_psym} {_side} intraday P&L={_pnl_pct:.2%} "
                                f"+ {_swing_regime} swing regime → candidate for swing promotion"
                            )

                # Generate swing signals for candidates (max 2 per cycle to avoid over-extending)
                for _csym, _cdata, _cpnl, _cside in _swing_candidates[:2]:
                    _sw_signal = StrategySignal(
                        signal_id=f"SWING_PROMO_{_csym}_{int(datetime.now().timestamp())}",
                        strategy_name=f"{_cdata.get('strategy_name', 'UNKNOWN')}_SWING",
                        symbol=_csym,
                        signal_type=_cside,
                        strength=min(0.85, 0.6 + _cpnl * 5),  # scale strength with profit
                        entry_price=float(_cdata.get("ltp", 0)),
                        stop_loss=float(_cdata.get("entry_price", 0)),  # SL at original entry = worst case breakeven
                        target_price=float(_cdata.get("ltp", 0)) * (1.04 if _cside == "BUY" else 0.96),
                        metadata={
                            "product_type": "CNC",
                            "swing_promotion": True,
                            "original_intraday_entry": float(_cdata.get("entry_price", 0)),
                            "intraday_pnl_pct": round(_cpnl, 4),
                            "swing_regime": self._latest_swing_regime,
                            "rationale": f"Intraday {_cside} in {_cpnl:.1%} profit, swing regime {self._latest_swing_regime} supports continuation",
                        }
                    )
                    generated_signals.append(_sw_signal)
                    logger.info(
                        f"AUDIT SWING-SWITCH: Generated CNC {_cside} signal for {_csym} "
                        f"(intraday profit {_cpnl:.1%} → swing with SL at breakeven)"
                    )
        except Exception as _sw_err:
            logger.debug(f"AUDIT SWING-SWITCH: evaluation failed ({_sw_err})")
        # ── End Dynamic Switching ─────────────────────────────────────────────

        # 6. Publish signals
        if generated_signals:
            logger.info(f"Publishing {len(generated_signals)} signals")
            self.signal_history.extend(generated_signals)
            payload = [s.model_dump(mode='json') for s in generated_signals]
            await self.publish_event("SIGNALS_GENERATED", {"signals": payload})
            # Cache for REST polling — write to BOTH Redis and in-process store
            import json as _json
            from datetime import datetime as _dt, timezone as _tz
            cached = {
                "signals": payload,
                "count": len(payload),
                "generated_at": _dt.now(_tz.utc).isoformat().replace("+00:00", "Z"),
            }
            # In-process store (always succeeds, zero-latency)
            _SIGNAL_STORE.update(cached)
            logger.info(
                f"Signal store updated: {len(payload)} signals, "
                f"symbols={[s.get('symbol') for s in payload[:5]]}"
            )
            # Redis (best-effort — enables multi-process / dashboard access)
            try:
                await _redis_cache.set("latest_signals", _json.dumps(cached), ttl=3600)
                logger.debug("Signals written to Redis cache")
            except Exception as _cache_err:
                logger.warning(f"Redis signal cache write failed (in-process store has data): {_cache_err}")

            # ── Strategy funnel telemetry: visible summary for the full pipeline ──
            try:
                _fn_strats  = len(suitable_strategies)
                _fn_symbs   = len(qualified)
                _fn_raw_sig = sum(len(b) for b in signal_batches)
                _fn_dedup   = len(_seen)
                _fn_pub     = len(payload)
                logger.info(
                    f"📊 STRATEGY FUNNEL | "
                    f"strategies_matched={_fn_strats} "
                    f"symbols_qualified={_fn_symbs} "
                    f"raw_signals={_fn_raw_sig} "
                    f"after_dedup={_fn_dedup} "
                    f"after_confluence={_fn_pub} "
                    f"published={_fn_pub} "
                    f"regime={regime}"
                )
                # Persist funnel stats to Redis for telemetry endpoint
                import json as _fj
                from datetime import datetime as _fdt, timezone as _ftz
                _raw_ft = await _redis_cache.get("strategy_funnel_telemetry")
                _ft = _fj.loads(_raw_ft) if _raw_ft else {"decision_cycles": 0, "total_signals_published": 0, "total_qualified": 0, "total_raw_signals": 0, "session_start": _fdt.now().isoformat()}
                # Reset totals when the cached key is from a prior trading day
                _today_ft = _fdt.now().strftime('%Y-%m-%d')
                if not str(_ft.get("session_start", "")).startswith(_today_ft):
                    _ft = {"decision_cycles": 0, "total_signals_published": 0, "total_qualified": 0, "total_raw_signals": 0, "session_start": _fdt.now().isoformat()}
                _ft["decision_cycles"] = _ft.get("decision_cycles", 0) + 1
                _ft["total_signals_published"] = _ft.get("total_signals_published", 0) + _fn_pub
                _ft["total_qualified"] = _ft.get("total_qualified", 0) + _fn_symbs
                _ft["total_raw_signals"] = _ft.get("total_raw_signals", 0) + _fn_raw_sig
                _ft["last_cycle_strategies_matched"] = _fn_strats
                _ft["last_cycle_symbols_qualified"] = _fn_symbs
                _ft["last_cycle_raw_signals"] = _fn_raw_sig
                _ft["last_cycle_published"] = _fn_pub
                _ft["last_cycle_at"] = _fdt.now(_ftz.utc).isoformat().replace("+00:00", "Z")
                await _redis_cache.set("strategy_funnel_telemetry", _fj.dumps(_ft), ttl=86400)
            except Exception as _fte:
                logger.debug(f"Strategy funnel telemetry failed: {_fte}")
        else:
            # Diagnostic: log WHY no signals were generated so we can debug
            _diag_parts = []
            _diag_parts.append(f"regime={regime}")
            _diag_parts.append(f"strategies_passed_filter={len(suitable_strategies)}")
            _diag_parts.append(f"qualified_symbols={len(qualified)}")
            _diag_parts.append(f"top_n={_top_n}")
            _diag_parts.append(f"paper={'Y' if _is_paper else 'N'}")
            if suitable_strategies:
                _diag_parts.append(
                    f"top_strategies=[{', '.join(s[0].name + ':' + str(round(s[1],1)) for s in suitable_strategies[:5])}]"
                )
            logger.warning(f"No signals generated this cycle | {' | '.join(_diag_parts)}")
    
    async def _filter_by_regime(
        self, regime: str, swing_regime: Optional[str] = None
    ) -> List[tuple]:
        """
        Filter strategies by regime suitability.
        Returns list of (strategy, weighted_score) tuples.
        Includes Improvement #1 (performance feedback), #3 (transition boost),
        and strategy grade integration from StrategyGrader.

        Dual-regime: INTRADAY strategies use the standard intraday 'regime'
        (3-month daily data); SWING strategies use 'swing_regime' (6-month
        data, EMA 14/28/50) for a stable weekly view — avoids whipsawing
        multi-day positions on single-session noise.

        MFT Objective: 10 trades/s, 3× Sharpe, ≥70% win rate.
        Threshold kept at 40 (not 50) to avoid over-filtering in thin regimes
        while grade-based multiplier naturally promotes proven strategies.
        """
        from src.services.order_type_router import get_strategy_trading_style
        _swing_regime = swing_regime or self._latest_swing_regime
        suitable = []
        weights = self.regime_weights.get(regime, self.regime_weights["SIDEWAYS"])

        # Paper mode flag — relax regime filter thresholds so all 49
        # strategies are testable.  Quality control stays in risk agent.
        _is_paper_filter = (
            getattr(settings, "PAPER_TRADING", False)
            or getattr(settings, "MODE", "") in ("PAPER", "LOCAL")
        )

        # ── F4.2: Use regime probability vector if available ──────────────
        # Instead of binary regime → single weight set, use probability-
        # weighted average across all regimes for smoother transitions.
        _regime_probs = None
        try:
            from src.database.redis import cache as _rcache_rp
            import json as _json_rp
            _raw_rp = await _rcache_rp.get("current_regime")
            if _raw_rp:
                _rp_data = _json_rp.loads(_raw_rp)
                _regime_probs = _rp_data.get("regime_probabilities")
        except Exception:
            pass

        # ── Load strategy grade cache (refreshed once per cycle) ──────────
        grade_cache = await self._get_grade_cache()

        for name, strategy in self.strategies.items():
            try:
                # Create minimal market data for suitability check
                # (strategies should handle empty data gracefully)
                market_data = pd.DataFrame()

                # Apply regime weight based on strategy type + effective regime
                # SWING strategies use the slower weekly swing_regime to avoid
                # whipsawing multi-day positions on intraday noise.
                strategy_type = self._classify_strategy(name)
                strat_style = get_strategy_trading_style(name)
                effective_regime = regime if strat_style == "INTRADAY" else _swing_regime
                base_score = await strategy.calculate_suitability(market_data, effective_regime)
                weights = dict(self.regime_weights.get(effective_regime, self.regime_weights["SIDEWAYS"]))

                # ── Sentiment tilt: nudge weights when sentiment diverges from regime ──
                # Sentiment (-1.0 to +1.0) adds a small directional bias on top of the
                # regime-based weights.  Max tilt = ±0.15 so sentiment can never override
                # regime — it can only tip borderline strategies at the margin.
                # Example: sentiment=+0.8 in SIDEWAYS → momentum gets +0.12,  hedge −0.12
                #          sentiment=−0.8 in BULL     → momentum gets −0.12,  hedge +0.12
                _sent = float(self._latest_sentiment) if hasattr(self, "_latest_sentiment") else 0.0
                if abs(_sent) >= 0.10:  # ignore negligible noise (|score| < 0.10)
                    _tilt = round(_sent * 0.15, 3)   # ±0.15 cap
                    weights["momentum"]       = max(0.30, weights.get("momentum",       1.0) + _tilt)
                    weights["trend"]          = max(0.30, weights.get("trend",          1.0) + _tilt * 0.7)
                    weights["mean_reversion"] = max(0.30, weights.get("mean_reversion", 1.0) - _tilt * 0.5)
                    weights["hedge"]          = max(0.30, weights.get("hedge",          1.0) - _tilt)
                    # Volatile / theta strategies are sentiment-neutral — no tilt applied

                weight = weights.get(strategy_type, 1.0)

                # F4.2: If probability vector is available, use it for smooth weighting
                if _regime_probs and isinstance(_regime_probs, dict):
                    try:
                        weight = regime_weighted_strategy_scores(
                            _regime_probs, self.regime_weights, strategy_type,
                        )
                    except Exception:
                        pass  # fall back to binary weight
                
                weighted_score = base_score * weight

                # ── Improvement #1: Performance Feedback multiplier ───────
                # Paper mode: skip performance/grade penalties entirely.
                # ALL 49 strategies must be testable in paper mode.
                # Quality control happens downstream (risk agent + Gemini).
                if not _is_paper_filter:
                    perf_mult = await self._performance_multiplier(name)
                    weighted_score *= perf_mult
                else:
                    perf_mult = 1.0

                # ── Strategy Grade multiplier (S/A/B/C/D/F) ──────────────
                # Integrates the multi-tier grading system into live selection.
                # S/A grades get boosted → higher probability of selection.
                # D/F grades get penalised → still selectable but need strong
                # regime fit to overcome (avoids zero-trade scenarios).
                if not _is_paper_filter:
                    grade_mult = self._grade_multiplier(name, grade_cache)
                    weighted_score *= grade_mult
                else:
                    grade_mult = 1.0

                # ── Improvement #3: Regime Transition suitability boost ───
                transition = self._latest_regime_transition
                if transition == "BREAKOUT_FROM_RANGE" and strategy_type in ("momentum", "trend"):
                    weighted_score += 20
                elif transition == "TOPPING_OUT" and strategy_type in ("hedge", "theta"):
                    weighted_score += 20
                elif transition == "BREAKDOWN" and strategy_type == "hedge":
                    weighted_score += 15
                
                # Paper mode: threshold=25 — still permissive for testing but
                # blocks clearly unsuitable strategies (e.g. mean_reversion score=30
                # in BULL regime). Day22 fix: was 10, letting everything through.
                # Live mode keeps 40 for curated selection.
                _threshold = 25.0 if _is_paper_filter else 40.0
                if weighted_score > _threshold:
                    suitable.append((strategy, weighted_score))
                else:
                    logger.debug(
                        f"Filtered out {name}: base={base_score:.0f} * w={weight:.1f} "
                        f"* perf={perf_mult:.2f} * grade={grade_mult:.2f} = {weighted_score:.1f} (<= {_threshold})"
                    )
                    
            except Exception as e:
                logger.debug(f"Suitability check failed for {name}: {e}")
        
        # Sort by weighted score
        suitable.sort(key=lambda x: x[1], reverse=True)
        
        if suitable:
            logger.info(
                f"Regime filter [{regime}]: {len(suitable)}/{len(self.strategies)} strategies passed "
                f"(top: {', '.join(f'{s[0].name}={s[1]:.0f}' for s in suitable[:5])})"
            )
        else:
            _thr_display = 10 if _is_paper_filter else 40
            logger.warning(
                f"Regime filter [{regime}]: 0/{len(self.strategies)} strategies passed threshold >{_thr_display}. "
                f"Check strategy suitability scores. (paper={_is_paper_filter})"
            )
        
        return suitable

    def _derive_stock_local_regime(
        self,
        symbol: str,
        market_data: pd.DataFrame,
        macro_regime: str,
        strategy_type: str,
    ) -> str:
        """
        Derive per-stock local regime from scanner-injected technical indicators.

        The macro regime (BEAR/VOLATILE/BULL/SIDEWAYS) reflects broad NIFTY/BANKNIFTY
        movement. Individual stocks diverge based on their own EMA alignment, relative
        strength vs NIFTY, and ADX direction — a sector rotator or fundamentally strong
        stock may trend BULL even during VOLATILE or BEAR macro conditions.

        Only overrides for DIRECTIONAL strategy types (momentum, trend, mean_reversion).
        Hedge and theta strategies always use macro regime — they are portfolio-level
        insurance decisions, not per-stock directional plays.

        Injected columns (written to market_data by _fetch via scanner cache):
            scan_rs_vs_nifty          — 15-day return ratio vs NIFTY 50
            scan_ema_aligned          — 1.0 if price > EMA20 > EMA50 > EMA200
            scan_ema_partial_aligned  — 1.0 if partial bull EMA stack
            scan_di_plus/scan_di_minus — ADX directional indicator lines
            scan_rsi                  — 14-period RSI
            sentiment_score           — per-stock news sentiment (SentimentAgent)
        """
        # Portfolio-level strategies always use macro regime
        if strategy_type in ("hedge", "theta"):
            return macro_regime

        try:
            # Fast path: use scanner's pre-computed per-stock regime if available
            if "scan_stock_regime" in market_data.columns:
                _sr = str(market_data["scan_stock_regime"].iloc[-1])
                if _sr in ("BULL", "BEAR", "SIDEWAYS", "VOLATILE"):
                    return _sr

            def _col(name: str, default: float) -> float:
                """Safely read last value of a market_data column."""
                if name in market_data.columns:
                    try:
                        return float(market_data[name].iloc[-1])
                    except Exception:
                        pass
                return default

            rs_vs_nifty = _col("scan_rs_vs_nifty",        1.0)
            ema_aligned = _col("scan_ema_aligned",         0.0)  # 1.0 = full bull stack
            ema_partial = _col("scan_ema_partial_aligned", 0.0)  # 1.0 = partial alignment
            di_plus     = _col("scan_di_plus",            25.0)
            di_minus    = _col("scan_di_minus",           25.0)
            rsi         = _col("scan_rsi",                50.0)
            sentiment   = _col("sentiment_score",          0.0)

            # ── Bull evidence (stock is stronger than macro suggests) ─────────
            bull = 0
            if ema_aligned >= 0.5:        bull += 3  # Full EMA bull stack confirmed
            elif ema_partial >= 0.5:      bull += 1  # Partial alignment — moderate signal
            if rs_vs_nifty >= 1.10:       bull += 2  # >10% alpha vs NIFTY: outperformer
            elif rs_vs_nifty >= 1.02:     bull += 1  # Slight outperformer
            if di_plus > di_minus + 5:    bull += 2  # ADX: directional bull bias confirmed
            if rsi > 55:                  bull += 1  # Mild momentum confirmation
            if sentiment > 0.25:          bull += 1  # Positive stock-specific news

            # ── Bear evidence (stock is weaker than macro suggests) ───────────
            bear = 0
            if ema_aligned < 0.5 and ema_partial < 0.5:  bear += 2  # No EMA alignment
            if rs_vs_nifty < 0.92:        bear += 2  # Underperforming index by >8%
            if di_minus > di_plus + 5:    bear += 2  # ADX: directional bear bias
            if rsi < 45:                  bear += 1  # Oversold/weak momentum
            if sentiment < -0.25:         bear += 1  # Negative stock-specific news

            # ── Override decision ─────────────────────────────────────────────
            if bull >= 5 and macro_regime in ("BEAR", "VOLATILE", "SIDEWAYS"):
                # Stock is individually bullish despite weak/volatile macro environment.
                # Directional strategies will generate BULL-context signals while risk
                # agent applies VOLATILE/BEAR position-size constraints from macro.
                logger.debug(
                    f"Stock regime override: {symbol} macro={macro_regime} → BULL "
                    f"(bull={bull} ema={ema_aligned:.0f}/{ema_partial:.0f} "
                    f"rs={rs_vs_nifty:.2f} di+={di_plus:.0f} di-={di_minus:.0f} "
                    f"rsi={rsi:.0f} sent={sentiment:.2f})"
                )
                return "BULL"

            if bear >= 5 and macro_regime in ("BULL", "SIDEWAYS"):
                # Stock is individually weak in an otherwise constructive macro.
                # Directional strategies will generate BEAR-context signals.
                logger.debug(
                    f"Stock regime override: {symbol} macro={macro_regime} → BEAR "
                    f"(bear={bear} ema={ema_aligned:.0f}/{ema_partial:.0f} "
                    f"rs={rs_vs_nifty:.2f} di+={di_plus:.0f} di-={di_minus:.0f} "
                    f"rsi={rsi:.0f} sent={sentiment:.2f})"
                )
                return "BEAR"

            # Day22 fix: detect SIDEWAYS when evidence is inconclusive.
            # Previously returned macro_regime, masking sideways stocks in BULL macro.
            if bull < 3 and bear < 3:
                logger.debug(
                    f"Stock regime: {symbol} → SIDEWAYS (bull={bull} bear={bear} "
                    f"inconclusive, macro={macro_regime})"
                )
                return "SIDEWAYS"

            return macro_regime

        except Exception:
            return macro_regime

    # ── Strategy Grade Integration ────────────────────────────────────────
    async def _get_grade_cache(self) -> Dict[str, Dict[str, Any]]:
        """
        Load strategy grade data from Redis cache (written by /api/strategies/grades).
        Returns {strategy_name: {grade, compositeScore, sharpe, winRate, ...}} or {}.
        Cached per-cycle to avoid repeated I/O.
        """
        if hasattr(self, '_grade_cache_ts'):
            from datetime import datetime as _dt, timezone as _tz
            # Refresh at most once per 3 minutes (matches orchestration cycle)
            if (_dt.now(_tz.utc) - self._grade_cache_ts).total_seconds() < 180:
                return getattr(self, '_grade_cache_data', {})

        try:
            raw = await _redis_cache.get("strategy_grades_cache")
            if raw:
                import json as _json
                data = _json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
                cache = {s["strategyName"]: s for s in data.get("strategies", [])}
            else:
                cache = {}
        except Exception:
            cache = {}

        from datetime import datetime as _dt, timezone as _tz
        self._grade_cache_ts = _dt.now(_tz.utc)
        self._grade_cache_data = cache
        return cache

    @staticmethod
    def _grade_multiplier(strategy_name: str, grade_cache: Dict[str, Dict]) -> float:
        """
        Map strategy grade (S/A/B/C/D/F) to a selection multiplier.

        MFT philosophy: reward proven strategies but don't block ungraded ones.
        - S grade:   1.30  (marketplace-ready, heavily boost)
        - A grade:   1.20  (live-ready, solid boost)
        - B grade:   1.10  (paper-ready, slight boost)
        - C grade:   1.00  (neutral — needs optimisation)
        - D grade:   0.85  (high risk — mild penalty)
        - F grade:   0.70  (not viable — significant penalty)
        - Ungraded:  1.00  (no data yet — no penalty, let perf_multiplier handle)

        Additionally, if grading data includes Sharpe > 2.0 or WinRate > 65%,
        apply an extra nudge (+0.05 each) to directly reward these KPIs.
        """
        info = grade_cache.get(strategy_name)
        if not info:
            return 1.0

        grade = info.get("grade", "C")
        _GRADE_MULT = {
            "S": 1.30, "A": 1.20, "B": 1.10,
            "C": 1.00, "D": 0.85, "F": 0.70,
        }
        mult = _GRADE_MULT.get(grade, 1.0)

        # Bonus nudge for standout Sharpe / WinRate from grading report
        sharpe = info.get("sharpe", 0)
        win_rate = info.get("winRate", 0)
        if sharpe >= 2.0:
            mult += 0.05
        if win_rate >= 65:
            mult += 0.05

        return mult

    async def _run_options_strategies(
        self, regime: str, sentiment: float
    ) -> list:
        """
        Run all options-mode strategies against the cached option chain data.

        For each opportunity in _options_chain_cache:
          1. Build a minimal 1-row DataFrame carrying spot price + chain metrics so
             the strategy can call option_chain_service.get_chain() internally.
          2. Temporarily set strategy.config["symbol"] to route the right chain.
          3. Collect and return all generated signals.

        Options-mode strategies are identified by config["mode"] == "options".
        Only strategies whose config["structure"] matches the chain's best-fit
        structure are paired, reducing noise.
        """
        options_strategies = [
            s for s in self.strategies.values()
            if getattr(s, "config", {}).get("mode") == "options"
        ]
        if not options_strategies:
            return []

        # Read orchestration directives from pipeline context
        _pref_structures: list = []
        _options_focus: float = 0.3
        try:
            from src.core.agent_manager import agent_manager as _am_opt
            if _am_opt:
                _pctx = _am_opt.get_pipeline_context()
                _pref_structures = _pctx.get("preferred_structures", [])
                _options_focus = float(_pctx.get("options_focus", 0.3))
        except Exception:
            pass

        # If orchestrator suppressed options this cycle, skip entirely
        if _options_focus <= 0.05:
            logger.info("Options path skipped: orchestrator options_focus ≤ 0.05")
            return []

        results = []

        for symbol, chain_opp in self._options_chain_cache.items():
            best_structure = chain_opp.get("structure", "")
            spot = chain_opp.get("spot_price", 0)
            if spot <= 0:
                continue

            # Build a minimal DataFrame: single-row representation so strategies
            # can at least pass the `market_data.empty` guard. Strategies will
            # internally re-fetch the full chain via option_chain_service.
            minimal_df = pd.DataFrame([{
                "close": spot,
                "open": spot,
                "high": spot,
                "low": spot,
                "volume": 1,
                "spot_price": spot,
                "iv_rank": chain_opp.get("iv_rank", 50),
                "atm_iv": chain_opp.get("atm_iv", 0),
                "oi_pcr": chain_opp.get("oi_pcr", 1.0),
                "atm_strike": chain_opp.get("atm_strike", 0),
                "expiry": chain_opp.get("expiry", ""),
                "greek_regime": chain_opp.get("greek_regime", "BALANCED"),
                "dte_days": chain_opp.get("dte_days", 7),
                "delta_short_call_strike": chain_opp.get("delta_short_call_strike", 0),
                "delta_long_call_strike": chain_opp.get("delta_long_call_strike", 0),
                "delta_short_put_strike": chain_opp.get("delta_short_put_strike", 0),
                "delta_long_put_strike": chain_opp.get("delta_long_put_strike", 0),
                "options_score": chain_opp.get("score", 0),
            }])
            minimal_df["symbol"] = symbol
            minimal_df["options_chain"] = [chain_opp]

            # Per-stock sentiment: prefer stock-specific over global
            _per_stock_map: dict = getattr(self, "_stock_sentiments", {})
            _stock_sent = _per_stock_map.get(symbol, sentiment)

            # Per-stock regime from scanner cache or option chain macro_regime
            _stock_regime = chain_opp.get("stock_regime") or regime
            # Also check equity scanner cache for this symbol's regime
            _eq_scan = self._scan_cache.get(symbol, {})
            _eq_regime = _eq_scan.get("indicators", {}).get("stock_regime")
            if _eq_regime and _eq_regime in ("BULL", "BEAR", "SIDEWAYS", "VOLATILE"):
                _stock_regime = _eq_regime

            for strategy in options_strategies:
                strat_structure = strategy.config.get("structure")
                # Route: only run if structures match (or strategy has no structure)
                if strat_structure and strat_structure != best_structure:
                    # Allow if orchestrator prefers this structure even if chain suggests different
                    if strat_structure not in _pref_structures:
                        continue

                # Temporarily point strategy at this symbol
                old_symbol = strategy.config.get("symbol")
                strategy.config["symbol"] = symbol
                try:
                    signal = await strategy.generate_signal(minimal_df, _stock_regime)
                    if signal:
                        signal.metadata["options_chain_score"] = chain_opp.get("score", 0)
                        signal.metadata["iv_rank"] = chain_opp.get("iv_rank", 0)
                        signal.metadata["oi_pcr"] = chain_opp.get("oi_pcr", 1.0)
                        signal.metadata["sentiment_score"] = _stock_sent
                        signal.metadata["regime"] = regime
                        signal.metadata["stock_regime"] = _stock_regime
                        # Orchestrator boost: preferred structures get +15% strength
                        if _pref_structures and strat_structure in _pref_structures:
                            signal.strength = min(1.0, signal.strength * 1.15)
                            signal.metadata["orchestrator_boosted"] = True
                        signal.strategy_name = strategy.name  # tag with instance name
                        results.append(signal)
                        # Handle both StrategySignal and OptionsSignal logging
                        sig_type = getattr(signal, "signal_type", getattr(signal, "structure_type", "OPTIONS"))
                        logger.info(
                            f"Options signal: {sig_type} {symbol} "
                            f"from {strategy.name} (chain_score={chain_opp.get('score', 0):.1f})"
                        )
                except Exception as exc:
                    logger.debug(
                        f"Options strategy {strategy.name} failed for {symbol}: {exc}"
                    )
                finally:
                    # Restore original symbol (or remove key if it wasn't set before)
                    if old_symbol is None:
                        strategy.config.pop("symbol", None)
                    else:
                        strategy.config["symbol"] = old_symbol

        return results

    # ── Explicit strategy → type map (avoids keyword misclassification) ─────
    _STRATEGY_TYPE_MAP: Dict[str, str] = {
        # Mean-reversion family
        "vwap_reversion": "mean_reversion",
        "bb_squeeze": "mean_reversion",
        "rsi_divergence": "mean_reversion",
        "mr_scalper": "mean_reversion",
        "gap_fill": "mean_reversion",
        "rs_pair_trade": "mean_reversion",
        "alpha_stat_arb_301": "mean_reversion",
        "universalstrategy_equity": "mean_reversion",
        # Theta / options-premium family
        "iron_condor": "theta",
        "alpha_short_straddle_501": "theta",
        "alpha_short_strangle_502": "theta",
        "alpha_iron_butterfly_503": "theta",
        "alpha_butterfly_012": "theta",
        "alpha_calendar_010": "theta",
        "alpha_straddle_014": "theta",
        "alpha_strangle_013": "theta",
        "theta_capture": "theta",
        "volatility_crush": "theta",
        "bull_call_spread": "theta",
        "alpha_bearput_008": "theta",
        "universalstrategy_bullcallspread": "theta",
        "universalstrategy_bearputspread": "theta",
        "universalstrategy_straddle": "theta",
        "index_options_scalper": "theta",
        # Hedge family
        "portfolio_hedge": "hedge",
        "alpha_delta_016": "hedge",
        "alpha_vix_015": "hedge",
        # Trend family
        "trend_pullback": "trend",
        "ema_crossover": "trend",
        "alpha_trend_003": "trend",
        "swing_breakout": "trend",
        # Momentum family
        "orb_momentum": "momentum",
        "momentum_rotation": "momentum",
        "sector_rotation": "momentum",
        "earnings_momentum": "momentum",
        "atr_breakout": "momentum",
        "alpha_ofi_004": "momentum",
        "alpha_sentiment_005": "momentum",
        "alpha_cross_mom_402": "momentum",
        "alpha_vol_arb_401": "momentum",
        "orb_vwap_fusion": "momentum",
        "power_first_hour": "momentum",
        # ── ALPHA_ ID aliases — strategy classes now emit these names directly ──
        "alpha_orb_001": "momentum",           # was "orb_momentum"
        "alpha_vwap_002": "mean_reversion",    # was "vwap_reversion"
        "alpha_bcs_007": "theta",              # was "bull_call_spread"
        "alpha_iron_011": "theta",             # was "iron_condor"
        "alpha_port_017": "hedge",             # was "portfolio_hedge"
        "alpha_breakout_101": "trend",         # was "swing_breakout"
        "alpha_pullback_102": "trend",         # was "trend_pullback"
        "alpha_ema_cross_104": "trend",        # was "ema_crossover"
        "alpha_momentum_201": "momentum",      # was "momentum_rotation"
        "alpha_sector_202": "momentum",        # was "sector_rotation"
        "alpha_bb_203": "mean_reversion",      # was "bb_squeeze"
        "alpha_rsi_div_204": "mean_reversion", # was "rsi_divergence"
        "alpha_earn_205": "momentum",          # was "earnings_momentum"
        "alpha_gap_206": "mean_reversion",     # was "gap_fill"
        "alpha_atr_207": "momentum",           # was "atr_breakout"
        "alpha_vol_crush_208": "theta",        # was "volatility_crush"
        "alpha_orb_vwap_307": "momentum",      # was "orb_vwap_fusion"
        "alpha_mr_scalp_302": "mean_reversion",# was "mr_scalper"
        "alpha_idx_scalp_303": "theta",        # was "index_options_scalper"
        "alpha_pfth_304": "momentum",          # was "power_first_hour"
        "alpha_rs_pair_305": "mean_reversion", # was "rs_pair_trade"
        "alpha_theta_306": "theta",            # was "theta_capture"
    }

    def _classify_strategy(self, strategy_name: str) -> str:
        """Classify strategy into type for regime weighting.

        Uses an explicit map first (covers all 42+ registered strategies),
        then falls back to keyword matching for any future additions.
        """
        name_lower = strategy_name.lower()

        # Explicit map — deterministic, no keyword ambiguity
        mapped = self._STRATEGY_TYPE_MAP.get(name_lower)
        if mapped:
            return mapped

        # Keyword fallback for unregistered/future strategies
        if any(x in name_lower for x in ["momentum", "orb", "breakout", "rotation", "earnings"]):
            return "momentum"
        elif any(x in name_lower for x in ["trend", "ema", "pullback", "swing"]):
            return "trend"
        elif any(x in name_lower for x in ["vwap", "reversion", "mean", "bb", "rsi", "scalper", "pair", "arb"]):
            return "mean_reversion"
        elif any(x in name_lower for x in ["condor", "spread", "theta", "straddle", "strangle",
                                            "butterfly", "calendar", "crush", "iron"]):
            return "theta"
        elif any(x in name_lower for x in ["hedge", "protect", "delta", "vix"]):
            return "hedge"
        else:
            return "mean_reversion"  # Safer default — gets neutral-to-good weight in all regimes

    # ── Improvement #4 — Dynamic Top-N Strategy Selection ─────────────────
    def _dynamic_top_n(self, suitable: list) -> int:
        """
        Determine how many strategies to deploy based on score distribution.

        Scores already include _performance_multiplier (Sharpe/WinRate/PF weighting)
        + _grade_multiplier (S/A/B/C/D/F) from _filter_by_regime, so this
        selection inherently favours high-Sharpe, high-win-rate strategies.

        Paper mode: Run ALL suitable strategies (no hard cap) for maximum
        coverage during testing. Quality control still applies upstream
        (grade + performance multipliers) and downstream (risk agent).

        Live mode rules (MFT-tuned Mar 2026):
          - top_score >= 80 and 5+ above 60  → top 15  (high conviction)
          - top_score >= 70 and 4+ above 55  → top 12  (good regime)
          - top_score >= 60 and 3+ above 50  → top 10  (normal — most common)
          - 2+ above 45                      → top 8   (mixed regime)
          - at least 1 above 40              → 5       (thin market)
          - otherwise                        → 0
        """
        if not suitable:
            return 0

        # Paper mode: deploy all suitable strategies for max testing coverage
        _is_paper = getattr(settings, "PAPER_TRADING", False) or \
                    getattr(settings, "MODE", "") in ("PAPER", "LOCAL")
        if _is_paper:
            n = len(suitable)
            logger.info(
                f"Dynamic Top-N (PAPER): deploying ALL {n} suitable strategies "
                f"(no hardcap — full 51-strategy coverage)"
            )
            return n

        top_score = suitable[0][1]
        above_60 = sum(1 for _, s in suitable if s >= 60)
        above_55 = sum(1 for _, s in suitable if s >= 55)
        above_50 = sum(1 for _, s in suitable if s >= 50)
        above_45 = sum(1 for _, s in suitable if s >= 45)
        above_40 = sum(1 for _, s in suitable if s >= 40)

        if top_score >= 80 and above_60 >= 5:
            n = min(15, len(suitable))
        elif top_score >= 70 and above_55 >= 4:
            n = min(12, len(suitable))
        elif top_score >= 60 and above_50 >= 3:
            n = min(10, len(suitable))
        elif above_45 >= 2:
            n = min(8, above_45)
        elif above_40 >= 1:
            n = 5
        else:
            n = 0

        logger.info(
            f"Dynamic Top-N: deploying {n} strategies "
            f"(top_score={top_score:.1f}, >60={above_60}, >55={above_55}, "
            f">50={above_50}, >45={above_45}, >40={above_40})"
        )
        return n

    # ── Improvement #2 — Multi-Strategy Signal Confluence Filter ──────────
    async def _apply_confluence_filter(
        self, signals: List[StrategySignal]
    ) -> List[StrategySignal]:
        """
        Group signals by symbol.  For each symbol:
          - Majority agree on direction → keep strongest, boost strength
          - Conflicting directions      → drop (no signal emitted)
          - Solo signal                 → keep at original strength
          - Non-directional (IRON_CONDOR, STRADDLE etc.) → pass through
        """
        from collections import defaultdict

        _DIRECTIONAL = {"BUY", "SELL"}
        # Option structures (Covered Call, Cash-Secured Put, Credit Spread)
        # are structurally hedged — their BUY/SELL label does NOT reflect
        # a pure directional bet.  Treating them as "directional" causes
        # false conflicts (e.g. CCALL BUY vs CSP SELL on same stock).
        _OPTION_STRUCTURES = {
            "COVERED_CALL", "CASH_SECURED_PUT", "CREDIT_SPREAD",
            "SHORT_PUT_SPREAD", "SHORT_CALL_SPREAD", "IRON_CONDOR",
            "IRON_BUTTERFLY", "STRADDLE", "STRANGLE",
        }

        by_symbol: Dict[str, list] = defaultdict(list)
        passthrough: List[StrategySignal] = []
        for sig in signals:
            _struct = getattr(sig, "structure_type", None) or sig.metadata.get("structure", "")
            if _struct and str(_struct).upper() in _OPTION_STRUCTURES:
                # Option-structure signal — bypass directional conflict check
                passthrough.append(sig)
            elif sig.signal_type in _DIRECTIONAL:
                by_symbol[sig.symbol].append(sig)
            else:
                # Non-directional signals (Iron Condor, Straddle, etc.)
                # bypass confluence — they are structurally hedged already.
                passthrough.append(sig)

        filtered: List[StrategySignal] = list(passthrough)
        for symbol, sym_signals in by_symbol.items():
            buy_count = sum(1 for s in sym_signals if s.signal_type == "BUY")
            sell_count = sum(1 for s in sym_signals if s.signal_type == "SELL")
            total = len(sym_signals)

            if total == 1:
                # Solo signal — keep as-is
                filtered.append(sym_signals[0])
            elif buy_count > sell_count and buy_count >= total * 0.5:
                best = max(
                    (s for s in sym_signals if s.signal_type == "BUY"),
                    key=lambda s: s.strength,
                )
                best.strength = min(1.0, best.strength + 0.1 * (buy_count - 1))
                best.metadata["confluence"] = f"{buy_count}/{total} strategies agree BUY"
                filtered.append(best)
            elif sell_count > buy_count and sell_count >= total * 0.5:
                best = max(
                    (s for s in sym_signals if s.signal_type == "SELL"),
                    key=lambda s: s.strength,
                )
                best.strength = min(1.0, best.strength + 0.1 * (sell_count - 1))
                best.metadata["confluence"] = f"{sell_count}/{total} strategies agree SELL"
                filtered.append(best)
            else:
                logger.info(
                    f"Confluence filter: dropping {symbol} "
                    f"(BUY={buy_count}, SELL={sell_count} — conflicting)"
                )

        logger.info(
            f"Confluence filter: {len(signals)} raw → {len(filtered)} after filter "
            f"({len(passthrough)} non-directional passed through)"
        )
        return filtered

    # ── Improvement #1 — Performance Feedback Loop ────────────────────────
    async def _performance_multiplier(self, strategy_name: str) -> float:
        """
        Boost or penalise strategy based on recent real performance.
        Queries last 30 closed trades for this strategy from DB.

        Scoring: combined weight of win_rate (40%) + sharpe_proxy (40%)
        + profit_factor (20%).  Returns multiplier in [0.4, 1.5].

        This ensures strategies with high Sharpe but moderate win rate
        (e.g., trend-followers) are not unfairly penalised, and
        strategies with high win rate but poor risk-adjusted returns
        (e.g., scalpers with large tail losses) are properly discounted.
        """
        try:
            from src.database.postgres import db
            if db.pool is None:
                return 1.0

            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT realized_pnl + unrealized_pnl AS pnl
                    FROM open_positions
                    WHERE status IN ('SL_HIT', 'TARGET_HIT', 'CLOSED')
                      AND strategy_name = $1
                      AND updated_at >= NOW() - INTERVAL '20 days'
                    ORDER BY updated_at DESC
                    LIMIT 30
                    """,
                    strategy_name,
                )

            if not rows or len(rows) < 5:
                return 1.0  # insufficient data — no adjustment

            import numpy as _np
            trades = [float(r["pnl"]) for r in rows]
            arr = _np.array(trades)
            wins = sum(1 for t in trades if t > 0)
            win_rate = wins / len(trades)

            # Sharpe proxy: mean / stdev of PnL
            sharpe_proxy = float(arr.mean() / arr.std()) if arr.std() > 0 else 0.0

            # Profit factor: gross profit / gross loss
            gross_profit = float(arr[arr > 0].sum()) if (arr > 0).any() else 0.0
            gross_loss = float(abs(arr[arr < 0].sum())) if (arr < 0).any() else 0.01
            profit_factor = gross_profit / max(gross_loss, 0.01)

            # Composite score: 0-100 scale
            # Win rate component (0-40): >65% = 40, <35% = 0
            wr_score = max(0, min(40, (win_rate - 0.35) / 0.30 * 40))
            # Sharpe component (0-40): >2.0 = 40, <0 = 0
            sp_score = max(0, min(40, sharpe_proxy / 2.0 * 40))
            # Profit factor component (0-20): >2.0 = 20, <0.5 = 0
            pf_score = max(0, min(20, (profit_factor - 0.5) / 1.5 * 20))

            composite = wr_score + sp_score + pf_score  # 0-100

            # Map composite to multiplier: 0→0.4, 50→1.0, 100→1.5
            if composite >= 50:
                multiplier = 1.0 + (composite - 50) / 100  # 50→1.0, 100→1.5
            else:
                multiplier = 0.4 + composite / 50 * 0.6  # 0→0.4, 50→1.0

            logger.debug(
                f"Perf multiplier {strategy_name}: wr={win_rate:.0%} "
                f"sharpe={sharpe_proxy:.2f} pf={profit_factor:.2f} "
                f"composite={composite:.0f} → mult={multiplier:.2f}"
            )
            return round(multiplier, 2)

        except Exception as e:
            logger.debug(f"Performance multiplier for {strategy_name} unavailable: {e}")
            return 1.0
    
    def _calculate_position_weight(
        self, 
        suitability: float, 
        sentiment: float, 
        strength: float
    ) -> float:
        """
        Calculate position weight based on conviction factors.
        
        FORMULA:
        weight = (suitability/100 * 0.4) + (sentiment_adj * 0.3) + (strength * 0.3)
        
        Range: 0.0 to 1.0
        """
        # Normalize sentiment (-1 to 1 range assumed)
        sentiment_adj = (sentiment + 1) / 2  # Convert to 0-1
        
        weight = (
            (suitability / 100) * 0.4 +
            sentiment_adj * 0.3 +
            strength * 0.3
        )
        
        return min(1.0, max(0.1, weight))  # Clamp to 0.1-1.0
    
    def update_session_performance(self, strategy_name: str, won: bool, pnl_inr: float = 0.0):
        """Called by orchestrator after each trade close to update Gemini's session context.

        This is the missing feedback loop that gives Gemini awareness of
        which strategies are misfiring today, enabling it to downgrade or
        reject further signals from a strategy on a losing streak.
        """
        rec = self._strategy_session_perf.setdefault(strategy_name, {
            "trades": 0, "wins": 0, "losses": 0,
            "consecutive_losses": 0, "session_pnl_inr": 0.0
        })
        rec["trades"] += 1
        rec["session_pnl_inr"] = round(rec["session_pnl_inr"] + pnl_inr, 2)
        if won:
            rec["wins"] += 1
            rec["consecutive_losses"] = 0
        else:
            rec["losses"] += 1
            rec["consecutive_losses"] += 1
        logger.info(
            f"[SESSION-PERF] {strategy_name}: {rec['wins']}W/{rec['losses']}L "
            f"consec_losses={rec['consecutive_losses']} pnl=₹{rec['session_pnl_inr']:,.0f}"
        )

    def _build_genai_validation_prompt(
        self,
        signal_descs: List[dict],
        regime: str,
        sentiment: float,
        session_perf: dict = None,
    ) -> str:
        import json as _json

        _perf_lines = []
        if session_perf:
            _perf_rows = []
            for _strategy_name, _stats in session_perf.items():
                _trades = int(_stats.get("trades", 0) or 0)
                _wins = int(_stats.get("wins", 0) or 0)
                _losses = int(_stats.get("losses", 0) or 0)
                _consecutive_losses = int(_stats.get("consecutive_losses", 0) or 0)
                _session_pnl = float(_stats.get("session_pnl_inr", 0.0) or 0.0)
                _win_rate = (_wins / _trades) if _trades > 0 else 0.0
                _status = (
                    "MISFIRE" if _consecutive_losses >= 3 else
                    "STRUGGLING" if _consecutive_losses >= 2 else
                    "HOT" if _win_rate >= 0.7 and _trades >= 3 else
                    "OK"
                )
                _priority = (
                    _consecutive_losses,
                    1 if _win_rate >= 0.7 and _trades >= 3 else 0,
                    _trades,
                    abs(_session_pnl),
                )
                _perf_rows.append((
                    _priority,
                    f"- {_strategy_name}: {_wins}W/{_losses}L WR={_win_rate:.0%} "
                    f"consec_loss={_consecutive_losses} pnl=₹{_session_pnl:,.0f} {_status}"
                ))

            _perf_rows.sort(reverse=True)
            _visible_count = min(8, len(_perf_rows))
            _perf_lines = [
                f"Tracked strategies: {len(_perf_rows)} | showing top {_visible_count} by live urgency"
            ]
            _perf_lines.extend(_line for _, _line in _perf_rows[:_visible_count])

        _session_perf_block = "\n".join(_perf_lines) if _perf_lines else "- No closed trades yet this session."
        _batch_json = _json.dumps(signal_descs, separators=(",", ":"), ensure_ascii=True)
        _vix = signal_descs[0].get("vix", "unknown") if signal_descs else "unknown"

        return f"""You are Gemini Alpha, the conviction layer in Agent Alpha.
Review the full signal batch as a portfolio, prefer sizing changes over rejections, and return strict JSON only.

Core rules:
- Use STRONG, MODERATE, or WEAK whenever the trade is logically valid; use REJECT only for hard technical violations.
- Hard rejections only: BUY with stop_loss >= entry, non-positive entry, RR < 0.8 on an unhedged directional trade, or a nonsensical structure.
- Judge cross-sectional momentum, relative-strength, and pair trades by stock-level relative edge, not index direction alone.
- Hedges or protective puts can be strong when they offset portfolio risk, even in bearish conditions.
- Theta or premium-selling setups prefer IV rank > 35 and calmer conditions; weaken them in strong trends or high VIX and avoid fresh weekly shorts after 14:00.
- Long-vol premium buys need cheap enough IV, real move potential, and should be rejected when entered too late on expiry day.
- Defined-risk directional option structures can pass with RR >= 1.2.
- Intraday signals degrade after 11:30 and should be sized down late in the day.
- Fresh swing longs in a BEAR index need clear stock-level relative strength.
- VIX guide: 12-18 normal, 18-22 elevated, 22-28 stress, >28 crisis.
- Portfolio coherence: strongest same-underlying directional signal wins, hedges may be boosted, and excess same-sector concentration should be weakened.
- Do not raise default liquidity concerns for liquid NIFTY 200 names.

Session rules:
- consecutive_losses >= 3 => WEAK
- consecutive_losses >= 5 => REJECT
- WR < 20% with trades >= 3 => WEAK
- WR >= 70% may be STRONG if the setup supports it

Market state:
- Index regime: {regime}
- Sentiment: {round(sentiment, 3)}
- VIX: {_vix}

Live session performance snapshot:
{_session_perf_block}

Signals batch ({len(signal_descs)} signals):
{_batch_json}

Return strict JSON only in this exact shape:
{{"evaluations":[{{"idx":0,"valid":true,"conviction":"MODERATE","confidence":0.7,"adjusted_strength":0.6,"hold_days":1,"market_edge":"...","risk_note":"...","reasoning":"..."}}]}}

Response rules:
- Return exactly {len(signal_descs)} evaluation objects in the same order as input.
- Only set valid=false when conviction=REJECT.
- When in doubt, downgrade to WEAK with adjusted_strength=0.55 instead of rejecting.
- Keep market_edge, risk_note, and reasoning concise.
"""

    def _get_genai_validation_max_tokens(self, signal_descs: List[dict]) -> int:
        _has_options_shape = any(
            _desc.get("structure_type") or _desc.get("options_greeks")
            for _desc in signal_descs
        )
        _budget = 384 + (len(signal_descs) * 256)
        if _has_options_shape:
            _budget += 128
        return min(3072, max(768, _budget))

    async def _validate_with_genai(
        self,
        signals: List[StrategySignal],
        regime: str,
        sentiment: float,
        session_perf: dict = None
    ) -> List[StrategySignal]:
        """
        Superhuman Institutional Trader & Analyst AI layer (Gemini).

        Gemini operates as a senior quant portfolio manager who:
          - Understands this is a deterministic multi-agent algo system
            (Scanner → Strategy → [this layer] → Risk → Execution)
          - Evaluates ALL signals as a portfolio batch for coherence
          - Distinguishes strategy archetypes: directional, cross-sectional
            momentum, market-neutral, delta-neutral, and hedging
          - Applies conviction levels (STRONG/MODERATE/WEAK/REJECT) instead
            of binary valid/invalid — WEAK signals are sized down but NOT
            killed (only REJECT hard-blocks a signal)
          - Adjusts signal strength which the Risk agent uses for position sizing
          - Only hard-rejects clear red flags: data errors, extreme illiquidity,
            terminal contradictions (e.g. BUY with SL > entry_price)

        Output per signal:
            valid           : false ONLY for REJECT conviction
            conviction      : STRONG | MODERATE | WEAK | REJECT
            confidence      : 0.0 – 1.0
            adjusted_strength : override for signal.strength (Gemini's sizing view)
            market_edge     : 1-sentence thesis for why this trade has edge
            risk_note       : top risk factor to monitor
            reasoning       : concise analyst rationale (SEBI audit trail)
        """
        if not self.genai_model:
            return signals

        import json as _json
        import re as _re

        # ── Build batch signal descriptors ───────────────────────────────────
        _sig_descs = []
        for _idx, _sig in enumerate(signals):
            _sl   = getattr(_sig, "stop_loss", None)
            _tgt  = getattr(_sig, "target_price", None)
            _ep   = float(_sig.entry_price or 0)
            _rr   = round(abs(_tgt - _ep) / abs(_ep - _sl), 2) if (_ep and _sl and _tgt and abs(_ep - _sl) > 0.01) else None
            _meta = _sig.metadata or {}
            _desc = {
                "idx": _idx,
                "symbol": _sig.symbol,
                "strategy": _sig.strategy_name,
                "signal_type": getattr(_sig, "signal_type", getattr(_sig, "structure_type", "BUY")),
                "entry": _ep,
                "stop_loss": _sl,
                "target": _tgt,
                "rr_ratio": _rr,
                "strength": round(float(getattr(_sig, "strength", 0.5)), 3),
                "market_regime": regime,
                "stock_regime": _meta.get("stock_regime", "UNKNOWN"),
                "sentiment": round(float(sentiment), 3),
                "suitability_score": round(float(_meta.get("suitability_score", 50)), 1),
                "signal_quality": round(float(_meta.get("signal_quality_score", 0.5)), 3),
                "vix": round(float(_meta.get("vix_at_entry", 0) or 0), 1),
                "iv_rank": round(float(_meta.get("iv_rank", 0) or 0), 1),
                "oi_pcr": round(float(_meta.get("oi_pcr", 1.0) or 1.0), 2),
                "data_rows": int(_meta.get("data_rows", 0) or 0),
                "options_greeks": _meta.get("greeks") or {},
                "hedge_type": _meta.get("hedge_type", ""),
                "structure_type": getattr(_sig, "structure_type", "") or "",
                "ltp_sanity": "FLAGGED" if _meta.get("ltp_sanity_failed") else "OK",
                "strategy_reason": str(_meta.get("reason", ""))[:80],
            }
            _sig_descs.append(_desc)

        if not _sig_descs:
            return signals

        _prompt = self._build_genai_validation_prompt(
            _sig_descs,
            regime,
            sentiment,
            session_perf,
        )
        _max_tokens = self._get_genai_validation_max_tokens(_sig_descs)

        try:
            from src.services.ai_router import ai_router

            response = await ai_router.generate(
                prompt=_prompt,
                agent_name="strategy_alpha",
                temperature=0.15,
                max_tokens=_max_tokens,
                json_mode=True,
            )
            _response_text = (response.text or "").strip()
            if not _response_text:
                logger.warning("[Gemini-Alpha] ai_router returned empty response — passing all signals through")
                return signals

            _provider = getattr(response, "provider", "") or ""
            _in_tok = _out_tok = 0
            if _provider.startswith("vertex"):
                _in_tok = max(len(_prompt) // 4, 400)
                _out_tok = max(len(_response_text) // 4, 120)
                await ai_cost_tracker.record_usage("strategy", input_tokens=_in_tok, output_tokens=_out_tok)

            # Parse response
            try:
                _parsed = _json.loads(_response_text)
            except Exception:
                _m = _re.search(r'\{.*\}', _response_text, _re.DOTALL)
                _parsed = _json.loads(_m.group()) if _m else {}

            _evals: list = _parsed.get("evaluations", [])
            # Build lookup by idx
            _eval_map = {int(e.get("idx", i)): e for i, e in enumerate(_evals)}

        except Exception as _batch_err:
            logger.warning(f"[Gemini-Alpha] Batch call failed ({_batch_err}) — passing all signals through")
            for _sig in signals:
                _sig.metadata["genai_validated"] = False
                _sig.metadata["genai_error"] = str(_batch_err)
            return signals

        # ── Apply evaluations to signals ─────────────────────────────────────
        validated_signals = []
        _approved = _rejected = _weak = 0

        for _idx, _sig in enumerate(signals):
            _ev = _eval_map.get(_idx, {})
            _conviction   = str(_ev.get("conviction", "MODERATE")).upper()
            _is_valid     = bool(_ev.get("valid", True))  # default pass-through
            _confidence   = float(_ev.get("confidence", 0.7))
            _adj_strength = float(_ev.get("adjusted_strength", _sig.strength))
            _hold_days    = int(_ev.get("hold_days", 0) or 0)   # 0=intraday, 1-3=swing
            _edge         = str(_ev.get("market_edge", ""))
            _risk_note    = str(_ev.get("risk_note", ""))
            _reasoning    = str(_ev.get("reasoning", ""))

            # Clamp adjusted_strength
            _adj_strength = round(min(0.98, max(0.05, _adj_strength)), 3)

            # Apply conviction-based strength multiplier if eval is missing
            if not _ev:
                _conviction = "MODERATE"
                _is_valid = True

            # Conviction → strength scaling
            _strength_mult = {"STRONG": 1.0, "MODERATE": 0.85, "WEAK": 0.55, "REJECT": 0.0}
            if _conviction in _strength_mult and _adj_strength == _sig.strength:
                _adj_strength = round(_sig.strength * _strength_mult.get(_conviction, 0.85), 3)

            # Q1: Cap maximum Gemini strength reduction at 30%.
            # Prevents Gemini from killing signal strength (e.g., 0.704→0.425 = 40% cut).
            # Live mode: still allows up to 30% reduction for genuine risk.
            # This preserves the AI quality layer while preventing over-penalisation.
            _max_reduction = 0.30  # max 30% reduction from original
            _floor = round(_sig.strength * (1.0 - _max_reduction), 3)
            if _adj_strength < _floor and _conviction != "REJECT":
                _adj_strength = _floor

            # Store full analysis in metadata for SEBI audit trail + frontend display
            _sig.metadata.update({
                "genai_validated":        _is_valid,
                "genai_conviction":       _conviction,         # STRONG|MODERATE|WEAK|REJECT
                "genai_confidence":       round(_confidence, 3),
                "genai_adjusted_strength": _adj_strength,
                "genai_hold_days":        _hold_days,          # 0=intraday, 1-3=swing
                "genai_market_edge":      _edge[:200],
                "genai_risk_note":        _risk_note[:200],
                "genai_reason":           _reasoning[:300],
                # AUDIT Layer-6: AI Quality Grade (derived from conviction + confidence)
                # A = STRONG + conf≥0.8, B = STRONG/MODERATE + conf≥0.6,
                # C = MODERATE + conf<0.6, D = WEAK, F = REJECT
                "ai_quality_grade": (
                    "A" if _conviction == "STRONG" and _confidence >= 0.8
                    else "B" if _conviction in ("STRONG", "MODERATE") and _confidence >= 0.6
                    else "C" if _conviction == "MODERATE"
                    else "D" if _conviction == "WEAK"
                    else "F"
                ),
            })

            if _conviction == "REJECT" or not _is_valid:
                _rejected += 1
                logger.info(
                    f"[Gemini-Alpha] REJECT {_sig.symbol} ({_sig.strategy_name}) "
                    f"conf={_confidence:.2f} | {_reasoning[:100]}"
                )
            else:
                # Apply Gemini's strength recommendation to influence Risk agent sizing
                _sig.strength = _adj_strength
                validated_signals.append(_sig)
                if _conviction == "STRONG":
                    _approved += 1
                    logger.info(
                        f"[Gemini-Alpha] STRONG {_sig.symbol} adj_str={_adj_strength:.2f} "
                        f"| Edge: {_edge[:80]}"
                    )
                elif _conviction == "WEAK":
                    _weak += 1
                    logger.info(
                        f"[Gemini-Alpha] WEAK {_sig.symbol} adj_str={_adj_strength:.2f} "
                        f"| Risk: {_risk_note[:80]}"
                    )
                else:
                    _approved += 1
                    logger.info(
                        f"[Gemini-Alpha] {_conviction} {_sig.symbol} adj_str={_adj_strength:.2f} "
                        f"| {_reasoning[:80]}"
                    )

        logger.info(
            f"[Gemini-Alpha] Batch complete: {len(signals)} in → "
            f"{_approved} APPROVED, {_weak} WEAK (sized-down), {_rejected} REJECTED "
            f"| tokens: in={_in_tok} out={_out_tok}"
        )

        # FIX-AUDIT-D20-M13: Write AI advisory decisions to SEBI permanent audit trail.
        # Previously only approval/rejection was logged, not AI strength adjustments.
        # SEBI requires full decision audit including GenAI-induced signal modifications.
        try:
            from src.database.redis import cache as _rc_audit
            from src.services.manual_controls import _audit
            for _sig_audit in signals:
                _meta_audit = _sig_audit.metadata or {}
                _genai_conv = _meta_audit.get("genai_conviction", "N/A")
                _orig_str = _meta_audit.get("original_strength", _sig_audit.strength)
                _adj_str_audit = _meta_audit.get("genai_adjusted_strength", _sig_audit.strength)
                if _genai_conv != "N/A":
                    await _audit(_rc_audit, "AI_ADVISORY", {
                        "strategy_id": _sig_audit.strategy_name,
                        "symbol": _sig_audit.symbol,
                        "operator": "gemini_alpha",
                        "conviction": _genai_conv,
                        "original_strength": float(_orig_str),
                        "adjusted_strength": float(_adj_str_audit),
                        "ai_quality_grade": _meta_audit.get("ai_quality_grade", "?"),
                        "reasoning": str(_meta_audit.get("genai_reason", ""))[:200],
                    })
        except Exception as _audit_err:
            logger.debug(f"SEBI AI audit write failed: {_audit_err}")

        # Day22 fix: if GenAI rejects ALL signals, do NOT fall back to
        # unvalidated originals. Return empty list — GenAI rejection is final.
        if not validated_signals:
            logger.info(
                f"GenAI rejected ALL {len(signals)} signals — returning empty "
                f"(was previously returning unvalidated originals)"
            )
        return validated_signals
    
    async def get_strategy_stats(self) -> Dict[str, Any]:
        """Get statistics about registered strategies and recent signals."""
        return {
            "registered_strategies": list(self.strategies.keys()),
            "total_strategies": len(self.strategies),
            "recent_signals": len(self.signal_history),
            "genai_enabled": self.genai_model is not None
        }
