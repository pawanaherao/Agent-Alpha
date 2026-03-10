"""
Enhanced Risk Agent with Kelly Criterion Position Sizing
SEBI Compliant: Transparent risk rules

Features:
1. Kelly Criterion position sizing
2. Portfolio heat check (max capital at risk)
3. Correlation filtering (sector concentration)
4. VIX-based position scaling
5. Daily loss limits (kill switch)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging
import numpy as np
import pandas as pd
from scipy import stats

from src.agents.base import BaseAgent
from src.core.config import settings
from src.core.messages import RiskDecision, AgentMessage
from src.services.nse_data import nse_data_service
from src.services.auto_closeout_handler import trigger_auto_closeout_if_needed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NSE sector mapping — used for sector concentration enforcement
# ---------------------------------------------------------------------------
_SECTOR_MAP: dict = {
    # Banking
    "HDFCBANK": "banking",  "ICICIBANK": "banking",  "AXISBANK": "banking",
    "KOTAKBANK": "banking", "SBIN": "banking",       "INDUSINDBK": "banking",
    "BANDHANBNK": "banking", "FEDERALBNK": "banking", "IDFCFIRSTB": "banking",
    # Finance / NBFC
    "BAJFINANCE": "finance",  "BAJAJFINSV": "finance", "HDFC": "finance",
    "MUTHOOTFIN": "finance",  "CHOLAFIN": "finance",  "M&MFIN": "finance",
    # IT / Software
    "TCS": "it",    "INFY": "it",    "WIPRO": "it",
    "HCLTECH": "it", "TECHM": "it",   "LTIM": "it",
    "MPHASIS": "it", "PERSISTENT": "it", "COFORGE": "it",
    # Energy / Oil & Gas
    "RELIANCE": "energy",  "ONGC": "energy",    "IOC": "energy",
    "BPCL": "energy",     "NTPC": "energy",     "POWERGRID": "energy",
    "TATAPOWER": "energy", "ADANIGREEN": "energy", "ADANIPORTS": "energy",
    # FMCG / Consumer
    "HINDUNILVR": "fmcg", "ITC": "fmcg",        "NESTLEIND": "fmcg",
    "BRITANNIA": "fmcg",  "DABUR": "fmcg",      "MARICO": "fmcg",
    "GODREJCP": "fmcg",   "COLPAL": "fmcg",     "EMAMILTD": "fmcg",
    # Automobile
    "MARUTI": "auto",    "TATAMOTORS": "auto", "M&M": "auto",
    "BAJAJ-AUTO": "auto", "HEROMOTOCO": "auto", "EICHERMOT": "auto",
    "TVSMOTOR": "auto",  "ASHOKLEY": "auto",
    # Pharma / Healthcare
    "SUNPHARMA": "pharma", "DRREDDY": "pharma",  "CIPLA": "pharma",
    "DIVISLAB": "pharma",  "AUROPHARMA": "pharma", "TORNTPHARM": "pharma",
    "LUPIN": "pharma",    "ALKEM": "pharma",     "APOLLOHOSP": "pharma",
    "MAXHEALTH": "pharma",
    # Metals / Mining
    "TATASTEEL": "metals", "HINDALCO": "metals", "JSWSTEEL": "metals",
    "SAIL": "metals",     "NMDC": "metals",     "VEDL": "metals",
    "NATIONALUM": "metals",
    # Telecom
    "BHARTIARTL": "telecom", "VBL": "telecom",
    # Infrastructure / Cement
    "LARSEN": "infra",    "LT": "infra",       "ULTRACEMCO": "infra",
    "GRASIM": "infra",   "AMBUJACEM": "infra", "ACC": "infra",
    "ADANIENT": "infra",  "BEL": "infra",      "HAL": "infra",
    # Retail / Consumer Discretionary
    "DMART": "retail",    "TITAN": "retail",    "TRENT": "retail",
    "PAGEIND": "retail",  "ZOMATO": "retail",   "NYKAA": "retail",
    # Insurance
    "SBILIFE": "insurance", "HDFCLIFE": "insurance", "ICICIPRULI": "insurance",
    # Chemicals
    "PIDILITIND": "chemicals", "SRF": "chemicals", "ATUL": "chemicals",
    "POLYCAB": "chemicals",
    # Diversified / Conglomerate
    "ASIANPAINT": "diversified", "HAVELLS": "diversified", "VOLTAS": "diversified",
    "PRESTIGE": "diversified", "COALINDIA": "mining", "UNIONBANK": "banking",
    # Indices (options underlyings)
    "NIFTY": "index", "NIFTY50": "index", "BANKNIFTY": "index",
    "FINNIFTY": "index", "MIDCPNIFTY": "index",
}


class RiskAgent(BaseAgent):
    """
    Enhanced Risk Agent with Kelly Criterion sizing.
    
    RISK CHECKS (WHITEBOX):
    1. Daily Loss Limit: -5% of capital (kill switch)
    2. Position Heat: Max 25% capital at risk at any time
    3. Single Position Size: Max 5% of capital
    4. Sector Concentration: Max 30% in single sector
    5. Kelly Criterion: Optimal position based on win rate
    6. VIX Scaling: Reduce size in high volatility
    7. Max Concurrent Positions: Limit open positions count
    8. Drawdown-Responsive Sizing: Scale down during drawdowns
    9. Regime-Aware Parameters: Tighten/widen by market regime
    """
    
    def __init__(self, name: str = "RiskAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        
        # Capital parameters
        self.total_capital = config.get('capital', 1_000_000) if config else 1_000_000  # 10L default
        self.daily_pnl = 0.0
        
        # Risk limits (MFT-tuned Mar 2026: widened for throughput)
        _is_paper = bool(getattr(settings, "PAPER_TRADING", False)) or \
                    getattr(settings, "MODE", "LIVE") in ("PAPER", "LOCAL")
        self.max_daily_loss_pct = 0.05  # 5% of capital
        self.max_position_size_pct = 0.08  # 8% per position (was 5%)
        self.max_portfolio_heat_pct = 0.35  # 35% total at risk (was 25%)
        self.max_sector_concentration = 0.60 if _is_paper else 0.30  # paper: relax to 60%
        self.max_concurrent_positions = 15    # P1: hard cap on open positions
        
        # Kelly parameters (MFT-tuned: 1/3 Kelly for higher capital deployment)
        self.default_win_rate = 0.55
        self.default_rr_ratio = 2.0
        self.kelly_fraction = 0.33  # Use third Kelly (was 0.25 quarter)
        # Baseline Kelly fraction (restored after drawdown recovery)
        self._base_kelly_fraction = 0.33
        
        # Drawdown tracking (P1-1: drawdown-responsive sizing)
        self._peak_capital = self.total_capital
        self._current_drawdown_pct = 0.0
        
        # Regime-aware risk parameters (P1-2)
        self._current_regime = "SIDEWAYS"
        self._regime_risk_profiles = {
            "BULL": {
                "max_position_size_pct": 0.08,
                "max_portfolio_heat_pct": 0.40,
                "kelly_fraction": 0.33,
                "max_concurrent_positions": 15,
            },
            "BEAR": {
                "max_position_size_pct": 0.04,
                "max_portfolio_heat_pct": 0.20,
                "kelly_fraction": 0.20,
                "max_concurrent_positions": 8,
            },
            "SIDEWAYS": {
                "max_position_size_pct": 0.06,
                "max_portfolio_heat_pct": 0.30,
                "kelly_fraction": 0.25,
                "max_concurrent_positions": 12,
            },
            "VOLATILE": {
                "max_position_size_pct": 0.03,
                "max_portfolio_heat_pct": 0.15,
                "kelly_fraction": 0.15,
                "max_concurrent_positions": 6,
            },
        }
        
        # VIX scaling
        self.vix_low = 12
        self.vix_high = 25
        
        # Current positions (simplified)
        self.open_positions: Dict[str, Dict] = {}
        self.sector_exposure: Dict[str, float] = {}
        self.price_history: Dict[str, pd.Series] = {} # For correlation
        
        self.nse_service = nse_data_service
        
        logger.info("Risk Agent initialized with Kelly + drawdown + regime-aware sizing")
    
    @property
    def max_daily_loss(self) -> float:
        """Maximum daily loss in absolute terms."""
        return -self.total_capital * self.max_daily_loss_pct
    
    async def validate_signal(self, signal_data: Dict[str, Any]) -> RiskDecision:
        """
        Validate signal against risk parameters.
        
        WHITEBOX LOGIC:
        1. Check kill switch (daily loss limit)
        2. Check portfolio heat
        3. Check sector concentration
        4. Calculate Kelly-based position size
        5. Apply VIX scaling
        6. Return decision with quantity
        """
        signal_id = signal_data.get('signal_id', 'UNKNOWN')
        symbol = signal_data.get('symbol', 'UNKNOWN')
        entry_price = float(signal_data.get('entry_price') or 0)
        stop_loss = float(signal_data.get('stop_loss') or 0)
        target_price = float(signal_data.get('target_price') or 0)
        strength = signal_data.get('strength', 0.5)

        # Guard: if strategy did not provide entry_price, fetch live LTP.
        # This covers all modes (LIVE, PAPER, LOCAL). Using a hardcoded ₹1
        # placeholder would produce nonsense position sizes and risk metrics.
        if entry_price <= 0:
            try:
                quote = await self.nse_service.get_live_quote(symbol)
                ltp = float(quote.get("ltp") or quote.get("last_price") or 0)
                if ltp > 0:
                    entry_price = ltp
                    # Derive stop/target from LTP using default 3%/6% ATR-proxy if missing
                    if stop_loss <= 0:
                        stop_loss = round(entry_price * 0.97, 2)
                    if target_price <= 0:
                        target_price = round(entry_price * 1.06, 2)
                    logger.info(
                        f"Signal {signal_id} for {symbol}: entry_price resolved via "
                        f"live quote → ₹{entry_price:.2f}"
                    )
                else:
                    raise ValueError("live quote returned LTP=0")
            except Exception as _ltp_err:
                logger.warning(
                    f"Signal {signal_id} for {symbol} has no entry_price and "
                    f"live quote failed ({_ltp_err}) — rejected"
                )
                return RiskDecision(
                    decision="REJECTED",
                    reason=f"No entry_price and live quote unavailable for {symbol}",
                    original_signal_id=signal_id,
                )
        
        # 1. Kill Switch Check
        if self.daily_pnl < self.max_daily_loss:
            logger.warning(f"Kill Switch Active! Daily PnL: {self.daily_pnl:.0f}")
            return RiskDecision(
                decision="REJECTED",
                reason=f"Kill Switch: Daily loss {self.daily_pnl:.0f} exceeds limit {self.max_daily_loss:.0f}",
                original_signal_id=signal_id
            )
        
        # 2. Portfolio Heat Check
        current_heat = self._calculate_portfolio_heat()
        if current_heat >= self.max_portfolio_heat_pct:
            logger.warning(f"Portfolio heat too high: {current_heat*100:.1f}%")
            return RiskDecision(
                decision="REJECTED",
                reason=f"Portfolio heat {current_heat*100:.1f}% exceeds limit {self.max_portfolio_heat_pct*100}%",
                original_signal_id=signal_id
            )
        
        # 2b. Max Concurrent Positions Check (P1 fix)
        if len(self.open_positions) >= self.max_concurrent_positions:
            logger.warning(
                f"Max concurrent positions reached: {len(self.open_positions)}/{self.max_concurrent_positions}"
            )
            return RiskDecision(
                decision="REJECTED",
                reason=f"Max concurrent positions {self.max_concurrent_positions} reached "
                       f"({len(self.open_positions)} open)",
                original_signal_id=signal_id,
            )

        # 2c. Apply drawdown-responsive sizing (P1-1)
        drawdown_multiplier = self._drawdown_multiplier()

        # 3. Sector Concentration Check (fast — O(1) dict lookup, no I/O)
        sector_msg = self._check_sector_concentration(
            symbol, entry_price * int(self.total_capital * self.max_position_size_pct / entry_price)
        )
        if sector_msg:
            logger.warning(f"Sector concentration breach for {symbol}: {sector_msg}")
            return RiskDecision(
                decision="REJECTED",
                reason=sector_msg,
                original_signal_id=signal_id,
            )

        # 4. Correlation Risk Check (Phase 4) — raised to 0.80 for sector sweeps
        correlation_risk = await self._calculate_correlation_risk(symbol)
        # Panel Fix M5: use >= 0.81 so that correlation_risk == 0.80 (exactly) flows
        # through to the 50 % Kelly ceiling tier below instead of hard-blocking here.
        # Floating-point values like 0.8000000001 triggered the old > 0.80 guard.
        if correlation_risk >= 0.81:
            logger.warning(f"Correlation too high for {symbol}: {correlation_risk:.2f}")
            return RiskDecision(
                decision="REJECTED",
                reason=f"Correlation {correlation_risk:.2f} with portfolio exceeds 0.81 — hard block",
                original_signal_id=signal_id
            )

        # ── Correlation-adjusted position ceiling (Medallion CEO Fix #11) ─────
        # If new position has meaningful correlation (0.60–0.80) with the existing
        # portfolio, reduce the Kelly position size proportionally instead of
        # hard-blocking.  This allows diversified entry at reduced size rather
        # than an all-or-nothing binary decision.
        #   corr 0.60–0.70 → position floor = 75% of Kelly
        #   corr 0.70–0.80 → position floor = 50% of Kelly
        _corr_kelly_mult = 1.0
        if 0.70 <= correlation_risk <= 0.80:
            _corr_kelly_mult = 0.50
            logger.info(
                f"Correlation ceiling: {symbol} corr={correlation_risk:.2f} — "
                f"Kelly reduced to 50% of calculated size"
            )
        elif 0.60 <= correlation_risk < 0.70:
            _corr_kelly_mult = 0.75
            logger.info(
                f"Correlation ceiling: {symbol} corr={correlation_risk:.2f} — "
                f"Kelly reduced to 75% of calculated size"
            )
        # ── End correlation ceiling ───────────────────────────────────────────

        # 4. VaR Check (Phase 4)
        var_value = await self._calculate_var(symbol, entry_price)
        if var_value > self.total_capital * 0.02: # Max 2% capital at risk per VaR
            logger.warning(f"VaR too high for {symbol}: {var_value:.0f}")
            return RiskDecision(
                decision="REJECTED",
                reason=f"VaR {var_value:.0f} exceeds 2% capital limit",
                original_signal_id=signal_id
            )

        # 5. Calculate risk per share
        # Multi-leg options (Iron Condor, spreads) store stop_loss/target_price
        # as absolute P&L amounts, not price levels.  Detect via metadata.
        _metadata = signal_data.get('metadata', {}) or {}
        _is_multileg = bool(
            _metadata.get('legs')
            or _metadata.get('structure') in ('IRON_CONDOR', 'BULL_CALL_SPREAD', 'BEAR_PUT_SPREAD', 'STRADDLE', 'STRANGLE')
            or signal_data.get('signal_type', '') in ('IRON_CONDOR', 'BULL_CALL_SPREAD', 'HEDGE_PUT')
        )

        if _is_multileg:
            # For multi-leg: stop_loss = max_loss amount, target_price = profit target amount
            risk_per_share = stop_loss if stop_loss > 0 else 1.0
            reward_per_share = target_price if target_price > 0 else risk_per_share * 2
        elif entry_price > 0 and stop_loss > 0:
            risk_per_share = abs(entry_price - stop_loss)
            reward_per_share = abs(target_price - entry_price) if target_price else risk_per_share * 2
        else:
            risk_per_share = entry_price * 0.03  # Default 3% stop
            reward_per_share = risk_per_share * 2
        
        # 4. Calculate Risk-Reward ratio
        rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 1.0
        
        # Multi-leg credit strategies (Iron Condor, credit spreads) inherently
        # have low R:R (0.3-1.0) but high win probability (65-80%).
        # Apply a lower floor (0.3) to allow these through.
        # MFT Mar 2026: equity floor 1.5→1.2; win-rate override allows 1.0:1
        # if strategy historically achieves >60% win rate.
        # Paper mode: 0.5 floor to test the full funnel (scalpers use 1:1 R:R)
        _is_paper_risk = bool(getattr(settings, "PAPER_TRADING", False)) or \
                         getattr(settings, "MODE", "LIVE") in ("PAPER", "LOCAL")
        _base_min_rr = 0.30 if _is_multileg else (0.5 if _is_paper_risk else 1.2)
        _strategy_wr = self.default_win_rate + (strength - 0.5) * 0.1
        if _strategy_wr > 0.60 and not _is_multileg:
            _base_min_rr = min(_base_min_rr, 1.0)  # High-WR strategies can accept tighter R:R
        if rr_ratio < _base_min_rr:
            return RiskDecision(
                decision="REJECTED",
                reason=f"Risk-Reward {rr_ratio:.2f} below minimum {_base_min_rr:.1f}",
                original_signal_id=signal_id
            )
        
        # 5. Kelly Criterion Position Size
        kelly_position = self._calculate_kelly_position(
            win_rate=self.default_win_rate + (strength - 0.5) * 0.1,
            rr_ratio=rr_ratio,
            risk_per_share=risk_per_share,
            entry_price=entry_price
        )
        
        # 6. VIX Scaling
        vix_multiplier = await self._get_vix_multiplier()
        adjusted_position = kelly_position * vix_multiplier * drawdown_multiplier * _corr_kelly_mult
        
        # 7. Apply position limits
        max_position_value = self.total_capital * self.max_position_size_pct
        if _is_multileg:
            # Multi-leg: size by max_loss per lot, not entry (spot) price
            _risk_per_lot = stop_loss if stop_loss > 0 else 1.0
            max_shares = int(max_position_value / _risk_per_lot) if _risk_per_lot > 0 else 1
        else:
            max_shares = int(max_position_value / entry_price) if entry_price > 0 else 0
        
        final_quantity = min(int(adjusted_position), max_shares)
        final_quantity = max(1, final_quantity)  # At least 1 share/lot
        
        # Position value and risk
        if _is_multileg:
            position_value = final_quantity * (stop_loss if stop_loss > 0 else entry_price)
            risk_amount = final_quantity * risk_per_share
        else:
            position_value = final_quantity * entry_price
            risk_amount = final_quantity * risk_per_share

        # ── Improvement #5 — Signal Strength Boost (macro alignment) ──────
        # Adjust strength based on portfolio/macro conditions so good signals
        # clear the HYBRID ≥ 0.8 auto-execute threshold more easily.
        _boost = 0.0
        _boost_reasons: list = []

        # VIX in sweet spot (calm but not complacent)
        _curr_vix = getattr(self, '_cached_vix', 15.0)
        if 12 <= _curr_vix <= 20:
            _boost += 0.05
            _boost_reasons.append(f"VIX={_curr_vix:.1f} in sweet spot")

        # Low portfolio heat — plenty of capacity
        if current_heat < 0.10:
            _boost += 0.05
            _boost_reasons.append(f"heat={current_heat*100:.0f}%<10%")
        elif current_heat < 0.15:
            _boost += 0.03
            _boost_reasons.append(f"heat={current_heat*100:.0f}%<15%")

        # Sector under-allocated (diversification benefit)
        _sector = _SECTOR_MAP.get(symbol.upper(), "other")
        _sector_val = self.sector_exposure.get(_sector, 0.0)
        _sector_pct = _sector_val / self.total_capital if self.total_capital else 0
        if _sector_pct < 0.15:
            _boost += 0.03
            _boost_reasons.append(f"sector {_sector}={_sector_pct*100:.0f}%<15%")

        # Sentiment aligned with signal direction
        signal_type = signal_data.get("signal_type", "BUY")
        _latest_sent = getattr(self, '_latest_sentiment', 0.0)
        _sentiment_aligned = (
            (signal_type == "BUY" and _latest_sent > 0.3)
            or (signal_type == "SELL" and _latest_sent < -0.3)
        )
        if _sentiment_aligned:
            _boost += 0.05
            _boost_reasons.append(f"sentiment={_latest_sent:.2f} aligned")

        # Cap total boost at +0.20
        _boost = min(_boost, 0.20)
        adjusted_strength = min(1.0, strength + _boost)
        if _boost > 0:
            signal_data["strength"] = adjusted_strength
            logger.info(
                f"Risk boost: {symbol} strength {strength:.2f}→{adjusted_strength:.2f} "
                f"(+{_boost:.2f}: {', '.join(_boost_reasons)})"
            )
        
        logger.info(
            f"Risk Approved: {symbol} | Qty={final_quantity}, "
            f"Value={position_value:.0f}, Risk={risk_amount:.0f}, "
            f"Kelly={kelly_position:.0f}, VIX_mult={vix_multiplier:.2f}, "
            f"DD_mult={drawdown_multiplier:.2f}"
        )
        
        return RiskDecision(
            decision="APPROVED",
            reason="Risk checks passed",
            original_signal_id=signal_id,
            modifications={
                "quantity": final_quantity,
                "position_value": position_value,
                "risk_amount": risk_amount,
                "kelly_size": kelly_position,
                "vix_multiplier": vix_multiplier,
                "drawdown_multiplier": drawdown_multiplier,
                "rr_ratio": rr_ratio,
                "strength_boost": _boost,
                "adjusted_strength": adjusted_strength,
            }
        )
    
    def _calculate_kelly_position(
        self,
        win_rate: float,
        rr_ratio: float,
        risk_per_share: float,
        entry_price: float
    ) -> float:
        """
        Kelly Criterion: f* = (bp - q) / b
        
        Where:
        - b = reward/risk ratio
        - p = win probability
        - q = loss probability (1 - p)
        - f* = fraction of capital to bet
        
        We use fractional Kelly (25%) for safety.
        """
        p = min(0.7, max(0.4, win_rate))  # Clamp win rate
        q = 1 - p
        b = rr_ratio
        
        # Kelly fraction
        kelly_f = (b * p - q) / b
        
        # Apply safety fraction
        kelly_f = max(0, kelly_f * self.kelly_fraction)
        
        # Convert to position size
        capital_to_risk = self.total_capital * kelly_f
        position_size = capital_to_risk / risk_per_share if risk_per_share > 0 else 0
        
        return position_size
    
    def _calculate_portfolio_heat(self) -> float:
        """Calculate current portfolio risk exposure."""
        total_at_risk = sum(
            pos.get('risk_amount', 0) 
            for pos in self.open_positions.values()
        )
        return total_at_risk / self.total_capital if self.total_capital > 0 else 0
    
    def _check_sector_concentration(
        self, new_symbol: str, new_position_value: float = 0
    ) -> Optional[str]:
        """
        Return a violation message if adding ``new_symbol`` would push the
        sector over ``max_sector_concentration`` (default 30 %).
        Returns None when the check passes.

        The check is intentionally synchronous and O(1) — it runs before the
        expensive async correlation check so we can fail-fast.
        """
        sector = _SECTOR_MAP.get(new_symbol.upper(), "other")
        # Skip concentration guard for broad-market indices
        if sector == "index":
            return None

        current_sector_value = self.sector_exposure.get(sector, 0.0)
        total_portfolio_value = sum(
            pos.get("entry_price", 0) * abs(pos.get("quantity", 0))
            for pos in self.open_positions.values()
        )

        if total_portfolio_value <= 0:
            return None  # No existing positions — no concentration risk yet

        projected_pct = (current_sector_value + new_position_value) / total_portfolio_value
        if projected_pct > self.max_sector_concentration:
            return (
                f"Sector concentration: {sector!r} would reach "
                f"{projected_pct * 100:.1f}% > limit {self.max_sector_concentration * 100:.0f}%"
            )
        return None

    async def _calculate_correlation_risk(self, symbol: str) -> float:
        """
        Calculate correlation of new symbol with existing portfolio.
        Enforces diversification.
        """
        if not self.open_positions:
            return 0.0
            
        try:
            # Fetch returns for new symbol
            df_new = await self.nse_service.get_stock_ohlc(symbol, period="3M")
            if df_new.empty: return 0.5 # Neutral fallback
            
            returns_new = df_new['close'].pct_change().dropna()
            
            correlations = []
            for existing_symbol in self.open_positions.keys():
                df_ext = await self.nse_service.get_stock_ohlc(existing_symbol, period="3M")
                if not df_ext.empty:
                    returns_ext = df_ext['close'].pct_change().dropna()
                    # Align indices
                    combined = pd.concat([returns_new, returns_ext], axis=1).dropna()
                    if len(combined) > 20:
                        corr = combined.corr().iloc[0, 1]
                        correlations.append(corr)
            
            return max(correlations) if correlations else 0.0
            
        except Exception as e:
            logger.debug(f"Correlation calculation failed: {e}")
            return 0.5

    async def _calculate_var(self, symbol: str, price: float) -> float:
        """
        Calculate Value-at-Risk (95% confidence) for the position.
        """
        try:
            df = await self.nse_service.get_stock_ohlc(symbol, period="3M")
            if df.empty: return 0.0
            
            returns = df['close'].pct_change().dropna()
            sigma = returns.std()
            
            # Parametric VaR (95% confidence = 1.645 sigma)
            var_pct = 1.645 * sigma
            
            # Position value is max possible size for this agent
            max_pos_value = self.total_capital * self.max_position_size_pct
            
            return max_pos_value * var_pct
            
        except Exception as e:
            logger.debug(f"VaR calculation failed: {e}")
            return 0.0
    
    async def _get_vix_multiplier(self) -> float:
        """
        Scale position size based on VIX.
        
        MFT-tuned Mar 2026: flattened scaling so volatility is opportunity.
        VIX < 12: 1.1x (calm, slightly more)
        VIX 12-20: 1.0x (normal sweet spot)
        VIX 20-30: 0.7x (elevated, moderate reduction)
        VIX > 30: 0.5x (extreme, halve size)
        """
        try:
            vix = await self.nse_service.get_india_vix()
        except Exception as _vix_err:
            logger.warning(f"VIX fetch failed, using neutral 15.0: {_vix_err}")
            vix = 15.0
        
        # Cache for strength boost (Improvement #5)
        self._cached_vix = vix
        
        if vix < 12:
            return 1.1
        elif vix <= 20:
            return 1.0
        elif vix <= 30:
            return 0.7
        else:
            return 0.5
    
    async def on_signals_received(self, payload: Dict[str, Any]):
        """Event Handler for SIGNALS_GENERATED."""
        raw_signals = payload.get('signals', [])
        approved_signals = []
        
        for signal in raw_signals:
            decision = await self.validate_signal(signal)
            
            if decision.decision == "APPROVED":
                approved_signals.append({
                    "signal": signal,
                    "risk_decision": decision.model_dump()
                })
            else:
                logger.info(f"Rejected: {signal.get('symbol')} - {decision.reason}")
        
        if approved_signals:
            logger.info(f"Approved {len(approved_signals)}/{len(raw_signals)} signals")
            self.total_signals_approved = getattr(self, 'total_signals_approved', 0) + len(approved_signals)
            logger.info(
                f"📊 RISK TELEMETRY | approved={len(approved_signals)}/{len(raw_signals)} "
                f"session_total_approved={self.total_signals_approved}"
            )
            await self.publish_event("SIGNALS_APPROVED", {"orders": approved_signals})
        else:
            logger.info("No signals approved this cycle")
    
    async def update_pnl(self, pnl_change: float):
        """Update daily PnL for kill switch tracking."""
        self.daily_pnl += pnl_change

        if self.daily_pnl < self.max_daily_loss:
            logger.error(f"KILL SWITCH TRIGGERED! Daily PnL: {self.daily_pnl:.0f}")

            # ── Alert: send kill switch notification ──
            try:
                from src.services.alerting import alerting_service
                await alerting_service.send_kill_switch_alert(
                    reason=f"Daily loss {self.daily_pnl:.0f} exceeds limit {self.max_daily_loss:.0f}",
                    portfolio_value=self.total_capital + self.daily_pnl,
                    daily_pnl=self.daily_pnl,
                )
            except Exception as _alert_err:
                logger.warning(f"Kill switch alert failed: {_alert_err}")

            # Wire auto-closeout: automatically close all open positions
            try:
                result = await trigger_auto_closeout_if_needed(
                    daily_pnl=self.daily_pnl,
                    total_capital=self.total_capital,
                )
                if result.get("triggered") and result.get("status") == "EXECUTED":
                    logger.critical(
                        f"Auto-closeout COMPLETE: {result.get('positions_closed', 0)} positions closed, "
                        f"total loss ₹{result.get('total_loss_at_closeout', 0):.0f}"
                    )
                elif result.get("status") == "ALREADY_CLOSING":
                    logger.warning("Auto-closeout already in progress — skipping re-trigger")
            except Exception as _e:
                logger.error(f"Auto-closeout handler error (positions may still be open): {_e}")
    
    async def add_position(self, symbol: str, position_data: Dict):
        """Track an open position."""
        self.open_positions[symbol] = position_data
    
    async def remove_position(self, symbol: str):
        """Remove a closed position."""
        self.open_positions.pop(symbol, None)
    
    async def reset_daily(self):
        """Reset daily counters (call at market open)."""
        self.daily_pnl = 0.0
        self._current_drawdown_pct = 0.0
        # Reset Kelly to regime baseline (sentiment adjustments restart fresh)
        self.kelly_fraction = self._base_kelly_fraction
        logger.info("Daily risk counters reset")

    # ------------------------------------------------------------------
    # Portfolio sync — subscribes to PORTFOLIO_UPDATED from PortfolioAgent
    # ------------------------------------------------------------------

    async def on_portfolio_updated(self, payload: Dict[str, Any]):
        """
        Sync open_positions and daily_pnl from PortfolioAgent.
        This makes kill switch and heat checks real (not cosmetic).
        """
        try:
            positions_list = payload.get("positions", [])

            # Rebuild open_positions dict keyed by symbol
            new_positions: Dict[str, Dict] = {}
            for pos in positions_list:
                sym = pos.get("symbol", "")
                if not sym:
                    continue
                entry_price = float(pos.get("buy_avg") or pos.get("entry_price", 0))
                ltp = float(pos.get("ltp", entry_price))
                net_qty = int(pos.get("net_qty") or pos.get("quantity", 0))
                stop_loss = float(pos.get("stop_loss") or entry_price * 0.97)
                risk_per_share = abs(entry_price - stop_loss)
                risk_amount = risk_per_share * abs(net_qty)

                new_positions[sym] = {
                    "symbol": sym,
                    "entry_price": entry_price,
                    "ltp": ltp,
                    "quantity": net_qty,
                    "stop_loss": stop_loss,
                    "risk_amount": risk_amount,
                    "unrealized_pnl": float(pos.get("unrealized_pnl", 0)),
                }

            self.open_positions = new_positions

            # Rebuild sector exposure map for concentration checks
            new_sector_exposure: Dict[str, float] = {}
            for sym, pos in new_positions.items():
                sec = _SECTOR_MAP.get(sym.upper(), "other")
                pos_value = pos.get("entry_price", 0) * abs(pos.get("quantity", 0))
                new_sector_exposure[sec] = new_sector_exposure.get(sec, 0.0) + pos_value
            self.sector_exposure = new_sector_exposure

            # Update daily PnL from realized gains (sets absolute value)
            realized = float(payload.get("total_realized_pnl", 0))
            if realized != 0:
                self.daily_pnl = realized  # Realized PnL IS daily PnL if reset at SOD

            # Update drawdown tracker (P1-1)
            self._update_drawdown()

            logger.debug(
                f"Risk synced: {len(self.open_positions)} positions, "
                f"daily_pnl={self.daily_pnl:.0f}, "
                f"heat={self._calculate_portfolio_heat()*100:.1f}%, "
                f"drawdown={self._current_drawdown_pct*100:.1f}%"
            )

        except Exception as e:
            logger.error(f"Risk sync from portfolio failed: {e}")

    async def on_sentiment_updated(self, data: Dict[str, Any]):
        """
        Adjust Kelly fraction and risk tolerance based on market sentiment.
        Called when SentimentAgent publishes SENTIMENT_UPDATED.
        """
        score: float = float(data.get("score", 0.0))  # -1 bearish → +1 bullish
        # Cache for Improvement #5 — strength boost
        self._latest_sentiment = score
        # Bearish sentiment → tighten Kelly fraction; bullish → relax slightly
        if score < -0.3:
            self.kelly_fraction = max(0.10, self.kelly_fraction - 0.02)
            logger.info(f"RiskAgent: bearish sentiment ({score:.2f}) — kelly_fraction={self.kelly_fraction:.2f}")
        elif score > 0.3:
            self.kelly_fraction = min(0.30, self.kelly_fraction + 0.01)
            logger.info(f"RiskAgent: bullish sentiment ({score:.2f}) — kelly_fraction={self.kelly_fraction:.2f}")
        else:
            # Neutral: nudge back to default 0.25
            self.kelly_fraction = self.kelly_fraction * 0.95 + 0.25 * 0.05

    async def on_regime_updated(self, data: Dict[str, Any]):
        """
        Adjust risk parameters when market regime changes (P1-2).
        Called when RegimeAgent publishes REGIME_UPDATED.
        """
        new_regime = data.get("regime", self._current_regime)
        if new_regime == self._current_regime:
            return

        old_regime = self._current_regime
        self._current_regime = new_regime
        self._apply_regime_profile(new_regime)
        logger.info(
            f"RiskAgent: regime {old_regime}→{new_regime} | "
            f"pos_size={self.max_position_size_pct*100:.0f}% "
            f"heat={self.max_portfolio_heat_pct*100:.0f}% "
            f"kelly={self.kelly_fraction:.2f} "
            f"max_pos={self.max_concurrent_positions}"
        )

    def _apply_regime_profile(self, regime: str):
        """Apply regime-specific risk parameters."""
        profile = self._regime_risk_profiles.get(regime, self._regime_risk_profiles["SIDEWAYS"])
        self.max_position_size_pct = profile["max_position_size_pct"]
        self.max_portfolio_heat_pct = profile["max_portfolio_heat_pct"]
        self._base_kelly_fraction = profile["kelly_fraction"]
        self.kelly_fraction = profile["kelly_fraction"]
        self.max_concurrent_positions = profile["max_concurrent_positions"]

    # ------------------------------------------------------------------
    # Drawdown-Responsive Sizing (P1-1)
    # ------------------------------------------------------------------

    def _drawdown_multiplier(self) -> float:
        """
        Scale position sizes based on current drawdown from peak equity.

        Drawdown tiers:
          0-5%   : 1.0x  (normal — no reduction)
          5-10%  : 0.75x (moderate drawdown — 25% size cut)
          10-15% : 0.50x (significant — halve positions)
          15-20% : 0.25x (severe — quarter positions)
          >20%   : 0.10x (near kill-switch — minimal new positions)

        This is the #1 Sharpe improvement lever — it prevents drawdowns
        from compounding by cutting size as they deepen, and gradually
        restores size as equity recovers.
        """
        dd = self._current_drawdown_pct
        if dd < 0.05:
            return 1.0
        elif dd < 0.10:
            return 0.75
        elif dd < 0.15:
            return 0.50
        elif dd < 0.20:
            return 0.25
        else:
            return 0.10

    def _update_drawdown(self):
        """Recalculate current drawdown from peak equity."""
        current_equity = self.total_capital + self.daily_pnl
        if current_equity > self._peak_capital:
            self._peak_capital = current_equity
        if self._peak_capital > 0:
            self._current_drawdown_pct = max(
                0, (self._peak_capital - current_equity) / self._peak_capital
            )
        else:
            self._current_drawdown_pct = 0.0

    async def update_win_rate_from_trades(self, closed_trades: list):
        """
        Recalculate Kelly win rate from recent closed trade history.
        Pass a list of dicts with 'pnl' key (positive = win).
        """
        if not closed_trades:
            return
        wins = sum(1 for t in closed_trades if float(t.get("pnl", 0)) > 0)
        self.default_win_rate = max(0.3, min(0.75, wins / len(closed_trades)))
        logger.info(
            f"Kelly win rate updated: {self.default_win_rate:.2f} "
            f"({wins}/{len(closed_trades)} trades)"
        )
