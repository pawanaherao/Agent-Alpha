"""Quick test of NSE Data Service (yfinance backend)"""
import asyncio
import sys
import os

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.services.nse_data import nse_data_service

async def main():
    print("Testing NSE Data Service (yfinance backend)...")
    
    # Test 1: Get index data for NIFTY 50
    try:
        print("\n1. Testing Index Data (NIFTY 50)...")
        df = await nse_data_service.get_index_ohlc("NIFTY 50", period="1M")
        print(f"✅ NIFTY 50 Historical: {len(df)} days of data")
        if not df.empty:
            latest = df.iloc[-1]
            print(f"   Latest: {latest['date']} | Close: {latest['close']}")
    except Exception as e:
        print(f"❌ Index data failed: {e}")

    # Test 2: Get stock price data
    try:
        print("\n2. Testing Stock Data (RELIANCE)...")
        df = await nse_data_service.get_stock_ohlc("RELIANCE", period="1M")
        print(f"✅ RELIANCE Stock Data: {len(df)} days")
        if not df.empty:
            latest = df.iloc[-1]
            print(f"   Latest: {latest['date']} | Close: {latest['close']}")
    except Exception as e:
        print(f"❌ Stock data failed: {e}")

    # Test 3: Get option chain
    try:
        print("\n3. Testing Option Chain (NIFTY)...")
        chain = await nse_data_service.get_option_chain("NIFTY")
        if chain:
            spot = chain.get('spot_price', 0)
            expiries = chain.get('expiry_dates', [])
            print(f"✅ NIFTY Option Chain: Spot = {spot}")
            print(f"   Expiries: {expiries[:3]}...")
        else:
            print("❌ Option chain returned empty")
    except Exception as e:
        print(f"❌ Option chain failed: {e}")

    # Test 4: Get India VIX
    try:
        print("\n4. Testing India VIX...")
        vix = await nse_data_service.get_india_vix()
        print(f"✅ India VIX: {vix}")
    except Exception as e:
         print(f"❌ India VIX failed: {e}")

    print("\n✅ NSE Data Service tests complete!")

if __name__ == "__main__":
    asyncio.run(main())
