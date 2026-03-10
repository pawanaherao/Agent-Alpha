# 🔍 AGENTIC ALPHA - LOCAL TESTING AUDIT REPORT
**Date:** February 18, 2026  
**Status:** CRITICAL ISSUES IDENTIFIED ⚠️  
**Audit Level:** Full Codebase

---

## 📋 EXECUTIVE SUMMARY

The Agentic Alpha codebase is **partially ready** for local testing. While the architecture is sound and well-structured, there are **critical blockers** and **15+ issues** preventing immediate local execution. This audit identifies all blockers and provides step-by-step remediation.

**Overall Health Score:** 6/10 ✅❌

---

## 🚨 CRITICAL BLOCKERS (Must Fix)

### 1. **Missing Environment Configuration (.env)**
- **Status:** ❌ BLOCKING
- **Severity:** CRITICAL
- **Issue:** No `.env` file provided
- **Impact:** Application cannot start - credentials undefined
- **Files Affected:**
  - `backend/src/core/config.py` - expects `.env`
  - `backend/main.py` - loads via `python-dotenv`
  - Frontend needs `.env.local`

**Action Required:**
```bash
# Create backend/.env
DHAN_CLIENT_ID=your_dhan_id_here
DHAN_ACCESS_TOKEN=your_dhan_token_here
TV_WEBHOOK_SECRET=your_webhook_secret_here
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=agentic_alpha
POSTGRES_HOST=localhost
REDIS_HOST=localhost
```

---

### 2. **Python Version Mismatch (CRITICAL)**
- **Status:** ❌ BLOCKING
- **Severity:** CRITICAL
- **Issue:** Requirements.txt specifies Python 3.12.x, but Docker uses Python 3.10
- **Files Affected:**
  - `backend/requirements.txt` - Line 4: "Python Version: 3.12.x REQUIRED"
  - `backend/Dockerfile` - Line 1: `FROM python:3.10-slim`
  - `numba>=0.61.2` requires Python 3.12+

**Error Expected:** `numba` compilation fails on Python 3.10

**Action Required:**
```dockerfile
# Update backend/Dockerfile Line 1
FROM python:3.12-slim
```

---

### 3. **TA-Lib Installation Not Automated**
- **Status:** ❌ BLOCKING
- **Severity:** HIGH
- **Issue:** TA-Lib commented out, requires manual `.whl` download on Windows
- **Files Affected:** `backend/requirements.txt` - Lines 32-35

**Why It Blocks:**
- Manual installation needed for live trading
- No fallback error handling if missing
- Dockerfile won't compile it

**Action Required:**
```bash
# 1. Download: https://github.com/cgohlke/talib-build/releases
# 2. For Python 3.12, Windows: TA_Lib-0.4.32-cp312-cp312-win_amd64.whl
# 3. Place in: backend/vendor/
# 4. Update Dockerfile to COPY and install locally
```

---

### 4. **Missing Database Schemas**
- **Status:** ❌ BLOCKING
- **Severity:** HIGH
- **Issue:** PostgreSQL connection configured but NO schema initialization
- **Files Affected:**
  - `src/database/postgres.py` - connects but no `CREATE TABLE`
  - `run_simulation.ps1` - references table `trades` that may not exist

**Impact:** Runtime errors when trying to store trade data

**Action Required:**
Create `backend/src/database/init_schemas.py`:
```python
# Schema creation scripts needed for:
# - trades (symbol, signal_type, status, created_at)
# - execution_logs
# - risk_assessment
# - portfolio_state
```

---

### 5. **Redis Connection Not Optional**
- **Status:** ⚠️ SEMI-BLOCKING
- **Severity:** MEDIUM
- **Issue:** `event_bus_redis.py` imports Redis but may fail if Redis not running
- **Files Affected:** `src/core/event_bus.py` - Lines 46-52

**Current Code:**
```python
try:
    from src.core.event_bus_redis import RedisEventBus
    event_bus = RedisEventBus()
except ImportError:
    event_bus = EventBus()
```

**Problem:** Falls back on `ImportError` (missing module) but fails on `ConnectionError` (Redis down)

**Action Required:** Add connection error handling

---

## ⚠️ HIGH-PRIORITY ISSUES

### 6. **Firestore GCP Project Not Configured**
- **Status:** ❌ NOT CONFIGURED
- **Severity:** HIGH
- **Issue:** 
  - `src/database/firestore.py` expects GCP credentials
  - `src/core/config.py` sets `GCP_PROJECT = "agentic-alpha-local"`
  - No emulator setup instructions

**Impact:** Real-time data storage will fail

**Solution:** Firestore Emulator or skip for local testing
```bash
# Option 1: Use Firestore Emulator
gcloud firestore emulators start
export FIRESTORE_EMULATOR_HOST=localhost:8080

# Option 2: Comment out Firestore in src/main.py (lines 46-50)
```

---

### 7. **DhanHQ Credentials Hardcoded in Code**
- **Status:** ❌ SECURITY ISSUE
- **Severity:** MEDIUM
- **Files Affected:** `src/services/dhan_client.py` - Lines 15-16
```python
self.client_id = "YOUR_CLIENT_ID" # TODO: Load from Secret Manager
self.access_token = "YOUR_ACCESS_TOKEN" # TODO: Load from Secret Manager
```

**Action Required:** Replace with environment variable loading

---

### 8. **Frontend API Endpoint Configuration Missing**
- **Status:** ⚠️ INCOMPLETE
- **Severity:** MEDIUM
- **Issue:** Frontend points to hardcoded `http://localhost:5000` or `8000` (unclear)
- **Files Affected:** 
  - `frontend/src/lib/` - API client configuration
  - `docker-compose.yml` - backend runs on port 5000 OR 8000

**Inconsistency:** `docker-compose.yml` shows port 5000, but `main.py` might use 8000

**Backend Startup Code:** `uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)`

**Action Required:**
- Standardize port (recommend 8000)
- Update `docker-compose.yml` backend service to use 8000
- Verify frontend API client uses correct port

---

### 9. **Windows PowerShell Scripts Have Issues**
- **Status:** ⚠️ BROKEN
- **Severity:** MEDIUM
- **Issues:**
  - Line 7: `curl.exe` is Windows-specific, not cross-platform
  - Line 8: `docker exec agentic_alpha_db` - container name may differ
  - No error handling for failed requests

**File:** `run_simulation.ps1`

**Action Required:**
```powershell
# Update container name reference
# Check actual container with: docker ps
# Use dynamic container ID or proper DNS name from docker-compose
```

---

### 10. **Missing .gitignore for Secrets & Data**
- **Status:** ❌ NOT FOUND
- **Severity:** MEDIUM
- **Issue:** 
  - No `.gitignore` found
  - CSV files, logs, and data directories may be tracked
  - API keys at risk if committed

**Action Required:**
```
# Create .gitignore
.env
.env.local
backend/logs/
backend/data/
backend/*.csv
backend/paper_trading_results.json
backend/__pycache__/
node_modules/
.next/
```

---

## 📦 DEPENDENCY ISSUES

### 11. **Incompatible Package Versions**
- **Status:** ⚠️ WARNING
- **Severity:** MEDIUM
- **Issues Identified:**
  - `pandas>=3.0.0` - MAJOR version, potential breaking changes
  - `numpy>=2.2.6` - Might have compatibility issues with old packages
  - `polars>=1.38.1` - Newer libraries may cause API changes
  - `numba>=0.61.2` - Requires Python 3.11+, contradicts 3.10 Dockerfile

**Documented Issue:** NumExpr and NumBA together can have edge cases

**Action Required:** Pin to safer versions
```
numpy==2.2.6
pandas==2.2.0
numba==0.59.0  # More stable, less breaking changes
```

---

### 12. **Missing Backend URL Configuration**
- **Status:** ⚠️ NOT FOUND
- **Severity:** MEDIUM
- **Files:** Frontend API clients in `frontend/src/lib/`

**Issue:** Frontend must know backend URL
- Development: `http://localhost:8000`
- Docker: `http://backend:5000` (or 8000)

**Action Required:**
```typescript
// frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 🗄️ DATABASE CONFIGURATION

### 13. **No Database Initialization Scripts**
- **Status:** ❌ MISSING
- **Severity:** HIGH
- **Issue:**
  - `run_simulation.ps1` queries `trades` table that may not exist
  - No SQL schema files found
  - Docker doesn't auto-create tables

**Solution:** Create SQL schema file:
```sql
-- backend/db/init.sql
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    signal_type VARCHAR(20),
    status VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(50),
    action VARCHAR(255),
    timestamp TIMESTAMP DEFAULT NOW()
);
```

---

### 14. **Docker Database Name Mismatch**
- **Status:** ⚠️ INCONSISTENT
- **Severity:** MEDIUM
- **Issue:**
  - `docker-compose.yml` doesn't include PostgreSQL service
  - Script assumes database exists

**Current:** Missing entire PostgreSQL service in docker-compose.yml

**Action Required:** Add to docker-compose.yml
```yaml
services:
  postgres:
    image: postgres:15-alpine
    container_name: agent-alpha-db
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: agentic_alpha
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backend/db/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - agent-alpha-net

volumes:
  postgres_data:
```

---

## 🔧 TESTING & INFRASTRUCTURE

### 15. **Test Files Exist But Setup Instructions Missing**
- **Status:** ⚠️ INCOMPLETE DOCUMENTATION
- **Severity:** MEDIUM
- **Test Files Found:**
  - `backend/test_integration.py` ✅
  - `backend/test_strategies.py` ✅
  - `backend/test_nse.py` ✅
  - `backend/test_all_agents.py` ✅

**Issue:** No `pytest.ini` or test runner configuration

**Action Required:**
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run tests
pytest backend/ -v --tb=short
```

---

### 16. **No Docker Compose Override for Local Development**
- **Status:** ⚠️ NOT FOUND
- **Severity:** LOW
- **Issue:** `docker-compose.yml` is production-like, no `docker-compose.override.yml` for local development with hot-reload

**Action Required:** Create `docker-compose.override.yml`
```yaml
version: '3.8'
services:
  backend:
    volumes:
      - ./backend:/app
    environment:
      - PYTHONUNBUFFERED=1
      - ENV=development
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

### 17. **Missing Port Clarification Documentation**
- **Status:** ⚠️ CONFUSING
- **Severity:** LOW
- **Issue:**
  - `docker-compose.yml` exposes port 5000
  - `backend/main.py` runs on port 8000
  - Frontend default assumes 3000

**Action Required:** Document in `LOCAL_SETUP.md`

---

## ✅ WHAT'S WORKING WELL

- ✅ Clear multi-agent architecture
- ✅ Good separation of concerns (agents, services, strategies)
- ✅ Logging infrastructure in place
- ✅ Event bus pattern implemented
- ✅ Multiple data source fallbacks (NSE, YFinance, Dhan)
- ✅ Frontend Next.js setup is clean
- ✅ Async/await patterns properly used
- ✅ Health check endpoints implemented

---

## 📋 QUICK START CHECKLIST

Before running `docker-compose up`:

- [ ] Create `backend/.env` with all credentials
- [ ] Fix Python version to 3.12 in Dockerfile
- [ ] Add PostgreSQL service to docker-compose.yml
- [ ] Create SQL schema scripts
- [ ] Add TA-Lib .whl to vendor/
- [ ] Create `frontend/.env.local` with API URL
- [ ] Create `.gitignore`
- [ ] Update docker-compose port for backend to 8000
- [ ] Test `python test_nse.py` manually first
- [ ] Verify `pip install -r requirements.txt` works locally

---

## 🔄 RECOMMENDED SETUP ORDER

### Phase 1: Local Environment (No Docker)
```bash
1. Create .env files
2. Install Python 3.12
3. Create venv: python -m venv venv
4. Install: pip install -r requirements.txt
5. Download TA-Lib .whl manually
6. Test: pytest backend/test_nse.py -v
```

### Phase 2: Database Setup
```bash
1. Install PostgreSQL locally OR use Docker
2. Run: psql -U user -d agentic_alpha -f backend/db/init.sql
3. Verify tables: psql -l
```

### Phase 3: Docker Compose
```bash
1. Fix all blockers
2. docker-compose build
3. docker-compose up
4. Test: curl http://localhost:8000/health
```

### Phase 4: Integration Testing
```bash
1. Run test suite: pytest backend/
2. Check logs: docker logs agent-alpha-backend
3. Frontend startup: cd frontend && npm run dev
```

---

## 📊 SEVERITY BREAKDOWN

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 CRITICAL | 3 | Blocking local testing |
| 🟠 HIGH | 6 | Must fix before testing |
| 🟡 MEDIUM | 6 | Should fix for stability |
| 🟢 LOW | 2 | Nice to have |
| **TOTAL** | **17** | **Issues Found** |

---

## 📝 NOTES FOR FUTURE IMPROVEMENTS

1. **Add Docker Secrets Management** - Don't pass secrets as env vars
2. **Implement Health Checks** - Add docker HEALTHCHECK directives
3. **Database Migrations** - Use Alembic for schema versioning
4. **CI/CD Pipeline** - GitHub Actions to test before commits
5. **Load Testing** - Add locust or k6 for performance testing
6. **API Documentation** - Generate OpenAPI/Swagger from FastAPI
7. **Monitoring** - Add Prometheus metrics collection
8. **Error Tracking** - Integrate Sentry or similar

---

**Audit Completed By:** Automated Codebase Analysis  
**Next Review:** After implementing all CRITICAL and HIGH priority items
