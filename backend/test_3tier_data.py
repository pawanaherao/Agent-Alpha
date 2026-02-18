import asyncio
import logging
import pandas as pd
from src.services.nse_data import nse_data_service

# Configure logging to see the fallback attempts
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_3tier():
    print("\n=== Testing 3-Tier Data Feed ===\n")
    
    # 1. Test Index Data (NIFTY 50)
    print("1. Testing NIFTY 50 (3-Tier Check)...")
    df_nifty = await nse_data_service.get_index_ohlc("NIFTY 50", period="1d")
    if not df_nifty.empty:
        print(f"✅ NIFTY 50 Success | Latest Close: {df_nifty.iloc[-1]['close']}")
        print(f"Columns: {df_nifty.columns.tolist()}")
    else:
        print("❌ NIFTY 50 Failed All Tiers")

    # 2. Test Stock Data (RELIANCE)
    print("\n2. Testing RELIANCE (3-Tier Check)...")
    df_reliance = await nse_data_service.get_stock_ohlc("RELIANCE", period="1d")
    if not df_reliance.empty:
        print(f"✅ RELIANCE Success | Latest Close: {df_reliance.iloc[-1]['close']}")
    else:
        print("❌ RELIANCE Failed All Tiers")

    # 3. Test Health Check
    print("\n3. Testing Health Check...")
    health = await nse_data_service.health_check()
    print(f"Health Status: {health}")

if __name__ == "__main__":
    asyncio.run(test_3tier())
