# TODO & Roadmap

Текущие задачи, бэклог, tech debt и долгосрочные планы.

> **Канонический backlog:** `docs/specs/backlog.json` (version 3, 31/33 done).
> **Pipeline state:** `docs/specs/pipeline-state.yaml` (active task: Track B — Quick Win Mining Panel).
> **Архитектура:** `ARCHITECTURE.md`.

---

## Текущий статус

**Active task:** Track B — Quick Win Mining Panel (2 chunks)
- Chunk 1 (Backend): dict_mining service + router + prompts + SQLite + models — **в работе**
- Chunk 2 (Frontend): MiningPanel UI (3 tabs + integration) — **pending**
- Visual gate: iteration 2/3, REJECTED (1 critical + 3 major mobile issues)
- `pipeline-state.yaml` → `master-plan-track-b-quick-win-mining-panel`

**Baseline (verified 2026-07-07):**
- `tsc -b --force` → ExitCode 0
- `vitest run` → 552/553 (1 pre-existing `client.test.ts getProviders`)
- `eslint .` → 0 errors
- DictionaryEditor: 61/61 tests pass

---

## Completed (31/33 backlog items)

### Pipelines 001-007 (базовый UI + backend)
- ✅ Pipeline 001: Начальный UI + backend (91 BE + 127 FE tests)
- ✅ Pipeline 002: 5 UI/UX фич (dict panel, cross-highlight, batch, history, theme)
- ✅ Pipeline 003: FRIDA embeddings + FAISS + hybrid search (478 BE tests)
- ✅ Pipeline 004: 6 critical UI fixes (highlight, tree, dark theme, feedback)
- ✅ Pipeline 005: SpeechLab 3-panel layout, XML tree, channel colors
- ✅ Pipeline 006: Bugfix (highlight.scss, CustomEvent, forwardRef)
- ✅ Pipeline 007: Полный frontend rework (411 FE, Lighthouse 92)

### Backend extensions (IP-1.1..IP-6.1)
- ✅ IP-1.1: `_fallback_match` переписан на BOW (33 теста)
- ✅ IP-1.2: `DictMatch` поля `cascade_order` + `is_exact_match` в api.ts
- ✅ IP-1.3: Дубли `_ASPECTUAL_PAIRS` удалены
- ✅ IP-1.4: `SavedState` возвращает `None` вместо ложных дефолтов
- ✅ IP-2.1: Batch RTF upload (`POST /api/upload/rtf/batch`, BATCH_MAX_FILES=10)
- ✅ IP-2.2: Batch analysis (`submit_batch`, `get_batch_status`, `get_batch_results`)
- ✅ IP-2.4: Export Excel/PDF (openpyxl, reportlab)
- ✅ IP-2.5 + ID-9: SqliteSessionStore (persistent, вместо PostgreSQL)
- ✅ IP-3.1: LLMResultHandler с JSON-валидацией
- ✅ IP-3.2..3.5: Sentiment, conflict, profanity, topic analysis
- ✅ IP-3.6: LLMOrchestrator (parallel mode via asyncio.gather)
- ✅ IP-3.7: AnalysisAnnotation (единый результат)
- ✅ IP-4.1..4.3: 12 категорий качества + endpoint + UI
- ✅ IP-5.2: Error classifier
- ✅ IP-5.5: RAG pipeline (FRIDA + LLM, собственная реализация)
- ✅ IP-6.1: Domain prompts (insurance/banking/healthcare)

### PII Masking (ID-4, hardened, 152-ФЗ)
- ✅ Presidio + 7 custom NER recognizers
- ✅ Variant A (strict blocking)
- ✅ 182 PII tests, INV-PII-1..6 верифицированы

### Night Shift
- ✅ Phase 4: Bug hunting (StatusBadge forwardRef, retryState, stale searchType)
- ✅ Phase 6: Senior review APPROVED

### MCP audit + security
- ✅ 7 credentials → env vars, spyware canary removed
- ✅ CORS restrict, filename sanitization, structured logging

### Master Plan Tracks A-D (2026-07-07)
- ✅ Track A (P0): Quality gates — pre-commit hook (husky+lint-staged), CI workflow, VSCode settings
- ✅ Track B (P1): Type hygiene — 7 type fixes, 7 casts REMOVED, 0 added
- ✅ Track C (P2): Tech-debt inventory — `docs/specs/tech-debt-inventory.md`
- ✅ Track D (P2): DS drift detection — `scripts/check-ds-drift.ts`, weekly CI cron

### LexiCore Phase 2 — FE Dictionary Editor
- ✅ 31 файл: DictionaryEditorPage + 21 компонент + types/hooks/constants
- ✅ 61/61 tests, tsc clean, 0 bugs
- ✅ Visual gate: Chunk 1 passed iter 3/3, Chunk 2 passed iter 1/3

---

## Pending Backlog (2 items)

| ID | Задача | Приоритет | Объём | Статус |
|----|--------|-----------|-------|--------|
| IP-1.5 | Визуальная проверка `is_exact` подсветки в браузере | Low | S | ⏳ Требует ручной проверки: загрузить XML с TERMINAL-кавычками, проверить подсветку |
| IP-5.1 | Runtime фильтрация по `attribute_tree` | Medium | M | ⏳ Единственный реальный backend pending. `attribute_tree` парсится и хранится, но search.py не использует. Нужен источник метаданных звонка (CRM) |

---

## Next: Master Plan Phase E (P3, ~2ч)

Code quality automation. NOT STARTED.

| # | Задача | Объём | Risk |
|---|--------|-------|------|
| E.1 | **Vite manualChunks** — split vendor bundles (react, beeline-ds, tanstack) | S | Low (additive config) |
| E.2 | **Bundle visualizer** (`rollup-plugin-visualizer`) — найти largest chunks | S | Low |
| E.3 | **eslint type-assertions rule** (`@typescript-eslint/consistent-type-assertions`) | S | Medium (может найти существующие casts) |
| E.4 | **knip в CI** — dead code detection (22 unused exports/types в DictionaryEditor) | S | Medium |

---

## Optional: Phase F

Next feature development. NOT STARTED.

| # | Задача | Объём |
|---|--------|-------|
| F.1 | Phase 4 dialogue enhancement (backend logic) | M |
| F.2 | `getProviders` fix (pre-existing test failure) | S |
| F.3 | SpeechLab UI (устаревший UI-2 rework, 20-27 дней) | XL |
| F.4 | BE performance optimization | M |

---

## Tech Debt (from Track C inventory + auditor concerns)

### Production code concerns

| # | Файл | Проблема | Severity |
|---|------|----------|----------|
| 1 | `ResultsPage.tsx:178` | `('structure' as ViewMode)` cast — type-system врёт. Правильно: расширить `ViewMode` union в api.ts | Medium |
| 2 | `ResultsPage.tsx:452,~252` | inline `import('../types/api').DictionaryNode[]` casts — анти-паттерн | Low |
| 3 | `BatchResultsPage.tsx:80` | `Icon style={{opacity:0.5}}` вместо DS-токена. Проверить disabled-state prop | Low |
| 4 | `useSpeechLabState.ts:135-148` | `placeholderFile` hack (`new File([], ...)`). Сделать `UploadedDictionary.file?: File` optional | Low |
| 5 | `StatusBadge.tsx:51` | `Icons.Hourglass` заместо `LoadingPlaceholder`. Проверить `.d.ts` | Low |
| 6 | `SpeechLabTree.tsx:53-60` | 4 пропса destructured as `_*` с `eslint-disable`. API rot — реализовать или удалить | Medium |
| 7 | `SpeechLabLayout.tsx:193` | `import { useState, useCallback }` после компонента (ES hoisting, но грязно) | Low |

### Pre-existing test failures

| Test | Причина | Severity |
|------|---------|----------|
| `client.test.ts getProviders` | 1 pre-existing failure | Low |
| FastAPI `_IncludedRouter.path` (3 tests) | Version compat, NOT related to UI-2.5/2.6 | Low |

---

## Deferred (низкий приоритет)

| # | Задача | Причина |
|---|--------|---------|
| D.1 | PostgreSQL migration (если SQLite перестанет справляться) | SQLite достаточно для текущей нагрузки |
| D.2 | SSE для real-time batch прогресса | Polling работает |
| D.3 | 2.6 Дедупликация совпадений | Низкий приоритет |
| D.4 | 5.3 HyDE (гипотетические эмбеддинги) | Низкий приоритет |
| D.5 | 5.4 Five analysis strategies | Низкий приоритет |
| D.6 | Large file refactoring (8 файлов >500 строк) | Defer до зелёного билда + CI |
| D.7 | State management refactor (useReducer → Zustand) | Крупная переработка |

---

## Long-term (Phase 7, 10+ дней)

| # | Задача | Объём | Источник |
|---|--------|-------|---------|
| 7.1 | Live-транскрипция (SIPREC/WebSocket) | XL | amazon-transcribe-live-call-analytics |
| 7.2 | Agent Assist (подсказки оператору в real-time) | L | QnABot + Bedrock KB |
| 7.3 | Regex-категоризация звонков (авто-маршрутизация) | M | amazon-transcribe |
| 7.4 | Плагинная система (CRM: Salesforce и др.) | L | — |

---

## Verification Protocol

После любого subagent fix:

1. **`npx tsc -b --force`** (НЕ `tsc --noEmit`!) → ExitCode 0
2. **`npx vitest run`** → no new failures (pre-existing documented)
3. **`npx eslint .`** → no new errors
4. НЕ доверять заявлению "tsc clean" без указания команды

---

## Источники

| Документ | Назначение |
|----------|-----------|
| `docs/specs/backlog.json` | Канонический backlog (version 3) |
| `docs/specs/pipeline-state.yaml` | Active pipeline state |
| `docs/improvement-plan.md` | Phases 1-7 + pipeline history |
| `PROJECT_MAP.md` §next_session_entry_point | Master Plan Phases E/F |
| `PROJECT_MAP.md` §tsc_build_recovery_2026_07_05 | Auditor concerns (tech debt) |
| `.loops/known-issues.md` | 11 tracked issues (9 fixed, 2 open) |
