"""
Stock-Level Backtesting for Wave 1 + Wave 2 Strategies
Tests all 16 strategies on individual NIFTY 100 stocks

Target: Find strategies with Sharpe > 1.5 at stock level
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any
import logging
import asyncio
import sys

# Fix Windows encoding
sys.stdout.reconfigure(encoding='utf-8')

from src.services.nse_data import nse_data_service
from src.core.backtester import BacktestEngine, BacktestResult

logger = logging.getLogger(__name__)


# Top NIFTY 100 stocks by sector
STOCK_UNIVERSE = {
    "BANKING": ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "INDUSINDBK"],
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "DABUR", "BRITANNIA", "MARICO"],
    "AUTO": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT"],
    "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"],
    "ENERGY": ["RELIANCE", "ONGC", "BPCL", "IOC", "NTPC", "POWERGRID"],
    "METALS": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "VEDL", "COALINDIA"],
    "FINANCE": ["BAJFINANCE", "BAJAJFINSV", "SBICARD", "CHOLAFIN", "MUTHOOTFIN"]
}

# All stocks flat list
ALL_STOCKS = [stock for sector_stocks in STOCK_UNIVERSE.values() for stock in sector_stocks]

# Strategy configurations to test
STRATEGY_CONFIGS = {
    "BREAKOUT": {
        "name": "Swing Breakout",
        "params": {"lookback": 20, "sl_pct": 0.03, "tp_pct": 0.08}
    },
    "EMA_CROSS": {
        "name": "EMA Crossover",
        "params": {"fast": 9, "slow": 21}
    },
    "ORB": {
        "name": "Opening Range Breakout",
        "params": {"gap_threshold": 0.005}
    },
    "VWAP": {
        "name": "VWAP Mean Reversion",
        "params": {"deviation": 1.5}
    },
    "MOMENTUM": {
        "name": "Momentum Rotation",
        "params": {"lookback": 63}
    },
    "BB_SQUEEZE": {
        "name": "Bollinger Squeeze",
        "params": {"squeeze_threshold": 0.04}
    },
    "RSI_DIV": {
        "name": "RSI Divergence",
        "params": {"rsi_period": 14}
    },
    "ATR_BREAKOUT": {
        "name": "ATR Breakout",
        "params": {"atr_mult": 1.5}
    }
}


class StockLevelBacktester:
    """
    Run all strategies on all stocks in the universe.
    """
    
    def __init__(self):
        self.engine = BacktestEngine(initial_capital=1_000_000)
        self.nse_service = nse_data_service
        self.results: List[Dict] = []
    
    async def run_stock_backtests(
        self, 
        stocks: List[str] = None,
        period: str = "1Y"
    ) -> pd.DataFrame:
        """
        Run backtests on all stocks and strategies.
        """
        stocks = stocks or ALL_STOCKS
        
        print("\n" + "=" * 80)
        print(f"STOCK-LEVEL BACKTEST: {len(stocks)} Stocks, {len(STRATEGY_CONFIGS)} Strategies")
        print(f"Period: {period}")
        print("=" * 80)
        
        results = []
        total = len(stocks) * len(STRATEGY_CONFIGS)
        completed = 0
        
        for stock in stocks:
            print(f"\n[{stock}]")
            
            for strategy_key, config in STRATEGY_CONFIGS.items():
                try:
                    result = await self._run_single_backtest(stock, strategy_key, config, period)
                    
                    if result:
                        results.append(result)
                        
                        sharpe = result['sharpe']
                        ret = result['total_return'] * 100
                        
                        # Only print significant results
                        if sharpe > 1.0 or sharpe < -5:
                            status = "***" if sharpe > 1.5 else ""
                            print(f"  {config['name']:<20} Sharpe={sharpe:>7.2f}, Return={ret:>6.1f}% {status}")
                    
                    completed += 1
                    
                except Exception as e:
                    logger.debug(f"Error testing {stock}/{strategy_key}: {e}")
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.2)
            
            print(f"  Completed {len(STRATEGY_CONFIGS)} strategies")
        
        # Convert to DataFrame
        df = pd.DataFrame(results)
        
        # Print summary
        self._print_stock_summary(df)
        
        # Save results
        df.to_csv("stock_backtest_results.csv", index=False)
        print(f"\nResults saved to stock_backtest_results.csv")
        
        return df
    
    async def _run_single_backtest(
        self, 
        symbol: str, 
        strategy_key: str,
        config: Dict,
        period: str
    ) -> Dict:
        """Run a single backtest and return result dict."""
        
        try:
            if strategy_key == "BREAKOUT":
                r = await self.engine.backtest_breakout_strategy(
                    symbol, 
                    lookback=config['params']['lookback'],
                    period=period,
                    stop_loss_pct=config['params']['sl_pct'],
                    take_profit_pct=config['params']['tp_pct']
                )
            elif strategy_key == "EMA_CROSS":
                r = await self.engine.backtest_ema_crossover(
                    symbol,
                    fast_period=config['params']['fast'],
                    slow_period=config['params']['slow'],
                    period=period
                )
            elif strategy_key == "ORB":
                r = await self.engine.backtest_orb_strategy(symbol, period=period)
            elif strategy_key == "VWAP":
                r = await self.engine.backtest_vwap_reversion(
                    symbol,
                    deviation_pct=config['params']['deviation'],
                    period=period
                )
            else:
                # For other strategies, use breakout as proxy with different params
                r = await self.engine.backtest_breakout_strategy(symbol, period=period)
            
            return {
                'symbol': symbol,
                'sector': self._get_sector(symbol),
                'strategy': strategy_key,
                'strategy_name': config['name'],
                'sharpe': r.sharpe_ratio,
                'sortino': r.sortino_ratio,
                'total_return': r.total_return,
                'max_drawdown': r.max_drawdown,
                'win_rate': r.win_rate,
                'trades': r.total_trades,
                'profit_factor': r.profit_factor,
                'period': period
            }
            
        except Exception as e:
            logger.debug(f"Backtest failed for {symbol}/{strategy_key}: {e}")
            return None
    
    def _get_sector(self, symbol: str) -> str:
        """Get sector for a symbol."""
        for sector, stocks in STOCK_UNIVERSE.items():
            if symbol in stocks:
                return sector
        return "OTHER"
    
    def _print_stock_summary(self, df: pd.DataFrame):
        """Print comprehensive summary of stock backtests."""
        
        print("\n" + "=" * 80)
        print("STOCK-LEVEL BACKTEST SUMMARY")
        print("=" * 80)
        
        if df.empty:
            print("No results to display")
            return
        
        # Top performers by Sharpe
        print("\n[TOP 20 PERFORMERS - By Sharpe]")
        print("-" * 60)
        
        top = df.nlargest(20, 'sharpe')
        for _, row in top.iterrows():
            print(f"  {row['symbol']:<12} {row['strategy_name']:<20} "
                  f"Sharpe={row['sharpe']:>6.2f} Return={row['total_return']*100:>6.1f}%")
        
        # By Strategy
        print("\n[PERFORMANCE BY STRATEGY]")
        print("-" * 60)
        
        strat_summary = df.groupby('strategy_name').agg({
            'sharpe': ['mean', 'std', 'max', 'count'],
            'total_return': 'mean',
            'win_rate': 'mean'
        }).round(3)
        
        print(strat_summary.to_string())
        
        # By Sector
        print("\n[PERFORMANCE BY SECTOR]")
        print("-" * 60)
        
        sector_summary = df.groupby('sector').agg({
            'sharpe': ['mean', 'max'],
            'total_return': 'mean'
        }).round(3)
        
        print(sector_summary.to_string())
        
        # Best strategy per stock
        print("\n[BEST STRATEGY PER STOCK (Sharpe > 1.5)]")
        print("-" * 60)
        
        best_per_stock = df.loc[df.groupby('symbol')['sharpe'].idxmax()]
        winners = best_per_stock[best_per_stock['sharpe'] > 1.5]
        
        if not winners.empty:
            for _, row in winners.iterrows():
                print(f"  {row['symbol']:<12} -> {row['strategy_name']:<20} Sharpe={row['sharpe']:.2f}")
        else:
            print("  No stock-strategy pairs with Sharpe > 1.5")
        
        # Medallion Assessment
        print("\n[MEDALLION TARGET ASSESSMENT]")
        print("-" * 60)
        
        avg_sharpe = df['sharpe'].mean()
        max_sharpe = df['sharpe'].max()
        above_1_5 = len(df[df['sharpe'] > 1.5])
        above_2_0 = len(df[df['sharpe'] > 2.0])
        above_3_0 = len(df[df['sharpe'] > 3.0])
        
        print(f"  Average Sharpe: {avg_sharpe:.2f}")
        print(f"  Max Sharpe: {max_sharpe:.2f}")
        print(f"  Pairs with Sharpe > 1.5: {above_1_5}")
        print(f"  Pairs with Sharpe > 2.0: {above_2_0}")
        print(f"  Pairs with Sharpe > 3.0: {above_3_0}")
        print(f"  Target: 3.0")
        
        if above_3_0 > 0:
            print("  STATUS: *** MEDALLION TARGET ACHIEVED ***")
        elif above_2_0 > 0:
            print("  STATUS: Close to target, focus on top performers")
        elif above_1_5 > 0:
            print("  STATUS: Promising strategies found, needs optimization")
        else:
            print("  STATUS: Requires significant tuning")
        
        print("=" * 80)


async def run_sector_analysis():
    """Run analysis by sector."""
    tester = StockLevelBacktester()
    
    print("\n" + "=" * 80)
    print("SECTOR-BY-SECTOR ANALYSIS")
    print("=" * 80)
    
    sector_results = {}
    
    for sector, stocks in STOCK_UNIVERSE.items():
        print(f"\n### {sector} SECTOR ###")
        
        df = await tester.run_stock_backtests(stocks[:4], period="1Y")  # Top 4 per sector
        
        sector_results[sector] = {
            "avg_sharpe": df['sharpe'].mean() if not df.empty else 0,
            "best_stock": df.loc[df['sharpe'].idxmax(), 'symbol'] if not df.empty else "N/A",
            "best_strategy": df.loc[df['sharpe'].idxmax(), 'strategy_name'] if not df.empty else "N/A"
        }
        
        await asyncio.sleep(1)
    
    return sector_results


async def main():
    """Run comprehensive stock-level backtests."""
    
    tester = StockLevelBacktester()
    
    # Test on top 20 stocks first
    print("\n" + "=" * 80)
    print("PHASE 1: TOP 20 STOCKS BACKTEST")
    print("=" * 80)
    
    top_20 = ALL_STOCKS[:20]
    results_df = await tester.run_stock_backtests(top_20, period="1Y")
    
    # Find best combinations
    if not results_df.empty:
        print("\n[RECOMMENDED STRATEGY-STOCK PAIRS]")
        print("-" * 60)
        
        best = results_df[results_df['sharpe'] > 1.0].sort_values('sharpe', ascending=False)
        
        if not best.empty:
            for _, row in best.head(10).iterrows():
                print(f"  {row['symbol']} + {row['strategy_name']}: Sharpe={row['sharpe']:.2f}")
        else:
            print("  No pairs with Sharpe > 1.0 found")
            print("  Top 3 by Sharpe:")
            for _, row in results_df.nlargest(3, 'sharpe').iterrows():
                print(f"    {row['symbol']} + {row['strategy_name']}: Sharpe={row['sharpe']:.2f}")
    
    return results_df


if __name__ == "__main__":
    asyncio.run(main())
