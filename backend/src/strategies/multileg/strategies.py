from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime
from src.strategies.base import BaseStrategy, StrategySignal

class IronCondor(BaseStrategy):
    """
    11. Iron Condor
    Sell OTM Call Spread + Sell OTM Put Spread (same expiry)
    Max Profit: Net Credit (Premium collected)
    Max Loss: Difference between strikes - Net Credit
    Best for: High probability, defined risk, sideways markets
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_IRON_011", config or {})
        self.call_strike_gap = config.get("call_strike_gap", 100) if config else 100
        self.put_strike_gap = config.get("put_strike_gap", 100) if config else 100

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 95.0 if regime == "SIDEWAYS" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Iron Condor signal"""
        try:
            if market_data.empty or len(market_data) < 5:
                return None
            
            current_close = market_data['close'].iloc[-1]
            recent_high = market_data['high'].iloc[-5:].max()
            recent_low = market_data['low'].iloc[-5:].min()
            
            mid_point = (recent_high + recent_low) / 2
            range_width = recent_high - recent_low
            
            # Signal in balanced sideways market
            if regime == "SIDEWAYS" and range_width > 0:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"CONDOR_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="SELL",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.80,
                    stop_loss=recent_high + (range_width * 0.25),
                    target_price=mid_point,
                    metadata={
                        "strategy_type": "iron_condor",
                        "put_short": round(mid_point - (range_width * 0.5)),
                        "put_long": round(mid_point - (range_width * 0.75)),
                        "call_short": round(mid_point + (range_width * 0.5)),
                        "call_long": round(mid_point + (range_width * 0.75)),
                        "max_profit_pct": 5,
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Iron Condor error: {e}")
            return None

class ButterflySpread(BaseStrategy):
    """
    12. Butterfly Spread
    Buy 1 ATM Option, Sell 2 OTM Options, Buy 1 Further OTM
    Limited Profit & Loss
    Max Profit: Occurs at middle strike at expiration
    Best for: Low risk, defined parameters, directional neutral or mild bias
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_BUTTERFLY_012", config or {})
        self.spread_width = config.get("spread_width", 100) if config else 100

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 85.0 if regime == "SIDEWAYS" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Butterfly Spread signal"""
        try:
            if market_data.empty or len(market_data) < 5:
                return None
            
            current_close = market_data['close'].iloc[-1]
            volatility = (market_data['high'].iloc[-5:] - market_data['low'].iloc[-5:]).mean()
            
            # Signal when volatility is moderate (good butterfly conditions)
            if regime == "SIDEWAYS" and volatility < (current_close * 0.03):
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"BUTTERFLY_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="BUY",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.75,
                    stop_loss=current_close + (self.spread_width * 0.5),
                    target_price=current_close,
                    metadata={
                        "strategy_type": "butterfly_spread",
                        "bottom_strike": round(current_close - self.spread_width),
                        "middle_strike": round(current_close),
                        "top_strike": round(current_close + self.spread_width),
                        "max_loss_pct": 3,
                        "max_profit_pct": 3,
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Butterfly Spread error: {e}")
            return None

class LongStrangle(BaseStrategy):
    """
    13. Long Strangle
    Buy OTM Call + Buy OTM Put (betting on volatility)
    Max Loss: Premium paid
    Max Profit: Unlimited (call side) / Large (put side)
    Best for: High volatility breakout plays, earnings, events
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_STRANGLE_013", config or {})
        self.strangle_width = config.get("strangle_width", 200) if config else 200

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 90.0 if regime == "VOLATILE" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Long Strangle signal - bet on volatility"""
        try:
            if market_data.empty or len(market_data) < 5:
                return None
            
            current_close = market_data['close'].iloc[-1]
            recent_volatility = (market_data['high'].iloc[-5:] - market_data['low'].iloc[-5:]).std()
            
            # Signal when expecting volatility expansion
            if regime == "VOLATILE" and recent_volatility > 0:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"STRANGLE_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="BUY",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.75,
                    stop_loss=current_close - (self.strangle_width * 0.5),
                    target_price=current_close + (self.strangle_width * 0.75),
                    metadata={
                        "strategy_type": "long_strangle",
                        "call_strike": round(current_close + self.strangle_width),
                        "put_strike": round(current_close - self.strangle_width),
                        "breakeven_up": current_close + (self.strangle_width * 0.25),
                        "breakeven_down": current_close - (self.strangle_width * 0.25),
                        "vol_expectation": "expansion",
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Long Strangle error: {e}")
            return None

