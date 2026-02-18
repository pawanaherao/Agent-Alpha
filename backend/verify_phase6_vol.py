import asyncio
import sys
import os
import logging
import numpy as np

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from src.strategies.quant.vol_surface import VolSurfaceBuilder

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase6Verifier")

async def test_vol_surface():
    print(f"\n=== Phase 6: VolSurface Verification ===\n")
    
    builder = VolSurfaceBuilder("NIFTY")
    
    # 1. Test Black-Scholes IV Calculation
    # Param: S=100, K=100, T=1, r=0.05, Call Price=10.4506 -> Sigma should be 0.20
    S = 100
    K = 100
    T = 1.0
    r = 0.05
    ref_price = 10.4506
    
    print("1. Testing IV Solver (Brent's Method)...")
    iv = builder.implied_volatility(ref_price, S, K, T, r, 'call')
    print(f"   Input Price: {ref_price}")
    print(f"   Calculated IV: {iv:.4f} (Expected: 0.2000)")
    
    if abs(iv - 0.20) < 0.001:
        print("   ✅ IV Calculation Accurate")
    else:
        print("   ❌ IV Calculation INCORRECT")

    # 2. Test Put-Call Parity IV
    # Put Price for same params: 5.5735
    put_price = 5.5735
    iv_put = builder.implied_volatility(put_price, S, K, T, r, 'put')
    print(f"   Put IV: {iv_put:.4f} (Expected: 0.2000)")
    
    if abs(iv_put - 0.20) < 0.001:
        print("   ✅ Put IV Accurate")
    else:
        print("   ❌ Put IV INCORRECT")

if __name__ == "__main__":
    asyncio.run(test_vol_surface())
