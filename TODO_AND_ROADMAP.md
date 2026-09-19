# TODO & Roadmap

Текущие задачи, бэклог, tech debt и долгосрочные планы.

> **Канонический backlog:** `docs/specs/backlog.json` (version 4, 45/53 done, 8 pending).
> **Pipeline state:** `docs/specs/pipeline-state.yaml` (active task: one-run-completion — final QA).
> **Архитектура:** `ARCHITECTURE.md`.

---

## Текущий статус

**Active task:** one-run-completion (Wave 1 Backend + Wave 2 Frontend) — ✅ ALL DONE (2026-09-19)

### One-Run Completion (2026-09-19)

**Wave 1 — Backend (coder):**
- ✅ Local TF-IDF embedding provider (`EMBEDDING_PROVIDER=local`) — офлайн-режим семантического поиска без FRIDA
- ✅ `embedding_factory.py` (frida|local|auto + probe с таймаутом + fallback), wiring в `main.py` lifespan, vocab save/load
- ✅ `/api/health` + `/api/embeddings/status` сообщают активный провайдер (`embedding.provider`)
- ✅ Кросс-батчевая стабильность индексов: append-only vocab + frozen IDF (ревью-фикс Major-1: re-sort ломал ранее сохранённые векторы, cos=0.0; после фикса cos=1.0, 5 регрессионных тестов)

**Wave 2 — Frontend (ui-coder):**
- ✅ **D.8** Batch Upload UI: DropZone `multiple` + batch-список + `submitBatch` → `/batch-results/:id` (BatchResultsPage)
- ✅ **N.MAJ.3** ViewMode "Структура": третий Tab + StructureTab (дерево совпадений по словарям, match-count Badge)
- ✅ Semantic-бейдж «FRIDA»/«Локальный режим (TF-IDF)» из `embedding_provider` (топ-бар + панель)
- ✅ Feedback wiring: like/dislike → `POST /api/feedback` (optimistic UI + error snackbar) — known-issues #1/#2 закрыты
- ✅ JK7 (чёрный прямоугольник dict-editor) + JK6 (контраст markdown) + tech-debt (Icon opacity → токен)
- ✅ Ревью-фиксы Major-2: адаптивная сетка dashboard (375/768), wrap-фиксы, provider-aware бейдж + тест

**Final QA (tester, 2026-09-19):**
- ✅ Полная батарея: tsc 0; vitest 624/624; eslint 0 errors (1 pre-existing warning); pytest 2231 passed / 1 skipped
- ✅ **IP-1.5** is_exact e2e (автоматизирован, SYNTHETIC data): API-проверки 28/28 (exact_bow match + offsets, near-miss не флагается), DOM `highlight-exact` только на точном совпадении, vision-gate PASS (`e2e-isexact-1440.png` + `ai-analysis-e2e-isexact-1440.md`)
- ✅ Batch flow e2e: 3 синтетических RTF → submitBatch → poll → результаты доступны
- ✅ Local semantic search e2e: `EMBEDDING_PROVIDER=local`, индексация, semantic (token-exact) + hybrid (морфология) поиск, provider=local в `/api/health`
- 🐛 Найдены и исправлены 3 UI-бага IP-1.5 (HighlightRenderer exact-preference, видимый dotted-underline индикатор DR-1, счётчик совпадений на отдельной строке) — отчёт: `docs/specs/test-report-one-run-completion.md`

**Baseline (verified 2026-09-19):**
- `tsc -b --force` → ExitCode 0
- `vitest run` → 624/624 passing (60 files)
- `eslint .` → 0 errors (1 pre-existing warning `useMiningState.ts`)
- Backend pytest → 2231 passed / 1 skipped

**Предыдущие вехи см. в git history / docs/specs/** (Track B Mining Panel ✅ 2026-07-12; maintenance 2026-07-13 — tsc -b --force миграция, rule 06, getProviders fix).

---

## Completed (45/53 backlog items)

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

### Master Plan Tracks A-E (2026-07-07..08)
- ✅ Track A (P0): Quality gates — pre-commit hook (husky+lint-staged), CI workflow, VSCode settings
- ✅ Track B (P1): Type hygiene — 7 type fixes, 7 casts REMOVED, 0 added
- ✅ Track C (P2): Tech-debt inventory — `docs/specs/tech-debt-inventory.md`
- ✅ Track D (P2): DS drift detection — `scripts/check-ds-drift.ts`, weekly CI cron
- ✅ Track E (P3): Code quality automation — Vite manualChunks, bundle visualizer, eslint rule, knip CI

### Master Plan Track B — Quick Win Mining Panel (2026-07-09..12)
- ✅ B.1 Backend: dict_mining.py (9 methods) + routers/mining.py (6 endpoints) + prompts/mining.yaml (5 prompts) + SQLite (5 tables) — 46/46 tests
- ✅ B.2 Frontend: MiningPanel (3 tabs: Similar / FN / Audit) + click-to-add integration — 61/61 DictionaryEditor tests preserved
- ✅ Reviewer: APPROVED iteration 1/3 (5 minor issues, 0 critical)
- ✅ Visual gate: PASSED iteration 3/3 (CDP-verified on 375/768/1440, 4 fixes applied)
- ✅ Final QA: PASSED (12 new MiningPanel tests, vitest 564/565 — getProviders fixed separately 2026-07-13)
- ✅ Vision-анализ: 5/5 pages PASS with gpt-5.4 (benchmark run, fallback chain updated)

### LexiCore Phase 2 — FE Dictionary Editor
- ✅ 31 файл: DictionaryEditorPage + 21 компонент + types/hooks/constants
- ✅ 61/61 tests, tsc clean, 0 bugs
- ✅ Visual gate: Chunk 1 passed iter 3/3, Chunk 2 passed iter 1/3

---

## Pending Backlog (8 items)

### Legacy pending (1 item)

| ID | Задача | Приоритет | Объём | Статус |
|----|--------|-----------|-------|--------|
| IP-5.1 | Runtime фильтрация по `attribute_tree` | Low | M | ⏳ `attribute_tree` парсится и хранится, но search.py не использует. Нужен источник метаданных звонка (CRM) |

### Done 2026-09-19 (was legacy pending / deferred)

| ID | Задача | Статус |
|----|--------|--------|
| IP-1.5 | Визуальная проверка `is_exact` подсветки в браузере | ✅ DONE 2026-09-19 — автоматизирована e2e (SYNTHETIC data, API 28/28 + vision PASS); найдены и закрыты 3 UI-бага (HighlightRenderer exact-preference, видимый DR-1 индикатор, счётчик совпадений). Артефакты: `docs/specs/screenshots/e2e-isexact-1440.png` + `ai-analysis-e2e-isexact-1440.md`, отчёт `docs/specs/test-report-one-run-completion.md` |
| N.MAJ.3 | ViewMode "Структура" (третий Tab ResultsPage) | ✅ DONE 2026-09-19 — W2/N.MAJ.3: `'structure'` возвращён в union + StructureTab (дерево совпадений по словарям с match-count Badge), тесты + visual gate |
| D.8 | Batch Upload UI (multi-file upload + BatchResultsPage) | ✅ DONE 2026-09-19 — W2/D.8: DropZone `multiple` + batch-список + `submitBatch` → `/batch-results/:id`; batch flow e2e (3 synthetic RTF → poll → results) PASS |

### Phase G — Dictionary Mining v2 (7 items, all low priority)

Продвинутый mining pipeline с active learning. Не блокирует ничего, не стартовал.

| ID | Задача | Объём | Описание |
|----|--------|-------|---------|
| DM-3.0 | ASR-repair + dedup + morph coverage test | M | Предобработка корпуса: ASR-ремонт, дедупликация, тест coverage морфологии |
| DM-3.1 | LLM-разметка корпуса | L | Пофразовый + dialogue summary + relevance_classify через LLM |
| DM-3.2 | TopicScout: TopicModeler + Mahalanobis | M | Topic modeling + outlier detection для discovery |
| DM-3.3 | Active Learning loop | L | 5 итераций × 20 диалогов, human-in-the-loop |
| DM-3.4 | Phrase extraction pipeline | L | S4 + BOW dry-run + XML-sanitizer для auto-extract фраз |
| DM-3.5 | Dictionary surgery | L | S6 + S15-light + жадный set cover для auto-fix словаря |
| DM-3.6 | Валидация + итерация | M | A/B тестирование, 3-5 циклов до дельты <2% |

---

## Next: Phase F (optional, after Track B done — Track B IS done)

Track B fully complete. Phase F optional feature development. NOT STARTED.

| # | Задача | Объём | Статус |
|---|--------|-------|--------|
| F.1 | Phase 4 dialogue enhancement (backend logic) | M | Not started |
| F.2 | `getProviders` fix (pre-existing test failure) | S | ✅ DONE 2026-07-13 (commit by coder agent, 14/14 passing) |
| F.3 | SpeechLab UI (устаревший UI-2 rework, 20-27 дней) | XL | Not started |
| F.4 | BE performance optimization | M | Not started |

---

## Tech Debt (from Track C inventory + auditor concerns)

> **Note:** Items 1-4 (ResultsPage ViewMode cast, inline imports, Icon opacity, placeholderFile hack) и item 6 (SpeechLabTree API rot) — **FIXED** в Master Plan Track B (Type Hygiene, 2026-07-07). Оставлены для истории.

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

| Test | Причина | Severity | Статус |
|------|---------|----------|--------|
| `client.test.ts getProviders` | Test expected `method: 'GET'`, impl uses fetch default (no method) — test was inconsistent with 3 sibling GET tests | Low | ✅ FIXED 2026-07-13 (test aligned with codebase convention, 14/14 passing) |
| FastAPI `_IncludedRouter.path` (3 tests) | Version compat, NOT related to UI-2.5/2.6 | Low | ⏳ Still pre-existing |

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
| ~~D.8~~ | **Batch Upload UI** | ✅ DONE 2026-09-19 (one-run-completion W2/D.8) — перенесено в «Done 2026-09-19» выше |

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
| `docs/specs/backlog.json` | Канонический backlog (version 4, 45/53 done) |
| `docs/specs/pipeline-state.yaml` | Active pipeline state |
| `docs/improvement-plan.md` | Phases 1-7 + pipeline history |
| `PROJECT_MAP.md` | File structure map |
| `.loops/known-issues.md` | 11 tracked issues (11 fixed/documented, 0 open) |
