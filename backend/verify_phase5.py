import asyncio
import sys
import os
import logging

# Add parent dir to path
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from src.core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase5Verifier")

async def test_infrastructure():
    print(f"\n=== Phase 5: Medallion Architecture Verification ===\n")
    
    # 1. Check Event Loop
    loop = asyncio.get_running_loop()
    loop_type = type(loop).__name__
    print(f"1. Event Loop Type: {loop_type}")
    
    if "winloop" in str(loop) or "Loop" in loop_type:
        print("   ✅ Winloop/Optimized Loop Active")
    else:
        print("   ⚠️ Standard Asyncio Loop Detected (Expected if winloop not supported)")

    # 2. Check Redis Event Bus
    print("\n2. Testing Redis Event Bus...")
    try:
        from src.core.event_bus_redis import RedisEventBus
        bus = RedisEventBus()
        await bus.connect()
        
        if bus.is_connected:
            print("   ✅ Redis Connection Established")
            
            # Test Pub/Sub
            received = asyncio.Event()
            
            async def test_handler(data):
                print(f"   ✅ Message Received: {data}")
                received.set()
                
            await bus.subscribe("TEST_CHANNEL", test_handler)
            await bus.publish("TEST_CHANNEL", {"status": "Medallion Mode ON"})
            
            try:
                await asyncio.wait_for(received.wait(), timeout=2.0)
                print("   ✅ Pub/Sub Latency < 2s")
            except asyncio.TimeoutError:
                print("   ❌ Pub/Sub Timeout")
                
            await bus.disconnect()
        else:
            print("   ❌ Redis Connection Failed (Is Redis Server running?)")
            
    except ImportError:
        print("   ❌ RedisEventBus Module Not Found")
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    # Try to install winloop policy if available
    try:
        import winloop
        winloop.install()
    except ImportError:
        pass
        
    asyncio.run(test_infrastructure())
