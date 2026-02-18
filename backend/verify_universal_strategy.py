import asyncio
import pandas as pd
import numpy as np
import logging
import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from src.strategies.universal_strategy import UniversalStrategy

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_universal_strategy():
    print("\n>>> Testing UniversalStrategy (The Super-Algo)...")
    
    # 1. Create Synthetic Data (Trending Up with a Dip)
    dates = pd.date_range(start="2024-01-01", periods=100, freq="D")
    prices = np.linspace(100, 150, 100) # Uptrend
    # Add a dip at the end to trigger RSI < 30
    prices[-5:] = [148, 140, 130, 120, 115] 
    
    df = pd.DataFrame({
        "open": prices,
        "high": prices + 2,
        "low": prices - 2,
        "close": prices,
        "volume": 1000
    }, index=dates)
    
    # 2. Test Case A: RSI Oversold Strategy
    # "Buy if RSI(14) < 30"
    config_a = {
        "symbol": "TEST_A",
        "entry_conditions": [
            {"type": "RSI", "period": 14, "condition": "LT", "value": 30}
        ]
    }
    
    print("\n[Test A] Config: RSI(14) < 30")
    strat_a = UniversalStrategy(config_a)
    signal_a = await strat_a.generate_signal(df, "SIDEWAYS")
    
    if signal_a and signal_a.signal_type == "BUY":
        print("   ✅ Signal Generated! Integration working.")
        print(f"      Metadata: {signal_a.metadata}")
    else:
        print("   ❌ No Signal. Check RSI calculation.")
        # Debug RSI value
        import pandas_ta as ta
        rsi = ta.rsi(df['close'], length=14).iloc[-1]
        print(f"      Actual RSI: {rsi:.2f}")

    # 3. Test Case B: SMA Crossover Strategy
    # "Buy if SMA(20) > SMA(50)" (Trend Following)
    # We need to reshape data to be defined uptrend
    prices_b = np.linspace(100, 200, 100)
    df_b = pd.DataFrame({"close": prices_b}, index=dates)
    
    config_b = {
        "symbol": "TEST_B",
        "entry_conditions": [
            {"type": "SMA", "period": 20, "condition": "GT", "value": "CLOSE"} # Invalid logic for demo, lets do Price > SMA
        ]
    }
    # Let's try: Price > SMA_20
    config_c = {
        "symbol": "TEST_C",
        "entry_conditions": [
            {"type": "SMA", "period": 20, "condition": "LT", "value": "CLOSE"} # SMA < CLOSE i.e. CLOSE > SMA
        ]
    }
    
    print("\n[Test C] Config: Close > SMA(20)")
    strat_c = UniversalStrategy(config_c)
    signal_c = await strat_c.generate_signal(df_b, "BULL")
    
    if signal_c:
        print("   ✅ Signal Generated! SMA Logic working.")
    else:
        print("   ❌ No Signal. Check SMA logic.")

if __name__ == "__main__":
    asyncio.run(test_universal_strategy())
