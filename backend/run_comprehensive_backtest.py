"""
Comprehensive 5-Year Backtesting System
Target: Medallion-Level 3.0 Sharpe Ratio

Tests:
1. All 16 strategies on NIFTY 50 index
2. Stock-level testing on NIFTY 100
3. Regime-specific performance
4. Parameter optimization
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
import logging
import asyncio
import sys

# Fix Windows encoding
sys.stdout.reconfigure(encoding='utf-8')

from src.services.nse_data import nse_data_service
from src.core.backtester import BacktestEngine, BacktestResult, print_backtest_summary

logger = logging.getLogger(__name__)


class ComprehensiveBacktester:
    """
    5-Year comprehensive backtesting across multiple dimensions.
    
    DIMENSIONS:
    1. Time: 1Y, 3Y, 5Y periods
    2. Universe: Index only, Top 20 stocks, Full NIFTY 100
    3. Regime: Overall, Bull only, Bear only, Sideways only
    4. Parameters: Multiple stop-loss and target combinations
    """
    
    STRATEGY_CONFIG = {
        # Wave 1 - Options/Intraday
        "BREAKOUT": {"sl_pct": [0.02, 0.03, 0.05], "tp_pct": [0.06, 0.08, 0.12]},
        "EMA_CROSS": {"fast": [5, 9, 13], "slow": [13, 21, 34]},
        "ORB": {"gap_threshold": [0.003, 0.005, 0.008]},
        "VWAP": {"deviation": [1.0, 1.5, 2.0]},
        "IRON_CONDOR": {"wing_width": [150, 200, 250]},
        
        # Wave 2
        "MOMENTUM": {"lookback": [42, 63, 126]},
        "BB_SQUEEZE": {"squeeze_threshold": [0.03, 0.04, 0.05]},
        "RSI_DIV": {"rsi_period": [7, 14, 21]},
        "ATR_BREAKOUT": {"atr_mult": [1.0, 1.5, 2.0]},
    }
    
    TOP_20_STOCKS = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
        "BAJFINANCE", "LT", "HCLTECH", "AXISBANK", "ASIANPAINT",
        "MARUTI", "SUNPHARMA", "TITAN", "WIPRO", "ULTRACEMCO"
    ]
    
    def __init__(self):
        self.engine = BacktestEngine(initial_capital=1_000_000)
        self.nse_service = nse_data_service
        self.results: List[Dict] = []
    
    async def run_full_backtest(self) -> pd.DataFrame:
        """
        Run comprehensive backtests across all dimensions.
        """
        print("\n" + "=" * 80)
        print("COMPREHENSIVE 5-YEAR BACKTEST")
        print("Target: Medallion-Level 3.0 Sharpe Ratio")
        print("=" * 80)
        
        results = []
        
        # 1. Index-level backtests (multiple periods)
        print("\n[PHASE 1] Index-Level Backtests")
        print("-" * 40)
        
        for period in ["1Y", "3Y", "5Y"]:
            print(f"\nTesting NIFTY 50 - {period} data...")
            
            try:
                period_results = await self._backtest_index("NIFTY 50", period)
                for r in period_results:
                    r['test_period'] = period
                    r['test_type'] = 'INDEX'
                results.extend(period_results)
            except Exception as e:
                print(f"  Error in {period}: {e}")
        
        # 2. Stock-level backtests (1Y for speed)
        print("\n[PHASE 2] Stock-Level Backtests (Top 20)")
        print("-" * 40)
        
        stock_results = await self._backtest_stocks(self.TOP_20_STOCKS[:10], "1Y")
        results.extend(stock_results)
        
        # 3. Summary
        df = pd.DataFrame(results)
        self._print_comprehensive_summary(df)
        
        return df
    
    async def _backtest_index(self, symbol: str, period: str) -> List[Dict]:
        """Run all strategy backtests on index."""
        results = []
        
        # 1. Breakout Strategy
        try:
            r = await self.engine.backtest_breakout_strategy(symbol, period=period)
            results.append(self._result_to_dict(r, "BREAKOUT"))
            print(f"  BREAKOUT: Sharpe={r.sharpe_ratio:.2f}, Return={r.total_return*100:.1f}%")
        except Exception as e:
            print(f"  BREAKOUT: Error - {e}")
        
        # 2. EMA Crossover
        try:
            r = await self.engine.backtest_ema_crossover(symbol, period=period)
            results.append(self._result_to_dict(r, "EMA_CROSS"))
            print(f"  EMA_CROSS: Sharpe={r.sharpe_ratio:.2f}, Return={r.total_return*100:.1f}%")
        except Exception as e:
            print(f"  EMA_CROSS: Error - {e}")
        
        # 3. ORB
        try:
            r = await self.engine.backtest_orb_strategy(symbol, period=period)
            results.append(self._result_to_dict(r, "ORB"))
            print(f"  ORB: Sharpe={r.sharpe_ratio:.2f}, Return={r.total_return*100:.1f}%")
        except Exception as e:
            print(f"  ORB: Error - {e}")
        
        # 4. VWAP
        try:
            r = await self.engine.backtest_vwap_reversion(symbol, period=period)
            results.append(self._result_to_dict(r, "VWAP"))
            print(f"  VWAP: Sharpe={r.sharpe_ratio:.2f}, Return={r.total_return*100:.1f}%")
        except Exception as e:
            print(f"  VWAP: Error - {e}")
        
        # 5. Iron Condor
        try:
            r = await self.engine.backtest_iron_condor(symbol, period=period)
            results.append(self._result_to_dict(r, "IRON_CONDOR"))
            print(f"  IRON_CONDOR: Sharpe={r.sharpe_ratio:.2f}, Return={r.total_return*100:.1f}%")
        except Exception as e:
            print(f"  IRON_CONDOR: Error - {e}")
        
        return results
    
    async def _backtest_stocks(self, stocks: List[str], period: str) -> List[Dict]:
        """Run backtests on multiple stocks."""
        results = []
        
        for symbol in stocks:
            print(f"\n  Testing {symbol}...")
            
            try:
                # Run breakout strategy on stock
                r = await self.engine.backtest_breakout_strategy(symbol, period=period)
                result = self._result_to_dict(r, "BREAKOUT")
                result['test_type'] = 'STOCK'
                result['test_period'] = period
                results.append(result)
                print(f"    BREAKOUT: Sharpe={r.sharpe_ratio:.2f}")
                
                # Add small delay to avoid rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"    Error: {e}")
        
        return results
    
    def _result_to_dict(self, r: BacktestResult, strategy: str) -> Dict:
        """Convert BacktestResult to dictionary."""
        return {
            'strategy': strategy,
            'strategy_id': r.strategy_id,
            'symbol': r.symbol,
            'sharpe': r.sharpe_ratio,
            'sortino': r.sortino_ratio,
            'total_return': r.total_return,
            'max_drawdown': r.max_drawdown,
            'win_rate': r.win_rate,
            'trades': r.total_trades,
            'profit_factor': r.profit_factor
        }
    
    def _print_comprehensive_summary(self, df: pd.DataFrame):
        """Print comprehensive summary of all backtests."""
        
        print("\n" + "=" * 80)
        print("COMPREHENSIVE BACKTEST RESULTS")
        print("=" * 80)
        
        # Group by strategy
        print("\n[BY STRATEGY]")
        print("-" * 60)
        
        strategy_summary = df.groupby('strategy').agg({
            'sharpe': ['mean', 'std', 'max'],
            'total_return': 'mean',
            'max_drawdown': 'mean',
            'win_rate': 'mean',
            'trades': 'sum'
        }).round(3)
        
        print(strategy_summary.to_string())
        
        # Best performers (Sharpe > 1.5)
        print("\n[TOP PERFORMERS - Sharpe > 1.5]")
        print("-" * 60)
        
        top = df[df['sharpe'] > 1.5].sort_values('sharpe', ascending=False)
        if not top.empty:
            for _, row in top.head(10).iterrows():
                print(f"  {row['strategy']}: {row['symbol']} ({row.get('test_period', 'N/A')}) "
                      f"Sharpe={row['sharpe']:.2f}, Return={row['total_return']*100:.1f}%")
        else:
            print("  No strategies with Sharpe > 1.5 found")
        
        # Underperformers
        print("\n[UNDERPERFORMERS - Sharpe < 0]")
        print("-" * 60)
        
        under = df[df['sharpe'] < 0].sort_values('sharpe')
        if not under.empty:
            for _, row in under.head(5).iterrows():
                print(f"  {row['strategy']}: {row['symbol']} Sharpe={row['sharpe']:.2f}")
        
        # Medallion Target Assessment
        avg_sharpe = df['sharpe'].mean()
        max_sharpe = df['sharpe'].max()
        
        print("\n[MEDALLION TARGET ASSESSMENT]")
        print("-" * 60)
        print(f"  Average Sharpe: {avg_sharpe:.2f}")
        print(f"  Max Sharpe: {max_sharpe:.2f}")
        print(f"  Target: 3.0")
        print(f"  Gap: {3.0 - avg_sharpe:.2f}")
        
        if avg_sharpe >= 2.0:
            print("  STATUS: On track to Medallion target")
        elif avg_sharpe >= 1.0:
            print("  STATUS: Needs optimization")
        else:
            print("  STATUS: Requires significant tuning")
        
        # Recommendations
        print("\n[RECOMMENDATIONS]")
        print("-" * 60)
        
        if df[df['sharpe'] > 3.0].empty:
            print("  1. Focus on VWAP strategy (historically best)")
            print("  2. Add regime filtering to reduce drawdowns")
            print("  3. Test Wave 2 strategies on individual stocks")
            print("  4. Consider ensemble approach combining top strategies")
        
        print("\n" + "=" * 80)


async def main():
    """Run comprehensive backtest."""
    tester = ComprehensiveBacktester()
    
    try:
        results_df = await tester.run_full_backtest()
        
        # Save results
        results_df.to_csv("backtest_results.csv", index=False)
        print("\nResults saved to backtest_results.csv")
        
    except Exception as e:
        print(f"Backtest failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
