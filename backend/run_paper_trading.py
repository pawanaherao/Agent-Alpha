"""
LOCAL PAPER TRADING SIMULATION
Run the top 5 strategy-stock pairs in simulated paper trading mode
Uses real NSE data but simulated trades (no actual orders)
"""

import asyncio
import sys
import logging
from datetime import datetime, time
from typing import Dict, List
import json

sys.stdout.reconfigure(encoding='utf-8')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from src.agents.scanner import ScannerAgent
from src.agents.regime import RegimeAgent
from src.agents.strategy import StrategyAgent
from src.agents.risk import RiskAgent
from src.services.nse_data import nse_data_service

# Top 5 from backtest
TOP_PAIRS = [
    {"strategy": "VWAP_Reversion", "symbol": "RELIANCE", "expected_sharpe": 36.39},
    {"strategy": "VWAP_Reversion", "symbol": "NTPC", "expected_sharpe": 20.13},
    {"strategy": "Momentum_Rotation", "symbol": "TATAMOTORS", "expected_sharpe": 4.85},
    {"strategy": "Sector_Rotation", "symbol": "TATASTEEL", "expected_sharpe": 3.69},
    {"strategy": "Swing_Breakout", "symbol": "TATAMOTORS", "expected_sharpe": 4.12},
]


class PaperTradingSimulator:
    """Paper trading simulator for local testing."""
    
    def __init__(self, capital: float = 1_000_000):
        self.capital = capital
        self.available_capital = capital
        self.positions = {}
        self.trades = []
        self.pnl = 0.0
        
        # Initialize agents
        self.regime_agent = None
        self.scanner_agent = None
        self.risk_agent = None
        
    async def initialize(self):
        """Initialize all agents."""
        logger.info("Initializing agents...")
        
        self.regime_agent = RegimeAgent("PaperRegime")
        await self.regime_agent.start()
        
        self.scanner_agent = ScannerAgent("PaperScanner")
        await self.scanner_agent.start()
        
        self.risk_agent = RiskAgent("PaperRisk")
        await self.risk_agent.start()
        
        logger.info("All agents initialized!")
    
    async def get_regime(self) -> str:
        """Get current market regime."""
        try:
            nifty_data = await nse_data_service.get_index_ohlc("NIFTY 50", period="3M")
            if nifty_data is not None and not nifty_data.empty:
                regime = await self.regime_agent.classify_regime(nifty_data)
                return regime
        except Exception as e:
            logger.warning(f"Regime error: {e}")
        return "SIDEWAYS"
    
    async def analyze_stock(self, symbol: str) -> Dict:
        """Analyze a stock for trading signals."""
        try:
            # Get stock data
            data = await nse_data_service.get_stock_ohlc(symbol, period="3M")
            if data is None or data.empty:
                return {"signal": None, "score": 0}
            
            # Get scanner score
            score, indicators = await self.scanner_agent._analyze_stock(symbol, {})
            
            return {
                "symbol": symbol,
                "score": score,
                "indicators": indicators,
                "price": float(data['close'].iloc[-1]),
                "signal": "BUY" if score > 70 else ("WATCH" if score > 50 else None)
            }
        except Exception as e:
            logger.error(f"Analysis error for {symbol}: {e}")
            return {"signal": None, "score": 0}
    
    def calculate_position_size(self, price: float, stop_loss: float) -> int:
        """Calculate position size using 2% risk rule."""
        risk_per_trade = self.available_capital * 0.02
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            return 0
        shares = int(risk_per_trade / stop_distance)
        max_position = self.available_capital * 0.10  # Max 10% per position
        shares = min(shares, int(max_position / price))
        return shares
    
    def simulate_trade(self, symbol: str, signal: str, price: float, stop_loss: float) -> Dict:
        """Simulate a paper trade."""
        shares = self.calculate_position_size(price, stop_loss)
        if shares == 0:
            return None
        
        trade_value = shares * price
        if trade_value > self.available_capital:
            shares = int(self.available_capital / price)
            trade_value = shares * price
        
        self.available_capital -= trade_value
        
        trade = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "signal": signal,
            "entry_price": price,
            "stop_loss": stop_loss,
            "shares": shares,
            "value": trade_value,
            "status": "OPEN"
        }
        
        self.positions[symbol] = trade
        self.trades.append(trade)
        
        return trade
    
    async def run_simulation(self, duration_minutes: int = 5):
        """Run paper trading simulation."""
        
        print("\n" + "=" * 70)
        print("  PAPER TRADING SIMULATION - LOCAL TEST")
        print("=" * 70)
        print(f"\n  Capital: Rs {self.capital:,.0f}")
        print(f"  Strategy Pairs: {len(TOP_PAIRS)}")
        print(f"  Duration: {duration_minutes} minutes")
        print("=" * 70)
        
        await self.initialize()
        
        # Get current regime
        regime = await self.get_regime()
        print(f"\n  Current Market Regime: {regime}")
        print(f"  VIX: {self.regime_agent.current_vix:.1f}")
        
        print("\n" + "-" * 70)
        print("  ANALYZING TOP STRATEGY-STOCK PAIRS")
        print("-" * 70)
        
        signals = []
        
        for pair in TOP_PAIRS:
            symbol = pair["symbol"]
            strategy = pair["strategy"]
            
            print(f"\n  Analyzing {symbol} for {strategy}...")
            
            analysis = await self.analyze_stock(symbol)
            
            if analysis.get("score", 0) > 0:
                print(f"    Price: Rs {analysis.get('price', 0):,.2f}")
                print(f"    Scanner Score: {analysis.get('score', 0):.1f}/100")
                print(f"    Signal: {analysis.get('signal', 'NONE')}")
                
                if analysis.get("signal") == "BUY":
                    signals.append({
                        "symbol": symbol,
                        "strategy": strategy,
                        "price": analysis["price"],
                        "score": analysis["score"],
                        "stop_loss": analysis["price"] * 0.97  # 3% stop
                    })
        
        # Simulate trades
        print("\n" + "-" * 70)
        print("  SIMULATED TRADES")
        print("-" * 70)
        
        if signals:
            for signal in signals:
                trade = self.simulate_trade(
                    signal["symbol"],
                    "BUY",
                    signal["price"],
                    signal["stop_loss"]
                )
                
                if trade:
                    print(f"\n  [PAPER TRADE] {trade['signal']} {trade['symbol']}")
                    print(f"    Entry: Rs {trade['entry_price']:,.2f}")
                    print(f"    Shares: {trade['shares']}")
                    print(f"    Value: Rs {trade['value']:,.2f}")
                    print(f"    Stop Loss: Rs {trade['stop_loss']:,.2f}")
        else:
            print("\n  No qualifying signals at this time.")
            print("  (Score > 70 required for BUY signal)")
        
        # Summary
        print("\n" + "=" * 70)
        print("  SIMULATION SUMMARY")
        print("=" * 70)
        
        print(f"\n  Starting Capital: Rs {self.capital:,.0f}")
        print(f"  Available Capital: Rs {self.available_capital:,.0f}")
        print(f"  Capital Deployed: Rs {self.capital - self.available_capital:,.0f}")
        print(f"  Open Positions: {len(self.positions)}")
        print(f"  Total Trades: {len(self.trades)}")
        
        if self.positions:
            print("\n  Open Positions:")
            for symbol, pos in self.positions.items():
                print(f"    {symbol}: {pos['shares']} shares @ Rs {pos['entry_price']:,.2f}")
        
        print("\n" + "=" * 70)
        print("  PAPER TRADING SIMULATION COMPLETE")
        print("=" * 70 + "\n")
        
        return {
            "regime": regime,
            "signals": signals,
            "trades": self.trades,
            "positions": self.positions
        }


async def main():
    """Main entry point."""
    simulator = PaperTradingSimulator(capital=1_000_000)
    results = await simulator.run_simulation(duration_minutes=1)
    
    # Save results
    with open("paper_trading_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "regime": results["regime"],
            "signals": len(results["signals"]),
            "trades": len(results["trades"])
        }, f, indent=2)
    
    print("Results saved to paper_trading_results.json")


if __name__ == "__main__":
    asyncio.run(main())
