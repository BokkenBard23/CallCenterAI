# OpenWiki Switcher - быстрый переключатель моделей
# Usage: .\openwiki.ps1 [model] "message"

param(
    [string]$Model = "claude-sonnet-4-5",
    [string]$Message = "",
    [switch]$Init,
    [switch]$Update,
    [switch]$Help
)

# Доступные модели
$models = @(
    "claude-opus-4-6",
    "claude-sonnet-4-5",
    "gpt-5.4",
    "gpt-5.2-codex",
    "GLM-5.2",
    "Qwen3.6-35B",
    "GigaChat-Max",
    "yandexgpt-5",
    "gemini-2.5-pro"
)

if ($Help) {
    Write-Host "OpenWiki Switcher - быстрый запуск OpenWiki с разными моделями" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Доступные модели:" -ForegroundColor Yellow
    $models | ForEach-Object { Write-Host "  - $_" }
    Write-Host ""
    Write-Host "Использование:" -ForegroundColor Cyan
    Write-Host "  .\openwiki.ps1 [модель] 'сообщение'" -ForegroundColor White
    Write-Host "  .\openwiki.ps1 -Init 'сообщение'" -ForegroundColor White
    Write-Host "  .\openwiki.ps1 -Update 'сообщение'" -ForegroundColor White
    Write-Host "  .\openwiki.ps1 -Help" -ForegroundColor White
    Write-Host ""
    Write-Host "Примеры:" -ForegroundColor Cyan
    Write-Host "  .\openwiki.ps1 claude-opus-4-6 'Что это за проект?'" -ForegroundColor White
    Write-Host "  .\openwiki.ps1 gpt-5.4 'Какая архитектура проекта?'" -ForegroundColor White
    Write-Host "  .\openwiki.ps1 -Init 'Создай документацию'" -ForegroundColor White
    exit 0
}

# Проверка модели
if ($models -notcontains $Model) {
    Write-Host "Модель '$Model' не найдена!" -ForegroundColor Red
    Write-Host "Доступные модели:" -ForegroundColor Yellow
    $models | ForEach-Object { Write-Host "  - $_" }
    exit 1
}

# Формирование команды
$command = "npm exec openwiki -- -p"
if ($Message) {
    $command += " '$Message'"
}
$command += " --modelId $Model"

if ($Init) {
    $command = "npm exec openwiki -- --init '$Message' --modelId $Model"
}
if ($Update) {
    $command = "npm exec openwiki -- --update '$Message' --modelId $Model"
}

Write-Host "Запуск OpenWiki с моделью: $Model" -ForegroundColor Green
Write-Host "Команда: $command" -ForegroundColor Gray
Write-Host ""

# Выполнение команды
Invoke-Expression $command
