import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint
import logging
import asyncio
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)

class PairsFinder:
    """
    Statistical Arbitrage Engine.
    Identifies cointegrated pairs for mean-reversion strategies.
    
    Logic:
    1. Fetch historical data for universe (NIFTY 100/50)
    2. Check correlation (> 0.8)
    3. Run Engle-Granger Cointegration Test (p-value < 0.05)
    4. Calculate Spread and Z-Score
    """
    def __init__(self, symbols: List[str] = None):
        self.symbols = symbols or nse_data_service.get_nifty_100_stocks()[:50] # Default to NIFTY 50 for speed
        self.data_cache = {}
        self.pairs = []

    async def fetch_data(self, period: str = "1y"):
        """Fetch historical closing prices for all symbols."""
        logger.info(f"Fetching data for {len(self.symbols)} symbols...")
        
        tasks = []
        sem = asyncio.Semaphore(10) # Limit concurrent requests
        
        async def fetch(sym):
            async with sem:
                try:
                    df = await nse_data_service.get_stock_ohlc(sym, period)
                    if not df.empty and 'close' in df.columns:
                        return sym, df['close']
                except Exception as e:
                    logger.debug(f"Failed to fetch {sym}: {e}")
                return sym, None

        for sym in self.symbols:
            tasks.append(fetch(sym))
            
        results = await asyncio.gather(*tasks)
        
        # Aggregate into a single DataFrame
        combined_data = {}
        for sym, series in results:
            if series is not None:
                combined_data[sym] = series
                
        # Align dates (inner join)
        self.df_prices = pd.DataFrame(combined_data).dropna()
        logger.info(f"Data fetched. Shape: {self.df_prices.shape}")

    async def find_pairs(self, p_value_threshold=0.05, correlation_threshold=0.9):
        """
        Identify cointegrated pairs.
        Complexity: O(N^2) - heavy computation.
        """
        if not hasattr(self, 'df_prices') or self.df_prices.empty:
            await self.fetch_data()
            
        keys = self.df_prices.columns
        n = len(keys)
        pairs_found = []
        
        logger.info(f"Scanning {n} stocks for pairs ({n*(n-1)//2} combinations)...")
        
        # This loop is CPU bound, running in thread to avoid blocking event loop
        loop = asyncio.get_running_loop()
        pairs_found = await loop.run_in_executor(
            None, 
            self._run_cointegration_tests, 
            keys, 
            p_value_threshold, 
            correlation_threshold
        )
            
        self.pairs = pairs_found
        logger.info(f"Found {len(self.pairs)} cointegrated pairs.")
        return self.pairs

    def _run_cointegration_tests(self, keys, p_threshold, corr_threshold):
        """Blocking Coinigration Logic."""
        results = []
        for i in range(n := len(keys)):
            for j in range(i + 1, n):
                s1 = self.df_prices[keys[i]]
                s2 = self.df_prices[keys[j]]
                
                # 1. Correlation Check (Fast filter)
                curr_corr = s1.corr(s2)
                if curr_corr < corr_threshold:
                    continue
                
                # 2. Cointegration Test
                # statsmodels coint returns: t-stat, p-value, crit_values
                try:
                    score, pvalue, _ = coint(s1, s2)
                    
                    if pvalue < p_threshold:
                        # Calculate Hedge Ratio (OLS)
                        # Spread = Y - b*X
                        x = sm.add_constant(s2)
                        model = sm.OLS(s1, x).fit()
                        hedge_ratio = model.params[keys[j]]
                        
                        results.append({
                            "stock1": keys[i],
                            "stock2": keys[j],
                            "correlation": curr_corr,
                            "p_value": pvalue,
                            "hedge_ratio": hedge_ratio,
                            "z_score_current": self._calculate_current_zscore(s1, s2, hedge_ratio)
                        })
                except Exception as e:
                    continue
                    
        return sorted(results, key=lambda x: x['p_value'])

    def _calculate_current_zscore(self, s1, s2, hedge_ratio):
        """Calculate Z-Score of the spread."""
        spread = s1 - hedge_ratio * s2
        mean = spread.mean()
        std = spread.std()
        return (spread.iloc[-1] - mean) / std

if __name__ == "__main__":
    # Test Runner
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        # Test with a small subset including known correlated pairs (Banks/IT)
        test_symbols = ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "SBIN", "INFY", "TCS", "WIPRO"]
        finder = PairsFinder(symbols=test_symbols)
        
        await finder.fetch_data(period="1y")
        pairs = await finder.find_pairs()
        
        print("\n=== TOP COINTEGRATED PAIRS ===")
        for p in pairs:
            print(f"{p['stock1']} vs {p['stock2']} | P-Val: {p['p_value']:.4f} | Corr: {p['correlation']:.2f}")

    asyncio.run(main())
