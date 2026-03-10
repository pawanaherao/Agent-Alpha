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
from datetime import datetime
import asyncio
import pandas as pd
import polars as pl
import logging

from src.agents.base import BaseAgent
from src.core.config import settings
from src.core.messages import AgentMessage
from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service

# GenAI imports (optional)
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

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
        # Latest sentiment/regime pushed from sensing events
        self._latest_sentiment: float = 0.0
        self._latest_regime: str = "SIDEWAYS"
        self.nse_service = nse_data_service
        
        # Strategy weights by regime
        self.regime_weights = {
            "BULL": {
                "momentum": 1.5,
                "trend": 1.3,
                "mean_reversion": 0.7,
                "theta": 0.5,
                "hedge": 0.3
            },
            "BEAR": {
                "momentum": 0.5,
                "trend": 0.7,
                "mean_reversion": 1.0,
                "theta": 0.8,
                "hedge": 1.5
            },
            "SIDEWAYS": {
                "momentum": 0.5,
                "trend": 0.5,
                "mean_reversion": 1.5,
                "theta": 1.5,
                "hedge": 0.8
            },
            "VOLATILE": {
                "momentum": 1.2,
                "trend": 0.8,
                "mean_reversion": 0.5,
                "theta": 0.3,
                "hedge": 1.2
            }
        }
        
        # GenAI model for signal validation
        self.genai_model = None
        if GENAI_AVAILABLE:
            try:
                self.genai_model = GenerativeModel("gemini-1.5-flash")
                logger.info("GenAI model initialized for signal validation")
            except Exception as e:
                logger.warning(f"GenAI initialization failed: {e}")
        
        self.signal_history: List[StrategySignal] = []
    
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
        """Cache latest sentiment score published by SentimentAgent."""
        self._latest_sentiment = float(data.get("score", self._latest_sentiment))
        logger.debug(f"StrategyAgent: sentiment → {self._latest_sentiment:.2f} "
                     f"({data.get('classification', '')})")

    async def on_regime_updated(self, data: Dict[str, Any]):
        """Cache latest regime published by RegimeAgent."""
        self._latest_regime = data.get("regime", self._latest_regime)
        logger.debug(f"StrategyAgent: regime → {self._latest_regime} "
                     f"(stat={data.get('statistical_regime', '')}, vix={data.get('vix', '')})")
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

        # Allow callers that pass raw string lists (legacy) as well as dicts
        def _sym(opp) -> str:
            return opp["symbol"] if isinstance(opp, dict) else str(opp)

        # 1. Filter strategies by regime suitability
        suitable_strategies = await self._filter_by_regime(regime)
        if not suitable_strategies:
            logger.warning("No suitable strategies for current regime")
            return

        logger.info(f"Suitable strategies: {[s[0].name for s in suitable_strategies]}")

        # 2. Pre-filter using scanner scores — avoid fetching data for weak setups
        qualified: list = []
        for opp in opportunities[:10]:
            symbol = _sym(opp)
            cached = self._scan_cache.get(symbol)
            scanner_score = cached.get("score", 100) if cached else 100
            if scanner_score >= 50:
                qualified.append((symbol, cached))
            else:
                logger.debug(f"Pre-filter: skipping {symbol} (scan_score={scanner_score:.0f})")

        if not qualified:
            logger.info("No qualified opportunities after scanner pre-filter")
            return

        # 3. PARALLEL data fetch — scanner cache hit avoids redundant indicator recalc
        async def _fetch(symbol: str, cached: Optional[Any]) -> tuple:
            try:
                if cached:
                    # Fast path: fetch OHLCV only (indicators already in cache)
                    market_data = await self.nse_service.get_stock_ohlc(
                        symbol, period="1Y"
                    )
                    if not market_data.empty:
                        # Inject pre-computed scanner scalar indicators as extra columns
                        for k, v in cached.get("indicators", {}).items():
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                market_data[f"scan_{k}"] = float(v)
                        market_data["scanner_score"] = cached.get("score", 0)
                else:
                    # Slow path: full fetch + indicator computation (cache miss)
                    market_data = await self.nse_service.get_stock_with_indicators(
                        symbol, period="1Y"
                    )

                if market_data.empty:
                    return symbol, pd.DataFrame()

                market_data["symbol"] = symbol

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
            for strategy, score in suitable_strategies[:3]:
                try:
                    signal = await strategy.generate_signal(market_data, regime)
                    if signal:
                        signal.metadata["suitability_score"] = score
                        signal.metadata["sentiment_score"] = sentiment
                        signal.metadata["regime"] = regime
                        signal.metadata["data_rows"] = len(market_data)
                        signal.metadata["position_weight"] = (
                            self._calculate_position_weight(score, sentiment, signal.strength)
                        )
                        signals.append(signal)
                        logger.info(
                            f"Signal: {signal.signal_type} {signal.symbol} "
                            f"from {signal.strategy_name} (strength={signal.strength:.2f})"
                        )
                except Exception as e:
                    logger.error(f"Signal generation failed for {strategy.name}: {e}")
            return signals

        signal_batches = await asyncio.gather(
            *[_gen(sym, data) for sym, data in fetch_results
              if not isinstance(data, BaseException)]
        )
        generated_signals: list = [s for batch in signal_batches for s in batch]

        # 5. GenAI validation (if enabled and signals exist)
        if generated_signals and self.genai_model:
            generated_signals = await self._validate_with_genai(
                generated_signals, regime, sentiment
            )

        # 5b. Options path — run options-mode strategies against cached chain data
        if self._options_chain_cache:
            options_signals = await self._run_options_strategies(regime, sentiment)
            if options_signals:
                generated_signals.extend(options_signals)
                logger.info(f"Options path added {len(options_signals)} signals")

        # 6. Publish signals
        if generated_signals:
            logger.info(f"Publishing {len(generated_signals)} signals")
            self.signal_history.extend(generated_signals)
            payload = [s.model_dump() for s in generated_signals]
            await self.publish_event("SIGNALS_GENERATED", {"signals": payload})
        else:
            logger.info("No signals generated this cycle")
    
    async def _filter_by_regime(self, regime: str) -> List[tuple]:
        """
        Filter strategies by regime suitability.
        Returns list of (strategy, weighted_score) tuples.
        """
        suitable = []
        weights = self.regime_weights.get(regime, self.regime_weights["SIDEWAYS"])
        
        for name, strategy in self.strategies.items():
            try:
                # Create minimal market data for suitability check
                # (strategies should handle empty data gracefully)
                market_data = pd.DataFrame()
                
                base_score = await strategy.calculate_suitability(market_data, regime)
                
                # Apply regime weight based on strategy type
                strategy_type = self._classify_strategy(name)
                weight = weights.get(strategy_type, 1.0)
                
                weighted_score = base_score * weight
                
                if weighted_score > 50.0:
                    suitable.append((strategy, weighted_score))
                    
            except Exception as e:
                logger.debug(f"Suitability check failed for {name}: {e}")
        
        # Sort by weighted score
        suitable.sort(key=lambda x: x[1], reverse=True)
        
        return suitable

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
                "iv_rank": chain_opp.get("iv_rank", 50),
                "atm_iv": chain_opp.get("atm_iv", 0),
                "oi_pcr": chain_opp.get("oi_pcr", 1.0),
                "options_score": chain_opp.get("score", 0),
            }])
            minimal_df["symbol"] = symbol

            for strategy in options_strategies:
                strat_structure = strategy.config.get("structure")
                # Route: only run if structures match (or strategy has no structure)
                if strat_structure and strat_structure != best_structure:
                    continue

                # Temporarily point strategy at this symbol
                old_symbol = strategy.config.get("symbol")
                strategy.config["symbol"] = symbol
                try:
                    signal = await strategy.generate_signal(minimal_df, regime)
                    if signal:
                        signal.metadata["options_chain_score"] = chain_opp.get("score", 0)
                        signal.metadata["iv_rank"] = chain_opp.get("iv_rank", 0)
                        signal.metadata["oi_pcr"] = chain_opp.get("oi_pcr", 1.0)
                        signal.metadata["sentiment_score"] = sentiment
                        signal.metadata["regime"] = regime
                        signal.strategy_name = strategy.name  # tag with instance name
                        results.append(signal)
                        logger.info(
                            f"Options signal: {signal.signal_type} {symbol} "
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

    def _classify_strategy(self, strategy_name: str) -> str:
        """Classify strategy into type for regime weighting."""
        name_lower = strategy_name.lower()
        
        if any(x in name_lower for x in ["momentum", "orb", "breakout"]):
            return "momentum"
        elif any(x in name_lower for x in ["trend", "ema", "pullback"]):
            return "trend"
        elif any(x in name_lower for x in ["vwap", "reversion", "mean"]):
            return "mean_reversion"
        elif any(x in name_lower for x in ["condor", "spread", "theta", "straddle"]):
            return "theta"
        elif any(x in name_lower for x in ["hedge", "protect"]):
            return "hedge"
        else:
            return "momentum"  # Default
    
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
    
    async def _validate_with_genai(
        self, 
        signals: List[StrategySignal],
        regime: str,
        sentiment: float
    ) -> List[StrategySignal]:
        """
        Validate signals using GenAI for additional confidence.
        
        This is an AUGMENTATION layer - GenAI validates but doesn't generate.
        All core logic remains whitebox.
        """
        if not self.genai_model:
            return signals
        
        validated_signals = []
        
        try:
            for signal in signals:
                # Create prompt for validation
                prompt = f"""
                Validate this trading signal for Indian market (NSE):
                
                Signal: {signal.signal_type} {signal.symbol}
                Strategy: {signal.strategy_name}
                Entry Price: {signal.entry_price}
                Stop Loss: {signal.stop_loss}
                Target: {signal.target_price}
                Signal Strength: {signal.strength}
                Market Regime: {regime}
                Sentiment Score: {sentiment}
                
                Consider:
                1. Is the strategy appropriate for the current regime?
                2. Is the risk-reward ratio acceptable (>1.5)?
                3. Any major risks or red flags?
                
                Respond with JSON: {{"valid": true/false, "confidence": 0.0-1.0, "reason": "..."}}
                """
                
                try:
                    response = await asyncio.to_thread(
                        self.genai_model.generate_content, prompt
                    )
                    
                    # Parse response (simplified)
                    response_text = response.text.lower()
                    
                    if '"valid": true' in response_text or '"valid":true' in response_text:
                        signal.metadata['genai_validated'] = True
                        signal.metadata['genai_response'] = response.text[:500]
                        validated_signals.append(signal)
                        logger.info(f"GenAI validated: {signal.symbol}")
                    else:
                        logger.info(f"GenAI rejected: {signal.symbol}")
                        
                except Exception as e:
                    # If GenAI fails, pass through the signal anyway
                    logger.warning(f"GenAI validation failed: {e}")
                    signal.metadata['genai_validated'] = False
                    signal.metadata['genai_error'] = str(e)
                    validated_signals.append(signal)
            
        except Exception as e:
            logger.error(f"GenAI validation batch failed: {e}")
            return signals  # Return original if validation fails
        
        return validated_signals if validated_signals else signals
    
    async def get_strategy_stats(self) -> Dict[str, Any]:
        """Get statistics about registered strategies and recent signals."""
        return {
            "registered_strategies": list(self.strategies.keys()),
            "total_strategies": len(self.strategies),
            "recent_signals": len(self.signal_history),
            "genai_enabled": self.genai_model is not None
        }
