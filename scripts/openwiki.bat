@echo off
setlocal enabledelayedexpansion

REM OpenWiki Switcher - быстрый переключатель моделей
REM Usage: openwiki.bat [model] [message]

set MODEL=%1
set MESSAGE=%2

REM Список моделей
set MODELS=claude-opus-4-6 claude-sonnet-4-5 gpt-5.4 gpt-5.2-codex GLM-5.2 Qwen3.6-35B GigaChat-Max yandexgpt-5 gemini-2.5-pro

REM Проверка HELP
if /i "%1"=="-help" (
    echo OpenWiki Switcher - быстрый запуск OpenWiki с разными моделями
    echo.
    echo Доступные модели:
    echo   claude-opus-4-6
    echo   claude-sonnet-4-5
    echo   gpt-5.4
    echo   gpt-5.2-codex
    echo   GLM-5.2
    echo   Qwen3.6-35B
    echo   GigaChat-Max
    echo   yandexgpt-5
    echo   gemini-2.5-pro
    echo.
    echo Использование:
    echo   openwiki.bat [model] "сообщение"
    echo   openwiki.bat -init "сообщение"
    echo   openwiki.bat -update "сообщение"
    exit /b 0
)

REM Проверка INIT
if /i "%1"=="-init" (
    if "%MESSAGE%"=="" (
        echo Ошибка: нужно указать сообщение
        exit /b 1
    )
    set MODEL=%MODEL%
    if "!MODEL!"=="" set MODEL=claude-sonnet-4-5
    npm exec openwiki -- --init "!MESSAGE!" --modelId !MODEL!
    exit /b 0
)

REM Проверка UPDATE
if /i "%1"=="-update" (
    if "%MESSAGE%"=="" (
        echo Ошибка: нужно указать сообщение
        exit /b 1
    )
    set MODEL=%MODEL%
    if "!MODEL!"=="" set MODEL=claude-sonnet-4-5
    npm exec openwiki -- --update "!MESSAGE!" --modelId !MODEL!
    exit /b 0
)

REM Если модель не указана, используем по умолчанию
if "!MODEL!"=="" (
    set MODEL=claude-sonnet-4-5
)

REM Проверка существования модели
set FOUND=0
for %%m in (%MODELS%) do (
    if /i "!MODEL!"=="%%m" set FOUND=1
)

if !FOUND!==0 (
    echo Модель "!MODEL!" не найдена!
    echo Доступные модели:
    echo   claude-opus-4-6
    echo   claude-sonnet-4-5
    echo   gpt-5.4
    echo   gpt-5.2-codex
    echo   GLM-5.2
    echo   Qwen3.6-35B
    echo   GigaChat-Max
    echo   yandexgpt-5
    echo   gemini-2.5-pro
    exit /b 1
)

echo Запуск OpenWiki с моделью: !MODEL!
echo.
npm exec openwiki -- -p "!MESSAGE!" --modelId !MODEL!
