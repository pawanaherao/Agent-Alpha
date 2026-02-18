import asyncio
import numpy as np
import pandas as pd
import sys
import os
import logging

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from src.strategies.quant.pairs_finder import PairsFinder

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase6Verifier")

def generate_synthetic_data(n=252):
    """Generate synthetic cointegrated and non-cointegrated pairs."""
    np.random.seed(42)
    
    # 1. Random Walk X
    X = np.random.randn(n).cumsum() + 100
    
    # 2. Cointegrated Y = 0.5*X + Noise (Stationary Spread)
    noise = np.random.randn(n) * 0.5
    Y = 0.5 * X + noise + 10
    
    # 3. Random Walk Z (Uncorrelated)
    Z = np.random.randn(n).cumsum() + 100
    
    df = pd.DataFrame({
        'STOCK_A': X,
        'STOCK_B': Y, # Should be paired with A
        'STOCK_C': Z  # Should not be paired
    })
    
    return df

async def test_pairs_finder():
    print(f"\n=== Phase 6: PairsFinder Verification ===\n")
    
    # Setup
    finder = PairsFinder(symbols=['STOCK_A', 'STOCK_B', 'STOCK_C'])
    
    # Inject synthetic data directly
    finder.df_prices = generate_synthetic_data()
    print("1. Generated Synthetic Data:")
    print(f"   Shape: {finder.df_prices.shape}")
    print(f"   Correlation (A, B): {finder.df_prices['STOCK_A'].corr(finder.df_prices['STOCK_B']):.4f} (Expected > 0.9)")
    print(f"   Correlation (A, C): {finder.df_prices['STOCK_A'].corr(finder.df_prices['STOCK_C']):.4f} (Expected Low)")
    
    # Run Finder
    print("\n2. Running Cointegration Tests...")
    pairs = await finder.find_pairs(p_value_threshold=0.05, correlation_threshold=0.8)
    
    # Assertions
    found_ab = False
    found_ac = False
    
    for p in pairs:
        s1, s2 = sorted([p['stock1'], p['stock2']])
        if s1 == 'STOCK_A' and s2 == 'STOCK_B':
            found_ab = True
            print(f"   ✅ Found Pair: {p['stock1']}-{p['stock2']}")
            print(f"      P-Value: {p['p_value']:.6f} (Expected < 0.05)")
            print(f"      Hedge Ratio: {p['hedge_ratio']:.4f} (Expected ~0.5 or ~2.0)")
            print(f"      Z-Score: {p['z_score_current']:.2f}")
        
        if 'STOCK_C' in [p['stock1'], p['stock2']]:
            found_ac = True
            print(f"   ❌ False Positive: {p['stock1']}-{p['stock2']}")
            
    if found_ab and not found_ac:
        print("\n   ✅ SUCCESS: Logic verified on synthetic data.")
    else:
        print("\n   ❌ FAILURE: Logic check failed.")

if __name__ == "__main__":
    asyncio.run(test_pairs_finder())
