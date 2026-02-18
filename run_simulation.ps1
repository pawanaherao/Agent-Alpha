# ============================================================================
# AGENTIC ALPHA - PAPER TRADING SIMULATION SCRIPT
# ============================================================================
# Runs continuous trading cycles for backtesting and paper trading
# Press Ctrl+C to stop

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "🚀 AGENTIC ALPHA - PAPER TRADING SIMULATION" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "" 

# Check if Docker services are running
Write-Host "🔍 Checking services..." -ForegroundColor Yellow

$backendUp = docker ps --filter "name=agent-alpha-backend" --filter "status=running" | Measure-Object
$postgresUp = docker ps --filter "name=agent-alpha-postgres" --filter "status=running" | Measure-Object

if ($backendUp.Count -eq 0) {
    Write-Host "❌ Backend service not running. Start with: docker-compose up" -ForegroundColor Red
    exit 1
}

if ($postgresUp.Count -eq 0) {
    Write-Host "⚠️  PostgreSQL not running. Database operations will be limited." -ForegroundColor Yellow
}

Write-Host "✅ Services OK" -ForegroundColor Green
Write-Host ""
Write-Host "Starting simulation loop... Press Ctrl+C to stop." -ForegroundColor Green
Write-Host ""

$cycle = 0

while ($true) {
    $cycle++
    $timestamp = Get-Date -Format "HH:mm:ss"
    
    # 1. Trigger Cycle
    Write-Host "[$timestamp] Cycle $cycle: Triggering cycle check..." -ForegroundColor Magenta -NoNewline
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/trigger-cycle" `
                                     -Method POST `
                                     -TimeoutSec 10 `
                                     -ErrorAction SilentlyContinue
        
        if ($response.StatusCode -eq 200) {
            Write-Host " ✅ DONE" -ForegroundColor Green
        } else {
            Write-Host " ⚠️  Status: $($response.StatusCode)" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host " ❌ Connection failed" -ForegroundColor Red
        Write-Host "   Ensure backend is running: docker compose logs backend" -ForegroundColor Red
    }
    
    # 2. Show latest trades (if PostgreSQL available)
    if ($postgresUp.Count -gt 0) {
        Write-Host "📊 Latest Trades:" -ForegroundColor Cyan
        try {
            docker exec agent-alpha-postgres psql -U user -d agentic_alpha -c `
                "SELECT symbol, signal_type, status, created_at FROM trades ORDER BY created_at DESC LIMIT 3;" `
                -ErrorAction SilentlyContinue 2> $null
        }
        catch {
            Write-Host "   (Database temporarily unavailable)" -ForegroundColor Gray
        }
    }
    
    # 3. Show execution summary
    try {
        $healthResponse = Invoke-WebRequest -Uri "http://localhost:8000/health" `
                                           -Method GET `
                                           -TimeoutSec 5 `
                                           -ErrorAction SilentlyContinue
        
        if ($healthResponse.StatusCode -eq 200) {
            $health = $healthResponse.Content | ConvertFrom-Json
            Write-Host "💚 System Status: $($health.status)" -ForegroundColor Green
        }
    }
    catch {
        Write-Host "💔 Backend unreachable" -ForegroundColor Red
    }
    
    # 4. Wait before next cycle
    Write-Host "⏳ Waiting 10 seconds before next cycle..." -ForegroundColor Gray
    Start-Sleep -Seconds 10
    Write-Host ""
}

