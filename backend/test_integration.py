"""
Integration test for NSE Data + Regime Agent
Tests the complete data flow with real NSE data
"""
import asyncio
import sys
sys.path.insert(0, '.')

async def test_integration():
    print("=" * 60)
    print("🧪 AGENTIC ALPHA v5.0 - Integration Test")
    print("=" * 60)
    
    # Test 1: NSE Data Service
    print("\n📊 Test 1: NSE Data Service")
    print("-" * 40)
    
    from src.services.nse_data import nse_data_service
    
    # Health check
    health = await nse_data_service.health_check()
    print(f"Health Status: {health['status']}")
    if health['status'] == 'healthy':
        print(f"  NIFTY Close: {health.get('nifty_close', 'N/A')}")
        print(f"  Data Date: {health.get('data_date', 'N/A')}")
        print(f"  Market Open: {health.get('market_open', 'N/A')}")
    else:
        print(f"  Error: {health.get('error', 'Unknown')}")
    
    # Test 2: Index Data
    print("\n📈 Test 2: NIFTY 50 Historical Data")
    print("-" * 40)
    
    df = await nse_data_service.get_index_ohlc("NIFTY 50", period="1M")
    if not df.empty:
        print(f"  Rows fetched: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        print(f"  Latest Close: {df.iloc[-1].get('close', 'N/A')}")
    else:
        print("  ❌ No data received")
    
    # Test 3: Stock Data
    print("\n🏢 Test 3: RELIANCE Stock Data")
    print("-" * 40)
    
    stock_df = await nse_data_service.get_stock_ohlc("RELIANCE", period="1M")
    if not stock_df.empty:
        print(f"  Rows fetched: {len(stock_df)}")
        print(f"  Latest Close: {stock_df.iloc[-1].get('close', 'N/A')}")
    else:
        print("  ❌ No data received")
    
    # Test 4: Regime Agent
    print("\n🎯 Test 4: Regime Agent with Real Data")
    print("-" * 40)
    
    from src.agents.regime import RegimeAgent
    
    regime_agent = RegimeAgent()
    regime = await regime_agent.analyze_with_real_data("NIFTY 50")
    
    print(f"  Current Regime: {regime}")
    print(f"  VIX Level: {regime_agent.current_vix:.2f}")
    
    # Get strategy weights
    weights = regime_agent.get_regime_strategy_weights()
    print(f"  Strategy Weights for {regime}:")
    for strategy_type, weight in weights.items():
        print(f"    - {strategy_type}: {weight*100:.0f}%")
    
    # Test 5: Universe
    print("\n🌐 Test 5: Trading Universe")
    print("-" * 40)
    
    nifty100 = nse_data_service.get_nifty_100_stocks()
    fno = nse_data_service.get_fno_stocks()
    
    print(f"  NIFTY 100 Stocks: {len(nifty100)}")
    print(f"  F&O Eligible: {len(fno)}")
    print(f"  Sample: {nifty100[:5]}...")
    
    print("\n" + "=" * 60)
    print("✅ Integration Test Complete!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_integration())
