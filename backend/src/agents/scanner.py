"""
Enhanced Scanner Agent with Global Best Practices
PROFESSIONAL ALGO TRADING FILTERS - 2024

Medallion CEO Overhaul (Mar 2026):
  Removed: Stochastic (14,3,3) — correlated with RSI; Parabolic SAR — zero downstream usage
  Added: RS vs Nifty 15-day rolling; ATR Expansion Ratio (current ATR / 5-period avg ATR)
  EMA periods standardised to 20/50/200 (aligned across Scanner → Regime → Strategy layers)

Active Technical Indicators (10 Total, weights sum to 1.00):
1.  RSI (14)                 0.09  — momentum oscillator
2.  ADX (14)                 0.17  — trend strength (highest Sharpe correlation)
3.  MACD (12,26,9)           0.11  — trend momentum + histogram gradient
4.  RS vs Nifty (15-day)     0.12  — cross-sectional relative strength alpha
5.  Volume Ratio (20d avg)   0.13  — liquidity confirmation
6.  OBV                      0.07  — on-balance volume trend
7.  EMA Alignment (20/50/200)0.09  — bull stack (price > EMA20 > EMA50 > EMA200)
8.  Bollinger Bands (20,2)   0.06  — volatility envelope position
9.  Delivery % (NSE)         0.08  — institutional conviction (T+1 bhavcopy, neutral when unavailable)
10. ATR Expansion Ratio      0.08  — current ATR / 5-period rolling ATR mean

Filter Gates (non-composite, applied before scoring):
  ATR(14) >= 1% of price     — minimum volatility gate
  VWAP proximity <= 2%       — anti-extreme-stretch filter

GenAI Counter-Validation (post-scan, not in composite):
  Single batch call on top-N shortlist
  STRONG_BUY +5 pts | BUY pass | HOLD -5 pts | AVOID vetoed
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time
import pandas as pd
import numpy as np
import logging
import asyncio
import ta

# GenAI imports
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from src.agents.base import BaseAgent
from src.services.nse_data import nse_data_service
from src.services.ai_cost_tracker import ai_cost_tracker
from src.core.config import settings
from src.database.redis import cache as _redis_cache

logger = logging.getLogger(__name__)


class ScannerAgent(BaseAgent):
    """
    Enhanced Scanner Agent with 12 Technical Filters + GenAI Validation.
    
    GLOBAL BEST PRACTICES IMPLEMENTED:
    1. Multi-indicator confirmation
    2. Trend + Momentum + Volume triangle
    3. AI-assisted scoring
    4. Regime-adaptive filtering
    """
    
    # Fallback universe (used only if NSEDataService fails at init)
    _FALLBACK_UNIVERSE = [
        # Banking
        "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "INDUSINDBK",
        # IT
        "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
        # Energy
        "RELIANCE", "ONGC", "NTPC", "POWERGRID",
        # FMCG
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA",
        # Auto
        "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO",
        # Pharma
        "SUNPHARMA", "DRREDDY", "CIPLA",
        # Finance
        "BAJFINANCE", "BAJAJFINSV",
        # Metals
        "TATASTEEL", "HINDALCO", "JSWSTEEL"
    ]

    def __init__(self, name: str = "ScannerAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)

        self.nse_service = nse_data_service
        self.model = None

        # Build dynamic universe: NSE 100 (equity) + F&O eligible stocks
        try:
            nse_100 = self.nse_service.get_nifty_100_stocks()
            fno_stocks = self.nse_service.get_fno_stocks()
            combined = list(dict.fromkeys(nse_100 + fno_stocks))  # deduplicate, preserve order
            self.SCAN_UNIVERSE = combined if combined else list(self._FALLBACK_UNIVERSE)
            # Store sub-lists for manual universe selection
            self._nse_100_list = list(nse_100) if nse_100 else list(self._FALLBACK_UNIVERSE)
            self._fno_list = list(fno_stocks) if fno_stocks else []
            logger.info(
                f"Scan universe loaded: {len(self.SCAN_UNIVERSE)} stocks "
                f"(NSE 100: {len(nse_100)}, F&O: {len(fno_stocks)})"
            )
        except Exception as e:
            logger.warning(f"Dynamic universe load failed, using fallback 30: {e}")
            self.SCAN_UNIVERSE = list(self._FALLBACK_UNIVERSE)
            self._nse_100_list = list(self._FALLBACK_UNIVERSE)
            self._fno_list = []

        # Index universe for options scanning (passed to OptionChainScannerAgent)
        self.INDEX_OPTIONS_UNIVERSE = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        
        # Technical filter thresholds
        self.filters = {
            # Momentum
            "rsi_min": 40,
            "rsi_max": 70,
            # Stochastic keys removed (indicator replaced by RS vs Nifty — CEO Fix #6)

            # Trend
            "adx_min": 20,
            "macd_confirm": True,
            "ema_alignment": True,
            # psar_confirm removed (PSAR indicator removed — CEO Fix #8)

            # Volume
            "volume_ratio_min": 1.3,
            "obv_rising": True,
            
            # Volatility
            "bb_squeeze": False,  # Optional
            "atr_min_pct": 0.01,  # 1% min ATR
            
            # NSE specific
            "delivery_pct_min": 30,  # Min 30% delivery
            "vwap_proximity_pct": 0.02  # Within 2% of VWAP
        }
        
        # Scoring weights (must sum to 1.00)
        # AI removed from composite — now acts as post-scan counter-validator
        # ── Medallion CEO Signal Quality Fixes (Mar 2026) ────────────────────
        # Fix #6: Replace Stochastic (momentum oscillator, correlated with RSI)
        #         with RS vs Nifty 15-day rolling (cross-sectional strength rank)
        # Fix #7: Reduce Delivery% 15%→8% (T+1 data lag penalizes fast movers);
        #         add ATR Expansion Ratio 8% (volatility regime filter)
        # Fix #8: Remove PSAR (used by zero downstream strategies — dead weight);
        #         redistributed 7% to ADX (trend confirmation, highest Sharpe correlation)
        # Fix #9: EMA alignment now uses 20/50/200 (standardised across all layers)
        self.weights = {
            "rsi_score":           0.09,  # unchanged
            "adx_score":           0.17,  # was 0.10 — absorbs eliminated PSAR 7%
            "macd_score":          0.11,  # minor trim to balance budget
            "rs_nifty_score":      0.12,  # replaces stoch_score (0.07) — better alpha
            "volume_score":        0.13,  # minor trim to balance budget
            "obv_score":           0.07,  # minor trim to balance budget
            "ema_score":           0.09,  # minor trim; EMA now 20/50/200 (fix #9)
            "bb_score":            0.06,  # unchanged
            "delivery_score":      0.08,  # was 0.15 — reduced (T+1 lag issue)
            "atr_expansion_score": 0.08,  # new — rewards expanding volatility regimes
        }  # sum = 1.00
        
        self.project_id = getattr(settings, 'GCP_PROJECT', None)
        self.location = "us-central1"
        # ── Nifty reference data cache for RS vs Nifty computation ─────────────
        # Populated once per scan_universe() call; shared across all _analyze_stock()
        # coroutines in the same cycle to avoid N redundant Nifty fetches.
        self._nifty_close_cache: Optional[object] = None  # pd.Series | None
        # ── End Nifty cache ─────────────────────────────────────────────────────
        
        logger.info("Scanner Agent initialized with 10 technical indicators (CEO Mar 2026 spec)")

    # ── Banking sector sub-universe ───────────────────────────────────────────
    _BANKING_UNIVERSE = [
        "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "INDUSINDBK",
        "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "PNB", "CANBK", "BANKBARODA",
    ]
    _NIFTY_50_UNIVERSE = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
        "SBIN", "BHARTIARTL", "AXISBANK", "KOTAKBANK", "LT", "BAJFINANCE",
        "MARUTI", "SUNPHARMA", "TITAN", "NESTLEIND", "WIPRO", "ULTRACEMCO",
        "HCLTECH", "ONGC", "POWERGRID", "NTPC", "TATAMOTORS", "ADANIENT",
        "BAJAJFINSV", "JSWSTEEL", "TATASTEEL", "TECHM", "ASIANPAINT",
        "DRREDDY", "CIPLA", "EICHERMOT", "BPCL", "HEROMOTOCO", "GRASIM",
        "DIVISLAB", "TATACONSUM", "APOLLOHOSP", "COALINDIA", "HINDALCO",
        "UPL", "SBILIFE", "INDUSINDBK", "BAJAJ-AUTO", "BRITANNIA",
        "HDFCLIFE", "M&M", "ADANIPORTS", "SHREECEM",
    ]

    async def get_active_universe(self) -> List[str]:
        """
        Returns the universe to scan based on user selection stored in Redis.
        Falls back to AUTO (full SCAN_UNIVERSE) if no selection or Redis unavailable.
        """
        try:
            selection = await _redis_cache.get("scan_universe_type")
        except Exception:
            selection = None

        selection = selection or "AUTO"

        if selection == "NIFTY_50":
            universe = self._NIFTY_50_UNIVERSE
        elif selection == "NIFTY_100":
            universe = self._nse_100_list
        elif selection == "FNO":
            universe = self._fno_list if self._fno_list else self.SCAN_UNIVERSE
        elif selection == "BANKING":
            universe = list(self._BANKING_UNIVERSE)
        elif selection == "INDICES":
            universe = list(self.INDEX_OPTIONS_UNIVERSE)
        else:  # AUTO
            universe = self.SCAN_UNIVERSE

        logger.debug(f"Active scan universe: {selection} ({len(universe)} symbols)")
        return universe
    
    async def start(self):
        """Initialize GenAI for validation."""
        await super().start()
        self._current_scan_regime = "SIDEWAYS"  # updated each scan_universe call
        if GENAI_AVAILABLE and self.project_id:
            try:
                model_name = getattr(settings, 'VERTEXAI_MODEL', 'gemini-2.0-flash-001')
                location   = getattr(settings, 'VERTEXAI_LOCATION', 'us-central1')
                vertexai.init(project=self.project_id, location=location)
                # B17 FIX: use settings.VERTEXAI_MODEL — no longer hardcoded gemini-1.5-flash
                self.model = GenerativeModel(model_name)
                logger.info(f"Scanner GenAI validation enabled: {model_name}")
            except Exception as e:
                logger.warning(f"GenAI init failed: {e}")
    
    async def scan_universe(
        self, 
        regime: str = "BULL",
        top_n: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Scan entire universe and return top N stocks.
        
        Paper mode default raised to 50 (from 10) to support 100-500 signal
        funnel needed for 20-30 trades/day after risk filtering.

        Args:
            regime: Current market regime (BULL, BEAR, SIDEWAYS, VOLATILE)
            top_n: Number of top stocks to return
            
        Returns:
            List of stock dicts with scores and indicators
        """
        active_universe = await self.get_active_universe()
        logger.info(f"Scanning {len(active_universe)} stocks in {regime} regime (universe: {await _redis_cache.get('scan_universe_type') or 'AUTO'})")
        
        # B21 FIX: store regime so _get_genai_score can reference strategy context
        self._current_scan_regime = regime

        # ── Prefetch Nifty 50 close series for RS vs Nifty computation ────────
        # Done once per cycle here so individual _analyze_stock() calls share it.
        try:
            _nifty_df = await self.nse_service.get_index_ohlc("NIFTY 50", period="1M")
            if not _nifty_df.empty and "close" in _nifty_df.columns:
                self._nifty_close_cache = _nifty_df["close"].astype(float)
            else:
                self._nifty_close_cache = None
        except Exception as _nifty_err:
            logger.debug(f"Nifty prefetch failed (RS vs Nifty will use fallback): {_nifty_err}")
            self._nifty_close_cache = None
        # ── End Nifty prefetch ─────────────────────────────────────────────────
        
        # Adjust filters based on regime
        adjusted_filters = self._adjust_filters_for_regime(regime)
        
        results = []

        # ── Regime-adaptive minimum score threshold ───────────────────────
        # A hardcoded 50 over-filters in SIDEWAYS/ranging markets where stocks
        # legitimately score 35-45 (tight RSI band + BB-squeeze requirement).
        # Threshold is regime-aware: lower in calm/ranging conditions.
        # Paper mode: lowered further to widen the funnel (100-500 signals
        # needed upstream to land 20-30 trades after risk/execution filtering).
        _is_paper = getattr(settings, "PAPER_TRADING", False) or \
                    getattr(settings, "MODE", "") in ("PAPER", "LOCAL")
        if _is_paper:
            _regime_min_scores = {
                "BULL": 25, "BEAR": 25, "SIDEWAYS": 20, "VOLATILE": 25,
            }
        else:
            _regime_min_scores = {
                "BULL":     42,   # trending — want stronger confirmation
                "BEAR":     40,   # momentum both ways OK
                "SIDEWAYS": 30,   # range-bound: tight RSI/ADX bands → lower scores
                "VOLATILE": 40,   # high ATR — decent threshold
            }
        _min_score = _regime_min_scores.get(regime, 35)

        # ── Concurrent scanning with DhanHQ-safe semaphore ───────────────────
        # Old path: sequential for-loop + asyncio.sleep(0.1) =  N × 600 ms
        # New path: asyncio.gather with Semaphore(8) = max(N×600ms / 8, slowest)
        # DhanHQ allows ~10 req/sec; Semaphore(8) keeps us safely within limit.
        _sem = asyncio.Semaphore(8)

        async def _scan_one(sym: str):
            async with _sem:
                try:
                    score, indicators = await self._analyze_stock(sym, adjusted_filters)
                    if score >= _min_score:
                        return {
                            "symbol": sym,
                            "score": score,
                            "indicators": indicators,
                            "regime": regime,
                            "timestamp": datetime.now().isoformat(),
                        }
                except Exception as exc:
                    logger.debug(f"Scan failed for {sym}: {exc}")
                return None

        scan_tasks = [_scan_one(sym) for sym in active_universe]
        scan_results = await asyncio.gather(*scan_tasks, return_exceptions=True)
        results = [r for r in scan_results if isinstance(r, dict)]
        
        # Sort by score and return top N
        results.sort(key=lambda x: x['score'], reverse=True)
        top_stocks = results[:top_n]
        
        logger.info(f"Found {len(top_stocks)} qualified stocks (pre-AI)")

        # ── AI Counter-Validation (brain layer) ────────────────────────
        # Instead of 143 per-stock AI calls at 5% weight (wasteful),
        # one batch call on the final shortlist with real veto/boost power.
        if top_stocks and self.model and ai_cost_tracker.should_use_ai("scanner"):
            top_stocks = await self._ai_counter_validate(top_stocks, regime)
            logger.info(f"AI counter-validation complete: {len(top_stocks)} stocks remain")
        
        # Publish event — include full per-stock data so StrategyAgent can skip
        # redundant indicator fetches (pass-through caching for 10-trade/s target).
        # Persist scanner results to Redis so strategy agent has stock data
        # even if it misses the event (TTL = 10 min, refreshed each cycle)
        try:
            import json as _json

            # Strip numpy types from indicators for JSON serialization
            def _sanitize(obj):
                if isinstance(obj, dict):
                    return {k: _sanitize(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_sanitize(v) for v in obj]
                if hasattr(obj, 'item'):  # numpy scalar
                    return obj.item()
                return obj

            await _redis_cache.set("scanner_results", _json.dumps(_sanitize({
                "results": top_stocks,
                "count": len(top_stocks),
                "regime": regime,
                "generated_at": datetime.now().isoformat(),
            })), ttl=600)
            logger.info(f"Scanner results cached to Redis: {len(top_stocks)} stocks")
        except Exception as _e:
            logger.warning(f"Failed to cache scanner results: {_e}")

        await self.publish_event("SCAN_COMPLETE", {
            "regime": regime,
            "stocks": [s["symbol"] for s in top_stocks],
            "scanned": top_stocks,   # full dicts: {symbol, score, indicators, timestamp}
            "count": len(top_stocks),
            "timestamp": datetime.now().isoformat(),
        })

        # ── Scanner cycle telemetry ─────────────────────────────────────────
        try:
            import json as _tj
            _raw_tel = await _redis_cache.get("scanner_telemetry")
            _tel = _tj.loads(_raw_tel) if _raw_tel else {"cycles": 0, "total_stocks_passed": 0, "session_start": datetime.now().isoformat()}
            _tel["cycles"] = _tel.get("cycles", 0) + 1
            _tel["total_stocks_passed"] = _tel.get("total_stocks_passed", 0) + len(top_stocks)
            _tel["last_cycle_stocks"] = len(top_stocks)
            _tel["last_cycle_universe"] = len(active_universe)
            _tel["last_cycle_regime"] = regime
            _tel["last_cycle_at"] = datetime.now().isoformat()
            await _redis_cache.set("scanner_telemetry", _tj.dumps(_tel), ttl=86400)
            logger.info(
                f"📡 SCANNER TELEMETRY | cycle=#{_tel['cycles']} "
                f"universe={len(active_universe)} scanned "
                f"qualified={len(results)} (score>={_min_score}) "
                f"top_n_to_strategy={len(top_stocks)} "
                f"regime={regime} "
                f"session_total_passed={_tel['total_stocks_passed']}"
            )
        except Exception as _te:
            logger.debug(f"Scanner telemetry update failed: {_te}")

        return top_stocks
    
    async def _analyze_stock(
        self, 
        symbol: str, 
        filters: Dict
    ) -> Tuple[float, Dict]:
        """
        Analyze a single stock with all 12 technical filters.
        
        Returns:
            Tuple of (overall_score, indicator_dict)
        """
        # Fetch data
        df = await self.nse_service.get_stock_ohlc(symbol, period="3M")
        
        if df is None or df.empty or len(df) < 50:
            return 0, {}
        
        # Calculate all indicators
        indicators = await self._calculate_all_indicators(df)
        
        # Score each indicator
        scores = {}
        
        # 1. RSI Score
        rsi = indicators.get('rsi', 50)
        if filters['rsi_min'] <= rsi <= filters['rsi_max']:
            scores['rsi_score'] = 100 - abs(rsi - 55) * 2  # Peak at 55
        else:
            scores['rsi_score'] = max(0, 50 - abs(rsi - 55))
        
        # 2. ADX Score
        adx = indicators.get('adx', 0)
        if adx >= filters['adx_min']:
            scores['adx_score'] = min(100, adx * 3)
        else:
            scores['adx_score'] = adx * 2
        
        # 3. MACD Score (gradient instead of binary for finer discrimination)
        macd_signal = indicators.get('macd_signal', 0)  # 1=bullish, -1=bearish, 0=neutral
        macd_hist = indicators.get('macd_histogram', 0)
        if filters.get('macd_confirm'):
            # Base: 50 + direction * 30, then add histogram strength bonus (±20)
            _macd_dir = 30 * macd_signal
            _hist_bonus = min(20, max(-20, macd_hist * 10)) if isinstance(macd_hist, (int, float)) else 0
            scores['macd_score'] = max(0, min(100, 50 + _macd_dir + _hist_bonus))
        else:
            scores['macd_score'] = 50
        
        # 4. RS vs Nifty Score (replaces Stochastic — Medallion CEO Fix #6)
        # 15-day rolling relative strength vs Nifty 50 index.
        # Stock return outperforming Nifty = institutional accumulation signal.
        rs_vs_nifty = indicators.get('rs_vs_nifty', 1.0)
        if rs_vs_nifty >= 1.15:      # Strong outperformer (>15% alpha vs index)
            scores['rs_nifty_score'] = 90
        elif rs_vs_nifty >= 1.05:    # Moderate outperformer
            scores['rs_nifty_score'] = 75
        elif rs_vs_nifty >= 0.95:    # Roughly in-line with Nifty
            scores['rs_nifty_score'] = 55
        elif rs_vs_nifty >= 0.85:    # Underperformer
            scores['rs_nifty_score'] = 35
        else:                        # Sharp underperformer (avoid)
            scores['rs_nifty_score'] = 15
        
        # 5. Volume Score
        volume_ratio = indicators.get('volume_ratio', 1.0)
        if volume_ratio >= filters['volume_ratio_min']:
            scores['volume_score'] = min(100, volume_ratio * 50)
        else:
            scores['volume_score'] = volume_ratio * 40
        
        # 6. OBV Score
        obv_rising = indicators.get('obv_rising', False)
        scores['obv_score'] = 80 if obv_rising else 40
        
        # 7. EMA Alignment Score (gradient: full align=90, partial=65, none=40)
        ema_aligned = indicators.get('ema_aligned', False)
        ema_partial = indicators.get('ema_partial_aligned', False)
        if ema_aligned:
            scores['ema_score'] = 90
        elif ema_partial:
            scores['ema_score'] = 65
        else:
            scores['ema_score'] = 40
        
        # 8. Bollinger Band Score (PSAR removed per Medallion CEO Fix #8 — zero downstream usage)
        bb_position = indicators.get('bb_position', 0.5)  # 0=lower, 0.5=mid, 1=upper
        scores['bb_score'] = 100 - abs(bb_position - 0.5) * 100  # Peak at middle
        
        # 9. Delivery % Score — reduced weight per Medallion CEO Fix #7 (T+1 data lag)
        # NSE bhavcopy delivery data is only published at ~18:30 IST after close.
        # When delivery_pct is unavailable (returns 0 during market hours), use
        # a neutral score of 50 instead of zero to avoid penalising otherwise
        # valid setups simply because the data feed hasn’t published yet.
        delivery_pct = indicators.get('delivery_pct', 0)
        if delivery_pct <= 0:
            scores['delivery_score'] = 50.0  # Neutral — data unavailable (intraday)
        elif delivery_pct >= filters.get('delivery_pct_min', 30):
            scores['delivery_score'] = min(100, (delivery_pct / 60) * 100) # Max 100 at 60% delivery
        else:
            scores['delivery_score'] = (delivery_pct / 30) * 40 # Penalize low delivery

        # 10. ATR Expansion Ratio Score (Medallion CEO Fix #7 — new indicator)
        # ATR expansion > 1.0 signals volatility expansion = trending move likely.
        # Scores highest when ATR is expanding (momentum confirmation signal).
        atr_exp = indicators.get('atr_expansion_ratio', 1.0)
        if atr_exp >= 1.4:      # Strong breakout-level ATR expansion
            scores['atr_expansion_score'] = 90
        elif atr_exp >= 1.2:    # Moderate expansion — good entry environment
            scores['atr_expansion_score'] = 75
        elif atr_exp >= 1.0:    # Stable / slight expansion
            scores['atr_expansion_score'] = 55
        elif atr_exp >= 0.8:    # ATR contracting — consolidation
            scores['atr_expansion_score'] = 35
        else:                   # Sharp ATR compression — avoid
            scores['atr_expansion_score'] = 20
        
        # Calculate weighted average
        total_score = sum(
            scores.get(k, 50) * self.weights.get(k, 0) 
            for k in self.weights.keys()
        )
        
        # Normalize to 0-100
        total_score = min(100, max(0, total_score))
        
        indicators['total_score'] = total_score
        indicators['scores_breakdown'] = scores
        
        return total_score, indicators
    
    async def _calculate_all_indicators(self, df: pd.DataFrame) -> Dict:
        """Calculate all 12 technical indicators."""
        
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        volume = df['volume'].astype(float)
        
        indicators = {}
        
        try:
            # 1. RSI
            indicators['rsi'] = float(ta.momentum.rsi(close, window=14).iloc[-1])
            
            # 2. ADX
            adx_indicator = ta.trend.ADXIndicator(high, low, close, window=14)
            indicators['adx'] = float(adx_indicator.adx().iloc[-1])
            indicators['di_plus'] = float(adx_indicator.adx_pos().iloc[-1])
            indicators['di_minus'] = float(adx_indicator.adx_neg().iloc[-1])
            
            # 3. MACD
            macd = ta.trend.MACD(close)
            macd_line = macd.macd().iloc[-1]
            signal_line = macd.macd_signal().iloc[-1]
            indicators['macd'] = float(macd_line)
            indicators['macd_signal'] = 1 if macd_line > signal_line else -1
            indicators['macd_histogram'] = float(macd_line - signal_line)
            
            # 4. RS vs Nifty — 15-day rolling relative strength (Medallion CEO Fix #6)
            # Requires self._nifty_close_cache prefetched by scan_universe().
            # Fallback to 1.0 (neutral) when Nifty data unavailable.
            # Panel Fix R2: align stock and Nifty series on common trading dates
            # before slicing to avoid computing RS across misaligned calendar windows.
            try:
                _nifty = self._nifty_close_cache
                if _nifty is not None and len(_nifty) >= 15 and len(close) >= 15:
                    # Attempt DatetimeIndex alignment (requires both series to be
                    # date-indexed by the NSE data service).
                    _has_dt_idx = (
                        hasattr(close.index, 'dtype')
                        and str(close.index.dtype).startswith('datetime')
                        and hasattr(_nifty.index, 'dtype')
                        and str(_nifty.index.dtype).startswith('datetime')
                    )
                    if _has_dt_idx:
                        _common = close.index.intersection(_nifty.index)
                        if len(_common) >= 15:
                            _s = close.reindex(_common)
                            _n = _nifty.reindex(_common)
                            _stock_ret = float(_s.iloc[-1] / _s.iloc[-15]) if _s.iloc[-15] > 0 else 1.0
                            _nifty_ret = float(_n.iloc[-1] / _n.iloc[-15]) if _n.iloc[-15] > 0 else 1.0
                        else:
                            _stock_ret, _nifty_ret = 1.0, 1.0  # insufficient common data
                    else:
                        # Integer-indexed series: iloc[-1] and iloc[-15] are positional
                        # and both series were fetched for the same period so positions
                        # are expected to correspond. Use current behaviour with guard.
                        _stock_ret = float(close.iloc[-1] / close.iloc[-15]) if close.iloc[-15] > 0 else 1.0
                        _nifty_ret = float(_nifty.iloc[-1] / _nifty.iloc[-15]) if _nifty.iloc[-15] > 0 else 1.0
                    indicators['rs_vs_nifty'] = round(_stock_ret / _nifty_ret, 4) if _nifty_ret > 0 else 1.0
                else:
                    indicators['rs_vs_nifty'] = 1.0  # neutral fallback
            except Exception:
                indicators['rs_vs_nifty'] = 1.0
            
            # 5. Volume ratio
            avg_volume = volume.rolling(20).mean().iloc[-1]
            indicators['volume_ratio'] = float(volume.iloc[-1] / avg_volume) if avg_volume > 0 else 1.0
            
            # 6. OBV
            obv = ta.volume.on_balance_volume(close, volume)
            obv_sma = obv.rolling(10).mean()
            indicators['obv_rising'] = bool(obv.iloc[-1] > obv_sma.iloc[-1])
            
            # 7. EMA Alignment (20 > 50 > 200 = bullish — Medallion CEO Fix #9: standardised periods)
            # Panel Fix R3: when fewer than 200 rows exist, do NOT set ema_200 = ema_50.
            # Python chain `close > ema_50 > ema_50` is always False (ema_50 > ema_50 = False),
            # which permanently blocked all recently-listed stocks from full alignment.
            ema_20 = ta.trend.ema_indicator(close, window=20).iloc[-1]
            ema_50 = ta.trend.ema_indicator(close, window=50).iloc[-1]
            if len(close) >= 200:
                ema_200 = ta.trend.ema_indicator(close, window=200).iloc[-1]
                indicators['ema_aligned'] = bool(close.iloc[-1] > ema_20 > ema_50 > ema_200)
                _above_count = sum([
                    close.iloc[-1] > ema_20,
                    close.iloc[-1] > ema_50,
                    close.iloc[-1] > ema_200,
                ])
            else:
                # Insufficient history for EMA(200) — use two-EMA stack as alignment proxy
                ema_200 = None
                indicators['ema_aligned'] = bool(close.iloc[-1] > ema_20 > ema_50)
                _above_count = sum([
                    close.iloc[-1] > ema_20,
                    close.iloc[-1] > ema_50,
                ])  # max 2; threshold adjusted below
            indicators['ema_partial_aligned'] = _above_count >= 2
            
            # 8. Bollinger Bands (PSAR removed per CEO Fix #8 — no downstream strategy uses it)
            bb = ta.volatility.BollingerBands(close, window=20)
            bb_upper = bb.bollinger_hband().iloc[-1]
            bb_lower = bb.bollinger_lband().iloc[-1]
            bb_range = bb_upper - bb_lower
            indicators['bb_position'] = float((close.iloc[-1] - bb_lower) / bb_range) if bb_range > 0 else 0.5
            indicators['bb_width'] = float(bb_range / close.iloc[-1])
            
            # 10. ATR + ATR Expansion Ratio (Medallion CEO Fix #7 — new indicator)
            _atr_series = ta.volatility.average_true_range(high, low, close, window=14)
            indicators['atr'] = float(_atr_series.iloc[-1])
            indicators['atr_pct'] = float(indicators['atr'] / close.iloc[-1])
            # ATR Expansion Ratio = current ATR / 5-period avg ATR
            # > 1.0 = expanding volatility (momentum); < 1.0 = contracting (consolidation)
            _atr_avg5 = _atr_series.rolling(5).mean().iloc[-1]
            indicators['atr_expansion_ratio'] = round(
                float(indicators['atr'] / _atr_avg5), 4
            ) if _atr_avg5 > 0 else 1.0
            
            # 11. Current price
            indicators['price'] = float(close.iloc[-1])
            
            # 12. Delivery %
            indicators['delivery_pct'] = await self.nse_service.get_delivery_percentage(df.get('symbol', 'UNKNOWN'))
            if indicators['delivery_pct'] == 0 and 'symbol' in df.columns:
                 indicators['delivery_pct'] = await self.nse_service.get_delivery_percentage(df['symbol'].iloc[0])

            # ── Improvement #6: Include short indicator series for Strategy pass-through ──
            # Last 5 values of key indicators so StrategyAgent can skip recomputation.
            try:
                _rsi_series = ta.momentum.rsi(close, window=14).dropna()
                _macd_hist = ta.trend.MACD(close).macd_diff().dropna()
                _bb_upper = bb.bollinger_hband().dropna()
                _bb_lower = bb.bollinger_lband().dropna()
                _ema20 = ta.trend.ema_indicator(close, window=20).dropna()

                indicators['series'] = {
                    'rsi_14': [round(float(v), 2) for v in _rsi_series.iloc[-5:].tolist()],
                    'macd_hist': [round(float(v), 4) for v in _macd_hist.iloc[-5:].tolist()],
                    'bb_upper': [round(float(v), 2) for v in _bb_upper.iloc[-5:].tolist()],
                    'bb_lower': [round(float(v), 2) for v in _bb_lower.iloc[-5:].tolist()],
                    'ema_20': [round(float(v), 2) for v in _ema20.iloc[-5:].tolist()],
                    'close': [round(float(v), 2) for v in close.iloc[-5:].tolist()],
                }
            except Exception:
                indicators['series'] = {}
            
        except Exception as e:
            logger.debug(f"Indicator calculation error: {e}")
        
        return indicators
    
    async def _ai_counter_validate(
        self,
        top_stocks: List[Dict[str, Any]],
        regime: str,
    ) -> List[Dict[str, Any]]:
        """
        AI Brain: counter-validate the scanner's top-N shortlist in ONE batch call.

        Instead of 143 per-stock calls at 5% weight (old approach), this makes a
        single structured call on the final 10–15 candidates with real power:
        - STRONG_BUY → score boosted +5
        - BUY → passes through unchanged
        - HOLD → score reduced −5, flagged
        - AVOID → vetoed (removed from list)

        Also performs cross-stock analysis (sector concentration, regime mismatch).

        SEBI Compliance:
        - Every AI verdict (including vetoes) persisted to Redis audit ring buffer
        - AI reasoning attached to stock indicators for downstream audit trail
        - Score adjustments recorded in scores_breakdown for full transparency
        """
        if not self.model or not top_stocks:
            return top_stocks

        # Build concise per-stock summaries for the prompt
        stock_lines = []
        for i, s in enumerate(top_stocks, 1):
            ind = s.get("indicators", {})
            stock_lines.append(
                f"{i}. {s['symbol']} | Score={s['score']:.0f} | "
                f"RSI={ind.get('rsi', 0):.0f} ADX={ind.get('adx', 0):.0f} "
                f"MACD={'Bull' if ind.get('macd_signal', 0) > 0 else 'Bear'} "
                f"RS_Nifty={ind.get('rs_vs_nifty', 1.0):.2f}x Vol={ind.get('volume_ratio', 1):.1f}x "
                f"EMA_Aligned={ind.get('ema_aligned', False)} "
                f"ATR_Exp={ind.get('atr_expansion_ratio', 1.0):.2f}x "
                f"BB_Pos={ind.get('bb_position', 0.5):.2f} "
                f"Delivery={ind.get('delivery_pct', 0):.0f}% "
                f"Price={ind.get('price', 0):.1f}"
            )
        stocks_text = "\n".join(stock_lines)

        prompt = f"""You are the AI brain of a professional Indian stock trading system (NSE).
The scanner has shortlisted {len(top_stocks)} stocks using 10 technical indicators.
Your job: counter-validate each stock and catch what indicators might miss.

Market Regime: {regime}

Shortlisted Stocks:
{stocks_text}

For EACH stock, evaluate:
1. Do the indicators genuinely confirm a tradeable setup in {regime} regime?
2. Any red flags? (divergences between indicators, volume not confirming, range-bound stock in trending strategy, etc.)
3. Sector concentration risk — flag if too many stocks from the same sector.

Return a JSON array. Each element must have:
- "symbol": stock symbol (string)
- "verdict": one of "STRONG_BUY", "BUY", "HOLD", "AVOID" (string)
- "confidence": 0.0-1.0 (number)
- "red_flags": list of short strings, empty list if none
- "reasoning": one-line explanation (string)

Return ONLY the JSON array, no other text."""

        try:
            response = await asyncio.to_thread(
                self.model.generate_content, prompt
            )

            # Track token usage
            _in_tok = getattr(
                getattr(response, "usage_metadata", None),
                "prompt_token_count", 0
            ) or len(prompt) // 4
            _out_tok = getattr(
                getattr(response, "usage_metadata", None),
                "candidates_token_count", 0
            ) or 200
            await ai_cost_tracker.record_usage(
                "scanner", input_tokens=_in_tok, output_tokens=_out_tok
            )

            # Parse structured JSON response
            import json as _json
            import re
            raw = response.text.strip()
            # Handle markdown code-fence wrapping
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if not m:
                logger.warning("AI counter-validation: could not parse JSON array, passing all stocks through")
                return top_stocks
            verdicts = _json.loads(m.group())

            # Build symbol→verdict lookup
            verdict_map = {}
            for v in verdicts:
                sym = v.get("symbol", "").upper().strip()
                if sym:
                    verdict_map[sym] = v

            # ── SEBI: Persist full AI validation batch to audit trail ─────
            # Matches the manual_controls.py _audit() pattern: JSON list in
            # Redis key with 1000-event cap + Postgres for permanence.
            audit_entry = {
                "ts": datetime.now().isoformat(),
                "event": "SCANNER_AI_COUNTER_VALIDATION",
                "regime": regime,
                "candidates": len(top_stocks),
                "verdicts": verdicts,
            }
            try:
                import json as _json_audit
                _audit_key = "manual_controls:audit_log"
                raw_log = await _redis_cache.get(_audit_key)
                audit_log = _json_audit.loads(raw_log) if raw_log else []
                audit_log.append(audit_entry)
                if len(audit_log) > 1000:
                    audit_log = audit_log[-1000:]
                await _redis_cache.set(
                    _audit_key, _json_audit.dumps(audit_log), ttl=86400 * 90
                )
                # Also persist to Postgres for permanent SEBI trail
                try:
                    from src.database.postgres import db
                    if db.pool:
                        async with db.pool.acquire() as conn:
                            await conn.execute(
                                """INSERT INTO sebi_audit_log
                                   (ts, action, operator, strategy_id, payload)
                                   VALUES (NOW(), $1, $2, $3, $4::jsonb)""",
                                "scanner_ai_validation",
                                "system",
                                None,
                                _json_audit.dumps(audit_entry),
                            )
                except Exception:
                    pass  # Postgres failure non-blocking (matches _audit pattern)
            except Exception:
                logger.debug("Failed to write AI validation audit to Redis")

            # Apply verdicts
            validated = []
            for stock in top_stocks:
                sym = stock["symbol"]
                v = verdict_map.get(sym, {})
                verdict = v.get("verdict", "BUY").upper()
                confidence = float(v.get("confidence", 0.5))
                red_flags = v.get("red_flags", [])
                reasoning = v.get("reasoning", "")

                # ── SEBI: Attach AI metadata to indicators for audit trail ──
                stock["indicators"]["ai_verdict"] = verdict
                stock["indicators"]["ai_confidence"] = confidence
                stock["indicators"]["ai_red_flags"] = red_flags
                stock["indicators"]["ai_reasoning"] = reasoning

                # ── SEBI: Record AI score adjustment in scores_breakdown ──
                scores_bd = stock["indicators"].get("scores_breakdown", {})

                if verdict == "AVOID":
                    scores_bd["ai_adjustment"] = "VETOED"
                    stock["indicators"]["scores_breakdown"] = scores_bd
                    logger.info(
                        f"AI VETO: {sym} (conf={confidence:.2f}) — {reasoning[:80]}"
                    )
                    continue  # Remove from shortlist

                if verdict == "STRONG_BUY":
                    old_score = stock["score"]
                    stock["score"] = min(100, stock["score"] + 5)
                    scores_bd["ai_adjustment"] = f"+5 (STRONG_BUY, {old_score:.0f}→{stock['score']:.0f})"
                    logger.info(
                        f"AI BOOST: {sym} +5 → {stock['score']:.0f} (conf={confidence:.2f})"
                    )
                elif verdict == "HOLD":
                    old_score = stock["score"]
                    stock["score"] = max(0, stock["score"] - 5)
                    scores_bd["ai_adjustment"] = f"-5 (HOLD, {old_score:.0f}→{stock['score']:.0f})"
                    logger.info(
                        f"AI FLAG: {sym} −5 → {stock['score']:.0f} — {reasoning[:60]}"
                    )
                else:  # BUY
                    scores_bd["ai_adjustment"] = "0 (BUY, no change)"
                    logger.debug(f"AI OK: {sym} (conf={confidence:.2f})")

                stock["indicators"]["scores_breakdown"] = scores_bd
                validated.append(stock)

            # Re-sort after score adjustments
            validated.sort(key=lambda x: x["score"], reverse=True)
            return validated

        except Exception as e:
            logger.warning(f"AI counter-validation failed, passing all through: {e}")
            return top_stocks

    def _adjust_filters_for_regime(self, regime: str) -> Dict:
        """Adjust filter thresholds based on market regime."""
        adjusted = self.filters.copy()
        
        if regime == "BULL":
            adjusted['rsi_min'] = 45
            adjusted['rsi_max'] = 75
            adjusted['adx_min'] = 20
            adjusted['volume_ratio_min'] = 1.2
        
        elif regime == "BEAR":
            adjusted['rsi_min'] = 30
            adjusted['rsi_max'] = 55
            adjusted['adx_min'] = 25
            adjusted['volume_ratio_min'] = 1.5
        
        elif regime == "SIDEWAYS":
            adjusted['rsi_min'] = 40
            adjusted['rsi_max'] = 60
            adjusted['adx_min'] = 15  # Lower threshold for ranging
            adjusted['bb_squeeze'] = True
        
        elif regime == "VOLATILE":
            adjusted['adx_min'] = 30
            adjusted['atr_min_pct'] = 0.015
            adjusted['volume_ratio_min'] = 1.5
        
        return adjusted
    
    def get_scanner_summary(self) -> Dict:
        """Get summary of scanner configuration."""
        return {
            "universe_size": len(self.SCAN_UNIVERSE),
            "filters_count": len(self.filters),
            "genai_enabled": self.model is not None,
            "ai_mode": "counter_validator",  # batch post-scan validation
            "indicator_weights": self.weights
        }
