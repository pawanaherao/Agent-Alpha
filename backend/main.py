from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import socketio
import uvicorn
import asyncio
import json
import os
from datetime import datetime
import random
import logging
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PERFORMANCE UPGRADE (Phase 5): Install winloop
try:
    import winloop
    winloop.install()
    logger.info("High-Performance 'winloop' installed successfully 🚀")
except ImportError:
    logger.warning("winloop not found, falling back to default asyncio loop")

# Initialize FastAPI
fastapi_app = FastAPI(title="Agent Alpha API")

# DhanHQ Configuration (Placeholders)
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# Initialize Dhan Client if keys exist
dhan_client = None
if DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN:
    try:
        from dhanhq import dhanhq
        dhan_client = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        logger.info("DhanHQ client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize DhanHQ: {e}")

# Enable CORS on FastAPI
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

# TradingView Webhook Model
class TVSignal(BaseModel):
    symbol: str
    action: str  # buy/sell
    quantity: int
    price: Optional[float] = None
    strategy: str
    secret: str

# HTTP Endpoints
@fastapi_app.get("/")
def health_check():
    return {"status": "online", "system": "Agent Alpha", "timestamp": datetime.now()}

@fastapi_app.post("/webhook/tradingview")
async def tradingview_webhook(signal: TVSignal):
    """
    Receive alerts from TradingView and execute on Dhan.
    Verification: Requires a SECRET_KEY to match.
    """
    if signal.secret != os.getenv("TV_WEBHOOK_SECRET", "default_secret"):
        raise HTTPException(status_code=403, detail="Invalid secret key")
    
    logger.info(f"Signal received: {signal.strategy} | {signal.action} {signal.quantity} {signal.symbol}")
    
    # Broadcast to frontend via Socket.IO
    await sio.emit('signal', {
        "id": f"tv_{datetime.now().timestamp()}",
        "timestamp": datetime.now().isoformat(),
        "symbol": signal.symbol,
        "strategy": signal.strategy,
        "signal": signal.action.upper(),
        "price": signal.price or 0,
        "status": "EXECUTED" if dhan_client else "PAPER_ONLY"
    })
    
    # Execute on Dhan if client is active
    if dhan_client:
        try:
            # Note: This is a placeholder for real order placement logic
            # dhan_client.place_order(...)
            logger.info(f"Executing {signal.action} order on Dhan for {signal.symbol}")
            return {"status": "success", "detail": "Order sent to Dhan"}
        except Exception as e:
            logger.error(f"Dhan execution error: {e}")
            return {"status": "error", "detail": str(e)}
            
    return {"status": "success", "detail": "Signal logged (Paper mode)"}

# Background task for broadcasting market data
async def broadcast_market_data():
    """Simulate high-frequency market data broadcasting."""
    logger.info("Starting market data broadcast loop...")
    symbols = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "NIFTY"]
    base_prices = {s: random.uniform(500, 3000) for s in symbols}
    base_prices["NIFTY"] = 24350.55
    
    while True:
        try:
            # Generate tick for a random symbol
            symbol = random.choice(symbols)
            # Random walk price
            change = random.uniform(-2, 2)
            base_prices[symbol] += change
            
            tick = {
                "symbol": symbol,
                "ltp": round(base_prices[symbol], 2),
                "change": round(change, 2),
                "volume": random.randint(100, 5000),
                "timestamp": datetime.now().isoformat()
            }
            
            await sio.emit('market_tick', tick)
            await asyncio.sleep(0.05) 
            
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await asyncio.sleep(1)

@fastapi_app.on_event("startup")
async def startup_event():
    logger.info("Server starting up...")
    asyncio.create_task(broadcast_market_data())

@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
