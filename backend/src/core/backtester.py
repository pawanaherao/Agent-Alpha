"""
Agentic Alpha v5.0 - Backtesting Framework
Uses vectorbt for high-performance backtesting

Supports:
- Equity strategies (Cash)
- Options strategies (simplified P&L)
- Multi-strategy portfolio simulation
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import logging
import asyncio

try:
    import vectorbt as vbt
    VECTORBT_AVAILABLE = True
except ImportError:
    VECTORBT_AVAILABLE = False
    print("WARNING: vectorbt not available. Install with: pip install vectorbt")

from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)


class BacktestResult:
    """Container for backtest results."""
    
    def __init__(
        self,
        strategy_id: str,
        symbol: str,
        total_return: float,
        sharpe_ratio: float,
        sortino_ratio: float,
        max_drawdown: float,
        win_rate: float,
        total_trades: int,
        profit_factor: float,
        avg_trade_pnl: float,
        start_date: str,
        end_date: str,
        equity_curve: Optional[pd.Series] = None
    ):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.total_return = total_return
        self.sharpe_ratio = sharpe_ratio
        self.sortino_ratio = sortino_ratio
        self.max_drawdown = max_drawdown
        self.win_rate = win_rate
        self.total_trades = total_trades
        self.profit_factor = profit_factor
        self.avg_trade_pnl = avg_trade_pnl
        self.start_date = start_date
        self.end_date = end_date
        self.equity_curve = equity_curve
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "total_return_pct": f"{self.total_return * 100:.2f}%",
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "max_drawdown_pct": f"{self.max_drawdown * 100:.2f}%",
            "win_rate_pct": f"{self.win_rate * 100:.1f}%",
            "total_trades": self.total_trades,
            "profit_factor": round(self.profit_factor, 2),
            "avg_trade_pnl_pct": f"{self.avg_trade_pnl * 100:.3f}%",
            "period": f"{self.start_date} to {self.end_date}"
        }
    
    def __repr__(self):
        return (
            f"BacktestResult({self.strategy_id}: "
            f"Return={self.total_return*100:.1f}%, "
            f"Sharpe={self.sharpe_ratio:.2f}, "
            f"MaxDD={self.max_drawdown*100:.1f}%)"
        )


class BacktestEngine:
    """
    High-performance backtesting engine using vectorbt.
    
    Supports:
    - Simple entry/exit signals
    - Stop-loss and take-profit
    - Position sizing
    - Multiple timeframes
    """
    
    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.nse_service = nse_data_service
        
        if not VECTORBT_AVAILABLE:
            logger.warning("vectorbt not available - using simplified backtesting")
    
    async def backtest_breakout_strategy(
        self,
        symbol: str = "NIFTY 50",
        lookback: int = 20,
        period: str = "1Y",
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.08
    ) -> BacktestResult:
        """
        Backtest 20-day breakout strategy.
        
        Entry: Price > 20-day high
        Exit: Stop-loss or take-profit
        """
        # Fetch data
        if "NIFTY" in symbol:
            df = await self.nse_service.get_index_ohlc(symbol, period=period)
        else:
            df = await self.nse_service.get_stock_ohlc(symbol, period=period)
        
        if df.empty or len(df) < lookback + 10:
            logger.error(f"Insufficient data for {symbol}")
            return self._empty_result("ALPHA_BREAKOUT_101", symbol)
        
        return self._run_breakout_backtest(
            df, "ALPHA_BREAKOUT_101", symbol, lookback, stop_loss_pct, take_profit_pct
        )
    
    async def backtest_ema_crossover(
        self,
        symbol: str = "NIFTY 50",
        fast_period: int = 9,
        slow_period: int = 21,
        period: str = "1Y"
    ) -> BacktestResult:
        """
        Backtest EMA crossover strategy.
        
        Entry: Fast EMA > Slow EMA (bullish cross)
        Exit: Fast EMA < Slow EMA (bearish cross)
        """
        # Fetch data
        if "NIFTY" in symbol:
            df = await self.nse_service.get_index_ohlc(symbol, period=period)
        else:
            df = await self.nse_service.get_stock_ohlc(symbol, period=period)
        
        if df.empty or len(df) < slow_period + 10:
            return self._empty_result("ALPHA_EMA_CROSS_104", symbol)
        
        return self._run_ema_crossover_backtest(
            df, "ALPHA_EMA_CROSS_104", symbol, fast_period, slow_period
        )
    
    async def backtest_orb_strategy(
        self,
        symbol: str = "NIFTY 50",
        period: str = "1Y"
    ) -> BacktestResult:
        """
        Backtest Opening Range Breakout (simplified daily version).
        
        Entry: Gap opens >0.5% (bullish) or <-0.5% (bearish)
        Exit: Same day close
        """
        if "NIFTY" in symbol:
            df = await self.nse_service.get_index_ohlc(symbol, period=period)
        else:
            df = await self.nse_service.get_stock_ohlc(symbol, period=period)
        
        if df.empty:
            return self._empty_result("ALPHA_ORB_001", symbol)
        
        return self._run_orb_backtest(df, "ALPHA_ORB_001", symbol)
    
    async def backtest_vwap_reversion(
        self,
        symbol: str = "NIFTY 50",
        deviation_pct: float = 1.5,
        period: str = "1Y"
    ) -> BacktestResult:
        """
        Backtest VWAP mean reversion (simplified daily version).
        
        Entry: Price deviates >deviation_pct from moving average
        Exit: Price reverts to average
        """
        if "NIFTY" in symbol:
            df = await self.nse_service.get_index_ohlc(symbol, period=period)
        else:
            df = await self.nse_service.get_stock_ohlc(symbol, period=period)
        
        if df.empty:
            return self._empty_result("ALPHA_VWAP_002", symbol)
        
        return self._run_mean_reversion_backtest(df, "ALPHA_VWAP_002", symbol, deviation_pct)
    
    async def backtest_iron_condor(
        self,
        symbol: str = "NIFTY 50",
        wing_width: int = 200,
        period: str = "1Y"
    ) -> BacktestResult:
        """
        Backtest Iron Condor (simplified - based on range prediction).
        
        Win if price stays within range.
        Loss if price breaks range.
        """
        if "NIFTY" in symbol:
            df = await self.nse_service.get_index_ohlc(symbol, period=period)
        else:
            df = await self.nse_service.get_stock_ohlc(symbol, period=period)
        
        if df.empty:
            return self._empty_result("ALPHA_IRON_011", symbol)
        
        return self._run_iron_condor_backtest(df, "ALPHA_IRON_011", symbol, wing_width)
    
    def _run_breakout_backtest(
        self,
        df: pd.DataFrame,
        strategy_id: str,
        symbol: str,
        lookback: int,
        sl_pct: float,
        tp_pct: float
    ) -> BacktestResult:
        """Execute breakout backtest logic."""
        
        # Ensure numeric close
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])
        
        if len(df) < lookback + 5:
            return self._empty_result(strategy_id, symbol)
        
        # Calculate signals
        df['high_20'] = df['high'].rolling(window=lookback).max().shift(1)
        df['signal'] = (df['close'] > df['high_20']).astype(int)
        
        # Calculate returns
        df['returns'] = df['close'].pct_change()
        df['strategy_returns'] = df['signal'].shift(1) * df['returns']
        
        # Apply simple SL/TP (approximate)
        df['strategy_returns'] = df['strategy_returns'].clip(lower=-sl_pct, upper=tp_pct)
        
        return self._calculate_metrics(df, strategy_id, symbol)
    
    def _run_ema_crossover_backtest(
        self,
        df: pd.DataFrame,
        strategy_id: str,
        symbol: str,
        fast: int,
        slow: int
    ) -> BacktestResult:
        """Execute EMA crossover backtest."""
        
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])
        
        if len(df) < slow + 5:
            return self._empty_result(strategy_id, symbol)
        
        # Calculate EMAs
        df['ema_fast'] = df['close'].ewm(span=fast, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=slow, adjust=False).mean()
        
        # Signal: 1 when fast > slow
        df['signal'] = (df['ema_fast'] > df['ema_slow']).astype(int)
        
        # Calculate returns
        df['returns'] = df['close'].pct_change()
        df['strategy_returns'] = df['signal'].shift(1) * df['returns']
        
        return self._calculate_metrics(df, strategy_id, symbol)
    
    def _run_orb_backtest(
        self,
        df: pd.DataFrame,
        strategy_id: str,
        symbol: str
    ) -> BacktestResult:
        """Execute ORB backtest (gap-based approximation)."""
        
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df = df.dropna(subset=['close', 'open'])
        
        # Gap calculation
        df['prev_close'] = df['close'].shift(1)
        df['gap_pct'] = (df['open'] - df['prev_close']) / df['prev_close']
        
        # Intraday return (open to close)
        df['intraday_return'] = (df['close'] - df['open']) / df['open']
        
        # Signal: Trade gaps > 0.5%
        df['long_signal'] = (df['gap_pct'] > 0.005).astype(int)
        df['short_signal'] = (df['gap_pct'] < -0.005).astype(int)
        
        # Strategy return: long if gap up, short if gap down
        df['strategy_returns'] = (
            df['long_signal'] * df['intraday_return'] + 
            df['short_signal'] * (-df['intraday_return'])
        )
        
        return self._calculate_metrics(df, strategy_id, symbol)
    
    def _run_mean_reversion_backtest(
        self,
        df: pd.DataFrame,
        strategy_id: str,
        symbol: str,
        deviation_pct: float
    ) -> BacktestResult:
        """Execute mean reversion backtest."""
        
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])
        
        # 20-day moving average as "VWAP proxy"
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['deviation'] = (df['close'] - df['ma20']) / df['ma20'] * 100
        
        # Buy when oversold, sell when overbought
        df['long_signal'] = (df['deviation'] < -deviation_pct).astype(int)
        df['short_signal'] = (df['deviation'] > deviation_pct).astype(int)
        
        df['returns'] = df['close'].pct_change()
        
        # Bet on reversion
        df['strategy_returns'] = (
            df['long_signal'].shift(1) * df['returns'] + 
            df['short_signal'].shift(1) * (-df['returns'])
        )
        
        return self._calculate_metrics(df, strategy_id, symbol)
    
    def _run_iron_condor_backtest(
        self,
        df: pd.DataFrame,
        strategy_id: str,
        symbol: str,
        wing_width: int
    ) -> BacktestResult:
        """Execute Iron Condor backtest (range-based)."""
        
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])
        
        # Weekly range prediction
        df['weekly_return'] = df['close'].pct_change(5)  # 5-day return
        
        # Win if weekly move < wing_width/spot (roughly 1%)
        threshold = wing_width / df['close'].mean()
        
        # Simplified: We win 70% of small moves, lose on big moves
        df['trade'] = 1  # Always trade
        df['win'] = (abs(df['weekly_return']) < threshold).astype(int)
        
        # Credit = 0.5% of spot, loss = 1% of spot (simplified)
        credit = 0.005
        loss = 0.01
        
        df['strategy_returns'] = df['win'] * credit + (1 - df['win']) * (-loss)
        
        return self._calculate_metrics(df, strategy_id, symbol)
    
    def _calculate_metrics(
        self,
        df: pd.DataFrame,
        strategy_id: str,
        symbol: str
    ) -> BacktestResult:
        """Calculate performance metrics from strategy returns."""
        
        returns = df['strategy_returns'].dropna()
        
        if len(returns) == 0:
            return self._empty_result(strategy_id, symbol)
        
        # Total return
        total_return = (1 + returns).prod() - 1
        
        # Sharpe Ratio (annualized, assuming 252 trading days)
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
        else:
            sharpe = 0.0
        
        # Sortino Ratio
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0 and downside_returns.std() > 0:
            sortino = (returns.mean() / downside_returns.std()) * np.sqrt(252)
        else:
            sortino = sharpe
        
        # Max Drawdown
        cumulative = (1 + returns).cumprod()
        rolling_max = cumulative.cummax()
        drawdown = (cumulative - rolling_max) / rolling_max
        max_drawdown = abs(drawdown.min())
        
        # Win Rate
        winning_trades = (returns > 0).sum()
        total_trades = (returns != 0).sum()
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Profit Factor
        gross_profit = returns[returns > 0].sum()
        gross_loss = abs(returns[returns < 0].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999
        
        # Average trade
        avg_trade = returns.mean()
        
        # Date range
        if 'date' in df.columns:
            start_date = str(df['date'].iloc[0])
            end_date = str(df['date'].iloc[-1])
        else:
            start_date = "Unknown"
            end_date = "Unknown"
        
        return BacktestResult(
            strategy_id=strategy_id,
            symbol=symbol,
            total_return=total_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            total_trades=int(total_trades),
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade,
            start_date=start_date,
            end_date=end_date,
            equity_curve=cumulative
        )
    
    def _empty_result(self, strategy_id: str, symbol: str) -> BacktestResult:
        """Return empty result for failed backtest."""
        return BacktestResult(
            strategy_id=strategy_id,
            symbol=symbol,
            total_return=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            total_trades=0,
            profit_factor=0.0,
            avg_trade_pnl=0.0,
            start_date="N/A",
            end_date="N/A"
        )


async def run_all_backtests(symbol: str = "NIFTY 50", period: str = "1Y") -> List[BacktestResult]:
    """
    Run backtests for all Wave 1 strategies.
    """
    engine = BacktestEngine()
    results = []
    
    print(f"\nRunning backtests on {symbol} for {period}...")
    print("=" * 60)
    
    # 1. Breakout Strategy
    print("Testing: ALPHA_BREAKOUT_101 (Swing Breakout)...")
    result = await engine.backtest_breakout_strategy(symbol, period=period)
    results.append(result)
    print(f"  -> Sharpe: {result.sharpe_ratio:.2f}, Return: {result.total_return*100:.1f}%")
    
    # 2. EMA Crossover
    print("Testing: ALPHA_EMA_CROSS_104 (EMA Crossover)...")
    result = await engine.backtest_ema_crossover(symbol, period=period)
    results.append(result)
    print(f"  -> Sharpe: {result.sharpe_ratio:.2f}, Return: {result.total_return*100:.1f}%")
    
    # 3. ORB Strategy
    print("Testing: ALPHA_ORB_001 (Opening Range Breakout)...")
    result = await engine.backtest_orb_strategy(symbol, period=period)
    results.append(result)
    print(f"  -> Sharpe: {result.sharpe_ratio:.2f}, Return: {result.total_return*100:.1f}%")
    
    # 4. VWAP Reversion
    print("Testing: ALPHA_VWAP_002 (VWAP Mean Reversion)...")
    result = await engine.backtest_vwap_reversion(symbol, period=period)
    results.append(result)
    print(f"  -> Sharpe: {result.sharpe_ratio:.2f}, Return: {result.total_return*100:.1f}%")
    
    # 5. Iron Condor
    print("Testing: ALPHA_IRON_011 (Iron Condor)...")
    result = await engine.backtest_iron_condor(symbol, period=period)
    results.append(result)
    print(f"  -> Sharpe: {result.sharpe_ratio:.2f}, Return: {result.total_return*100:.1f}%")
    
    print("=" * 60)
    print(f"Completed {len(results)} backtests.\n")
    
    return results


def print_backtest_summary(results: List[BacktestResult]):
    """Print formatted summary of backtest results."""
    
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS SUMMARY")
    print("=" * 80)
    print(f"{'Strategy ID':<25} {'Return':>10} {'Sharpe':>8} {'MaxDD':>10} {'WinRate':>10} {'Trades':>8}")
    print("-" * 80)
    
    for r in results:
        print(
            f"{r.strategy_id:<25} "
            f"{r.total_return*100:>9.1f}% "
            f"{r.sharpe_ratio:>8.2f} "
            f"{r.max_drawdown*100:>9.1f}% "
            f"{r.win_rate*100:>9.1f}% "
            f"{r.total_trades:>8d}"
        )
    
    print("-" * 80)
    
    # Summary stats
    avg_sharpe = np.mean([r.sharpe_ratio for r in results])
    avg_return = np.mean([r.total_return for r in results])
    
    print(f"{'AVERAGE':<25} {avg_return*100:>9.1f}% {avg_sharpe:>8.2f}")
    print("=" * 80)


# Main entry point
async def main():
    """Run all backtests and display results."""
    results = await run_all_backtests("NIFTY 50", "1Y")
    print_backtest_summary(results)
    return results


if __name__ == "__main__":
    asyncio.run(main())
