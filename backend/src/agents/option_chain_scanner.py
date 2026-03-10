"""
Option Chain Scanner Agent
==========================
Scans all NSE F&O indices and high-OI stocks to detect tradable multi-leg
options structures.  Publishes OPTIONS_SCAN_COMPLETE for StrategyAgent to
consume — parallel to the equity ScannerAgent inside the 3-minute cycle.

Scanning happens in three stages:
  Stage 1 — Collect chains in parallel (asyncio.gather)
  Stage 2 — Score each chain for four canonical structures:
              IRON_CONDOR, BULL_CALL_SPREAD, BEAR_PUT_SPREAD, STRADDLE
  Stage 3 — Filter, rank, and publish OPTIONS_SCAN_COMPLETE

Published event payload:
  {
    "regime": str,
    "chains": [
      {
        "symbol": str,
        "structure": str,             # best-fit structure name
        "score": float,               # 0-100
        "iv_rank": float,             # 0-100 percentile
        "atm_iv": float,
        "oi_pcr": float,              # put-call OI ratio
        "atm_strike": float,
        "expiry": str,                # ISO date
        "legs": [...],                # raw OptionChainItem-level dicts
        "chain_summary": {...}
      }, ...
    ],
    "count": int,
    "timestamp": str
  }
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.agents.base import BaseAgent
from src.services.option_chain import option_chain_service, LOT_SIZES
from src.models.options import OptionChain, OptionChainItem, OptionType

logger = logging.getLogger(__name__)

# ─── Universe ────────────────────────────────────────────────────────────────
# Always scan indices first; F&O stocks added by regime-filter in Stage 1
INDEX_UNIVERSE: List[str] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]

# Top-25 equity F&O by average OI + liquidity (fallback when nse_service unavailable)
_DEFAULT_EQUITY_FNO: List[str] = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "AXISBANK", "BAJFINANCE", "BAJAJFINSV", "TATAMOTORS",
    "WIPRO", "HCLTECH", "BHARTIARTL", "ITC", "MARUTI",
    "SUNPHARMA", "DRREDDY", "KOTAKBANK", "INDUSINDBK", "LT",
    "TATASTEEL", "HINDALCO", "TITAN", "M&M", "NTPC",
]


# ─── Scoring helpers ─────────────────────────────────────────────────────────
def _call_oi(chain: OptionChain) -> float:
    return sum(s.oi or 0 for s in chain.strikes if s.option_type == OptionType.CALL)


def _put_oi(chain: OptionChain) -> float:
    return sum(s.oi or 0 for s in chain.strikes if s.option_type == OptionType.PUT)


def _pcr(chain: OptionChain) -> float:
    c = _call_oi(chain)
    p = _put_oi(chain)
    return (p / c) if c > 0 else 1.0


def _atm_iv(chain: OptionChain) -> float:
    """Return average IV of ATM call + put."""
    spot = chain.spot_price or 0
    if not spot or not chain.strikes:
        return 0.0
    nearest = min(chain.strikes, key=lambda s: abs(s.strike - spot))
    atm_strike = nearest.strike
    atm = [s for s in chain.strikes if s.strike == atm_strike]
    ivs = [s.iv for s in atm if s.iv and s.iv > 0]
    return sum(ivs) / len(ivs) if ivs else 0.0


def _iv_rank(current_iv: float, symbol: str) -> float:
    """
    Simplified IV rank using rough 52-week IV range benchmarks.
    A proper implementation would query a volatility surface DB.
    Returns a 0-100 percentile estimate.
    """
    # Benchmark: (low_iv, high_iv) rough estimates per underlying type
    benchmarks: Dict[str, Tuple[float, float]] = {
        "NIFTY":       (10, 30),
        "BANKNIFTY":   (12, 40),
        "FINNIFTY":    (12, 35),
        "MIDCPNIFTY":  (13, 38),
    }
    lo, hi = benchmarks.get(symbol, (15, 55))
    if hi <= lo:
        return 50.0
    rank = (current_iv - lo) / (hi - lo) * 100
    return max(0.0, min(100.0, rank))


def _score_iron_condor(atm_iv_val: float, iv_r: float, pcr_val: float) -> float:
    """IC is best when IV rank is high (sell expensive premium)."""
    score = 0.0
    if iv_r > 70:
        score += 40
    elif iv_r > 50:
        score += 20
    # Balanced PCR (0.8-1.2) → range-bound market → good for IC
    if 0.8 <= pcr_val <= 1.2:
        score += 30
    elif 0.6 <= pcr_val <= 1.5:
        score += 15
    # High absolute IV → rich premium
    if atm_iv_val > 20:
        score += 30
    elif atm_iv_val > 12:
        score += 15
    return min(score, 100.0)


def _score_bull_call_spread(atm_iv_val: float, iv_r: float, pcr_val: float) -> float:
    """BCS favours moderate IV (not too expensive to buy), bullish bias (PCR <1)."""
    score = 0.0
    if pcr_val < 0.8:
        score += 40  # bullish signal
    elif pcr_val < 1.0:
        score += 20
    if 30 < iv_r < 60:
        score += 30  # moderate IV — affordable debit
    elif iv_r <= 30:
        score += 20
    if 12 <= atm_iv_val <= 25:
        score += 30
    elif atm_iv_val < 35:
        score += 15
    return min(score, 100.0)


def _score_bear_put_spread(atm_iv_val: float, iv_r: float, pcr_val: float) -> float:
    """BPS favours moderate IV, bearish bias (PCR > 1.2)."""
    score = 0.0
    if pcr_val > 1.2:
        score += 40
    elif pcr_val > 1.0:
        score += 20
    if 30 < iv_r < 60:
        score += 30
    elif iv_r <= 30:
        score += 20
    if 12 <= atm_iv_val <= 25:
        score += 30
    elif atm_iv_val < 35:
        score += 15
    return min(score, 100.0)


def _score_straddle(atm_iv_val: float, iv_r: float, pcr_val: float) -> float:
    """Short straddle suits low IV rank + neutral PCR (sell when cheap)."""
    score = 0.0
    if iv_r < 30:
        score += 50  # not too expensive to sell
    elif iv_r < 50:
        score += 20
    if 0.9 <= pcr_val <= 1.1:
        score += 30  # neutral
    return min(score, 100.0)


def _best_structure(
    atm_iv_val: float, iv_r: float, pcr_val: float
) -> Tuple[str, float]:
    """Return (structure_name, score) for the best fit."""
    candidates = {
        "IRON_CONDOR":      _score_iron_condor(atm_iv_val, iv_r, pcr_val),
        "BULL_CALL_SPREAD":  _score_bull_call_spread(atm_iv_val, iv_r, pcr_val),
        "BEAR_PUT_SPREAD":   _score_bear_put_spread(atm_iv_val, iv_r, pcr_val),
        "STRADDLE":          _score_straddle(atm_iv_val, iv_r, pcr_val),
    }
    best = max(candidates, key=lambda k: candidates[k])
    return best, candidates[best]


# ─── Agent ───────────────────────────────────────────────────────────────────

class OptionChainScannerAgent(BaseAgent):
    """
    Scans option chains for all F&O indices + top equity F&O stocks.
    Publishes OPTIONS_SCAN_COMPLETE with scored structure opportunities.
    """

    # Minimum score to qualify an opportunity
    MIN_SCORE: float = 40.0
    # Max symbols to fetch in one cycle (protect API rate limits)
    MAX_SYMBOLS: int = int(30)

    def __init__(self, name: str = "OptionChainScannerAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)

        self._option_chain_svc = option_chain_service
        self._equity_fno: List[str] = list(_DEFAULT_EQUITY_FNO)

        # Try to load full F&O list from nse_data_service
        try:
            from src.services.nse_data import nse_data_service as _nse
            fno = _nse.get_fno_stocks()
            if fno:
                self._equity_fno = fno
        except Exception as exc:
            logger.warning(f"Could not load F&O stocks from NSEDataService: {exc}")

        logger.info(
            f"OptionChainScannerAgent initialised — "
            f"{len(INDEX_UNIVERSE)} indices + {len(self._equity_fno)} equity F&O"
        )

    # ── Public entry-point ────────────────────────────────────────────────────
    async def scan_option_universe(self, regime: str) -> List[Dict[str, Any]]:
        """
        Main scan routine called by AgentManager every 3-minute cycle.

        Steps:
          1. Select symbols to scan (indices always + regime-filtered equity)
          2. Fetch option chains in parallel batches
          3. Score and rank opportunities
          4. Publish OPTIONS_SCAN_COMPLETE and return list
        """
        self.status = "RUNNING"
        start_ts = datetime.now()

        symbols = self._select_symbols(regime)
        logger.info(f"[OptionChainScanner] Scanning {len(symbols)} symbols (regime={regime})")

        chains_raw = await self._fetch_chains_parallel(symbols)

        opportunities = []
        for symbol, chain in chains_raw:
            opp = self._score_chain(symbol, chain)
            if opp and opp["score"] >= self.MIN_SCORE:
                opportunities.append(opp)

        # Sort by score descending
        opportunities.sort(key=lambda x: x["score"], reverse=True)

        elapsed = (datetime.now() - start_ts).total_seconds()
        logger.info(
            f"[OptionChainScanner] Found {len(opportunities)} opportunities "
            f"from {len(symbols)} symbols in {elapsed:.2f}s"
        )

        await self.publish_event("OPTIONS_SCAN_COMPLETE", {
            "regime": regime,
            "chains": opportunities,
            "count": len(opportunities),
            "scanned_count": len(symbols),
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        })

        self.status = "READY"
        self.last_execution_time = datetime.now()
        return opportunities

    # ── Symbol selection ──────────────────────────────────────────────────────
    def _select_symbols(self, regime: str) -> List[str]:
        """
        Always include all 4 indices.
        In BULL/BEAR regimes add top 15 equity F&O.
        In SIDEWAYS/VOLATILE add top 20 (IC + straddle opportunities).
        """
        equity_count = 20 if regime in ("SIDEWAYS", "VOLATILE", "volatile", "sideways") else 15
        equity = self._equity_fno[:equity_count]

        symbols = list(INDEX_UNIVERSE) + equity
        # Cap at MAX_SYMBOLS
        return symbols[: self.MAX_SYMBOLS]

    # ── Parallel chain fetch ──────────────────────────────────────────────────
    async def _fetch_chains_parallel(
        self, symbols: List[str]
    ) -> List[Tuple[str, Optional[OptionChain]]]:
        """Fetch all chains concurrently; handle per-symbol errors gracefully."""

        async def _fetch_one(sym: str) -> Tuple[str, Optional[OptionChain]]:
            try:
                chain = await self._option_chain_svc.get_chain(
                    sym, num_strikes=10, expiry_type="WEEKLY", enrich_greeks=True
                )
                return sym, chain
            except Exception as exc:
                logger.debug(f"Chain fetch failed for {sym}: {exc}")
                return sym, None

        tasks = [_fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return [r for r in results if r[1] is not None]  # drop failed

    # ── Scoring ───────────────────────────────────────────────────────────────
    def _score_chain(
        self, symbol: str, chain: OptionChain
    ) -> Optional[Dict[str, Any]]:
        """
        Score a single chain and return an opportunity dict, or None if
        there is insufficient data.
        """
        if not chain or not chain.strikes:
            return None

        spot = chain.spot_price or 0
        if spot <= 0:
            return None

        # Core metrics
        atm_iv_val = _atm_iv(chain)
        pcr_val = _pcr(chain)
        iv_r = _iv_rank(atm_iv_val, symbol)

        structure, score = _best_structure(atm_iv_val, iv_r, pcr_val)

        # ATM strike
        nearest = min(chain.strikes, key=lambda s: abs(s.strike - spot))
        atm_strike = nearest.strike

        # Collect ATM ± 2 strike rows for downstream strategy use
        sorted_strikes = sorted(chain.strikes, key=lambda s: s.strike)
        near_atm = [
            {
                "strike": s.strike,
                "option_type": s.option_type.value if s.option_type else "CE",
                "ltp": s.ltp or 0,
                "iv": s.iv or 0,
                "oi": s.oi or 0,
                "delta": s.greeks.delta if s.greeks else None,
                "gamma": s.greeks.gamma if s.greeks else None,
                "theta": s.greeks.theta if s.greeks else None,
                "vega": s.greeks.vega if s.greeks else None,
            }
            for s in sorted_strikes
            if abs(s.strike - atm_strike) <= 2 * STRIKE_STEPS_FALLBACK(symbol)
        ]

        return {
            "symbol": symbol,
            "structure": structure,
            "score": round(score, 2),
            "iv_rank": round(iv_r, 2),
            "atm_iv": round(atm_iv_val, 4),
            "oi_pcr": round(pcr_val, 4),
            "atm_strike": atm_strike,
            "spot_price": spot,
            "expiry": chain.expiry or "",
            "lot_size": LOT_SIZES.get(symbol, LOT_SIZES.get("NIFTY", 25)),
            "legs": near_atm,
            "chain_summary": {
                "total_strikes": len(chain.strikes),
                "call_oi": _call_oi(chain),
                "put_oi": _put_oi(chain),
            },
        }


def STRIKE_STEPS_FALLBACK(symbol: str) -> float:
    """Minimal inline helper to avoid circular import with option_chain.py."""
    from src.services.option_chain import STRIKE_STEPS, DEFAULT_STRIKE_STEP
    return STRIKE_STEPS.get(symbol, DEFAULT_STRIKE_STEP)


# Module-level singleton
option_chain_scanner = OptionChainScannerAgent()
