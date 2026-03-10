from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime
from src.strategies.base import BaseStrategy, StrategySignal

class LongStraddle(BaseStrategy):
    """
    14. Long Straddle
    Buy ATM Call + Buy ATM Put (both same strike)
    Max Loss: Premium paid for both options
    Max Profit: Unlimited (call side) / Large (put side)
    Best for: High volatility expectation, earnings, major events
    Profit from: Large moves in either direction
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_STRADDLE_014", config or {})
        self.iv_threshold = config.get("iv_threshold", 30) if config else 30
        self.atr_multiplier = config.get("atr_multiplier", 1.5) if config else 1.5

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        # High VIX expectation
        return 80.0 if regime == "VOLATILE" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Long Straddle signal - ATM straddle on volatility spike"""
        try:
            if market_data.empty or len(market_data) < 5:
                return None
            
            current_close = market_data['close'].iloc[-1]
            
            # Calculate ATR for volatility
            high_low = market_data['high'] - market_data['low']
            atr = high_low.iloc[-5:].mean()
            atr_pct = (atr / current_close) * 100
            
            # Signal when expecting volatility increase
            if regime == "VOLATILE" and atr_pct > 2:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"STRADDLE_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="BUY",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.78,
                    stop_loss=current_close - (atr * self.atr_multiplier),
                    target_price=current_close + (atr * self.atr_multiplier * 1.5),
                    metadata={
                        "strategy_type": "long_straddle",
                        "strike": round(current_close),
                        "atr_pct": round(atr_pct, 2),
                        "breakeven_ranges": [
                            round(current_close - atr),
                            round(current_close + atr)
                        ],
                        "entry_type": "LONG_STRADDLE",
                        "vol_expectation": "expansion",
                        "time_decay_risk": True,
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Long Straddle error: {e}")
            return None

class VIXTrading(BaseStrategy):
    """
    15. VIX Trading Strategy
    Trades volatility index movements
    Long VIX: When expecting market turbulence
    Short VIX: When market stabilizes
    
    Note: In this implementation, we simulate with price volatility proxies
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_VIX_015", config or {})
        self.vol_lookback = config.get("vol_lookback", 20) if config else 20
        self.vol_threshold = config.get("vol_threshold", 2.0) if config else 2.0

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        # VIX useful in all regimes but especially volatile
        if regime == "VOLATILE":
            return 70.0
        elif regime == "BEAR":
            return 60.0
        return 40.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate VIX trading signal based on volatility regime changes"""
        try:
            if market_data.empty or len(market_data) < self.vol_lookback:
                return None
            
            # Calculate rolling volatility using price changes
            returns = market_data['close'].pct_change()
            recent_vol = returns.iloc[-self.vol_lookback:].std() * 100
            prior_vol = returns.iloc[-self.vol_lookback*2:-self.vol_lookback].std() * 100
            
            current_close = market_data['close'].iloc[-1]
            
            # Signal when volatility is expanding (long VIX proxy)
            if recent_vol > prior_vol * 1.2 and recent_vol > self.vol_threshold:
                return StrategySignal(
                    signal_id=f"VIX_LONG_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol="VIX",
                    signal_type="BUY",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.70,
                    stop_loss=current_close - (current_close * 0.1),
                    target_price=current_close + (current_close * 0.15),
                    metadata={
                        "strategy_type": "vix_trading",
                        "volatility_direction": "expansion",
                        "recent_vol_pct": round(recent_vol, 2),
                        "vol_change": round(((recent_vol/prior_vol - 1) * 100), 2),
                        "regime": regime,
                        "entry_type": "LONG_VIX",
                        "hedge_benefit": "Portfolio protection"
                    }
                )
            # Signal when volatility is contracting (short VIX proxy)
            elif prior_vol > recent_vol * 1.2 and regime in ["BULL", "SIDEWAYS"]:
                return StrategySignal(
                    signal_id=f"VIX_SHORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol="VIX",
                    signal_type="SELL",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.70,
                    stop_loss=current_close + (current_close * 0.12),
                    target_price=current_close - (current_close * 0.1),
                    metadata={
                        "strategy_type": "vix_trading",
                        "volatility_direction": "contraction",
                        "recent_vol_pct": round(recent_vol, 2),
                        "vol_change": round(((recent_vol/prior_vol - 1) * 100), 2),
                        "regime": regime,
                        "entry_type": "SHORT_VIX",
                        "profit_from": "Vol crush"
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"VIX Trading error: {e}")
            return None

