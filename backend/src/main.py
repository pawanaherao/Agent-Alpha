from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.core.config import settings
from src.database.postgres import db
from src.database.redis import cache
from src.database.firestore import db_firestore
from src.core.event_bus import EventBus
from src.core.agent_manager import AgentManager
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Core Components
scheduler = AsyncIOScheduler()
event_bus = EventBus()
agent_manager = AgentManager(event_bus)

async def orchestration_loop():
    """
    The 3-Minute Heartbeat of Agentic Alpha.
    Triggers the Multi-Agent Workflow.
    """
    logger.info("💓 HEARTBEAT: Triggering orchestration cycle...")
    await agent_manager.run_cycle()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"🚀 Starting Agentic Alpha v4.0 in {settings.MODE} mode...")
    
    # 1. Initialize Databases
    try:
        await db.connect()
        logger.info("✅ Database Connected")
    except Exception as e:
        logger.warning(f"⚠️ Database Connection Failed (Mocking enabled for LOCAL): {e}")
        
    try:
        await cache.connect()
        logger.info("✅ Redis Connected")
    except Exception as e:
        logger.warning(f"⚠️ Redis Connection Failed (Mocking enabled for LOCAL): {e}")

    try:
        db_firestore.connect()
        logger.info("✅ Firestore Connected")
    except Exception as e:
        logger.warning(f"⚠️ Firestore Connection Failed (Mocking enabled): {e}")
    
    # 2. Initialize Agents
    await agent_manager.initialize_agents()
    await agent_manager.start_all()
    
    # 3. Start Scheduler
    scheduler.add_job(orchestration_loop, 'interval', minutes=3)
    scheduler.start()
    
    # 4. Run one immediate cycle for check (optional, good for debugging)
    # await orchestration_loop() 
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    await agent_manager.stop_all()
    await db.disconnect()
    await cache.disconnect()
    scheduler.shutdown()

app = FastAPI(
    title="Agentic Alpha 2026",
    version="4.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mode": settings.MODE,
        "agents_running": agent_manager.is_running,
        "database": "connected" if db.pool else "disconnected",
        "redis": "connected" if cache.client else "disconnected"
    }

@app.post("/trigger-cycle")
async def trigger_cycle():
    """Manually trigger a cycle (for testing)"""
    await orchestration_loop()
    return {"status": "Cycle Triggered"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
