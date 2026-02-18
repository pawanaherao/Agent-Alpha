# 🛠️ REMEDIATION GUIDE - FIXING LOCAL TESTING ISSUES

## Quick Reference: All Fixes Needed

---

## FIX #1: Create Backend Environment File

**File:** `backend/.env`

```bash
# ============================================================================
# BACKEND ENVIRONMENT VARIABLES
# ============================================================================

# Execution Mode
ENV=development
MODE=LOCAL

# Database Configuration
POSTGRES_USER=user
POSTGRES_PASSWORD=password_dev_local
POSTGRES_DB=agentic_alpha
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379

# GCP Configuration (for Firestore)
GCP_PROJECT=agentic-alpha-local
FIRESTORE_EMULATOR_HOST=localhost:8080

# DhanHQ Trading API (Optional - Paper Trading)
# Get these from: https://dhan.com/api
DHAN_CLIENT_ID=your_dhan_client_id_here
DHAN_ACCESS_TOKEN=your_dhan_access_token_here

# TradingView Webhook (Optional)
TV_WEBHOOK_SECRET=your_webhook_secret_key_here

# Python Settings
PYTHONUNBUFFERED=1
```

---

## FIX #2: Update Python Version in Docker

**File:** `backend/Dockerfile` - Replace Line 1

```dockerfile
# BEFORE:
FROM python:3.10-slim

# AFTER:
FROM python:3.12-slim
```

**Why:** Requirements specify Python 3.12 for numba and numpy compatibility

---

## FIX #3: Create Frontend Environment File

**File:** `frontend/.env.local`

```bash
# Backend API configuration
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000

# Development
NODE_ENV=development
```

---

## FIX #4: Add PostgreSQL Service to Docker Compose

**File:** `docker-compose.yml` - Add after version declaration and before services

```yaml
version: '3.8'

services:
  # PostgreSQL Database (NEW)
  postgres:
    image: postgres:15-alpine
    container_name: agent-alpha-db
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password_dev_local
      POSTGRES_DB: agentic_alpha
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backend/db:/docker-entrypoint-initdb.d
    networks:
      - agent-alpha-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d agentic_alpha"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis Cache (NEW)
  redis:
    image: redis:7-alpine
    container_name: agent-alpha-redis
    ports:
      - "6379:6379"
    networks:
      - agent-alpha-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Frontend Service (EXISTING - update as shown)
  frontend:
    build:
      context: ./frontend
    container_name: agent-alpha-frontend
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=development
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - agent-alpha-net

  # Backend Service (EXISTING - update as shown)
  backend:
    build:
      context: ./backend
    container_name: agent-alpha-backend
    ports:
      - "8000:8000"  # Changed from 5000 to 8000
    environment:
      - ENV=development
      - MODE=LOCAL
      - PYTHONUNBUFFERED=1
      - DATABASE_URL=postgresql://user:password_dev_local@postgres:5432/agentic_alpha
      - REDIS_HOST=redis
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./backend/data:/app/data
      - ./backend/logs:/app/logs
    networks:
      - agent-alpha-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  agent-alpha-net:
    driver: bridge

volumes:
  postgres_data:
```

---

## FIX #5: Create Database Schema Initialization Script

**File:** `backend/db/init.sql`

```sql
-- ============================================================================
-- AGENTIC ALPHA - DATABASE SCHEMA INITIALIZATION
-- ============================================================================

-- Create trades table
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    signal_type VARCHAR(20) NOT NULL,
    action VARCHAR(10),  -- BUY, SELL, HOLD
    quantity INT DEFAULT 1,
    price DECIMAL(10, 2),
    status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING, EXECUTED, CANCELLED, FAILED
    strategy VARCHAR(100),
    agent_name VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_symbol (symbol),
    INDEX idx_created_at (created_at)
);

-- Create execution logs table
CREATE TABLE IF NOT EXISTS execution_logs (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(50) NOT NULL,
    event_type VARCHAR(50),
    action TEXT,
    status VARCHAR(20),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_agent_name (agent_name),
    INDEX idx_created_at (created_at)
);

-- Create risk assessment table
CREATE TABLE IF NOT EXISTS risk_assessment (
    id SERIAL PRIMARY KEY,
    trade_id INT REFERENCES trades(id),
    risk_score DECIMAL(5, 2),
    max_loss DECIMAL(12, 2),
    portfolio_impact DECIMAL(5, 2),
    approved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create portfolio state table
CREATE TABLE IF NOT EXISTS portfolio_state (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50),
    quantity INT DEFAULT 0,
    avg_cost DECIMAL(12, 2),
    current_value DECIMAL(12, 2),
    unrealized_pnl DECIMAL(12, 2),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_symbol (symbol)
);

-- Create market data cache table
CREATE TABLE IF NOT EXISTS market_data_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10),  -- 1M, 5M, 15M, 1H, 1D
    open DECIMAL(12, 2),
    high DECIMAL(12, 2),
    low DECIMAL(12, 2),
    close DECIMAL(12, 2),
    volume BIGINT,
    timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timeframe, timestamp),
    INDEX idx_symbol_time (symbol, timestamp)
);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "user";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "user";
```

---

## FIX #6: Update Backend Main Port Configuration

**File:** `backend/main.py` - Update port in if __name__ == "__main__"

```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

---

## FIX #7: Fix Firestore Configuration for Local Development

**File:** `backend/src/database/firestore.py` - Update connect method

```python
import os
from google.cloud import firestore
from src.core.config import settings
import logging

logger = logging.getLogger(__name__)

class FirestoreClient:
    """
    Wrapper for Google Cloud Firestore.
    Used for real-time data and audit logs.
    Supports local emulator mode.
    """
    def __init__(self):
        self.client = None
        self.using_emulator = os.getenv("FIRESTORE_EMULATOR_HOST") is not None

    def connect(self):
        """Initialize Firestore client."""
        try:
            if self.using_emulator:
                logger.info("🔧 Using Firestore Emulator")
                # AsyncClient will respect FIRESTORE_EMULATOR_HOST env var
                self.client = firestore.AsyncClient(project=settings.GCP_PROJECT)
            else:
                logger.warning("⚠️ Firestore emulator not configured. Skipping Firestore.")
                self.client = None
            
            if self.client:
                logger.info("✅ Connected to Firestore")
        except Exception as e:
            logger.error(f"⚠️ Failed to connect to Firestore: {e}")
            # Don't raise - allow app to continue without Firestore in local mode

    async def get_document(self, collection: str, doc_id: str):
        """Get a document."""
        if not self.client:
            return None
        try:
            doc_ref = self.client.collection(collection).document(doc_id)
            doc = await doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error getting Firestore document: {e}")
            return None

    async def set_document(self, collection: str, doc_id: str, data: dict):
        """Set/Update a document."""
        if not self.client:
            return
        try:
            doc_ref = self.client.collection(collection).document(doc_id)
            await doc_ref.set(data)
        except Exception as e:
            logger.error(f"Error setting Firestore document: {e}")

    async def add_document(self, collection: str, data: dict):
        """Add a document with auto-generated ID."""
        if not self.client:
            return None
        try:
            doc_ref = await self.client.collection(collection).add(data)
            return doc_ref.id
        except Exception as e:
            logger.error(f"Error adding Firestore document: {e}")
            return None

db_firestore = FirestoreClient()
```

---

## FIX #8: Fix Redis Connection Error Handling

**File:** `backend/src/core/event_bus.py` - Update lines 46-52

```python
# Global Event Bus Instance Factory
# Phase 5: Medallion Architecture Upgrade
event_bus = None

try:
    from src.core.event_bus_redis import RedisEventBus
    event_bus = RedisEventBus()
    logger.info("Using Redis-backed Event Bus")
except ImportError:
    logger.warning("RedisEventBus not available, using in-memory Event Bus")
    event_bus = EventBus()
except Exception as e:
    logger.warning(f"Failed to initialize Redis Event Bus: {e}. Using in-memory Event Bus")
    event_bus = EventBus()

# Ensure event_bus is never None
if event_bus is None:
    event_bus = EventBus()
```

---

## FIX #9: Create .gitignore File

**File:** `.gitignore`

```bash
# Environment Variables
.env
.env.local
.env.*.local

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
venv/
env/
ENV/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Data & Logs
backend/data/
backend/logs/
backend/*.csv
backend/*.json
frontend/.next/

# Node
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Database
*.db
*.sqlite
postgres_data/

# Cache
.pytest_cache/
.mypy_cache/
.coverage

# OS
Thumbs.db
.DS_Store
```

---

## FIX #10: Fix DhanHQ Hardcoded Credentials

**File:** `backend/src/services/dhan_client.py`

```python
import os
import logging
from dhanhq import dhanhq

logger = logging.getLogger(__name__)

class DhanClientWrapper:
    """
    Wrapper for DhanHQ trading API.
    Loads credentials from environment variables.
    """
    def __init__(self):
        self.client = None
        self.client_id = os.getenv("DHAN_CLIENT_ID", "")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN", "")
        
        if self.client_id and self.access_token:
            try:
                self.client = dhanhq(self.client_id, self.access_token)
                logger.info("✅ DhanHQ client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize DhanHQ: {e}")
        else:
            logger.warning("⚠️ DhanHQ credentials not set. Paper trading mode only.")

    def is_connected(self):
        """Check if DhanHQ client is available."""
        return self.client is not None

    def place_order(self, symbol: str, quantity: int, price: float, side: str):
        """Place an order on DhanHQ."""
        if not self.client:
            logger.warning(f"Paper Trade Simulation: {side} {quantity} {symbol} @ {price}")
            return {"status": "paper_simulated", "symbol": symbol}
        
        try:
            # Implement actual order placement
            logger.info(f"Placing order: {side} {quantity} {symbol}")
            # response = self.client.place_order(...)
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return {"status": "error", "message": str(e)}

# Global instance
dhan_client = DhanClientWrapper()
```

---

## FIX #11: Create Local Development Docker Override

**File:** `docker-compose.override.yml`

```yaml
version: '3.8'

services:
  backend:
    volumes:
      - ./backend:/app
    environment:
      - ENV=development
      - PYTHONUNBUFFERED=1
      - DATABASE_URL=postgresql://user:password_dev_local@postgres:5432/agentic_alpha
    command: >
      bash -c "pip install -r requirements.txt && 
               uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

  frontend:
    volumes:
      - ./frontend:/app
      - /app/node_modules
    environment:
      - NODE_ENV=development
    command: npm run dev

  postgres:
    environment:
      - POSTGRES_PASSWORD=password_dev_local

  redis:
    # Redis doesn't need override
    command: redis-server --appendonly yes
```

---

## FIX #12: Update Backend Requirements for Windows

**File:** `backend/requirements.txt` - Add after ta-lib section

```bash
# Windows-specific optimizations
winloop>=0.1.7          # High-Performance Event Loop for Windows
pywin32>=306            # Windows compatibility

# Add after existing requirements:
# Note: TA-Lib installation
# 1. Download .whl from https://github.com/cgohlke/talib-build/releases
# 2. Get: TA_Lib-0.4.32-cp312-cp312-win_amd64.whl
# 3. Run: pip install TA_Lib-0.4.32-cp312-cp312-win_amd64.whl
```

---

## FIX #13: Create Startup Script for Local Testing

**File:** `backend/startup_local.py`

```python
#!/usr/bin/env python
"""
Local development startup script.
Handles setup and initialization for local testing.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def setup_local_environment():
    """Initialize local development environment."""
    logger.info("🚀 Starting Agentic Alpha Local Setup")
    
    # 1. Verify Python version
    import sys
    if sys.version_info < (3, 12):
        logger.error("❌ Python 3.12+ required")
        return False
    logger.info(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    
    # 2. Check environment variables
    required_vars = ['POSTGRES_USER', 'POSTGRES_HOST', 'REDIS_HOST']
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.warning(f"⚠️ Missing env vars: {', '.join(missing)}")
    
    # 3. Test database connection
    try:
        import asyncpg
        conn = await asyncpg.connect(
            user=os.getenv('POSTGRES_USER'),
            password=os.getenv('POSTGRES_PASSWORD'),
            database=os.getenv('POSTGRES_DB'),
            host=os.getenv('POSTGRES_HOST', 'localhost')
        )
        await conn.close()
        logger.info("✅ PostgreSQL connection successful")
    except Exception as e:
        logger.warning(f"⚠️ PostgreSQL connection failed: {e}")
        logger.info("   Ensure PostgreSQL is running or use Docker")
    
    # 4. Test Redis connection
    try:
        import redis.asyncio as redis
        r = redis.Redis(host=os.getenv('REDIS_HOST', 'localhost'))
        await r.ping()
        await r.aclose()
        logger.info("✅ Redis connection successful")
    except Exception as e:
        logger.warning(f"⚠️ Redis connection failed: {e}")
        logger.info("   Ensure Redis is running or use Docker")
    
    # 5. List available agents
    logger.info("\n📊 Available Agents:")
    from src.agents import sentiment, regime, scanner, strategy, risk, execution, portfolio
    agents = ['Sentiment', 'Regime', 'Scanner', 'Strategy', 'Risk', 'Execution', 'Portfolio']
    for agent in agents:
        logger.info(f"   ✅ {agent}Agent")
    
    logger.info("\n✅ Local environment ready!")
    return True

if __name__ == "__main__":
    success = asyncio.run(setup_local_environment())
    exit(0 if success else 1)
```

---

## QUICK START COMMAND SEQUENCE

```bash
# 1. Navigate to project
cd "c:\Users\pawan\Documents\code lab\Agent Alpha"

# 2. Create all .env and .gitignore files (from this guide)

# 3. For Docker approach:
docker-compose build
docker-compose up

# 4. For local Python development:
python -m venv venv
venv\Scripts\activate
pip install -r backend/requirements.txt
python backend/startup_local.py
python backend/main.py

# 5. Test API health
curl http://localhost:8000/health

# 6. Run tests
pytest backend/ -v
```

---

## VERIFICATION CHECKLIST

After applying fixes:

- [ ] `curl http://localhost:8000/health` returns `{"status": "healthy"}`
- [ ] `docker ps` shows postgres, redis, frontend, backend running
- [ ] `pytest backend/test_nse.py -v` passes
- [ ] Frontend loads at `http://localhost:3000`
- [ ] PostgreSQL tables created: `psql -U user -d agentic_alpha -c "\dt"`
- [ ] No import errors: `python -c "from src.main import app"`
- [ ] Logs show "✅ Database Connected"

---

**Last Updated:** February 18, 2026
