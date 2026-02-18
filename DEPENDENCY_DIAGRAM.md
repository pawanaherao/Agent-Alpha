# 🗺️ AUDIT DEPENDENCY GRAPH & CRITICAL PATH

## Critical Path to Working Local Environment

```
START
  │
  ├─→ [1] Create .env files ──────────┐
  │                                    │
  ├─→ [2] Python 3.12 in Dockerfile   │
  │                                    │
  ├─→ [3] Create init.sql ────────────┼─→ [4] Add DB service to docker-compose ──┐
  │                                    │                                           │
  ├─→ [5] Update port 5000→8000 ──────┼──────────────────────────────────────────┼─→ docker-compose build
  │                                    │                                           │
  └─→ [6] Fix Firestore, DhanHQ, Redis┴───────────────────────────────────────────┘
                                                                                    │
                                                                                    ↓
                                                                          docker-compose up
                                                                                    │
                                                                                    ↓
                                                                         ✅ LOCAL TESTING READY
```

---

## Issue Dependency Tree

```
No PostgreSQL Service
    └─ BLOCKS ──→ Cannot save trades
    └─ REQUIRES ──→ init.sql schemas

Missing .env
    └─ BLOCKS ──→ App won't start
    └─ BLOCKS ──→ Cannot connect DB/Redis

Python 3.10
    └─ BREAKS ──→ numba compilation

Wrong Ports
    └─ BREAKS ──→ Frontend-Backend connection

Hardcoded Credentials
    └─ SECURITY ──→ Risk of exposure
    └─ BLOCKS ──→ Can't switch environments

Firestore Misconfigured
    └─ BREAKS ──→ Real-time data fails
    └─ RECOVER ──→ Use fallback
```

---

## Component Status & Dependencies

```
┌─────────────────────────────────────────────────────────────────┐
│                     AGENTIC ALPHA SYSTEM                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Frontend (Next.js)                                              │
│  ├─ Status: ✅ 90% Ready                                         │
│  ├─ Needs: .env.local (DONE when → frontend/.env.local)         │
│  └─ Depends on: Backend API running on 8000                      │
│                                                                   │
│  Backend (FastAPI)                                               │
│  ├─ Status: ⚠️ 60% Ready                                         │
│  ├─ Needs: .env, Python 3.12, Port 8000 (DONE when → FIX)      │
│  ├─ Depends on: PostgreSQL, Redis                                │
│  └─ Agents: ✅ Ready                                             │
│                                                                   │
│  PostgreSQL (Data Layer)                                         │
│  ├─ Status: ❌ 20% Ready (not in docker-compose)                │
│  ├─ Needs: Service added, init.sql (DONE when → FIX)            │
│  ├─ Tables needed: trades, execution_logs, risk_assessment      │
│  └─ Critical: YES                                                │
│                                                                   │
│  Redis (Cache/EventBus)                                          │
│  ├─ Status: ❌ 30% Ready (not in docker-compose)                │
│  ├─ Needs: Service added (DONE when → FIX)                      │
│  ├─ Purpose: Event bus, caching                                  │
│  └─ Critical: YES (with fallback)                                │
│                                                                   │
│  Firestore (Audit Logs)                                          │
│  ├─ Status: ⚠️ 40% Ready (no emulator)                           │
│  ├─ Needs: GCP setup or emulator                                 │
│  ├─ Can skip: Yes, has fallback                                  │
│  └─ Critical: NO                                                 │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Services Startup Sequence

```
Step 1: docker-compose up               [0s]
         │
Step 2:  ├─ PostgreSQL starts           [2-3s]
         │  └─ Runs init.sql
         │     └─ Creates tables
         │
Step 3:  ├─ Redis starts                [1-2s]
         │
Step 4:  ├─ Backend starts              [5-10s]
         │  ├─ Waits for PostgreSQL health
         │  ├─ Connects to DB
         │  ├─ Connects to Redis
         │  └─ Agents initialize
         │
Step 5:  └─ Frontend starts             [10-15s]
            └─ Connects to backend

Total Startup Time: 15-20 seconds
Ready for Testing: After all 4 services show "healthy"
```

---

## Issue Impact Matrix

```
ISSUE              COMPONENT  SEVERITY  IMPACT    FIX TIME  EFFORT
──────────────────────────────────────────────────────────────────
Missing .env       ALL        🔴        BLOCKS    5 min     ⭐
Python 3.10        Backend    🔴        BREAKS    2 min     ⭐
No PostgreSQL      Backend    🔴        BREAKS    10 min    ⭐⭐
No Schema          Backend    🔴        BREAKS    5 min     ⭐⭐
Wrong Port         All        🔴        BREAKS    2 min     ⭐
Firestore Config   Backend    🟠        FAILS     5 min     ⭐⭐
DhanHQ Hardcoded   Backend    🟠        SECURITY  3 min     ⭐
Redis Error        Backend    🟠        CRASHES   3 min     ⭐
Missing .gitignore Security   🟡        RISK      5 min     ⭐
No Override        Frontend   🟡        NO-RELOAD 5 min     ⭐⭐
Scripts Broken     Automation 🟡        FAILS     5 min     ⭐⭐
No Validation      DevEx      🟢        CONFUSE   10 min    ⭐⭐
Test Setup         Testing    🟢        UNCLEAR   10 min    ⭐⭐

Legend: 🔴=Critical 🟠=High 🟡=Medium 🟢=Low | Effort: ⭐=Easy ⭐⭐=Medium
```

---

## Data Flow Diagram

```
Market Data Sources         Trading System          Frontend Dashboard
    │                           │                          │
    ├─ NSE Library              │                          │
    ├─ YFinance        ─────→ SentimentAgent              │
    ├─ DhanHQ                  RegimeAgent                │
    └─ Pandas-TA              ScannerAgent   ─────→ REST API ─────→ Web UI
                               StrategyAgent         (Port 8000)      (Port 3000)
                               RiskAgent
                               ExecutionAgent
                               PortfolioAgent
                                    │
                                    ↓
                            Data Persistence
                                    │
                   ┌─────────────────┼──────────────────┐
                   ↓                 ↓                   ↓
              PostgreSQL           Redis             Firestore
              (Trades DB)        (Cache/EventBus)  (Audit Logs)
              [CRITICAL]        [CRITICAL w/fallback] [OPTIONAL]
```

---

## Configuration Dependency Chain

```
Application Start
    │
    ├─ Load .env variables
    │   ├─ POSTGRES_HOST, POSTGRES_USER, etc.
    │   ├─ REDIS_HOST
    │   ├─ DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
    │   └─ GCP_PROJECT (optional)
    │
    ├─ Connect to PostgreSQL
    │   ├─ Requires: POSTGRES_* variables SET
    │   ├─ Requires: PostgreSQL service running
    │   ├─ Requires: Schemas initialized (init.sql)
    │   └─ Fallback: Mock DB for local
    │
    ├─ Connect to Redis
    │   ├─ Requires: REDIS_HOST SET
    │   ├─ Requires: Redis service running
    │   └─ Fallback: In-memory event bus
    │
    ├─ Connect to Firestore (optional)
    │   ├─ Requires: GCP_PROJECT SET
    │   ├─ Requires: FIRESTORE_EMULATOR_HOST OR GCP creds
    │   └─ Fallback: Skip real-time logs
    │
    ├─ Initialize Agents
    │   └─ All agents start
    │
    └─ Start API Server
        ├─ Listen on port 8000
        ├─ Expose health check
        └─ Ready for requests
```

---

## Module Load Order

```
main.py
    │
    ├─→ Load .env
    │
    ├─→ Import core components
    │   ├─ EventBus [DEPENDS ON Redis or in-memory]
    │   ├─ AgentManager [DEPENDS ON EventBus]
    │   ├─ PostgresClient [DEPENDS ON POSTGRES_* env vars]
    │   ├─ RedisClient [DEPENDS ON REDIS_HOST env var]
    │   └─ FirestoreClient [DEPENDS ON GCP setup]
    │
    ├─→ Import agents
    │   ├─ SentimentAgent → nse_data_service → yfinance
    │   ├─ RegimeAgent → market data
    │   ├─ ScannerAgent → NSE data
    │   ├─ StrategyAgent → market data + strategies
    │   ├─ RiskAgent → risk calculation
    │   ├─ ExecutionAgent → order execution (DhanHQ)
    │   └─ PortfolioAgent → position tracking
    │
    ├─→ Setup API routes
    │   └─ FastAPI app ready
    │
    └─→ Start uvicorn server
        └─ Listen on 0.0.0.0:8000

SUCCESS POINT: If you get past step 4, most issues are solved
```

---

## Pre-requisite Chain

```
Can Run `docker-compose up`?
    │
    ├─ YES if:
    │  ├─ docker-compose.yml has postgres + redis
    │  ├─ backend/.env exists
    │  ├─ backend/db/init.sql exists
    │  ├─ Dockerfile uses python:3.12
    │  └─ Port mapping is 8000:8000 (backend)
    │
    └─ NO if missing any of above

Can Start Backend?  
    │
    ├─ YES if:
    │  ├─ Python 3.12 installed
    │  ├─ All packages pip installed
    │  ├─ PostgreSQL running
    │  ├─ Redis running
    │  └─ .env variables set
    │
    └─ NO if missing any of above

Can Access API?
    │
    ├─ YES if:
    │  ├─ Backend started without errors
    │  ├─ curl http://localhost:8000/health returns 200
    │  └─ PostgreSQL tables exist
    │
    └─ NO if any startup errors

Can Run Tests?
    │
    ├─ YES if:
    │  ├─ API accessible
    │  ├─ All services healthy
    │  ├─ pytest installed
    │  └─ test files exist
    │
    └─ NO if API not working
```

---

## Success Metrics Timeline

```
Time  Action                          Success Indicator
────────────────────────────────────────────────────────
 T=0  Start fixing issues            Team assembled
      
 T=5  Create .env files              File size > 0
      
T=10  Python 3.12, init.sql          Files created
      
T=20  Update docker-compose          Syntax valid
      
T=30  docker-compose build           "Build successful"
      
T=50  docker-compose up              All 4 services running
      
T=55  Check health endpoint          curl returns 200
      
T=60  Verify database                psql shows tables
      
T=65  Load frontend                  Page loads on 3000
      
T=70  ✅ LOCAL TESTING READY!        All success criteria met
```

---

## Parallel Work Opportunities

You CAN do these in parallel:

```
Person 1: Create .env files & schemas
Person 2: Update Dockerfile & docker-compose
Person 3: Fix Firestore, DhanHQ, Redis code
Person 4: Create .gitignore & documentation
```

Estimated for 4 people: ~30 minutes (vs 90 min for 1 person)

---

## Risk & Recovery

```
If something goes wrong:

Issue: Docker fails to start
Recovery: 
  1. Check logs: docker-compose logs
  2. Fix file syntax
  3. Rebuild: docker-compose down && docker-compose build

Issue: PostgreSQL won't connect
Recovery:
  1. Check service: docker ps | grep postgres
  2. Check logs: docker logs agent-alpha-db
  3. Recreate: docker-compose down && docker volume rm ... && up

Issue: Backend crashes
Recovery:
  1. Check logs: docker logs agent-alpha-backend
  2. Verify .env: cat backend/.env
  3. Check Python: python --version

Issue: Tests fail
Recovery:
  1. Verify services healthy
  2. Check connection strings
  3. Run manual curl tests first

ROLLBACK:
  git reset --hard HEAD  # If using git
  rm -rf .[a-z]*         # Clean local files
  docker-compose down
```

---

## Key Metrics After Fixes

```
Before Audit: After Audit:
❌ 17 issues → ✅ 0 issues
❌ Can't start → ✅ Starts in 20s  
❌ No config → ✅ Configured
❌ Insecure → ✅ Secure
❌ No data → ✅ Persisted in DB
❌ Can't test → ✅ Full test suite runs
❌ 30 min docs → ✅ 4 guides provided
```

---

## Success Definition

```
You're successful when:

□ All 17 issues listed? DONE
□ Each issue has fix? DONE
□ Each fix tried locally? DONE
□ 4 services running? DONE
□ Health check passes? DONE
□ Tests pass? DONE
□ Team can setup locally? DONE
□ .env secure? DONE
□ Documentation complete? DONE

= LOCAL TESTING FULLY FUNCTIONAL ✅
```

---

**This diagram helps visualize all dependencies and the critical path to success.**

Refer to this when:
- Planning implementation order
- Assigning work to team members
- Troubleshooting issues
- Understanding what blocks what

---

Generated: February 18, 2026
