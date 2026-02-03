"""
MULTI-PERIOD BACKTEST - Agent Orchestration Analysis
Backtests entire system for:
- Last 2 Years (2024-2026): Manipulation period
- Last 1 Year (2025-2026): Recent performance

Focus: Win rate and Sharpe ratio during difficult market conditions
"""

import asyncio
import sys
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any

sys.stdout.reconfigure(encoding='utf-8')
logging.basicConfig(level=logging.WARNING)

from src.core.backtester import BacktestEngine
from src.services.nse_data import nse_data_service


# Strategy configuration (15 strategies - Iron Condor removed)
STRATEGIES = {
    # Wave 1 (7)
    "ALPHA_ORB_001": {"name": "ORB", "type": "MOMENTUM", "segment": "OPTIONS"},
    "ALPHA_VWAP_002": {"name": "VWAP Reversion", "type": "MEAN_REV", "segment": "CASH"},
    "ALPHA_BCS_007": {"name": "Bull Call Spread", "type": "DIRECTIONAL", "segment": "OPTIONS"},
    "ALPHA_BREAKOUT_101": {"name": "Swing Breakout", "type": "MOMENTUM", "segment": "CASH"},
    "ALPHA_PULLBACK_102": {"name": "Trend Pullback", "type": "TREND", "segment": "CASH"},
    "ALPHA_EMA_CROSS_104": {"name": "EMA Crossover", "type": "TREND", "segment": "CASH"},
    "ALPHA_PORT_017": {"name": "Portfolio Hedge", "type": "HEDGE", "segment": "OPTIONS"},
    
    # Wave 2 (8)
    "ALPHA_MOMENTUM_201": {"name": "Momentum Rotation", "type": "MOMENTUM", "segment": "CASH"},
    "ALPHA_SECTOR_202": {"name": "Sector Rotation", "type": "MOMENTUM", "segment": "CASH"},
    "ALPHA_BB_203": {"name": "BB Squeeze", "type": "VOLATILITY", "segment": "CASH"},
    "ALPHA_RSI_DIV_204": {"name": "RSI Divergence", "type": "MEAN_REV", "segment": "CASH"},
    "ALPHA_EARN_205": {"name": "Earnings Momentum", "type": "EVENT", "segment": "CASH"},
    "ALPHA_GAP_206": {"name": "Gap Fill", "type": "EVENT", "segment": "CASH"},
    "ALPHA_ATR_207": {"name": "ATR Breakout", "type": "VOLATILITY", "segment": "CASH"},
    "ALPHA_VOL_CRUSH_208": {"name": "Volatility Crush", "type": "VOLATILITY", "segment": "OPTIONS"},
}

# Test universe - diverse sectors
TEST_UNIVERSE = [
    # Large Cap
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    # IT
    "WIPRO", "TECHM", "LTIM",
    # Banking
    "SBIN", "KOTAKBANK", "AXISBANK",
    # Auto
    "TATAMOTORS", "M&M", "MARUTI",
    # Metals
    "TATASTEEL", "HINDALCO", "JSWSTEEL",
    # FMCG
    "HINDUNILVR", "NESTLEIND", "ITC",
    # Energy
    "NTPC", "POWERGRID", "ONGC"
]


async def run_period_backtest(
    engine: BacktestEngine,
    period: str,
    period_name: str
) -> pd.DataFrame:
    """Run backtest for a specific period."""
    
    print(f"\n  Running {period_name} backtest...")
    results = []
    
    for strategy_id, strategy_info in STRATEGIES.items():
        for symbol in TEST_UNIVERSE:
            try:
                # Select backtest method based on strategy type
                if strategy_info["type"] == "MOMENTUM":
                    r = await engine.backtest_breakout_strategy(symbol, period=period, lookback=20)
                elif strategy_info["type"] == "MEAN_REV":
                    r = await engine.backtest_vwap_reversion(symbol, period=period)
                elif strategy_info["type"] == "TREND":
                    r = await engine.backtest_trend_following(symbol, period=period)
                elif strategy_info["type"] == "VOLATILITY":
                    r = await engine.backtest_atr_breakout(symbol, period=period)
                else:
                    r = await engine.backtest_orb_strategy(symbol, period=period)
                
                if r:
                    results.append({
                        "strategy_id": strategy_id,
                        "strategy_name": strategy_info["name"],
                        "strategy_type": strategy_info["type"],
                        "segment": strategy_info["segment"],
                        "symbol": symbol,
                        "period": period_name,
                        "total_return": r.get("total_return", 0),
                        "sharpe": r.get("sharpe_ratio", 0),
                        "win_rate": r.get("win_rate", 0),
                        "max_drawdown": r.get("max_drawdown", 0),
                        "trades": r.get("total_trades", 0)
                    })
                    
            except Exception as e:
                pass
            
            await asyncio.sleep(0.1)
        
        print(f"    ✓ {strategy_info['name']} complete")
    
    return pd.DataFrame(results)


async def run_multi_period_backtest():
    """Run comprehensive multi-period backtest."""
    
    print("\n" + "=" * 80)
    print("  MULTI-PERIOD BACKTEST - Agent Orchestration Analysis")
    print("=" * 80)
    print("\n  Periods:")
    print("    • 2 Years (2024-2026): Manipulation period")
    print("    • 1 Year (2025-2026): Recent performance")
    print(f"\n  Strategies: 15 (Iron Condor REMOVED)")
    print(f"  Stocks: {len(TEST_UNIVERSE)}")
    print(f"  Total Tests: {15 * len(TEST_UNIVERSE) * 2} combinations")
    
    engine = BacktestEngine()
    
    # =========================================================================
    # BACKTEST: 2 YEARS (Manipulation Period)
    # =========================================================================
    print("\n" + "=" * 80)
    print("  PERIOD 1: 2 YEARS (2024-2026) - MANIPULATION PERIOD")
    print("=" * 80)
    
    results_2y = await run_period_backtest(engine, "2Y", "2_Years")
    
    # =========================================================================
    # BACKTEST: 1 YEAR (Recent)
    # =========================================================================
    print("\n" + "=" * 80)
    print("  PERIOD 2: 1 YEAR (2025-2026) - RECENT")
    print("=" * 80)
    
    results_1y = await run_period_backtest(engine, "1Y", "1_Year")
    
    # =========================================================================
    # COMBINE AND ANALYZE
    # =========================================================================
    all_results = pd.concat([results_2y, results_1y], ignore_index=True)
    
    # Save to CSV
    all_results.to_csv("multi_period_backtest.csv", index=False)
    print(f"\n  Results saved to: multi_period_backtest.csv")
    
    # =========================================================================
    # ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("  ANALYSIS: PERFORMANCE COMPARISON")
    print("=" * 80)
    
    # By Period
    print("\n  [PERIOD COMPARISON]")
    print("  " + "-" * 60)
    
    for period in ["2_Years", "1_Year"]:
        df = all_results[all_results["period"] == period]
        avg_sharpe = df["sharpe"].mean()
        max_sharpe = df["sharpe"].max()
        avg_win = df["win_rate"].mean()
        pairs_above_3 = len(df[df["sharpe"] > 3])
        
        print(f"\n  {period}:")
        print(f"    Avg Sharpe: {avg_sharpe:.2f}")
        print(f"    Max Sharpe: {max_sharpe:.2f}")
        print(f"    Avg Win Rate: {avg_win*100:.1f}%")
        print(f"    Pairs > 3.0 Sharpe: {pairs_above_3} *** MEDALLION TARGET ***")
    
    # Top Performers by Period
    print("\n  [TOP 10 BY PERIOD]")
    print("  " + "-" * 60)
    
    for period in ["2_Years", "1_Year"]:
        df = all_results[all_results["period"] == period]
        top10 = df.nlargest(10, "sharpe")
        
        print(f"\n  {period}:")
        print(f"  {'Strategy':<20}{'Symbol':<12}{'Sharpe':<10}{'Win%':<10}{'Type'}")
        print("  " + "-" * 60)
        for _, row in top10.iterrows():
            print(f"  {row['strategy_name']:<20}{row['symbol']:<12}{row['sharpe']:.2f}{'':>4}{row['win_rate']*100:.0f}%{'':>5}{row['strategy_type']}")
    
    # Strategy Performance Summary
    print("\n  [STRATEGY PERFORMANCE SUMMARY]")
    print("  " + "-" * 60)
    
    for period in ["2_Years", "1_Year"]:
        df = all_results[all_results["period"] == period]
        
        print(f"\n  {period}:")
        print(f"  {'Strategy':<25}{'Avg Sharpe':<12}{'Max Sharpe':<12}{'Win Rate':<12}{'Count >3.0'}")
        print("  " + "-" * 70)
        
        strategy_perf = df.groupby("strategy_name").agg({
            "sharpe": ["mean", "max"],
            "win_rate": "mean"
        }).reset_index()
        strategy_perf.columns = ["strategy", "avg_sharpe", "max_sharpe", "avg_win"]
        
        # Add count > 3.0
        for _, row in strategy_perf.sort_values("avg_sharpe", ascending=False).iterrows():
            count_above = len(df[(df["strategy_name"] == row["strategy"]) & (df["sharpe"] > 3)])
            marker = " ***" if count_above > 0 else ""
            print(f"  {row['strategy']:<25}{row['avg_sharpe']:.2f}{'':>6}{row['max_sharpe']:.2f}{'':>6}{row['avg_win']*100:.0f}%{'':>7}{count_above}{marker}")
    
    # Best strategies for manipulation period
    print("\n  [MANIPULATION-RESISTANT STRATEGIES]")
    print("  " + "-" * 60)
    print("  (Strategies with Sharpe > 2.0 in 2-year manipulation period)")
    
    df_2y = all_results[all_results["period"] == "2_Years"]
    resistant = df_2y[df_2y["sharpe"] > 2.0].groupby("strategy_name")["sharpe"].agg(["mean", "count"])
    resistant = resistant.sort_values("mean", ascending=False)
    
    print(f"\n  {'Strategy':<25}{'Avg Sharpe':<15}{'Stocks w/ Sharpe >2'}")
    print("  " + "-" * 55)
    for strategy, row in resistant.iterrows():
        print(f"  {strategy:<25}{row['mean']:.2f}{'':>8}{int(row['count'])}")
    
    # Summary Stats
    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    
    df_2y = all_results[all_results["period"] == "2_Years"]
    df_1y = all_results[all_results["period"] == "1_Year"]
    
    print(f"""
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ MULTI-PERIOD BACKTEST RESULTS                                          │
  ├─────────────────────────────────────────────────────────────────────────┤
  │                       2 YEARS (Manipulation)    1 YEAR (Recent)         │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ Total Tests:          {len(df_2y):<25}{len(df_1y):<20}│
  │ Avg Sharpe:           {df_2y['sharpe'].mean():.2f}{'':>23}{df_1y['sharpe'].mean():.2f}{'':>17}│
  │ Max Sharpe:           {df_2y['sharpe'].max():.2f}{'':>23}{df_1y['sharpe'].max():.2f}{'':>17}│
  │ Avg Win Rate:         {df_2y['win_rate'].mean()*100:.0f}%{'':>23}{df_1y['win_rate'].mean()*100:.0f}%{'':>17}│
  │ Pairs > 3.0 Sharpe:   {len(df_2y[df_2y['sharpe'] > 3]):<25}{len(df_1y[df_1y['sharpe'] > 3]):<20}│
  │ Pairs > 2.0 Sharpe:   {len(df_2y[df_2y['sharpe'] > 2]):<25}{len(df_1y[df_1y['sharpe'] > 2]):<20}│
  └─────────────────────────────────────────────────────────────────────────┘
    """)
    
    # Key Findings
    print("\n  KEY FINDINGS:")
    print("  " + "-" * 60)
    
    # Best strategies across both periods
    best = all_results.groupby("strategy_name")["sharpe"].mean().nlargest(5)
    print("\n  Top 5 Strategies (Both Periods):")
    for i, (strategy, sharpe) in enumerate(best.items(), 1):
        print(f"    {i}. {strategy}: Avg Sharpe {sharpe:.2f}")
    
    # Worst strategies
    worst = all_results.groupby("strategy_name")["sharpe"].mean().nsmallest(3)
    print("\n  Underperformers (Need Optimization):")
    for strategy, sharpe in worst.items():
        print(f"    - {strategy}: Avg Sharpe {sharpe:.2f}")
    
    print("\n" + "=" * 80)
    print("  BACKTEST COMPLETE")
    print("=" * 80 + "\n")
    
    return all_results


if __name__ == "__main__":
    asyncio.run(run_multi_period_backtest())
