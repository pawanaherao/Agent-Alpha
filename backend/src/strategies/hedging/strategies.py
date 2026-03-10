from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime
from src.strategies.base import BaseStrategy, StrategySignal

class DeltaHedging(BaseStrategy):
    """
    16. Delta Hedging
    Continuously adjust hedge ratio to maintain delta-neutral position
    Lock in gains, manage risk dynamically
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_DELTA_016", config or {})
        self.target_delta = config.get("target_delta", 0.0) if config else 0.0
        self.rehedge_threshold = config.get("rehedge_threshold", 0.1) if config else 0.1

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 100.0  # Always monitoring

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Delta Hedging rebalancing signal"""
        try:
            if market_data.empty or len(market_data) < 5:
                return None
            
            current_close = market_data['close'].iloc[-1]
            
            # Calculate simple delta proxy using price momentum
            closes = market_data['close'].iloc[-5:].values
            momentum = (closes[-1] - closes[0]) / closes[0]
            
            # If position has drifted significantly, rehedge
            if abs(momentum) > self.rehedge_threshold:
                signal_direction = "SELL" if momentum > 0 else "BUY"
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"DELTA_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type=signal_direction,
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.85,
                    stop_loss=current_close + (current_close * abs(momentum) * 2),
                    target_price=current_close,
                    metadata={
                        "entry_type": "DELTA_HEDGE_REBALANCE",
                        "strategy_type": "delta_hedging",
                        "current_delta": round(momentum, 3),
                        "target_delta": self.target_delta,
                        "rehedge_reason": "Delta drift exceeded threshold",
                        "rehedge_direction": signal_direction,
                        "position_management": "Active"
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Delta Hedging error: {e}")
            return None

class PortfolioHedge(BaseStrategy):
    """
    17. Portfolio Hedge
    Protective hedging for portfolio downside protection
    Buy protective puts / Sell upside calls
    Reduce maximum drawdown risk
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_PORT_017", config or {})
        self.dd_threshold = config.get("dd_threshold", 0.05) if config else 0.05
        self.hedge_ratio = config.get("hedge_ratio", 0.5) if config else 0.5

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 100.0  # Always on

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Portfolio Hedge signal when drawdown risk is high"""
        try:
            if market_data.empty or len(market_data) < 20:
                return None
            
            # Calculate rolling maximum and drawdown
            rolling_max = market_data['close'].rolling(window=20).max()
            drawdown = (market_data['close'] - rolling_max) / rolling_max
            current_dd = drawdown.iloc[-1]
            current_close = market_data['close'].iloc[-1]
            
            # Signal when drawdown exceeds threshold (portfolio protection needed)
            if current_dd < -self.dd_threshold:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"HEDGE_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="BUY",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=max(1, int(abs(current_dd) * 10)),
                    strength=0.80,
                    stop_loss=current_close + (current_close * 0.03),
                    target_price=current_close - (current_close * abs(current_dd) * 0.5),
                    metadata={
                        "entry_type": "PORTFOLIO_HEDGE",
                        "instrument_type": "PUT",
                        "strategy_type": "portfolio_hedge",
                        "current_drawdown_pct": round(current_dd * 100, 2),
                        "dd_threshold_pct": self.dd_threshold * 100,
                        "hedge_ratio": self.hedge_ratio,
                        "protection_strike": round(current_close * (1 - self.hedge_ratio)),
                        "purpose": "Downside protection",
                        "cost_acceptable": True
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Portfolio Hedge error: {e}")
            return None

class PairTrading(BaseStrategy):
    """
    18. Pair Trading (Statistical Arbitrage)
    Long one stock, short correlated stock
    Market neutral strategy exploiting relative mispricing
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_PAIR_018", config or {})
        self.correlation_threshold = config.get("correlation_threshold", 0.7) if config else 0.7
        self.zscore_threshold = config.get("zscore_threshold", 2.0) if config else 2.0

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        # Works best in sideways markets, market neutral
        return 75.0 if regime in ["SIDEWAYS", "BULL"] else 50.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Pair Trading signal based on spread deviation"""
        try:
            if market_data.empty or len(market_data) < 30:
                return None
            
            current_close = market_data['close'].iloc[-1]
            
            # Calculate simple spread metric
            closes = market_data['close'].iloc[-30:].values
            spread_mean = np.mean(closes)
            spread_std = np.std(closes)
            
            # Calculate z-score of current price vs mean
            current_zscore = (current_close - spread_mean) / spread_std if spread_std > 0 else 0
            
            # Signal when pair is significantly mispriced
            if abs(current_zscore) > self.zscore_threshold:
                signal_direction = "SELL" if current_zscore > 0 else "BUY"
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"PAIR_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type=signal_direction,
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.72,
                    stop_loss=current_close + (spread_std * 1.5),
                    target_price=spread_mean,
                    metadata={
                        "entry_type": "PAIR_TRADE",
                        "strategy_type": "pair_trading",
                        "zscore": round(current_zscore, 2),
                        "spread_mean": round(spread_mean, 2),
                        "spread_std": round(spread_std, 2),
                        "mean_reversion_target": round(spread_mean, 2),
                        "market_neutral": True,
                        "long_instrument": "Primary pair",
                        "short_instrument": "Correlated pair"
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Pair Trading error: {e}")
            return None

