from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.core.config import settings
from src.database.postgres import db
from src.database.redis import cache
from src.database.firestore import get_firestore_client
from src.core.event_bus import EventBus
from src.core.agent_manager import AgentManager, is_market_open
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
        firestore_client = get_firestore_client()
        if firestore_client.is_connected:
            logger.info("✅ Firestore Connected")
        else:
            logger.info("ℹ️  Firestore disabled (using PostgreSQL for audit logs)")
    except Exception as e:
        logger.warning(f"⚠️ Firestore init failed (non-critical): {e}")
    
    # 2. Initialize Agents
    await agent_manager.initialize_agents()
    await agent_manager.start_all()
    
    # 3. Start Scheduler — runs every 3 minutes, market-hours gate is inside run_cycle
    scheduler.add_job(orchestration_loop, 'interval', minutes=3, id='heartbeat')
    scheduler.start()
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    scheduler.shutdown(wait=False)
    await agent_manager.stop_all()
    await db.disconnect()
    await cache.disconnect()

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
        "market_open": is_market_open(),
        "agents_running": agent_manager.is_running,
        "database": "connected" if db.pool else "disconnected",
        "redis": "connected" if cache.client else "disconnected"
    }

@app.post("/trigger-cycle")
async def trigger_cycle():
    """Manually trigger a cycle (bypasses market-hours gate for testing)."""
    await agent_manager.run_cycle()
    return {"status": "Cycle Triggered"}

@app.get("/positions")
async def get_positions():
    """Live broker positions from DhanHQ."""
    from src.services.dhan_client import get_dhan_client
    dhan = get_dhan_client()
    positions = await dhan.get_positions()
    return {"positions": positions, "count": len(positions)}

@app.get("/trades")
async def get_trades():
    """Today's filled trades from DhanHQ."""
    from src.services.dhan_client import get_dhan_client
    dhan = get_dhan_client()
    trades = await dhan.get_trades()
    return {"trades": trades, "count": len(trades)}

@app.get("/pnl")
async def get_pnl():
    """Today's PnL summary from the daily_pnl table."""
    try:
        from datetime import date
        if db.pool is None:
            return {"error": "database not connected"}
        today = date.today()
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM daily_pnl WHERE trade_date = $1", today
            )
        if row:
            return dict(row)
        return {"trade_date": str(today), "realized_pnl": 0, "unrealized_pnl": 0}
    except Exception as e:
        return {"error": str(e)}

@app.get("/market-status")
async def market_status():
    """NSE market open/closed status."""
    from datetime import datetime
    from src.core.agent_manager import NSE_MARKET_OPEN, NSE_MARKET_CLOSE, is_market_day
    now = datetime.now()
    return {
        "market_open": is_market_open(now),
        "is_trading_day": is_market_day(now.date()),
        "server_time": now.isoformat(),
        "trading_start": str(NSE_MARKET_OPEN),
        "trading_end": str(NSE_MARKET_CLOSE),
    }

# ============================================================================
# Options Module Endpoints
# ============================================================================

@app.get("/options/positions")
async def options_positions():
    """All open options multi-leg positions with aggregated Greeks & P&L."""
    from src.services.options_position_manager import options_position_manager
    summary = options_position_manager.portfolio_summary()
    return summary

@app.get("/options/chain/{symbol}")
async def options_chain(symbol: str, num_strikes: int = 10, greeks: bool = True):
    """Live option chain with Greeks for a symbol."""
    from src.services.option_chain import option_chain_service
    chain = await option_chain_service.get_chain(
        symbol, num_strikes=num_strikes, enrich_greeks=greeks
    )
    return {
        "symbol": chain.symbol,
        "spot_price": chain.spot_price,
        "expiry_dates": chain.expiry_dates,
        "atm_strike": chain.atm_strike,
        "items_count": len(chain.items),
        "items": [item.dict() for item in chain.items[:50]],  # cap response size
    }

@app.get("/options/greeks/{position_id}")
async def options_greeks(position_id: str):
    """Greeks snapshot for a specific options position."""
    from src.services.options_position_manager import options_position_manager
    from src.services.greeks import greeks_engine
    pos = options_position_manager.get_position(position_id)
    if not pos:
        return {"error": f"Position {position_id} not found"}
    portfolio_g = greeks_engine.portfolio_greeks(pos.legs)
    return {
        "position_id": position_id,
        "greeks": portfolio_g.dict() if portfolio_g else {},
        "legs": len(pos.legs),
        "status": pos.status.value if hasattr(pos.status, "value") else str(pos.status),
    }

@app.post("/options/adjust/{position_id}")
async def options_adjust(position_id: str, adjustment_type: str = "SURRENDER", reason: str = "manual"):
    """Manually trigger an adjustment on an open options position."""
    from src.services.adjustment_engine import adjustment_engine
    from src.models.options import AdjustmentRequest, AdjustmentType
    try:
        adj_type = AdjustmentType(adjustment_type)
    except ValueError:
        return {"error": f"Invalid adjustment_type: {adjustment_type}"}
    req = AdjustmentRequest(
        position_id=position_id,
        adjustment_type=adj_type,
        reason=reason,
    )
    ok = await adjustment_engine.process(req)
    return {"position_id": position_id, "adjustment": adjustment_type, "success": ok}

@app.get("/options/validate")
async def options_validate_sebi():
    """Health check for SEBI options validator."""
    from src.middleware.sebi_options import sebi_validator
    cfg = sebi_validator.config
    return {
        "validator": "SEBIOptionsValidator",
        "enabled": settings.OPTIONS_ENABLED,
        "max_lots_per_ul": cfg.max_lots_per_underlying,
        "max_open_structures": cfg.max_open_structures,
        "margin_buffer_pct": cfg.margin_buffer_pct,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
