# dump-openapi-spec.ps1
# Дампит OpenAPI спецификацию из запущенного FastAPI backend в docs/openapi.json
# Использование: powershell -File scripts/dump-openapi-spec.ps1

$backendUrl = "http://localhost:8000/api/health"
$specUrl = "http://localhost:8000/openapi.json"
$outputDir = "docs"
$outputFile = "$outputDir/openapi.json"

Write-Host "=== OpenAPI Spec Dump ===" -ForegroundColor Cyan

# Проверить что backend запущен
try {
    $health = Invoke-RestMethod -Uri $backendUrl -Method GET -TimeoutSec 5 -ErrorAction Stop
    Write-Host "Backend is running on port 8000" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Backend not running on localhost:8000" -ForegroundColor Red
    Write-Host "Start it with: cd backend && uvicorn app.main:app --port 8000" -ForegroundColor Yellow
    exit 1
}

# Создать директорию docs если нет
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    Write-Host "Created directory: $outputDir" -ForegroundColor Gray
}

# Скачать спецификацию
try {
    $spec = Invoke-RestMethod -Uri $specUrl -Method GET -TimeoutSec 10 -ErrorAction Stop
    $specJson = $spec | ConvertTo-Json -Depth 50
    Set-Content -Path $outputFile -Value $specJson -Encoding UTF8
    Write-Host "Spec saved to: $outputFile" -ForegroundColor Green
    
    # Статистика
    $paths = ($spec.paths | Get-Member -MemberType NoteProperty).Count
    $schemas = 0
    if ($spec.components -and $spec.components.schemas) {
        $schemas = ($spec.components.schemas | Get-Member -MemberType NoteProperty).Count
    }
    Write-Host "Endpoints: $paths" -ForegroundColor Cyan
    Write-Host "Schemas: $schemas" -ForegroundColor Cyan
    Write-Host "OpenAPI version: $($spec.openapi)" -ForegroundColor Cyan
    Write-Host "API title: $($spec.info.title)" -ForegroundColor Cyan
} catch {
    Write-Host "ERROR: Failed to fetch OpenAPI spec from $specUrl" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Done! To use offline, change openapi-schema-explorer command to:" -ForegroundColor Yellow
Write-Host "  [""npx"", ""-y"", ""mcp-openapi-schema-explorer@latest"", ""docs/openapi.json"", ""--output-format"", ""json""]" -ForegroundColor Gray
