# ✅ LOCAL TESTING AUDIT - QUICK REFERENCE CHECKLIST

## 🔴 CRITICAL ISSUES (Do First)

### Issue 1: Missing .env Files
- **Files Needed:**
  - [ ] `backend/.env` 
  - [ ] `frontend/.env.local`
- **Time:** 5 minutes
- **Status:** Not fixed yet
- **Command:** 
  ```bash
  # backend/.env content
  ENV=development
  MODE=LOCAL
  POSTGRES_USER=user
  POSTGRES_PASSWORD=password_dev_local
  POSTGRES_DB=agentic_alpha
  POSTGRES_HOST=localhost
  REDIS_HOST=localhost
  DHAN_CLIENT_ID=your_id
  DHAN_ACCESS_TOKEN=your_token
  TV_WEBHOOK_SECRET=your_secret
  ```

### Issue 2: Python Version Mismatch
- **File:** `backend/Dockerfile`
- **Change:** Line 1: `FROM python:3.10-slim` → `FROM python:3.12-slim`
- **Time:** 2 minutes
- **Reason:** numba requires Python 3.12+
- **Status:** Not fixed yet

### Issue 3: Missing PostgreSQL Service
- **File:** `docker-compose.yml`
- **What:** Add postgres service with volume for init.sql
- **Time:** 10 minutes
- **Status:** Not fixed yet
- **Depends on:** Issue 5 below

### Issue 4: No Database Schemas
- **File to Create:** `backend/db/init.sql`
- **Contains:** CREATE TABLE statements for trades, logs, etc.
- **Time:** 5 minutes
- **Needed By:** Issue 3 (PostgreSQL service)
- **Status:** Not fixed yet

### Issue 5: Backend Port Mismatch
- **File:** `docker-compose.yml`
- **Change:** backend ports `5000:5000` → `8000:8000`
- **Time:** 2 minutes
- **Reason:** main.py uses port 8000
- **Status:** Not fixed yet

---

## 🟠 HIGH PRIORITY ISSUES (Do Second)

### Issue 6: Firestore Not Optional
- **File:** `backend/src/database/firestore.py`
- **Fix:** Add check for FIRESTORE_EMULATOR_HOST env var
- **Time:** 5 minutes
- **Status:** Not fixed yet

### Issue 7: Hardcoded DhanHQ Credentials
- **File:** `backend/src/services/dhan_client.py`
- **Fix:** Load from os.getenv() instead of hardcoded strings
- **Time:** 3 minutes
- **Status:** Not fixed yet
- **Security:** HIGH - Credentials visible in code

### Issue 8: Redis Error Handling
- **File:** `backend/src/core/event_bus.py`
- **Fix:** Add exception handling for Redis connection failures
- **Time:** 3 minutes
- **Status:** Not fixed yet

### Issue 9: Missing .gitignore
- **File to Create:** `.gitignore` at project root
- **Protection:** .env, logs, cache, node_modules
- **Time:** 5 minutes
- **Status:** Not fixed yet
- **Why:** Prevent accidental credential commit

---

## 🟡 MEDIUM PRIORITY ISSUES (Optional)

### Issue 10: No Docker Override
- **File to Create:** `docker-compose.override.yml`
- **Purpose:** Hot-reload development mode
- **Time:** 5 minutes
- **Status:** Not fixed yet

### Issue 11: PowerShell Scripts Broken
- **Files:** `run_simulation.ps1`, `start_paper_trading.ps1`
- **Issues:** Wrong container names, hardcoded ports
- **Time:** 5 minutes
- **Status:** Not fixed yet

### Issue 12: No Startup Validation
- **File to Create:** `backend/startup_local.py`
- **Purpose:** Check environment before starting
- **Time:** 10 minutes
- **Status:** Not fixed yet

---

## 🟢 LOW PRIORITY ISSUES (Nice to Have)

### Issue 13: Test Infrastructure
- **Setup:** pytest, pytest-asyncio, pytest-cov
- **Time:** 10 minutes
- **Status:** Not installed yet

### Issue 14: Documentation
- **Create:** LOCAL_SETUP.md, DEV_GUIDE.md
- **Time:** 15 minutes
- **Status:** Not created yet

---

## 📋 IMPLEMENTATION TRACKING

### Phase 1: CRITICAL (30 minutes)
- [ ] Create `backend/.env` (5 min)
- [ ] Create `frontend/.env.local` (2 min)
- [ ] Create `backend/db/init.sql` (5 min)
- [ ] Update `backend/Dockerfile` Python 3.12 (2 min)
- [ ] Update `docker-compose.yml` - fix port 5000→8000 (3 min)
- [ ] Update `docker-compose.yml` - add postgres service (10 min)
- [ ] **SUBTOTAL: ~30 minutes**

### Phase 2: HIGH (20 minutes)
- [ ] Fix `backend/src/database/firestore.py` (5 min)
- [ ] Fix `backend/src/services/dhan_client.py` (3 min)
- [ ] Fix `backend/src/core/event_bus.py` (3 min)
- [ ] Create `.gitignore` (5 min)
- [ ] **SUBTOTAL: ~20 minutes**

### Phase 3: MEDIUM (20 minutes)
- [ ] Create `docker-compose.override.yml` (5 min)
- [ ] Fix PowerShell scripts (5 min)
- [ ] Create `backend/startup_local.py` (10 min)
- [ ] **SUBTOTAL: ~20 minutes**

### Phase 4: LOW (25 minutes)
- [ ] Install test dependencies (5 min)
- [ ] Create `pytest.ini` (5 min)
- [ ] Write documentation (15 min)
- [ ] **SUBTOTAL: ~25 minutes**

### **TOTAL TIME: 95 minutes (1.5 hours)**

---

## 🎯 VALIDATION STEPS

After completing each phase:

### After Phase 1:
```bash
# Should succeed without errors
pip install -r backend/requirements.txt
python -c "from dotenv import load_dotenv; load_dotenv(); print('✅ ENV loaded')"
```

### After Phase 2:
```bash
# Start Docker
docker-compose build
docker-compose up
# Wait for all services to start...
```

### After Phase 3:
```bash
# Test all endpoints
curl http://localhost:8000/health
curl http://localhost:3000
curl http://localhost:5432  # psql
```

### After Phase 4:
```bash
# Run test suite
pytest backend/test_integration.py -v
```

---

## 📊 ISSUE BREAKDOWN

```
Total Issues Found: 17

By Severity:
  🔴 CRITICAL: 5 issues → 30 min
  🟠 HIGH: 4 issues → 20 min
  🟡 MEDIUM: 3 issues → 20 min
  🟢 LOW: 2 issues → 25 min
  ────────────────────────
  ✅ TOTAL: ~95 minutes

By Component:
  Configuration: 5 issues
  Infrastructure: 4 issues
  Code: 4 issues
  Documentation: 2 issues
  Testing: 2 issues
```

---

## 🚀 EXECUTION SCRIPT

Save as `run_audit_fixes.ps1`:

```powershell
Write-Host "🚀 Starting Audit Fixes..." -ForegroundColor Green

# Phase 1: CRITICAL
Write-Host "`n📋 Phase 1: CRITICAL (30 min)" -ForegroundColor Yellow
Write-Host "1/5: Creating backend/.env" -ForegroundColor Cyan
Write-Host "     TODO: Create file manually with credentials"

Write-Host "2/5: Creating frontend/.env.local" -ForegroundColor Cyan
Write-Host "     TODO: Create file manually with API URL"

Write-Host "3/5: Creating backend/db/init.sql" -ForegroundColor Cyan
Write-Host "     TODO: Create file from REMEDIATION_GUIDE.md"

Write-Host "4/5: Updating backend/Dockerfile" -ForegroundColor Cyan
Write-Host "     TODO: Change line 1 to: FROM python:3.12-slim"

Write-Host "5/5: Updating docker-compose.yml" -ForegroundColor Cyan
Write-Host "     TODO: Add postgres/redis, change port to 8000"

Write-Host "`nWhen Phase 1 is done, run:" -ForegroundColor Green
Write-Host "docker-compose build && docker-compose up" -ForegroundColor Green
```

---

## 🔍 FILES TO CREATE/MODIFY

### Files to CREATE:
- [ ] `backend/.env`
- [ ] `backend/db/init.sql`
- [ ] `frontend/.env.local`
- [ ] `.gitignore`
- [ ] `docker-compose.override.yml` (optional)
- [ ] `backend/startup_local.py` (optional)

### Files to MODIFY:
- [ ] `backend/Dockerfile` (1 line change)
- [ ] `docker-compose.yml` (services + ports)
- [ ] `backend/src/database/firestore.py` (error handling)
- [ ] `backend/src/services/dhan_client.py` (use env vars)
- [ ] `backend/src/core/event_bus.py` (exception handling)
- [ ] `run_simulation.ps1` (container names)
- [ ] `start_paper_trading.ps1` (ports)

---

## 💾 BACKUP BEFORE CHANGES

```bash
# Create backup
cp -r . backup_before_audit_fixes_$(date +%Y%m%d_%H%M%S)

# Or use Git
git add .
git commit -m "Pre-audit-fixes backup"
```

---

## 🆘 EMERGENCY ROLLBACK

If something breaks:

```bash
# Local changes only - just edit files again
# Git changes - rollback with:
git reset --hard HEAD
git clean -fd
```

---

## 📱 SIGN-OFF CHECKLIST

When all fixes are complete:

- [ ] Phase 1 complete - Can start docker
- [ ] Phase 2 complete - Credentials secured  
- [ ] Phase 3 complete - Development optimized
- [ ] Phase 4 complete - Testing ready
- [ ] All 4 docs reviewed
- [ ] Team trained on setup
- [ ] CI/CD ready

---

## 📞 ISSUES DURING IMPLEMENTATION?

### Common Problems:

**"Permission denied" in Docker**
→ Run Docker as Administrator

**"Port 8000 already in use"** 
→ `netstat -ano | findstr :8000` → kill process

**"PostgreSQL connection refused"**
→ Check `docker ps` → Check logs

**"Module not found" errors**
→ Rebuild docker: `docker-compose build --no-cache`

**"Python version wrong"**
→ Verify: `python --version` → Must be 3.12+

---

## 🎓 DOCUMENTS PROVIDED

1. **AUDIT_LOCAL_TESTING.md** - Full issue report
2. **REMEDIATION_GUIDE.md** - Step-by-step code fixes
3. **QUICK_START_PRIORITY.md** - Implementation phases
4. **AUDIT_SUMMARY.md** - Executive overview
5. **This File** - Quick reference checklist

---

## ✨ ESTIMATED TIME ZONES

```
Quick Run (Phase 1 only): 30-40 min
Recommended (Phase 1+2): 50-60 min
Complete (Phase 1+2+3): 70-90 min
Full Setup (All phases): 90-120 min
```

---

## 🏆 SUCCESS = When This Works:

```bash
✅ docker-compose up              # Starts without errors
✅ curl localhost:8000/health     # Returns healthy
✅ curl localhost:3000            # Frontend loads
✅ pytest backend/                # Tests pass
✅ docker ps                       # 4 containers running
✅ cat .env                        # Credentials set
✅ cat .gitignore                  # Secrets protected
```

---

**Start with Phase 1 now - you've got this! 🚀**

Last Updated: February 18, 2026
