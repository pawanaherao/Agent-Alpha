# ⚡ FAST-TRACK IMPLEMENTATION PRIORITY

## Phase 1: CRITICAL (Start Here - Blocks Everything)
⏱️ **Estimated Time: 30 minutes**

These MUST be fixed before ANY testing:

### 1. Create .env Files (5 min)
- [ ] `backend/.env` - Database, Redis, API credentials
- [ ] `frontend/.env.local` - Backend URL configuration

**Command:**
```bash
cd backend
copy NUL .env
# Edit .env with credentials from REMEDIATION_GUIDE.md

cd ../frontend  
copy NUL .env.local
# Edit with: NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2. Fix Python Version (2 min)
- [ ] Update `backend/Dockerfile` Line 1: `FROM python:3.10-slim` → `FROM python:3.12-slim`

**Why:** numba requires Python 3.12+

---

### 3. Create Database Service (15 min)
- [ ] Add PostgreSQL and Redis to `docker-compose.yml` (from REMEDIATION_GUIDE.md)
- [ ] Create `backend/db/init.sql` with schema

**Verification:**
```bash
docker-compose up postgres redis
docker exec agent-alpha-db psql -U user -d agentic_alpha -c "\dt"  # Should show tables
```

### 4. Fix Backend Port (2 min)
- [ ] `docker-compose.yml` backend service: `5000:5000` → `8000:8000`
- [ ] Confirm `backend/main.py` runs on 8000

---

## Phase 2: HIGH PRIORITY (Needed for Basic Testing)
⏱️ **Estimated Time: 20 minutes**

### 5. Fix Firestore Configuration (5 min)
- [ ] Update `backend/src/database/firestore.py` - Add graceful fallback for emulator

### 6. Fix DhanHQ Credentials (3 min)
- [ ] Update `backend/src/services/dhan_client.py` - Load from env vars, not hardcoded

### 7. Add Event Bus Error Handling (3 min)
- [ ] Update `backend/src/core/event_bus.py` - Handle Redis connection failures

### 8. Create .gitignore (5 min)
- [ ] Add `.gitignore` at project root (from REMEDIATION_GUIDE.md)

---

## Phase 3: MEDIUM PRIORITY (Stability & Documentation)
⏱️ **Estimated Time: 20 minutes**

### 9. Create Docker Override (5 min)
- [ ] `docker-compose.override.yml` for local hot-reload development

### 10. Fix PowerShell Scripts (5 min)
- [ ] Update `run_simulation.ps1` - Fix container names and error handling
- [ ] Update `start_paper_trading.ps1` - Verify port numbers

### 11. Add Startup Validation (10 min)
- [ ] Create `backend/startup_local.py` - Validates environment before running

---

## Phase 4: NICE TO HAVE (Future Improvements)
⏱️ **Estimated Time: 30 minutes** (optional)

### 12. Documentation
- [ ] Create `LOCAL_SETUP.md` - Step-by-step for new developers
- [ ] Add inline comments to config files

### 13. Testing Infrastructure
- [ ] Install pytest and setup test runner
- [ ] Create `pytest.ini` configuration

### 14. Development Tooling
- [ ] Add pre-commit hooks for linting
- [ ] Create development requirements.txt (with pytest, black, etc.)

---

## ⚠️ WHAT YOU MUST DO FIRST - The Absolute Minimum

**If you can only do 5 minutes of work:**

1. Create `backend/.env` - Copy from REMEDIATION_GUIDE.md
2. Create `frontend/.env.local` - Just add: `NEXT_PUBLIC_API_URL=http://localhost:8000`
3. Update `backend/Dockerfile` - Change Python 3.10 to 3.12 (1 line)

**That's your absolute minimum.** With these 3 things, you can:
```bash
pip install -r backend/requirements.txt  # Will work without errors
python backend/main.py  # Will start (though DB will fail gracefully)
```

---

## 📊 ISSUE IMPACT MATRIX

| Issue | Impact | Effort | Priority |
|-------|--------|--------|----------|
| Missing .env | App won't start | 5 min | CRITICAL |
| Python version mismatch | numba fails | 2 min | CRITICAL |
| No PostgreSQL service | Data loss | 15 min | CRITICAL |
| Missing schema | Tables don't exist | 10 min | CRITICAL |
| Wrong backend port | Frontend can't connect | 2 min | CRITICAL |
| Firestore misconfigured | Falls back safely | 5 min | HIGH |
| Hardcoded DhanHQ creds | Security risk | 3 min | HIGH |
| Redis error handling | Crashes if Redis down | 3 min | HIGH |
| Missing .gitignore | Secrets exposed | 5 min | MEDIUM |
| Docker override missing | No hot-reload | 5 min | MEDIUM |
| PowerShell scripts broken | Automation fails | 5 min | MEDIUM |
| No TA-Lib automation | Manual install needed | 10 min | MEDIUM |
| Test setup incomplete | Can't run tests | 10 min | LOW |

---

## 🎯 TESTING MILESTONES

### ✅ Milestone 1: Can Start Backend
**When:** After Phase 1
```bash
python backend/main.py
# Should show: "🚀 Starting Agentic Alpha v4.0"
```

### ✅ Milestone 2: Can Docker Compose
**When:** After Phase 1 + database schemas
```bash
docker-compose up
# Should show 4 services starting
```

### ✅ Milestone 3: Health Checks Pass
**When:** After Phase 2
```bash
curl http://localhost:8000/health
# Should return: {"status": "healthy", ...}
```

### ✅ Milestone 4: Full Integration
**When:** After Phase 2 + Phase 3
```bash
pytest backend/test_integration.py -v
# All tests pass
```

---

## 🚀 ACTUAL EXECUTION STEPS

### Step-by-Step Commands

```powershell
# 1. Navigate to project
cd "C:\Users\pawan\Documents\code lab\Agent Alpha"

# 2. Create .env files (use Notepad or VS Code)
# backend\.env - copy content from REMEDIATION_GUIDE.md FIX #1
# frontend\.env.local - copy content from REMEDIATION_GUIDE.md FIX #3

# 3. Update Dockerfile (5 seconds)
# Edit backend/Dockerfile line 1: FROM python:3.12-slim

# 4. Create database schema
mkdir backend\db
# Create backend/db/init.sql with content from REMEDIATION_GUIDE.md FIX #5

# 5. Update docker-compose (copy new version from REMEDIATION_GUIDE.md FIX #4)

# 6. Build and test
docker-compose build
docker-compose up

# 7. In new terminal - test API
curl http://localhost:8000/health

# 8. (Optional) Run Python tests
pytest backend/test_integration.py -v
```

---

## ❌ COMMON MISTAKES TO AVOID

1. **Don't skip the .env files** - App will fail immediately
2. **Don't use Python 3.10** - numba won't compile
3. **Don't forget PostgreSQL service** - All data queries will fail
4. **Don't mix ports** - 8000 for backend, 3000 for frontend (not 5000)
5. **Don't hardcode credentials** - Load from .env always
6. **Don't skip database init** - Tables won't exist
7. **Don't edit docker-compose.yml without docker-compose.override.yml** - Won't hot-reload

---

## 📈 SUCCESS CRITERIA

All boxes checked = Local testing is go:

- [ ] `backend/.env` exists with all required variables
- [ ] `frontend/.env.local` exists
- [ ] `backend/Dockerfile` uses Python 3.12
- [ ] `backend/db/init.sql` exists
- [ ] `docker-compose.yml` has postgres and redis services
- [ ] Backend port changed to 8000
- [ ] `curl http://localhost:8000/health` returns 200
- [ ] `docker ps` shows 4 containers running
- [ ] `psql -U user -d agentic_alpha -c "\dt"` shows all tables
- [ ] Frontend loads at `http://localhost:3000`

---

## 🆘 TROUBLESHOOTING QUICK LINKS

### "ModuleNotFoundError: No module named 'numba'"
→ Fix: Install Python 3.12, rebuild `pip install -r requirements.txt`

### "PostgreSQL connection refused"
→ Fix: Check `docker ps`, ensure postgres container is running

### "Redis connection timeout"
→ Fix: Check `docker logs agent-alpha-redis`

### "Port 8000 already in use"
→ Fix: `netstat -ano | findstr :8000` then kill that process

### "Frontend can't connect to backend"
→ Fix: Check `frontend/.env.local` has `NEXT_PUBLIC_API_URL=http://localhost:8000`

### "Permission denied error in Docker"
→ Fix: Run Docker in administrator mode or use WSL2

---

## 📋 COMPLETION CHECKLIST

Copy this and check off as you go:

```
PHASE 1 - CRITICAL (MUST DO)
[ ] .env files created
[ ] Dockerfile Python updated to 3.12
[ ] docker-compose.yml has postgres + redis
[ ] backend/db/init.sql created
[ ] Backend port changed to 8000

PHASE 2 - HIGH (SHOULD DO)
[ ] Firestore configuration fixed
[ ] DhanHQ credentials use .env
[ ] Event bus error handling added
[ ] .gitignore created

PHASE 3 - MEDIUM (NICE)
[ ] docker-compose.override.yml created
[ ] PowerShell scripts updated
[ ] startup_local.py created

TESTING
[ ] docker-compose up succeeds
[ ] curl /health returns 200
[ ] PostgreSQL tables exist
[ ] Frontend loads on 3000
[ ] pytest passes on test_integration.py
```

---

**Ready to begin? Start with Phase 1 - it's only 30 minutes to a working local environment!**
