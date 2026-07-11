# ============================================================================
# CallCenterAI Documentation Generator
# Model: GLM-5.2 via Beeline AI API (api.ai.beeline.ru)
# ============================================================================

# --- Configuration ----------------------------------------------------------
$ApiKey   = "<REDACTED>"
$BaseUrl  = "https://api.ai.beeline.ru/api/v3"
$Model    = "GLM-5.2"
$OutputDir = "docs/openwiki"

# Retry settings for 429 / 504 / timeouts
$MaxRetries     = 5
$RetryDelaySec  = 30
$RequestTimeout = 900

# --- Helpers ----------------------------------------------------------------
function Log-Step { param($m) Write-Host ""; Write-Host "=== $m ===" -ForegroundColor Cyan }
function Log-Info { param($m) Write-Host "[INFO] $m" -ForegroundColor Gray }
function Log-Ok   { param($m) Write-Host "[OK]   $m" -ForegroundColor Green }
function Log-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Log-Err  { param($m) Write-Host "[ERR]  $m" -ForegroundColor Red }

# --- Banner -----------------------------------------------------------------
Write-Host ""
Write-Host "  CallCenterAI Documentation Generator" -ForegroundColor White
Write-Host "  Model:    $Model" -ForegroundColor White
Write-Host "  Endpoint: $BaseUrl" -ForegroundColor White
Write-Host "  Output:   $OutputDir" -ForegroundColor White
Write-Host ""

# --- Step 1: Prepare output directory ---------------------------------------
Log-Step "Step 1: Prepare output directory"
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    Log-Ok "Created: $OutputDir"
} else {
    Log-Info "Already exists: $OutputDir"
}

# --- Step 2: Collect project structure --------------------------------------
Log-Step "Step 2: Collect project structure"

$searchPaths = @("src","backend","scripts")
$existingPaths = $searchPaths | Where-Object { Test-Path $_ }
if ($existingPaths.Count -eq 0) {
    Log-Warn "No standard source dirs found, using current directory"
    $existingPaths = @(".")
}

$extensions = @("*.ts","*.tsx","*.js","*.jsx","*.json","*.py","*.md","*.yaml","*.yml")
$projectFiles = @()
foreach ($ext in $extensions) {
    foreach ($p in $existingPaths) {
        $found = Get-ChildItem -Path $p -Recurse -Include $ext -ErrorAction SilentlyContinue |
                 Where-Object { $_.FullName -notmatch "node_modules" -and
                                $_.FullName -notmatch "\\.test\\." -and
                                $_.FullName -notmatch "\\.spec\\." -and
                                $_.FullName -notmatch "\\.d\\.ts" }
        if ($found) { $projectFiles += $found }
    }
}
$projectFiles = $projectFiles | Sort-Object FullName -Unique | Select-Object -First 60
Log-Info "Found $($projectFiles.Count) source files"

# Read sample file contents (limit size to avoid huge prompts)
$fileContents = ""
$totalChars = 0
$maxChars   = 30000
foreach ($file in $projectFiles) {
    if ($totalChars -ge $maxChars) { break }
    $rel = $file.FullName.Replace((Get-Location).Path + "\", "")
    $content = Get-Content -Path $file.FullName -Raw -ErrorAction SilentlyContinue
    if ($content) {
        if ($content.Length -gt 2000) { $content = $content.Substring(0,2000) + "..." }
        $fileContents += "### FILE: $rel`n```````n$content`n``````n`n"
        $totalChars += $content.Length
    }
}
Log-Info "Collected $totalChars chars of file content"

# --- Step 3: Build prompt ---------------------------------------------------
Log-Step "Step 3: Build prompt"

$prompt = @"
You are an expert technical documentation generator. Analyze the following codebase and generate comprehensive, professional documentation in Markdown format.

PROJECT INFORMATION:
- Name: CallCenterAI
- Type: AI-powered call center solution
- Files analyzed: $($projectFiles.Count)

PROJECT STRUCTURE:
$($projectFiles | ForEach-Object { $_.FullName.Replace((Get-Location).Path + "\", "") } | Out-String)

SAMPLE FILE CONTENTS:
$fileContents

Generate documentation with these sections:
1. PROJECT OVERVIEW - brief description, goals, target audience
2. TECHNOLOGY STACK - backend, frontend, database, infrastructure
3. CORE FEATURES - list and describe each major feature
4. ARCHITECTURE - system overview, component interactions, data flow
5. INSTALLATION & SETUP - prerequisites, steps, configuration
6. USAGE GUIDE - how to run, examples
7. API REFERENCE - endpoints, request/response formats, auth
8. CONFIGURATION - env variables, config files, defaults
9. DEPLOYMENT - production steps, scaling, monitoring
10. TROUBLESHOOTING - common issues and solutions

IMPORTANT:
- Use professional technical writing
- Include code examples where appropriate
- Use proper Markdown formatting with headings and code blocks
- Output ONLY the documentation, no meta-commentary
"@

Log-Info "Prompt length: $($prompt.Length) chars"

# --- Step 4: Call Beeline AI API (with retry) -------------------------------
Log-Step "Step 4: Call Beeline AI API ($Model)"

$headers = @{
    "Authorization" = "Bearer $ApiKey"
    "Content-Type"  = "application/json"
}

$body = @{
    model       = $Model
    messages    = @(
        @{ role = "system"; content = "You are an expert technical documentation generator. Generate comprehensive, professional documentation in Markdown format with code examples and clear structure." },
        @{ role = "user";   content = $prompt }
    )
    temperature = 0.7
    max_tokens  = 16000
    stream      = $false
} | ConvertTo-Json -Depth 10

$attempt = 0
$success = $false
$response = $null

while (-not $success -and $attempt -lt $MaxRetries) {
    $attempt++
    Log-Info "Attempt $attempt/$MaxRetries ..."
    $startTime = Get-Date
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/chat/completions" `
                                      -Method Post `
                                      -Headers $headers `
                                      -Body $body `
                                      -ContentType "application/json" `
                                      -TimeoutSec $RequestTimeout
        $duration = ((Get-Date) - $startTime).TotalSeconds
        Log-Ok "API call succeeded in $([math]::Round($duration,1))s"
        $success = $true
    } catch {
        $duration = ((Get-Date) - $startTime).TotalSeconds
        $status = $null
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
        }
        Log-Err "Attempt $attempt failed after $([math]::Round($duration,1))s (HTTP $status): $($_.Exception.Message)"

        if ($status -eq 429) {
            Log-Warn "Rate limited (429). Waiting $RetryDelaySec s before retry..."
            Start-Sleep -Seconds $RetryDelaySec
        } elseif ($status -eq 504 -or $status -eq 502 -or $status -eq 503) {
            Log-Warn "Server error ($status). Waiting $RetryDelaySec s before retry..."
            Start-Sleep -Seconds $RetryDelaySec
        } else {
            Log-Err "Non-retriable error. Stopping."
            break
        }
    }
}

# --- Step 5: Save documentation ---------------------------------------------
if ($success -and $response) {
    Log-Step "Step 5: Save documentation"

    $documentation = $response.choices[0].message.content
    $outputPath = Join-Path $OutputDir "README.md"

    # Save as UTF-8 (with BOM for Windows compatibility)
    $utf8WithBom = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText((Resolve-Path $OutputDir).Path + "\README.md", $documentation, $utf8WithBom)

    $fileSize = (Get-Item $outputPath).Length
    Log-Ok "Documentation saved: $outputPath"
    Log-Info "File size: $([math]::Round($fileSize/1KB,2)) KB"

    # --- Preview ------------------------------------------------------------
    Log-Step "Preview (first 30 lines)"
    Get-Content $outputPath | Select-Object -First 30

    Write-Host ""
    Write-Host "================================================" -ForegroundColor Green
    Write-Host " DONE! Documentation generated by $Model" -ForegroundColor Green
    Write-Host " File: $outputPath" -ForegroundColor Green
    Write-Host " Size: $([math]::Round($fileSize/1KB,2)) KB" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Green
} else {
    Log-Err "All retries exhausted. Documentation NOT generated."
    Log-Info "Possible causes:"
    Log-Info "  - GLM-5.2 rate limit (429) - wait 5-10 min and retry"
    Log-Info "  - Server timeout (504) - try again later"
    Log-Info "  - Network issues - check VPN/connection"
    exit 1
}
