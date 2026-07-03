# Запуск Chrome с Remote Debugging для playwright-mcp
$chromePath = "<chrome>"
$debugPort = 9222
$userDataDir = "<chrome-debug-profile>"

# Проверить, слушает ли уже порт
$portCheck = Test-NetConnection -ComputerName localhost -Port $debugPort -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
if ($portCheck.TcpTestSucceeded) {
    Write-Host "Chrome already running on port $debugPort" -ForegroundColor Green
    exit 0
}

# Запустить Chrome
if (Test-Path $chromePath) {
    Start-Process $chromePath -ArgumentList "--remote-debugging-port=$debugPort", "--user-data-dir=$userDataDir", "--no-first-run"
    Start-Sleep -Seconds 3
    
    $verify = Test-NetConnection -ComputerName localhost -Port $debugPort -WarningAction SilentlyContinue
    if ($verify.TcpTestSucceeded) {
        Write-Host "Chrome started successfully on port $debugPort" -ForegroundColor Green
    } else {
        Write-Host "ERROR: Chrome started but port $debugPort not responding" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "ERROR: Chrome not found at $chromePath" -ForegroundColor Red
    exit 1
}
