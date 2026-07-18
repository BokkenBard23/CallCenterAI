<#
    .SYNOPSIS
        Запускает OpenWiki для генерации/обновления wiki-документации
        в текущем репозитории <repo>.

    .DESCRIPTION
        - Проверяет, что openwiki установлен и доступен в PATH.
        - Проверяет наличие ~/.openwiki/.env (провайдер, ключ модели).
        - Запускает интерактивный режим code (документация репозитория
          пишется в ./openwiki/, поддерживаются AGENTS.md и CLAUDE.md).
        - Если папки openwiki/ ещё нет — OpenWiki сам создаст её
          и сгенерирует начальную документацию.
        - После выхода из чата окно консоли НЕ закрывается автоматически,
          чтобы можно было прочитать финальный вывод и ошибки.

    .USAGE
        .\start-openwiki.ps1
        .\start-openwiki.ps1 -Message "Сначала опиши API-роуты"
        .\start-openwiki.ps1 -OneShot        # print-mode, без интерактива
        .\start-openwiki.ps1 -Update         # только обновить существующую wiki
#>

[CmdletBinding()]
param(
    [string]$Message = "Please generate documentation for this repository",
    [switch]$Update,
    [switch]$OneShot
)

$ErrorActionPreference = "Stop"
$repoRoot = "<repo>"

Write-Host "=== OpenWiki launcher ===" -ForegroundColor Cyan

# --- 0. Проверка репозитория ---
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot ".git"))) {
    Write-Warning "В $repoRoot не найден .git — OpenWiki работает с git-репозиторием."
}

# --- 1. Проверка, что openwiki установлен ---
$openwikiCmd = Get-Command openwiki -ErrorAction SilentlyContinue
if (-not $openwikiCmd) {
    Write-Host "openwiki не найден в PATH. Установите:" -ForegroundColor Red
    Write-Host "    npm install -g openwiki" -ForegroundColor Yellow
    Read-Host "Нажмите Enter для выхода"
    exit 1
}
Write-Host ("openwiki: " + $openwikiCmd.Source) -ForegroundColor Green

# --- 2. Проверка конфигурации ~/.openwiki/.env ---
$envFile = Join-Path $env:USERPROFILE ".openwiki\.env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host "Не найден $envFile" -ForegroundColor Red
    Write-Host "Сначала запустите 'openwiki --init' и пройдите мастер настройки провайдера/модели." -ForegroundColor Yellow
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# Покажем безопасную сводку конфигурации (без секретов)
Write-Host "--- Конфигурация (~/.openwiki/.env, секреты скрыты) ---" -ForegroundColor DarkGray
Get-Content -LiteralPath $envFile | ForEach-Object {
    if ($_ -match '^(#|$)') { return $_ }
    if ($_ -match 'KEY|TOKEN|SECRET') {
        $name = ($_ -split '=', 2)[0]
        return "$name=***REDACTED***"
    }
    return $_
} | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

# --- 3. Проверка существования wiki ---
$wikiDir = Join-Path $repoRoot "openwiki"
$wikiExists = Test-Path -LiteralPath $wikiDir
if ($wikiExists) {
    Write-Host "Wiki уже существует: $wikiDir" -ForegroundColor Green
    if (-not $Update -and -not $PSBoundParameters.ContainsKey('Message')) {
        Write-Host "Подсказка: используйте -Update для обновления существующей wiki." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "Папки openwiki/ ещё нет — OpenWiki создаст её и сгенерирует начальную документацию." -ForegroundColor Yellow
}

# --- 4. Сборка аргументов запуска ---
$args = @()
if ($OneShot) {
    $args += @("-p")  # one-shot: вывести ответ и выйти
}
if ($Update) {
    $args += @("--update")
} elseif (-not $wikiExists) {
    $args += @("--init")
}
if ($Message) {
    $args += $Message
}

Write-Host "--- Запуск ---" -ForegroundColor Cyan
Write-Host "cwd:    $repoRoot" -ForegroundColor DarkGray
Write-Host "cmd:    openwiki $($args -join ' ')" -ForegroundColor DarkGray
Write-Host ""

Set-Location -LiteralPath $repoRoot
& openwiki @args
$exitCode = $LASTEXITCODE

Write-Host ""
Write-Host "=== OpenWiki завершился с кодом $exitCode ===" -ForegroundColor Cyan
Read-Host "Нажмите Enter, чтобы закрыть окно"
exit $exitCode
