"""Quick test of NSE Data Service"""
from nselib import capital_market, derivatives
from datetime import datetime, timedelta

print("Testing nselib connection...")

# Test 1: Get index data for NIFTY 50
try:
    end_date = datetime.now().strftime("%d-%m-%Y")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%d-%m-%Y")
    
    data = capital_market.index_data(
        index="NIFTY 50",
        from_date=start_date,
        to_date=end_date
    )
    print(f"✅ NIFTY 50 Historical: {len(data)} days of data")
    if not data.empty:
        print(f"   Latest Close: {data.iloc[-1]['CLOSE'] if 'CLOSE' in data.columns else data.iloc[-1]}")
except Exception as e:
    print(f"❌ Index data failed: {e}")

# Test 2: Get stock price data
try:
    data = capital_market.price_volume_and_deliverable_position_data(
        symbol="RELIANCE",
        from_date=start_date,
        to_date=end_date
    )
    print(f"✅ RELIANCE Stock Data: {len(data)} days")
    if not data.empty:
        print(f"   Columns: {list(data.columns)}")
except Exception as e:
    print(f"❌ Stock data failed: {e}")

# Test 3: Get option chain
try:
    chain = derivatives.nse_live_option_chain("NIFTY")
    if chain is not None:
        spot = chain.get('records', {}).get('underlyingValue', 0)
        expiries = chain.get('records', {}).get('expiryDates', [])
        print(f"✅ NIFTY Option Chain: Spot = {spot}")
        print(f"   Expiries: {expiries[:3]}...")
    else:
        print("❌ Option chain returned None")
except Exception as e:
    print(f"❌ Option chain failed: {e}")

# Test 4: Get F&O lot sizes
try:
    lots = derivatives.fno_lot_size()
    if lots is not None and not lots.empty:
        print(f"✅ F&O Lot Sizes: {len(lots)} symbols")
    else:
        print("⚠️ F&O lot sizes empty")
except Exception as e:
    print(f"❌ F&O lot sizes failed: {e}")

print("\n✅ NSE Data Service tests complete!")
