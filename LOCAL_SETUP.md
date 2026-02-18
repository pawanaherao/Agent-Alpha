# 🚀 LOCAL TESTING QUICK START GUIDE

**Status:** All Phase 1 Critical Fixes Applied ✅

---

## What Was Fixed

Your local testing environment is now configured with:

✅ **Database Layer** - PostgreSQL + Redis in docker-compose  
✅ **Environment Config** - .env files for backend/frontend  
✅ **Database Schemas** - init.sql with all required tables  
✅ **Python Version** - Updated to 3.12 (numba compatible)  
✅ **Port Configuration** - Backend now on 8000, frontend on 3000  
✅ **Security** - .gitignore protecting credentials  
✅ **Dev Setup** - docker-compose.override.yml for hot-reload  

---

## Prerequisites

Before running locally, you need:

- **Docker** - [Install Docker Desktop](https://www.docker.com/products/docker-desktop)
- **Docker Compose** - Usually included with Docker Desktop
- **Git** - For cloning/pulling changes

Verify installation:
```powershell
docker --version
docker-compose --version
```

---

## Quick Start (5 minutes)

### Step 1: Validate Configuration
```powershell
cd "c:\Users\pawan\Documents\code lab\Agent Alpha"
python startup_validation.py
```

Expected output:
```
✅ backend/.env exists
✅ frontend/.env.local exists
✅ backend/db/init.sql exists
✅ All checks passed!
```

### Step 2: Build Docker Images
```powershell
docker-compose build
```

First build takes 2-5 minutes. Subsequent builds are faster.

### Step 3: Start Services
```powershell
docker-compose up
```

Wait for output showing:
```
agent-alpha-postgres | database system is ready to accept connections
agent-alpha-redis | Ready to accept connections
agent-alpha-backend | Uvicorn running on http://0.0.0.0:8000
agent-alpha-frontend | ▲ Next.js 16.1.6
```

---

## Verify Services Are Running

Open new PowerShell window (while services run in first window):

### Test Backend API
```powershell
curl http://localhost:8000/health
# Should return: {"status":"healthy"}
```

### Test Frontend
```powershell
Start-Process http://localhost:3000
# Opens frontend in browser
```

### Test Database
```powershell
docker exec agent-alpha-postgres psql -U user -d agentic_alpha -c "SELECT * FROM trades LIMIT 1;"
# Should return empty table (OK on first run)
```

### View API Documentation
```powershell
Start-Process http://localhost:8000/docs
# Opens interactive Swagger documentation
```

---

## Common Commands

### View Logs
```powershell
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f postgres
docker-compose logs -f redis
```

### Stop Services
```powershell
# Graceful shutdown
docker-compose down

# Stop + remove volumes (WARNING: deletes database)
docker-compose down -v
```

### Rebuild After Code Changes
```powershell
# Quick rebuild (if you modified backend/frontend code)
docker-compose up --build
```

### Access Database Directly
```powershell
# Connect to PostgreSQL CLI
docker exec -it agent-alpha-postgres psql -U user -d agentic_alpha

# Then you can run SQL:
# \dt (show tables)
# SELECT * FROM trades;
# \q (exit)
```

### Access Redis CLI
```powershell
docker exec -it agent-alpha-redis redis-cli
# Then: PING (should return PONG)
# SET key value
# GET key
```

---

## Environment Variables

Secrets are stored in `.env` files (NOT in git):

### Backend Configuration (`backend/.env`)
```
ENV=development
POSTGRES_USER=user
POSTGRES_PASSWORD=password_dev_local
POSTGRES_DB=agentic_alpha
POSTGRES_HOST=localhost
REDIS_HOST=localhost
DHAN_CLIENT_ID=your_dhan_id_here  # Optional for paper trading
DHAN_ACCESS_TOKEN=your_dhan_token_here  # Optional
```

### Frontend Configuration (`frontend/.env.local`)
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Troubleshooting

### Issue: "docker-compose: command not found"
**Solution:** Update docker-compose syntax in newer Docker Desktop:
```powershell
# Old syntax:
docker-compose up

# New syntax:
docker compose up
```

### Issue: Port 8000 Already in Use
**Solution:** Find and stop other services:
```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### Issue: PostgreSQL Won't Start
**Solution:** Check database volume:
```powershell
docker volume ls
docker volume rm agent_alpha_postgres_data  # WARNING: Deletes all data
docker-compose up  # Rebuilds fresh database
```

### Issue: "Connection refused" to Backend
**Solution:** Backend may still be starting:
```powershell
docker logs agent-alpha-backend
# Wait for: "Application startup complete"
```

### Issue: Frontend shows "Cannot reach API"
**Solution:** Check backend is running and port is correct:
```powershell
curl http://localhost:8000/health
# If fails, check docker logs
docker-compose logs backend
```

---

## Next Steps

Now that local environment is running:

1. **Run Tests** (after we fix strategies):
   ```powershell
   docker exec agent-alpha-backend pytest backend/tests/ -v
   ```

2. **View Logs** in real-time:
   ```powershell
   docker-compose logs -f
   ```

3. **Modify Code**:
   - Backend code changes auto-reload in Docker
   - Frontend code changes auto-refresh
   - Just save and refresh browser

4. **Phase 2: Fix Strategies**:
   - After local testing is working, we'll fix the strategies codebase
   - Follow the fixes in STRATEGIES_FIXES.md

---

## Performance Tips

- **First startup**: 2-5 minutes (downloading images, compiling)
- **Subsequent startups**: 10-15 seconds
- **Code reload time**: <1 second for most changes
- **Database query time**: Usually <100ms local

If services are slow:
- Allocate more Docker resources (Settings > Resources > Memory)
- Restart Docker Desktop completely
- Rebuild images: `docker-compose build --no-cache`

---

## Stopping Local Environment

When done testing:
```powershell
# Graceful shutdown (data preserved)
docker-compose down

# Shutdown + full reset (WARNING: deletes database)
docker-compose down -v
```

Your code changes are SAVED locally, Docker just stops running.
To resume: `docker-compose up`

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    YOUR LOCAL ENVIRONMENT                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Browser (localhost:3000)                                   │
│      │                                                       │
│      ├──> Frontend (Next.js)                                │
│      │        │                                             │
│      │        └──> API calls                                │
│      │              │                                       │
│      └─────────> Backend API (FastAPI) localhost:8000       │
│                     │         │                             │
│                     │         └────> PostgreSQL (5432)      │
│                     │                    │                  │
│                     │                    └> Database tables  │
│                     │                                        │
│                     └──────> Redis (6379)                   │
│                              │                              │
│                              └> Cache/Events                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

All services run locally in Docker containers.

---

## Support

If you encounter issues:

1. **Check logs**: `docker-compose logs`
2. **Check startup validation**: `python startup_validation.py`
3. **Review error messages** in console output
4. **Restart Docker**: `docker-compose down && docker-compose up`
5. **Full rebuild**: `docker-compose down -v && docker-compose build --no-cache && docker-compose up`

Good luck! 🚀
