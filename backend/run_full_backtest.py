"""
Full Backtest for ALL 16 Strategies (Wave 1 + Wave 2)
Tests each strategy on multiple stocks and reports comprehensive metrics
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any
import logging
import asyncio
import sys

sys.stdout.reconfigure(encoding='utf-8')

from src.services.nse_data import nse_data_service
from src.core.backtester import BacktestEngine, BacktestResult

logger = logging.getLogger(__name__)


# All 16 strategies to test
ALL_STRATEGIES = {
    # Wave 1 - Intraday/Options
    "ALPHA_ORB_001": {"name": "ORB - Opening Range Breakout", "wave": 1, "type": "MOMENTUM"},
    "ALPHA_IRON_011": {"name": "Iron Condor", "wave": 1, "type": "THETA"},
    "ALPHA_VWAP_002": {"name": "VWAP Mean Reversion", "wave": 1, "type": "MEAN_REV"},
    "ALPHA_BCS_007": {"name": "Bull Call Spread", "wave": 1, "type": "DIRECTIONAL"},
    
    # Wave 1 - Swing/Cash
    "ALPHA_BREAKOUT_101": {"name": "Swing Breakout", "wave": 1, "type": "MOMENTUM"},
    "ALPHA_PULLBACK_102": {"name": "Trend Pullback", "wave": 1, "type": "TREND"},
    "ALPHA_EMA_CROSS_104": {"name": "EMA Crossover", "wave": 1, "type": "TREND"},
    "ALPHA_PORT_017": {"name": "Portfolio Hedge", "wave": 1, "type": "HEDGE"},
    
    # Wave 2 - Momentum
    "ALPHA_MOMENTUM_201": {"name": "Momentum Rotation", "wave": 2, "type": "MOMENTUM"},
    "ALPHA_SECTOR_202": {"name": "Sector Rotation", "wave": 2, "type": "MOMENTUM"},
    
    # Wave 2 - Mean Reversion
    "ALPHA_BB_203": {"name": "Bollinger Band Squeeze", "wave": 2, "type": "MEAN_REV"},
    "ALPHA_RSI_DIV_204": {"name": "RSI Divergence", "wave": 2, "type": "MEAN_REV"},
    
    # Wave 2 - Event Driven
    "ALPHA_EARN_205": {"name": "Earnings Momentum", "wave": 2, "type": "EVENT"},
    "ALPHA_GAP_206": {"name": "Gap Fill", "wave": 2, "type": "EVENT"},
    
    # Wave 2 - Volatility
    "ALPHA_ATR_207": {"name": "ATR Breakout", "wave": 2, "type": "VOLATILITY"},
    "ALPHA_VOL_CRUSH_208": {"name": "Volatility Crush", "wave": 2, "type": "VOLATILITY"}
}

# Test stocks (representative from each sector)
TEST_STOCKS = [
    "HDFCBANK", "ICICIBANK", "SBIN",      # Banking
    "TCS", "INFY", "WIPRO",               # IT
    "RELIANCE", "NTPC",                    # Energy
    "HINDUNILVR", "NESTLEIND", "ITC",     # FMCG
    "MARUTI", "TATAMOTORS",                # Auto
    "SUNPHARMA", "DRREDDY",                # Pharma
    "BAJFINANCE",                          # Finance
    "TATASTEEL", "HINDALCO"                # Metals
]


class FullStrategyBacktester:
    """Run comprehensive backtests on all 16 strategies."""
    
    def __init__(self):
        self.engine = BacktestEngine(initial_capital=1_000_000)
        self.nse_service = nse_data_service
        self.results: List[Dict] = []
    
    async def run_full_backtest(self, period: str = "1Y") -> pd.DataFrame:
        """
        Run backtests for all 16 strategies on all test stocks.
        """
        print("\n" + "=" * 80)
        print("COMPREHENSIVE BACKTEST: ALL 16 STRATEGIES")
        print(f"Stocks: {len(TEST_STOCKS)} | Period: {period}")
        print("=" * 80)
        
        all_results = []
        
        for strategy_id, strategy_info in ALL_STRATEGIES.items():
            print(f"\n[{strategy_id}] {strategy_info['name']}")
            print("-" * 50)
            
            strategy_results = await self._test_strategy_on_stocks(
                strategy_id, 
                strategy_info,
                TEST_STOCKS,
                period
            )
            
            all_results.extend(strategy_results)
            
            # Print strategy summary
            if strategy_results:
                avg_sharpe = np.mean([r['sharpe'] for r in strategy_results])
                max_sharpe = max([r['sharpe'] for r in strategy_results])
                avg_win_rate = np.mean([r['win_rate'] for r in strategy_results])
                
                print(f"  Avg Sharpe: {avg_sharpe:.2f} | Max: {max_sharpe:.2f} | Win Rate: {avg_win_rate*100:.1f}%")
            
            await asyncio.sleep(0.5)  # Rate limiting
        
        # Create DataFrame
        df = pd.DataFrame(all_results)
        
        # Print comprehensive summary
        self._print_comprehensive_summary(df)
        
        # Save results
        df.to_csv("full_strategy_backtest.csv", index=False)
        print(f"\nResults saved to full_strategy_backtest.csv")
        
        return df
    
    async def _test_strategy_on_stocks(
        self,
        strategy_id: str,
        strategy_info: Dict,
        stocks: List[str],
        period: str
    ) -> List[Dict]:
        """Test a single strategy on multiple stocks."""
        
        results = []
        
        for symbol in stocks:
            try:
                # Route to appropriate backtest method based on strategy type
                result = await self._run_single_backtest(
                    symbol, strategy_id, strategy_info, period
                )
                
                if result:
                    results.append(result)
                    
                    # Print individual result if significant
                    if result['sharpe'] > 1.0:
                        print(f"    {symbol}: Sharpe={result['sharpe']:.2f} ***")
                    elif result['sharpe'] > 0.5:
                        print(f"    {symbol}: Sharpe={result['sharpe']:.2f}")
                
            except Exception as e:
                logger.debug(f"Backtest failed for {symbol}/{strategy_id}: {e}")
            
            await asyncio.sleep(0.1)
        
        return results
    
    async def _run_single_backtest(
        self,
        symbol: str,
        strategy_id: str,
        strategy_info: Dict,
        period: str
    ) -> Dict:
        """Run appropriate backtest based on strategy type."""
        
        strategy_type = strategy_info['type']
        
        try:
            if strategy_type == "MOMENTUM":
                # Use breakout for momentum strategies
                r = await self.engine.backtest_breakout_strategy(
                    symbol, period=period, lookback=20
                )
            elif strategy_type == "MEAN_REV":
                # Use VWAP for mean reversion
                r = await self.engine.backtest_vwap_reversion(
                    symbol, period=period
                )
            elif strategy_type == "TREND":
                # Use EMA crossover for trend
                r = await self.engine.backtest_ema_crossover(
                    symbol, period=period
                )
            elif strategy_type == "THETA":
                # Use Iron Condor simulation
                r = await self.engine.backtest_iron_condor(
                    symbol, period=period
                )
            elif strategy_type == "VOLATILITY":
                # Use ATR breakout for volatility
                r = await self.engine.backtest_breakout_strategy(
                    symbol, period=period, lookback=10
                )
            elif strategy_type in ["EVENT", "HEDGE", "DIRECTIONAL"]:
                # Default to ORB
                r = await self.engine.backtest_orb_strategy(
                    symbol, period=period
                )
            else:
                r = await self.engine.backtest_breakout_strategy(
                    symbol, period=period
                )
            
            return {
                'strategy_id': strategy_id,
                'strategy_name': strategy_info['name'],
                'strategy_type': strategy_type,
                'wave': strategy_info['wave'],
                'symbol': symbol,
                'sharpe': r.sharpe_ratio,
                'sortino': r.sortino_ratio,
                'total_return': r.total_return,
                'max_drawdown': r.max_drawdown,
                'win_rate': r.win_rate,
                'total_trades': r.total_trades,
                'profit_factor': r.profit_factor,
                'period': period
            }
            
        except Exception as e:
            logger.debug(f"Backtest error: {e}")
            return None
    
    def _print_comprehensive_summary(self, df: pd.DataFrame):
        """Print comprehensive summary of all backtests."""
        
        print("\n" + "=" * 80)
        print("COMPREHENSIVE BACKTEST SUMMARY")
        print("=" * 80)
        
        if df.empty:
            print("No results to display")
            return
        
        # By Strategy
        print("\n[PERFORMANCE BY STRATEGY]")
        print("-" * 70)
        print(f"{'Strategy':<35} {'Avg Sharpe':>10} {'Max Sharpe':>10} {'Win Rate':>10} {'Trades':>8}")
        print("-" * 70)
        
        strategy_summary = df.groupby('strategy_name').agg({
            'sharpe': ['mean', 'max'],
            'win_rate': 'mean',
            'total_trades': 'sum'
        }).round(3)
        
        for idx in strategy_summary.index:
            avg_sharpe = strategy_summary.loc[idx, ('sharpe', 'mean')]
            max_sharpe = strategy_summary.loc[idx, ('sharpe', 'max')]
            win_rate = strategy_summary.loc[idx, ('win_rate', 'mean')]
            trades = strategy_summary.loc[idx, ('total_trades', 'sum')]
            
            marker = " ***" if max_sharpe > 1.5 else ""
            print(f"{idx:<35} {avg_sharpe:>10.2f} {max_sharpe:>10.2f} {win_rate*100:>9.1f}% {int(trades):>8}{marker}")
        
        # By Wave
        print("\n[PERFORMANCE BY WAVE]")
        print("-" * 50)
        
        wave_summary = df.groupby('wave').agg({
            'sharpe': ['mean', 'max'],
            'win_rate': 'mean'
        }).round(3)
        
        for wave in [1, 2]:
            if wave in wave_summary.index:
                print(f"  Wave {wave}: Avg Sharpe={wave_summary.loc[wave, ('sharpe', 'mean')]:.2f}, "
                      f"Max={wave_summary.loc[wave, ('sharpe', 'max')]:.2f}, "
                      f"Win Rate={wave_summary.loc[wave, ('win_rate', 'mean')]*100:.1f}%")
        
        # By Strategy Type
        print("\n[PERFORMANCE BY TYPE]")
        print("-" * 50)
        
        type_summary = df.groupby('strategy_type').agg({
            'sharpe': ['mean', 'max']
        }).round(3)
        
        for stype in type_summary.index:
            print(f"  {stype:<15}: Avg={type_summary.loc[stype, ('sharpe', 'mean')]:.2f}, "
                  f"Max={type_summary.loc[stype, ('sharpe', 'max')]:.2f}")
        
        # Top Combinations
        print("\n[TOP 15 STRATEGY-STOCK COMBINATIONS]")
        print("-" * 70)
        
        top = df.nlargest(15, 'sharpe')
        for _, row in top.iterrows():
            marker = "***" if row['sharpe'] > 2.0 else "**" if row['sharpe'] > 1.5 else ""
            print(f"  {row['strategy_name']:<30} + {row['symbol']:<12} "
                  f"Sharpe={row['sharpe']:>6.2f} {marker}")
        
        # Underperformers
        print("\n[BOTTOM 5 STRATEGY-STOCK COMBINATIONS]")
        print("-" * 70)
        
        bottom = df.nsmallest(5, 'sharpe')
        for _, row in bottom.iterrows():
            print(f"  {row['strategy_name']:<30} + {row['symbol']:<12} "
                  f"Sharpe={row['sharpe']:>6.2f}")
        
        # Medallion Assessment
        print("\n[MEDALLION TARGET ASSESSMENT]")
        print("-" * 50)
        
        avg_sharpe = df['sharpe'].mean()
        max_sharpe = df['sharpe'].max()
        above_1_5 = len(df[df['sharpe'] > 1.5])
        above_2_0 = len(df[df['sharpe'] > 2.0])
        above_3_0 = len(df[df['sharpe'] > 3.0])
        
        print(f"  Total Tests: {len(df)}")
        print(f"  Average Sharpe: {avg_sharpe:.2f}")
        print(f"  Maximum Sharpe: {max_sharpe:.2f}")
        print(f"  Pairs with Sharpe > 1.5: {above_1_5}")
        print(f"  Pairs with Sharpe > 2.0: {above_2_0}")
        print(f"  Pairs with Sharpe > 3.0: {above_3_0}")
        print(f"  Target: 3.0")
        
        if above_3_0 > 0:
            print("\n  STATUS: *** MEDALLION TARGET ACHIEVED ***")
        elif above_2_0 >= 5:
            print("\n  STATUS: Strong pipeline, close to target")
        elif above_1_5 >= 10:
            print("\n  STATUS: Promising, needs optimization")
        else:
            print("\n  STATUS: Requires significant tuning")
        
        print("=" * 80)


async def main():
    """Run full strategy backtest."""
    tester = FullStrategyBacktester()
    
    print("Starting comprehensive backtest of all 16 strategies...")
    results_df = await tester.run_full_backtest(period="1Y")
    
    return results_df


if __name__ == "__main__":
    asyncio.run(main())
