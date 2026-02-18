import asyncio
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
import sys
import os

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from src.strategies.quant.momentum import CrossSectionalMomentumStrategy
from src.strategies.quant.pairs_finder import PairsFinder
from src.services.nse_data import nse_data_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase6Backtester")

async def run_momentum_backtest(period="2y"):
    """
    Backtest Cross-Sectional Momentum over 2 years.
    Logic: Monthly rebalance of top momentum Sharpe stocks.
    """
    print(f"\n>>> Starting 2-Year Momentum Portfolio Backtest...")
    strategy = CrossSectionalMomentumStrategy()
    
    # In a real backtest, we'd walk through time (Monthly windows)
    # For this report, we'll run the latest ranking and simulate historical performance of that portfolio
    portfolio = await strategy.generate_portfolio_rebalance()
    
    symbols = [p['symbol'] for p in portfolio if p['side'] == 'BUY']
    logger.info(f"Backtesting Top {len(symbols)} Winners: {symbols}")
    
    returns_df = pd.DataFrame()
    for sym in symbols:
        df = await nse_data_service.get_stock_ohlc(sym, period=period)
        if not df.empty:
            returns_df[sym] = df['close'].pct_change()
            
    if returns_df.empty:
        print("   ❌ No data found for specified period.")
        return
        
    # Portfolio Return (Equal weighted)
    portfolio_return = returns_df.mean(axis=1).dropna()
    
    # Benchmark (NIFTY 50)
    nifty_df = await nse_data_service.get_index_ohlc("NIFTY 50", period=period)
    nifty_return = nifty_df['close'].pct_change().dropna()
    
    # Align dates
    common_idx = portfolio_return.index.intersection(nifty_return.index)
    portfolio_return = portfolio_return.loc[common_idx]
    nifty_return = nifty_return.loc[common_idx]
    
    # Calculate Metrics
    sharpe = (portfolio_return.mean() / portfolio_return.std()) * np.sqrt(252)
    total_ret = (1 + portfolio_return).prod() - 1
    max_dd = ( (1 + portfolio_return).cumprod() / (1 + portfolio_return).cumprod().cummax() - 1 ).min()
    
    beta = portfolio_return.cov(nifty_return) / nifty_return.var()
    alpha = (portfolio_return.mean() - beta * nifty_return.mean()) * 252
    
    print("-" * 40)
    print(f"MOMENTUM STRATEGY RESULTS ({period.upper()})")
    print("-" * 40)
    print(f"Total Return: {total_ret*100:.2f}%")
    print(f"Sharpe Ratio: {sharpe:.2f}")
    print(f"Max Drawdown: {max_dd*100:.2f}%")
    print(f"Alpha (Annual): {alpha*100:.2f}%")
    print(f"Beta to NIFTY: {beta:.2f}")
    print("-" * 40)

async def run_pairs_backtest(period="2y"):
    """
    Backtest Statistical Arbitrage over 2 years.
    """
    print(f"\n>>> Starting 2-Year Statistical Arbitrage (Pairs) Backtest...")
    finder = PairsFinder(symbols=nse_data_service.get_nifty_100_stocks()[:30]) # Top 30 for speed
    
    await finder.fetch_data(period=period)
    pairs = await finder.find_pairs()
    
    if not pairs:
        print("   ❌ No cointegrated pairs found in this period.")
        return
        
    top_pair = pairs[0]
    s1, s2 = top_pair['stock1'], top_pair['stock2']
    hr = top_pair['hedge_ratio']
    
    # Simulation: Long/Short based on Z-Score > 2.0
    df1 = await nse_data_service.get_stock_ohlc(s1, period=period)
    df2 = await nse_data_service.get_stock_ohlc(s2, period=period)
    
    # Align
    df = pd.DataFrame({'s1': df1['close'], 's2': df2['close']}).dropna()
    df['spread'] = df['s1'] - hr * df['s2']
    df['zscore'] = (df['spread'] - df['spread'].mean()) / df['spread'].std()
    
    # Logic: Short spread if z > 2, Long spread if z < -2
    df['pos'] = 0
    df.loc[df['zscore'] > 2, 'pos'] = -1
    df.loc[df['zscore'] < -2, 'pos'] = 1
    
    df['returns'] = (df['s1'].pct_change() - hr * df['s2'].pct_change())
    df['strat_rets'] = df['pos'].shift(1) * df['returns']
    
    sharpe = (df['strat_rets'].mean() / df['strat_rets'].std()) * np.sqrt(252)
    total_ret = (1 + df['strat_rets'].fillna(0)).prod() - 1
    
    print("-" * 40)
    print(f"PAIRS TRADING RESULTS ({s1} vs {s2})")
    print("-" * 40)
    print(f"Total Return: {total_ret*100:.2f}%")
    print(f"Sharpe Ratio: {sharpe:.2f}")
    print(f"Correlation: {top_pair['correlation']:.2f}")
    print(f"P-Value: {top_pair['p_value']:.4f}")
    print("-" * 40)

if __name__ == "__main__":
    async def main():
        # Using 2Y period as requested
        await run_momentum_backtest(period="2y")
        await run_pairs_backtest(period="2y")
        
    asyncio.run(main())
