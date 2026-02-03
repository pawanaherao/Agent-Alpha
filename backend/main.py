from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import json
from datetime import datetime
import random

app = FastAPI(title="Agent Alpha API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "online", "system": "Agent Alpha", "timestamp": datetime.now()}

@app.get("/api/market-status")
def get_market_status():
    return {
        "market_status": "OPEN",
        "nifty_level": 24350.55,
        "vix": 15.2,
        "regime": "BULL_TREND"
    }

# WebSocket for real-time portfolio updates
@app.websocket("/ws/portfolio")
async def websocket_portfolio(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Simulate real-time P&L updates
            data = {
                "type": "PORTFOLIO_UPDATE",
                "timestamp": datetime.now().isoformat(),
                "total_pnl": round(random.uniform(-5000, 15000), 2),
                "active_positions": 3,
                "capital_used": 450000
            }
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(1)  # 1-second update interval
    except Exception as e:
        print(f"WebSocket error: {e}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
