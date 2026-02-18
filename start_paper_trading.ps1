# ============================================================================
# AGENTIC ALPHA - PAPER TRADING LAUNCHER
# ============================================================================
# Starts the full local paper trading environment

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "🚀 AGENTIC ALPHA - PAPER TRADING ENVIRONMENT" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Docker
Write-Host "🔍 Checking Docker..." -ForegroundColor Yellow -NoNewline
docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host " ❌ FAILED" -ForegroundColor Red
    Write-Error "Docker is not running! Please start Docker Desktop."
    exit 1
}
Write-Host " ✅ OK" -ForegroundColor Green

# 2. Validate Configuration
Write-Host "✅ Validating configuration..." -ForegroundColor Yellow -NoNewline
python startup_validation.py > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host " ⚠️  WARNING" -ForegroundColor Yellow
    Write-Host "   Some configuration may be missing. Run: python startup_validation.py" -ForegroundColor Gray
} else {
    Write-Host " ✅ OK" -ForegroundColor Green
}

# 3. Build & Start Containers
Write-Host ""
Write-Host "🐳 Building and starting containers..." -ForegroundColor Yellow
docker-compose up --build -d 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to start containers" -ForegroundColor Red
    Write-Host "Run this for details: docker-compose logs" -ForegroundColor Gray
    exit 1
}

Write-Host "⏳ Waiting for services to be ready (30 seconds)..." -ForegroundColor Yellow

# Wait and check health
$maxWait = 30
$startTime = Get-Date

while ((Get-Date) - $startTime -lt [timespan]::fromseconds($maxWait)) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" `
                                     -Method GET `
                                     -TimeoutSec 2 `
                                     -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Host "✅ Services ready!" -ForegroundColor Green
            break
        }
    }
    catch {
        # Still waiting
    }
    Start-Sleep -Seconds 2
}

# 4. Show Status
Write-Host ""
Write-Host "📊 Container Status:" -ForegroundColor Cyan
docker-compose ps

# 5. Show Access URLs
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "✅ SYSTEM ONLINE" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "🌐 Frontend (Dashboard):   http://localhost:3000" -ForegroundColor White
Write-Host "   Strategy Builder:       http://localhost:3000/strategy-builder" -ForegroundColor White
Write-Host "   Portfolio View:         http://localhost:3000/portfolio" -ForegroundColor White
Write-Host ""
Write-Host "🔌 Backend API:            http://localhost:8000" -ForegroundColor White
Write-Host "   API Docs (Swagger):     http://localhost:8000/docs" -ForegroundColor White
Write-Host "   API Health:             http://localhost:8000/health" -ForegroundColor White
Write-Host ""
Write-Host "💾 Database:               localhost:5432" -ForegroundColor White
Write-Host "   User: user" -ForegroundColor Gray
Write-Host "   Database: agentic_alpha" -ForegroundColor Gray
Write-Host ""
Write-Host "📋 Useful Commands:" -ForegroundColor Cyan
Write-Host "   View logs:              docker-compose logs -f" -ForegroundColor Gray
Write-Host "   View backend logs:      docker-compose logs -f backend" -ForegroundColor Gray
Write-Host "   Run simulation:         .\run_simulation.ps1" -ForegroundColor Gray
Write-Host "   Stop services:          docker-compose down" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "Ready for paper trading! 🚀" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# docker-compose logs -f
