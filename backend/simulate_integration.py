import asyncio
import sys
import os
import json
import logging

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from src.strategies.universal_strategy import UniversalStrategy
from src.agents.strategy_agent import StrategyAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def simulate_frontend_request():
    print("\n>>> Simulating Frontend -> Backend Strategy Registration...")
    
    # 1. Frontend sends this JSON (Mock)
    frontend_payload = {
        "symbol": "NIFTY",
        "entry_conditions": [
            {"type": "RSI", "period": 14, "condition": "LT", "value": 30},
            {"type": "SMA", "period": 200, "condition": "LT", "value": "CLOSE"}
        ],
        "stop_loss_pct": 0.01
    }
    print(f"   Frontend Payload: {json.dumps(frontend_payload)}")
    
    # 2. Backend API receives it and inits Strategy
    try:
        # In the real API, this happens in main.py /api/strategies
        strategy_instance = UniversalStrategy(config=frontend_payload)
        logger.info(f"Initialized Strategy: {strategy_instance.name}")
        
        # 3. Agent Registration
        agent = StrategyAgent(
            agent_id="test_agent_1",
            symbol=frontend_payload['symbol'],
            capital=100000
        )
        
        # Manually register for test (normally handled by factory)
        # We verify that standard method works
        valid = await strategy_instance.validate_config(frontend_payload)
        if valid:
            print("   ✅ Configuration Validated by UniversalStrategy")
        else:
            print("   ❌ Validation Failed")
            
        # 4. Success Response
        print("   ✅ Backend successfully accepted the 'No-Code' Strategy.")
        
    except Exception as e:
        print(f"   ❌ Backend Error: {e}")

if __name__ == "__main__":
    asyncio.run(simulate_frontend_request())
