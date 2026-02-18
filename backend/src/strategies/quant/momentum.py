import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timedelta

from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)

class CrossSectionalMomentumStrategy(BaseStrategy):
    """
    Institutional Momentum Strategy (Market Neutral).
    
    Logic:
    1. Universe: NIFTY 100
    2. Ranking: 12-Month Returns (skipping last 1 month to avoid reversal)
    3. Volatility Adjustment: Rank by Sharpe Ratio, not just raw return
    4. Portfolio: Long Top 10 Winners / Short NIFTY Futures (Hedged)
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("MomentumFactor", config or {})
        self.lookback_period = "1y"
        self.skip_recent_period = 21 # Skip last month (short-term reversal effect)
        self.top_n = 10
        
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Momentum works best in trending markets (BULL/BEAR).
        """
        suitability_map = {
            "BULL": 90.0,
            "BEAR": 80.0,
            "SIDEWAYS": 30.0,
            "VOLATILE": 60.0
        }
        return suitability_map.get(regime, 50.0)

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """
        This strategy runs on a Portfolio level, not single stock.
        It returns a Batch Signal or rebalancing instruction.
        """
        # For compatibility with the single-stock engine, this method might return None
        # and we expose a separate 'rebalance_portfolio' method.
        return None

    async def generate_portfolio_rebalance(self) -> List[Dict]:
        """
        Generate Long/Short portfolio weights.
        """
        universe = nse_data_service.get_nifty_100_stocks()
        logger.info(f"Ranking {len(universe)} stocks for Momentum...")
        
        scores = []
        
        # 1. Fetch Data for Universe
        # OPTIMIZATION: In production, use batch fetch or SQL
        for symbol in universe:
            try:
                df = await nse_data_service.get_stock_ohlc(symbol, period=self.lookback_period)
                if df.empty or len(df) < 200: continue
                
                # Close series
                closes = df['close'].values
                
                # 2. Calculate Momentum (12M - 1M)
                # Return from 1 year ago to 1 month ago
                p_current = closes[-self.skip_recent_period]
                p_past = closes[0]
                
                raw_return = (p_current - p_past) / p_past
                
                # 3. Volatility Adjustment (std dev of daily returns)
                daily_rets = df['close'].pct_change().dropna()
                vol = daily_rets.std() * np.sqrt(252)
                
                if vol == 0: continue
                
                # Sharpe-like Momentum Score
                score = raw_return / vol
                
                scores.append({
                    "symbol": symbol,
                    "score": score,
                    "raw_ret": raw_return,
                    "vol": vol,
                    "price": closes[-1]
                })
                
            except Exception as e:
                logger.debug(f"Failed to rank {symbol}: {e}")
                
        # 4. Rank and Select
        scores.sort(key=lambda x: x['score'], reverse=True)
        
        top_winners = scores[:self.top_n]
        bottom_losers = scores[-self.top_n:]
        
        logger.info(f"Top 3 Momentum: {[x['symbol'] for x in top_winners[:3]]}")
        
        portfolio = []
        
        # Long Legs
        for x in top_winners:
            portfolio.append({
                "symbol": x['symbol'],
                "side": "BUY",
                "weight": 0.1, # Equal weight 10% each
                "reason": f"High Momentum Score: {x['score']:.2f}"
            })
            
        # Hedge (Short NIFTY Futures)
        # In a generic implementation, we might short the losers (Long/Short Equity)
        # But for easier execution, we short the Index Future (Beta Hedging)
        portfolio.append({
            "symbol": "NIFTY-FUT",
            "side": "SELL",
            "weight": 1.0, # Fully hedged against market
            "reason": "Market Beta Hedge"
        })
        
        return portfolio
