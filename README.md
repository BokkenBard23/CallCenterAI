# CallCenterAI

Платформа анализа звонков колл-центра: транскрипция → SmartLogger morphological matching → LLM-анализ → PII-masking → semantic search.

## Документация

Полная документация поддерживается OpenWiki: **[openwiki/quickstart.md](openwiki/quickstart.md)** — начните отсюда, далее по ссылкам на архитектуру, воркфлоу, доменную логику, операции и тестирование.

## Быстрый старт

```bash
start.bat                                  # запуск проекта (frontend + backend + Postgres)
npm run dev                                # только frontend
cd backend && uv run uvicorn app.main:app --reload   # только backend
```
