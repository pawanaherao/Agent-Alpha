import asyncio
import sys
import os
import logging
import pandas as pd
import numpy as np

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from src.strategies.quant.momentum import CrossSectionalMomentumStrategy
from src.services.nse_data import nse_data_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase6Verifier")

# Mock the NSE Service to return synthetic data without network calls
async def mock_get_stock_ohlc(symbol, period="1y"):
    # Generate random walk
    np.random.seed(hash(symbol) % 2**32) 
    
    # Create different drift for different stocks to simulate winners/losers
    drift = 0.0
    if symbol == "WINNER_1": drift = 0.002 # High positive drift
    elif symbol == "LOSER_1": drift = -0.002 # High negative drift
    else: drift = np.random.normal(0, 0.0005)
    
    returns = np.random.normal(drift, 0.01, 252)
    price_path = 100 * np.cumprod(1 + returns)
    
    dates = pd.date_range(end=pd.Timestamp.now(), periods=252)
    df = pd.DataFrame({
        'date': dates,
        'open': price_path,
        'high': price_path * 1.01,
        'low': price_path * 0.99,
        'close': price_path,
        'volume': 100000
    })
    return df

def mock_get_nifty_100_stocks():
    # Return a mix of synthetic symbols
    return ["WINNER_1", "LOSER_1"] + [f"STOCK_{i}" for i in range(50)]

async def test_momentum_strategy():
    print(f"\n=== Phase 6: Momentum Strategy Verification ===\n")
    
    strategy = CrossSectionalMomentumStrategy()
    
    # MONKEY PATCHING nse_data_service for test isolation
    original_get_ohlc = nse_data_service.get_stock_ohlc
    original_get_universe = nse_data_service.get_nifty_100_stocks
    
    nse_data_service.get_stock_ohlc = mock_get_stock_ohlc
    nse_data_service.get_nifty_100_stocks = mock_get_nifty_100_stocks
    
    try:
        print("1. Generarting Portfolio Rebalance Signal...")
        portfolio = await strategy.generate_portfolio_rebalance()
        
        print(f"2. Portfolio Items: {len(portfolio)}")
        
        winner_found = False
        hedge_found = False
        
        for item in portfolio:
            print(f"   Position: {item['side']} {item['symbol']} ({item['weight']*100}%) | {item.get('reason','')}")
            
            if item['symbol'] == "WINNER_1" and item['side'] == "BUY":
                winner_found = True
            if item['symbol'] == "NIFTY-FUT" and item['side'] == "SELL":
                hedge_found = True
                
        if winner_found:
            print("   ✅ Correctly identified WINNER_1 (High Positive Drift)")
        else:
            print("   ❌ Failed to identify WINNER_1")
            
        if hedge_found:
            print("   ✅ Correctly added Market Beta Hedge (NIFTY-FUT)")
        else:
            print("   ❌ Failed to add Hedge")
            
    finally:
        # Restore service
        nse_data_service.get_stock_ohlc = original_get_ohlc
        nse_data_service.get_nifty_100_stocks = original_get_universe

if __name__ == "__main__":
    asyncio.run(test_momentum_strategy())
