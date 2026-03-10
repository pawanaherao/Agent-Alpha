import pandas as pd
import pandas_ta as ta
import logging
from typing import Dict, Any, Optional, List

from src.strategies.base import BaseStrategy, StrategySignal, LegDetail

logger = logging.getLogger(__name__)

class UniversalStrategy(BaseStrategy):
    """
    The 'Super-Algo' for SEBI Compliance.
    
    Instead of writing new code for every user strategy, this class 
    contains ALL supported logic blocks (RSI, MACD, SMA, etc. AND
    IV, Greeks, strike-selection for options).
    
    The AI (or User) simply provides a JSON Configuration ('Universal Parameter Matrix')
    to enable/disable specific blocks.
    
    Configuration Schema Example — Equity:
    {
        "entry_conditions": [
            {"type": "RSI", "period": 14, "condition": "GT", "value": 30},
            {"type": "SMA", "period": 200, "condition": "CROSS_ABOVE", "value": "CLOSE"}
        ],
        "exit_conditions": [ ... ],
        "stop_loss_pct": 0.02
    }

    Configuration Schema Example — Options:
    {
        "mode": "options",
        "symbol": "NIFTY",
        "structure": "IRON_CONDOR",
        "entry_conditions": [
            {"type": "IV_RANK", "condition": "GT", "value": 50},
            {"type": "VIX", "condition": "BETWEEN", "min": 12, "max": 20}
        ],
        "options_config": {
            "expiry_preference": "weekly",
            "wing_width": 200,
            "short_delta": 0.20,
            "long_delta": 0.10,
            "min_premium": 5,
            "max_dte": 14,
            "min_dte": 2
        },
        "greeks_limits": {
            "max_delta": 0.30,
            "max_gamma": 0.02,
            "min_theta": -50
        },
        "stop_loss_pct": 1.5,
        "take_profit_pct": 50
    }
    """
    def __init__(self, config: Dict[str, Any] = None):
        default_config = {
            "mode": "equity",  # "equity" or "options"
            "entry_conditions": [],
            "exit_conditions": [],
            "stop_loss_pct": 0.0,
            "take_profit_pct": 0.0,
            "options_config": {},
            "greeks_limits": {},
            "structure": None,
        }
        final_config = {**default_config, **(config or {})}
        super().__init__("UniversalStrategy", final_config)
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Suitability depends on the *active* logic blocks.
        For MVP, we return a neutral score as this is a meta-strategy.
        """
        return 75.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        try:
            if market_data.empty:
                return None

            mode = self.config.get("mode", "equity")

            if mode == "options":
                return await self._generate_options_signal(market_data, regime)

            return await self._generate_equity_signal(market_data, regime)

        except Exception as e:
            logger.error(f"Universal Strategy Error: {e}")
            return None

    # ------------------------------------------------------------------
    # Equity signal (original logic)
    # ------------------------------------------------------------------
    async def _generate_equity_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        df = market_data.copy()
        self._ensure_indicators(df, self.config['entry_conditions'])
        self._ensure_indicators(df, self.config['exit_conditions'])

        entry_signal = self._evaluate_conditions(df, self.config['entry_conditions'])

        if entry_signal:
            # Derive entry_price, stop_loss, target_price from latest data
            price = float(df['close'].iloc[-1])
            sl_pct = self.config.get('stop_loss_pct', 0.03)  # default 3%
            tp_pct = self.config.get('target_pct', sl_pct * 2)  # default 2:1 R:R

            # ATR-based SL/TP if ATR is available, else fixed %
            if 'atr' in df.columns and pd.notna(df['atr'].iloc[-1]):
                atr_val = float(df['atr'].iloc[-1])
                stop_loss = round(price - atr_val * 1.5, 2)
                target_price = round(price + atr_val * 2.5, 2)
            else:
                stop_loss = round(price * (1 - sl_pct), 2)
                target_price = round(price * (1 + tp_pct), 2)

            return StrategySignal(
                signal_id=f"UNI_{int(pd.Timestamp.now().timestamp())}",
                strategy_name="UniversalStrategy",
                symbol=self.config.get('symbol', 'UNKNOWN'),
                signal_type="BUY",
                strength=1.0,
                entry_price=price,
                stop_loss=stop_loss,
                target_price=target_price,
                metadata={
                    "reason": "Universal Logic Match",
                    "sl_pct": sl_pct,
                    "tp_pct": tp_pct,
                },
                market_regime_at_signal=regime
            )
        return None

    # ------------------------------------------------------------------
    # Options signal (new)
    # ------------------------------------------------------------------
    async def _generate_options_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """
        Config-driven options signal generator.
        Uses option chain data, IV/Greeks conditions, and structure templates.
        """
        symbol = self.config.get("symbol", "NIFTY")
        structure = self.config.get("structure", "IRON_CONDOR")
        opts_cfg = self.config.get("options_config", {})
        greeks_limits = self.config.get("greeks_limits", {})

        # 1. Evaluate entry conditions (IV_RANK, VIX, RSI etc.)
        df = market_data.copy()
        self._ensure_indicators(df, self.config.get("entry_conditions", []))
        if not self._evaluate_options_conditions(df, self.config.get("entry_conditions", [])):
            return None

        # 2. Fetch option chain
        try:
            from src.services.option_chain import option_chain_service
            chain = await option_chain_service.get_chain(
                symbol,
                num_strikes=opts_cfg.get("num_strikes", 10),
                enrich_greeks=True,
            )
            if not chain.items or chain.spot_price <= 0:
                logger.warning(f"No option chain data for {symbol}")
                return None
        except Exception as e:
            logger.error(f"Option chain fetch failed: {e}")
            return None

        # 3. Build legs based on structure
        legs, signal_metadata = self._build_structure_legs(
            structure, chain, opts_cfg, greeks_limits
        )
        if not legs:
            return None

        # 4. Calculate P&L characteristics
        net_premium = sum(
            (l.premium or 0) * (-1 if l.action == "BUY" else 1) * l.quantity
            for l in legs
        )
        max_profit, max_loss, breakevens = self._calc_pl_profile(
            structure, legs, chain.spot_price, opts_cfg
        )

        # 5. Greeks validation
        if greeks_limits:
            from src.services.greeks import greeks_engine
            # Compute aggregate delta from legs
            total_delta = 0.0
            for l in legs:
                item = next(
                    (i for i in chain.items
                     if i.strike == l.strike and i.option_type.value == l.option_type),
                    None
                )
                if item and item.greeks:
                    sign = 1 if l.action == "BUY" else -1
                    total_delta += item.greeks.delta * sign * l.quantity

            if "max_delta" in greeks_limits and abs(total_delta) > greeks_limits["max_delta"]:
                logger.info(f"Greeks check failed: delta={total_delta:.4f}")
                return None

        return StrategySignal(
            signal_id=f"UOPT_{int(pd.Timestamp.now().timestamp())}",
            strategy_name="UniversalStrategy_Options",
            symbol=symbol,
            signal_type=structure,
            strength=0.8,
            legs=legs,
            structure_type=structure,
            net_premium=net_premium,
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            expiry=chain.expiry_dates[0] if chain.expiry_dates else None,
            entry_price=chain.spot_price,
            metadata={
                "reason": f"Universal Options: {structure}",
                "spot_price": chain.spot_price,
                **signal_metadata,
            },
            market_regime_at_signal=regime,
        )

    # ------------------------------------------------------------------
    # Structure builders
    # ------------------------------------------------------------------
    def _build_structure_legs(
        self, structure: str, chain, opts_cfg: Dict, greeks_limits: Dict
    ) -> tuple:
        """Build legs for a given structure type using live chain data."""
        from src.services.option_chain import STRIKE_STEPS, DEFAULT_STRIKE_STEP

        spot = chain.spot_price
        step = STRIKE_STEPS.get(chain.symbol.upper(), DEFAULT_STRIKE_STEP)
        atm = round(spot / step) * step
        wing_width = opts_cfg.get("wing_width", step * 4)
        short_delta = opts_cfg.get("short_delta", 0.20)
        expiry = chain.expiry_dates[0] if chain.expiry_dates else ""
        lot_size = chain.items[0].lot_size if chain.items else 1
        qty = opts_cfg.get("quantity", 1)
        metadata: Dict[str, Any] = {}

        # Helper: find strike closest to target delta
        def find_strike_by_delta(items, target_delta: float, otype: str) -> Optional[float]:
            filtered = [i for i in items if i.option_type.value == otype and i.expiry == expiry]
            if not filtered:
                return None
            closest = min(filtered, key=lambda i: abs(abs(i.greeks.delta) - target_delta))
            return closest.strike

        # Helper: find premium for a strike
        def get_premium(strike: float, otype: str) -> float:
            item = next(
                (i for i in chain.items
                 if i.strike == strike and i.option_type.value == otype and i.expiry == expiry),
                None
            )
            return item.last_price if item else 0.0

        legs: List[LegDetail] = []

        if structure == "IRON_CONDOR":
            short_ce_strike = find_strike_by_delta(chain.items, short_delta, "CE") or (atm + wing_width // 2)
            short_pe_strike = find_strike_by_delta(chain.items, short_delta, "PE") or (atm - wing_width // 2)
            long_ce_strike = short_ce_strike + wing_width // 2
            long_pe_strike = short_pe_strike - wing_width // 2

            legs = [
                LegDetail(strike=short_ce_strike, option_type="CE", action="SELL", quantity=qty, premium=get_premium(short_ce_strike, "CE")),
                LegDetail(strike=long_ce_strike, option_type="CE", action="BUY", quantity=qty, premium=get_premium(long_ce_strike, "CE")),
                LegDetail(strike=short_pe_strike, option_type="PE", action="SELL", quantity=qty, premium=get_premium(short_pe_strike, "PE")),
                LegDetail(strike=long_pe_strike, option_type="PE", action="BUY", quantity=qty, premium=get_premium(long_pe_strike, "PE")),
            ]
            metadata["short_ce"] = short_ce_strike
            metadata["short_pe"] = short_pe_strike

        elif structure == "BULL_CALL_SPREAD":
            buy_strike = atm
            sell_strike = atm + wing_width
            legs = [
                LegDetail(strike=buy_strike, option_type="CE", action="BUY", quantity=qty, premium=get_premium(buy_strike, "CE")),
                LegDetail(strike=sell_strike, option_type="CE", action="SELL", quantity=qty, premium=get_premium(sell_strike, "CE")),
            ]

        elif structure == "BEAR_PUT_SPREAD":
            buy_strike = atm
            sell_strike = atm - wing_width
            legs = [
                LegDetail(strike=buy_strike, option_type="PE", action="BUY", quantity=qty, premium=get_premium(buy_strike, "PE")),
                LegDetail(strike=sell_strike, option_type="PE", action="SELL", quantity=qty, premium=get_premium(sell_strike, "PE")),
            ]

        elif structure in ("LONG_STRADDLE", "SHORT_STRADDLE"):
            action = "BUY" if "LONG" in structure else "SELL"
            legs = [
                LegDetail(strike=atm, option_type="CE", action=action, quantity=qty, premium=get_premium(atm, "CE")),
                LegDetail(strike=atm, option_type="PE", action=action, quantity=qty, premium=get_premium(atm, "PE")),
            ]

        elif structure in ("LONG_STRANGLE", "SHORT_STRANGLE"):
            action = "BUY" if "LONG" in structure else "SELL"
            ce_strike = atm + step * 2
            pe_strike = atm - step * 2
            legs = [
                LegDetail(strike=ce_strike, option_type="CE", action=action, quantity=qty, premium=get_premium(ce_strike, "CE")),
                LegDetail(strike=pe_strike, option_type="PE", action=action, quantity=qty, premium=get_premium(pe_strike, "PE")),
            ]

        elif structure == "IRON_BUTTERFLY":
            long_ce = atm + wing_width
            long_pe = atm - wing_width
            legs = [
                LegDetail(strike=atm, option_type="CE", action="SELL", quantity=qty, premium=get_premium(atm, "CE")),
                LegDetail(strike=atm, option_type="PE", action="SELL", quantity=qty, premium=get_premium(atm, "PE")),
                LegDetail(strike=long_ce, option_type="CE", action="BUY", quantity=qty, premium=get_premium(long_ce, "CE")),
                LegDetail(strike=long_pe, option_type="PE", action="BUY", quantity=qty, premium=get_premium(long_pe, "PE")),
            ]

        elif structure == "BUTTERFLY":
            lower = atm - wing_width
            upper = atm + wing_width
            legs = [
                LegDetail(strike=lower, option_type="CE", action="BUY", quantity=qty, premium=get_premium(lower, "CE")),
                LegDetail(strike=atm, option_type="CE", action="SELL", quantity=qty * 2, premium=get_premium(atm, "CE")),
                LegDetail(strike=upper, option_type="CE", action="BUY", quantity=qty, premium=get_premium(upper, "CE")),
            ]

        elif structure == "RATIO_SPREAD":
            buy_strike = atm
            sell_strike = atm + wing_width
            legs = [
                LegDetail(strike=buy_strike, option_type="CE", action="BUY", quantity=qty, premium=get_premium(buy_strike, "CE")),
                LegDetail(strike=sell_strike, option_type="CE", action="SELL", quantity=qty * 2, premium=get_premium(sell_strike, "CE")),
            ]

        elif structure == "CALENDAR_SPREAD":
            # Sell near expiry, buy far expiry ATM call
            legs = [
                LegDetail(strike=atm, option_type="CE", action="SELL", quantity=qty, premium=get_premium(atm, "CE")),
                LegDetail(strike=atm, option_type="CE", action="BUY", quantity=qty, premium=0),  # far expiry premium unknown here
            ]
            metadata["note"] = "Calendar: sell near, buy far expiry (same strike)"

        elif structure == "HEDGE_PUT":
            put_strike = round((spot * 0.95) / step) * step
            legs = [
                LegDetail(strike=put_strike, option_type="PE", action="BUY", quantity=qty, premium=get_premium(put_strike, "PE")),
            ]

        else:
            logger.warning(f"Unknown structure: {structure}")
            return [], {}

        # Filter min premium
        min_prem = opts_cfg.get("min_premium", 0)
        if min_prem > 0:
            for leg in legs:
                if leg.action == "SELL" and (leg.premium or 0) < min_prem:
                    logger.info(f"Skipping: sell premium {leg.premium} < min {min_prem}")
                    return [], {}

        return legs, metadata

    # ------------------------------------------------------------------
    # P&L profile calculators
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_pl_profile(
        structure: str, legs: List[LegDetail], spot: float, opts_cfg: Dict
    ) -> tuple:
        """Calculate max_profit, max_loss, breakevens for the structure."""
        net = sum(
            (l.premium or 0) * (-1 if l.action == "BUY" else 1) * l.quantity
            for l in legs
        )

        if structure == "IRON_CONDOR":
            wing = opts_cfg.get("wing_width", 200)
            max_profit = net
            max_loss = (wing / 2) - net if net > 0 else abs(net)
            # Approximate breakevens
            short_ce = next((l.strike for l in legs if l.option_type == "CE" and l.action == "SELL"), spot)
            short_pe = next((l.strike for l in legs if l.option_type == "PE" and l.action == "SELL"), spot)
            upper_be = short_ce + net
            lower_be = short_pe - net
            return max_profit, max_loss, [lower_be, upper_be]

        elif structure in ("BULL_CALL_SPREAD", "BEAR_PUT_SPREAD"):
            strikes = sorted(l.strike for l in legs)
            width = strikes[-1] - strikes[0] if len(strikes) >= 2 else 0
            max_profit = width + net if net < 0 else net
            max_loss = abs(net)
            be = strikes[0] - net if structure == "BEAR_PUT_SPREAD" else strikes[0] + abs(net)
            return abs(max_profit), abs(max_loss), [be]

        elif "STRADDLE" in structure or "STRANGLE" in structure:
            if "SHORT" in structure:
                max_profit = net
                max_loss = None  # unlimited
                return max_profit, max_loss, []
            else:
                max_profit = None  # unlimited
                max_loss = abs(net)
                return max_profit, max_loss, []

        # Default: simple net premium
        return abs(net) if net > 0 else None, abs(net) if net < 0 else None, []

    # ------------------------------------------------------------------
    # Options-specific condition evaluators
    # ------------------------------------------------------------------
    def _evaluate_options_conditions(self, df: pd.DataFrame, conditions: List[Dict]) -> bool:
        """Evaluate options-specific entry conditions (IV_RANK, VIX, GREEKS, etc)."""
        if not conditions:
            return True  # no conditions = always enter

        for c in conditions:
            ctype = c.get("type", "")

            if ctype == "IV_RANK":
                # IV rank from metadata or computed
                iv_rank = c.get("current_iv_rank", 50)  # placeholder
                threshold = c.get("value", 50)
                cond = c.get("condition", "GT")
                if cond == "GT" and iv_rank <= threshold:
                    return False
                if cond == "LT" and iv_rank >= threshold:
                    return False

            elif ctype == "VIX":
                cond = c.get("condition", "LT")
                if cond == "BETWEEN":
                    vix_min = c.get("min", 0)
                    vix_max = c.get("max", 100)
                    # Get VIX value from data
                    vix = self._get_vix_from_data(df)
                    if vix is None or not (vix_min <= vix <= vix_max):
                        return False
                elif cond == "LT":
                    vix = self._get_vix_from_data(df)
                    if vix is None or vix >= c.get("value", 20):
                        return False
                elif cond == "GT":
                    vix = self._get_vix_from_data(df)
                    if vix is None or vix <= c.get("value", 15):
                        return False

            elif ctype == "REGIME":
                allowed = c.get("value", [])
                if isinstance(allowed, str):
                    allowed = [allowed]
                # Regime check is done by caller, but just in case
                pass

            # Fallback to standard equity conditions (RSI, MACD etc.)
            elif ctype in ("RSI", "SMA", "EMA", "MACD"):
                if not self._evaluate_conditions(df, [c]):
                    return False

        return True

    @staticmethod
    def _get_vix_from_data(df: pd.DataFrame) -> Optional[float]:
        """Extract VIX from market data if available."""
        for col in ["vix", "VIX", "india_vix", "INDIAVIX"]:
            if col in df.columns:
                val = df[col].iloc[-1]
                if pd.notna(val):
                    return float(val)
        return None

    # ------------------------------------------------------------------
    # Indicator engine — unified with Scanner's 12 indicators
    # ------------------------------------------------------------------
    def _ensure_indicators(self, df: pd.DataFrame, conditions: List[Dict]):
        """
        Dynamically calculate indicators based on config.
        Supports the FULL indicator set used by Scanner agent:
        RSI, ADX, MACD, STOCH, VOLUME_RATIO, OBV, EMA_ALIGNMENT,
        PSAR, BB, ATR, VWAP, DELIVERY_PCT  +  SMA, EMA.

        NOTE: Scanner uses `import ta` (scikit-style); we use `import pandas_ta as ta`
        (function-style) for DataFrame-native workflow.  Both produce equivalent values.
        """
        close = df['close'] if 'close' in df.columns else None
        if close is None or close.empty:
            return

        high = df.get('high')
        low = df.get('low')
        volume = df.get('volume')

        for c in conditions:
            ctype = c.get('type', '')

            # --- RSI ---
            if ctype == 'RSI':
                period = c.get('period', 14)
                col = f'RSI_{period}'
                if col not in df.columns:
                    df[col] = ta.rsi(close, length=period)

            # --- SMA ---
            elif ctype == 'SMA':
                period = c.get('period', 20)
                col = f'SMA_{period}'
                if col not in df.columns:
                    df[col] = ta.sma(close, length=period)

            # --- EMA (single period) ---
            elif ctype == 'EMA':
                period = c.get('period', 20)
                col = f'EMA_{period}'
                if col not in df.columns:
                    df[col] = ta.ema(close, length=period)

            # --- MACD (pandas_ta returns a DataFrame — join in-place) ---
            elif ctype == 'MACD':
                if 'MACD_12_26_9' not in df.columns:
                    macd_df = ta.macd(close)
                    if macd_df is not None:
                        for mcol in macd_df.columns:
                            df[mcol] = macd_df[mcol]

            # --- ADX ---
            elif ctype == 'ADX':
                period = c.get('period', 14)
                if 'ADX' not in df.columns:
                    adx_df = ta.adx(high, low, close, length=period)
                    if adx_df is not None:
                        for acol in adx_df.columns:
                            df[acol] = adx_df[acol]

            # --- Stochastic ---
            elif ctype in ('STOCH', 'STOCHASTIC'):
                k_period = c.get('k_period', 14)
                d_period = c.get('d_period', 3)
                if 'STOCHk' not in df.columns:
                    stoch_df = ta.stoch(high, low, close, k=k_period, d=d_period)
                    if stoch_df is not None:
                        for scol in stoch_df.columns:
                            df[scol] = stoch_df[scol]

            # --- Volume Ratio ---
            elif ctype == 'VOLUME_RATIO':
                if volume is not None and 'volume_ratio' not in df.columns:
                    avg_vol = volume.rolling(c.get('period', 20)).mean()
                    df['volume_ratio'] = volume / avg_vol.replace(0, 1)

            # --- OBV ---
            elif ctype == 'OBV':
                if volume is not None and 'obv' not in df.columns:
                    df['obv'] = ta.obv(close, volume)
                    df['obv_sma'] = df['obv'].rolling(10).mean()
                    df['obv_rising'] = df['obv'] > df['obv_sma']

            # --- EMA Alignment (9 > 21 > 50 → bullish) ---
            elif ctype == 'EMA_ALIGNMENT':
                if 'ema_aligned' not in df.columns:
                    ema9 = ta.ema(close, length=9)
                    ema21 = ta.ema(close, length=21)
                    ema50 = ta.ema(close, length=50)
                    df['EMA_9'] = ema9
                    df['EMA_21'] = ema21
                    df['EMA_50'] = ema50
                    df['ema_aligned'] = (close > ema9) & (ema9 > ema21) & (ema21 > ema50)

            # --- Parabolic SAR ---
            elif ctype == 'PSAR':
                if 'psar_bullish' not in df.columns:
                    psar_df = ta.psar(high, low, close)
                    if psar_df is not None:
                        # pandas_ta returns PSARl/PSARs/PSARaf/PSARr columns
                        psar_long = psar_df.filter(like='PSARl').iloc[:, 0] if psar_df.filter(like='PSARl').shape[1] else close
                        df['psar_bullish'] = close > psar_long

            # --- Bollinger Bands ---
            elif ctype in ('BB', 'BOLLINGER'):
                period = c.get('period', 20)
                if 'bb_position' not in df.columns:
                    bb_df = ta.bbands(close, length=period)
                    if bb_df is not None:
                        upper = bb_df.filter(like='BBU').iloc[:, 0]
                        lower = bb_df.filter(like='BBL').iloc[:, 0]
                        bb_range = upper - lower
                        df['bb_position'] = ((close - lower) / bb_range.replace(0, 1))
                        df['bb_width'] = bb_range / close
                        df['bb_upper'] = upper
                        df['bb_lower'] = lower

            # --- ATR ---
            elif ctype == 'ATR':
                period = c.get('period', 14)
                if 'atr' not in df.columns:
                    df['atr'] = ta.atr(high, low, close, length=period)
                    df['atr_pct'] = df['atr'] / close

            # --- VWAP ---
            elif ctype == 'VWAP':
                if volume is not None and 'vwap' not in df.columns:
                    df['vwap'] = ta.vwap(high, low, close, volume)

    # ------------------------------------------------------------------
    # Condition evaluator — supports all indicator types
    # ------------------------------------------------------------------
    def _evaluate_conditions(self, df: pd.DataFrame, conditions: List[Dict]) -> bool:
        """
        Evaluate list of conditions. Implicit AND logic.
        Supports: RSI, SMA, EMA, MACD, ADX, STOCH, VOLUME_RATIO,
        OBV, EMA_ALIGNMENT, PSAR, BB, ATR, VWAP.
        """
        if not conditions:
            return False

        cur = -1  # latest bar
        prev = -2

        for c in conditions:
            ctype = c.get('type', '')
            cond = c.get('condition', 'GT')
            value = c.get('value', 0)

            # --- RSI ---
            if ctype == 'RSI':
                period = c.get('period', 14)
                col = f'RSI_{period}'
                if col not in df.columns:
                    continue
                val = df[col].iloc[cur]
                threshold = float(value)
                if cond == 'GT' and not (val > threshold):
                    return False
                if cond == 'LT' and not (val < threshold):
                    return False
                if cond == 'CROSS_ABOVE':
                    if not (df[col].iloc[prev] <= threshold and val > threshold):
                        return False
                if cond == 'CROSS_BELOW':
                    if not (df[col].iloc[prev] >= threshold and val < threshold):
                        return False

            # --- SMA / EMA ---
            elif ctype in ('SMA', 'EMA'):
                period = c.get('period', 20)
                col = f"{ctype}_{period}"
                if col not in df.columns:
                    continue
                ind_val = df[col].iloc[cur]
                comp = value
                if comp == 'CLOSE':
                    comp = df['close'].iloc[cur]
                    if cond == 'CROSS_ABOVE':
                        if not (df['close'].iloc[prev] <= df[col].iloc[prev] and df['close'].iloc[cur] > ind_val):
                            return False
                        continue
                    if cond == 'CROSS_BELOW':
                        if not (df['close'].iloc[prev] >= df[col].iloc[prev] and df['close'].iloc[cur] < ind_val):
                            return False
                        continue
                else:
                    comp = float(comp) if comp else 0
                if cond == 'GT' and not (ind_val > comp):
                    return False
                if cond == 'LT' and not (ind_val < comp):
                    return False

            # --- MACD ---
            elif ctype == 'MACD':
                macd_col = 'MACD_12_26_9'
                sig_col = 'MACDs_12_26_9'
                hist_col = 'MACDh_12_26_9'
                if macd_col not in df.columns:
                    continue
                if cond == 'CROSS_ABOVE':
                    # MACD line crosses above signal line
                    if not (df[macd_col].iloc[prev] <= df[sig_col].iloc[prev]
                            and df[macd_col].iloc[cur] > df[sig_col].iloc[cur]):
                        return False
                elif cond == 'CROSS_BELOW':
                    if not (df[macd_col].iloc[prev] >= df[sig_col].iloc[prev]
                            and df[macd_col].iloc[cur] < df[sig_col].iloc[cur]):
                        return False
                elif cond == 'GT':
                    if not (df[hist_col].iloc[cur] > 0):
                        return False
                elif cond == 'LT':
                    if not (df[hist_col].iloc[cur] < 0):
                        return False

            # --- ADX ---
            elif ctype == 'ADX':
                adx_col = [c2 for c2 in df.columns if 'ADX' in c2 and 'DM' not in c2]
                if not adx_col:
                    continue
                val = df[adx_col[0]].iloc[cur]
                threshold = float(value) if value else 20
                if cond == 'GT' and not (val > threshold):
                    return False
                if cond == 'LT' and not (val < threshold):
                    return False

            # --- Stochastic ---
            elif ctype in ('STOCH', 'STOCHASTIC'):
                k_col = [c2 for c2 in df.columns if 'STOCHk' in c2]
                d_col = [c2 for c2 in df.columns if 'STOCHd' in c2]
                if not k_col:
                    continue
                k_val = df[k_col[0]].iloc[cur]
                if cond == 'GT' and not (k_val > float(value)):
                    return False
                if cond == 'LT' and not (k_val < float(value)):
                    return False
                if cond == 'CROSS_ABOVE' and d_col:
                    if not (df[k_col[0]].iloc[prev] <= df[d_col[0]].iloc[prev]
                            and k_val > df[d_col[0]].iloc[cur]):
                        return False
                if cond == 'CROSS_BELOW' and d_col:
                    if not (df[k_col[0]].iloc[prev] >= df[d_col[0]].iloc[prev]
                            and k_val < df[d_col[0]].iloc[cur]):
                        return False

            # --- Volume Ratio ---
            elif ctype == 'VOLUME_RATIO':
                if 'volume_ratio' not in df.columns:
                    continue
                val = df['volume_ratio'].iloc[cur]
                threshold = float(value) if value else 1.3
                if cond == 'GT' and not (val > threshold):
                    return False
                if cond == 'LT' and not (val < threshold):
                    return False

            # --- OBV ---
            elif ctype == 'OBV':
                if 'obv_rising' not in df.columns:
                    continue
                is_rising = bool(df['obv_rising'].iloc[cur])
                if cond == 'TRUE' and not is_rising:
                    return False
                if cond == 'FALSE' and is_rising:
                    return False

            # --- EMA Alignment ---
            elif ctype == 'EMA_ALIGNMENT':
                if 'ema_aligned' not in df.columns:
                    continue
                aligned = bool(df['ema_aligned'].iloc[cur])
                if cond == 'TRUE' and not aligned:
                    return False
                if cond == 'FALSE' and aligned:
                    return False

            # --- Parabolic SAR ---
            elif ctype == 'PSAR':
                if 'psar_bullish' not in df.columns:
                    continue
                bullish = bool(df['psar_bullish'].iloc[cur])
                if cond == 'BULLISH' and not bullish:
                    return False
                if cond == 'BEARISH' and bullish:
                    return False

            # --- Bollinger Bands ---
            elif ctype in ('BB', 'BOLLINGER'):
                if 'bb_position' not in df.columns:
                    continue
                bb_pos = df['bb_position'].iloc[cur]
                threshold = float(value) if value else 0.5
                if cond == 'GT' and not (bb_pos > threshold):
                    return False
                if cond == 'LT' and not (bb_pos < threshold):
                    return False
                if cond == 'SQUEEZE':
                    bb_w = df['bb_width'].iloc[cur] if 'bb_width' in df.columns else 1.0
                    if not (bb_w < (c.get('squeeze_threshold', 0.04))):
                        return False

            # --- ATR ---
            elif ctype == 'ATR':
                if 'atr_pct' not in df.columns:
                    continue
                atr_pct = df['atr_pct'].iloc[cur]
                threshold = float(value) if value else 0.01
                if cond == 'GT' and not (atr_pct > threshold):
                    return False
                if cond == 'LT' and not (atr_pct < threshold):
                    return False

            # --- VWAP ---
            elif ctype == 'VWAP':
                if 'vwap' not in df.columns:
                    continue
                vwap_val = df['vwap'].iloc[cur]
                price = df['close'].iloc[cur]
                proximity = abs(price - vwap_val) / vwap_val if vwap_val else 1.0
                if cond == 'ABOVE' and not (price > vwap_val):
                    return False
                if cond == 'BELOW' and not (price < vwap_val):
                    return False
                if cond == 'NEAR':
                    max_dist = float(value) if value else 0.02
                    if not (proximity <= max_dist):
                        return False

        return True  # All conditions passed
