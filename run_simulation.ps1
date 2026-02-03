# Run Continuous Trading Simulation (Ctrl+C to stop)
Write-Host "🚀 Starting Live Paper Trading Simulation..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow

while ($true) {
    # 1. Trigger Cycle
    Write-Host "⏳ Triggering Cycle check..." -NoNewline
    $response = curl.exe -s -X POST http://localhost:8000/trigger-cycle
    Write-Host " DONE" -ForegroundColor Cyan
    
    # 2. Show latest trades
    Write-Host "📊 Latest Trades:" -ForegroundColor Magenta
    docker exec agentic_alpha_db psql -U user -d agentic_alpha -c "SELECT symbol, signal_type, status, created_at FROM trades ORDER BY created_at DESC LIMIT 3;"
    
    # 3. Wait 5 seconds
    Start-Sleep -Seconds 5
}
