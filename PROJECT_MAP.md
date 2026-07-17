# Карта проекта CallCenterAI

### meta

project: CallCenterAI
updated: 2026-07-07
version: 2.4
previous_version: 2.3 (2026-07-05 LexiCore Phase 2 + master_plan_next_session)
total_files: ~195
changed_since_last:
  - Master Plan Tracks A, B, C, D COMPLETE (2026-07-07). Фазы E и F — следующий шаг.
  - Track A (Quality Gates, P0, БЛОКЕР): pre-commit hook (husky+lint-staged, tsc -b --noEmit), .github/workflows/ci.yml (npm ci → typecheck → lint → test, block PR), .vscode/settings.json (tsconfig.app.json active project). Orchestrator verification protocol A.4 enforced.
  - Track B (Type Hygiene, P1): 7 type-level fixes — ViewMode union extended, UploadedDictionary.file optional, SpeechLabTree 4 unused props removed, ResultsPage inline import casts removed (5×), Icon disabled DS gap confirmed, LoadingPlaceholder DS gap confirmed, SpeechLabLayout hooks import lifted. 7 casts REMOVED, 0 added.
  - Track C (Tech-Debt Inventory, P2, read-only): docs/specs/tech-debt-inventory.md — 3 TODO/FIXME, 0 `as any` (Track B clean preserved!), 20 eslint-disable (all justified), 0 console.log/debugger в production, knip: 22 unused exports/types (DictionaryEditor + types/api.ts Phase 2 leftovers).
  - Track D (DS Drift Detection, P2): docs/specs/ds-prop-inventory.json (47 компонентов, 40.5 KB), scripts/check-ds-drift.ts (regex .d.ts parser + src/ grep), .github/workflows/ds-drift.yml (weekly Sunday cron + GitHub issue on drift). npm run check:ds-drift активен.
  - Quality gates infrastructure ACTIVE: pre-commit hook blocks commit с type error (verified via integration test), CI workflow блокирует PR, DS drift weekly cron настроен.
  - Baseline (verified orchestrator-ом 2026-07-07): tsc -b --force ExitCode 0, eslint 0 errors, vitest 552/553 (1 pre-existing client.test.ts getProviders).
  - Memory entities: track_a_complete, track_b_complete, track_c_complete, track_d_complete (с relations через INDEX).
  - Точка входа новой сессии: memory_open_nodes(['INDEX','track_d_complete','master_plan_next_session','tsc_composite_project_gotcha'])
  - LexiCore Port Phase 2 — FE Dictionary Editor UI COMPLETE (предыдущая сессия, сохранено в history)
  - Route /dictionary/:sessionId (lazy+ErrorBoundary в App.tsx) — редактор словарей ключевых фраз
  - 31 файл: DictionaryEditorPage.tsx + 21 компонент в src/components/DictionaryEditor/ (11 impl + 10 tests) + types/hooks/constants + модификации
  - Deps установлены: @tanstack/react-table@8.21.3 (headless table state mgmt), react-markdown@10.1.0 (AI summary rendering)
  - 2 chunks: Chunk 1 (Core CRUD editing — DictionaryEditorPage, DictionaryTreePanel, ConditionsTable+TanStack, SearchFilterBar, ConditionRowActions; AG-LEXICORE-PHASE2-FE-1), Chunk 2 (Assistance panels — AIAnalysisPanel Sidesheet, PhraseSuggestionsModal, DuplicatesModal, ValidationIssuesPanel, StatisticsPanel+WordFrequencyBar, XmlExportDialog; AG-LEXICORE-PHASE2-FE-2)
  - Channel color-coding via Badge semantic: ANY=neutral, OPERATOR=violet, CLIENT=success, SYSTEM hidden (BE gap)
  - jump-to-condition: DuplicatesModal/ValidationIssuesPanel → ConditionsTable highlightRowIdx + scrollIntoView
  - AbortController for cancel on close во всех 6 overlays с async fetch
  - 61/61 tests pass (35 Chunk 2 + 26 Chunk 1). tsc --noEmit ExitCode 0 (full project). 0 bugs.
  - Visual gate: Chunk 1 passed iter 3/3 (3 blocking issues fixed: C-1 TableCell→TableData, M-1 dark theme CSS tokens, M-2 focus-visible; D-1 Slider infinite loop surfaced+fixed), Chunk 2 passed iter 1/3
  - Controlled deviation: added GET /api/dictionary/{session_id} backend endpoint (~20 lines, additive) — FE не может получить дерево на mount (GET /tokens возвращает плоский DisplayToken[])
  - Memory entities created: CallCenterAI_Project, lexicore_phase2_fe_editor, beeline_ds_v25_patterns, pipeline_mcp_inventory, session_2026_07_05_summary
  - Артефакты: spec.md, spec-chunk-{1,2}.md, design-spec.md, design-spec-chunk-{1,2}.md, ui-implementation-brief.md (lock-in rubric 8.5/10), user-scenarios.json, implementation-chunk-{1,2}.md, visual-gate-chunk-{1,2}.md, review-chunk-{1,2}.md, test-report-chunk-{1,2}.md, lexicore-port-research.md (consolidated research)
  - Phase 4 dialogue enhancement (backend logic) — DEFERRED

### stack

frontend: React 18 + Vite 7 + TypeScript 5.9 + @beeline/design-system-react 2.5 + react-router-dom 7
backend: FastAPI + Pydantic 2 + FAISS + pymorphy3 + lxml + Presidio + slowapi
tests_fe: vitest + @testing-library/react
tests_be: pytest

### architecture

flow_fe: main.tsx → App.tsx (lazy routes) → pages → components/hooks → context (AnalysisContext reducer) + api/client.ts → FastAPI backend
flow_be: main.py (FastAPI app, lifespan startup hook for LLM limits) → routers/* (HTTP) → services/* (business logic) → models.py (pydantic) + prompts/*.yaml (YAML-driven LLM prompts via PromptManager)
storage: SqliteSessionStore (BE sessions + dictionaries in JSON blob) + LocalStorage (FE history) + FAISS (vector store)
llm: multi-provider orchestrator (GLM-5.2 via glm-xlarge/glm-xlarge-fast + Qwen3.5 via qwen-medium + Qwen3.6 via qwen-medium-preview + Ollama/YandexGPT/GigaChat fallback) with per-provider asyncio.Semaphore (GLM=2 shared, Qwen=3 each, total max 8 parallel), CircuitBreaker, parallel orchestrator mode (asyncio.gather), smart task→model routing, YAML-driven prompts (PromptManager), generic LLMResultValidator with fallback
search: иерархический по XML-словарю (search.py) + векторный FAISS (vector_store.py) + гибридный (hybrid_search.py: RRF k=60 + NER boost) + enhanced (search_enhanced: BM25 + LogOdds fusion + token explainability)
parser: xml_parser.py (SmartLogger XML → DictionaryNode) + logic_builder.py (PhraseGroup + logic_tree) + morph_matcher.py (BOW morph/exact, free order)
search_logic: logic tree (И/ИЛИ/НЕ) на основе PhraseGroup.operator + is_exception, NOT>AND>OR precedence (build_phrase_logic_tree → evaluate_phrase_logic_tree), GATE = node_matched AND NOT suppressed
time_gap: ExtraLimitations (real XML time-gap limits, NOT phrase-WITHOUT) — _parse_extra_limitations → _apply_time_gap_filter (_filter_start_end / _filter_parent / _apply_gap_filter / _find_channel_gaps). Requires DialogueTurn.start_offset/end_offset. No-op when RTF lacks timing.
remainder: SpeechLabRemainderRequest nodes — DictMatch.is_remainder flag set; catch-all fallback suppression of siblings — TODO (not blocking UI-3 display)
pii: Presidio (pii_masking.py + routers/pii.py)

### next_session_entry_point

**ПРИОРИТЕТ: Завершить генеральный план — Фаза E (P3, ~2ч) + опционально F. Tracks A-D COMPLETE.**

Полный план: memory entity `master_plan_next_session` (supersedes `quality_gates_plan`).
Root cause: memory entity `root_cause_analysis` + `tsc_composite_project_gotcha`.

**Точка входа (новая сессия):**
1. `memory_open_nodes(['INDEX', 'track_d_complete', 'master_plan_next_session', 'tsc_composite_project_gotcha'])`
2. Прочитать `docs/specs/tech-debt-inventory.md` (Track C output — факты для E)
3. Проверить baseline: `npx tsc -b --force` ExitCode 0; `npx vitest run` 552/553; `npx eslint .` 0 errors; `npm run check:ds-drift` (exit 1 = inventory gap, не blocker)
4. Начать Фазу E.1 (Vite manualChunks)

**Статус фаз (2026-07-07):**
- ✅ A (P0, COMPLETE): Quality gates — pre-commit hook, CI workflow, VSCode settings, verification protocol A.4.
- ✅ B (P1, COMPLETE): Type hygiene — 7 type-level fixes, 7 casts REMOVED, 0 added.
- ✅ C (P2, COMPLETE): Tech-debt inventory (read-only) — docs/specs/tech-debt-inventory.md. 0 `as any`, 0 console.log, 20 eslint-disable (all justified).
- ✅ D (P2, COMPLETE): DS drift detection — docs/specs/ds-prop-inventory.json (47 components), scripts/check-ds-drift.ts, .github/workflows/ds-drift.yml (weekly cron).
- ⏳ E (P3, ~2ч): Code quality automation — Vite manualChunks, bundle visualizer, eslint type-assertions rule, knip в CI. NOT STARTED.
- ⏳ F (optional): Next feature — Phase 4 dialogue enhancement / getProviders fix / SpeechLab UI / BE performance. NOT STARTED.

**Распределение ролей:**
- **pipeline-orchestrator** (главный): запускает фазы, ПЕРЕПРОВЕРЯЕТ tsc -b --force после каждого subagent, НЕ доверяет "tsc clean"
- **coder** (основной исполнитель): все задачи A-E (config/scripts/type fixes/inventory)
- **reviewer** (аудитор): second opinion после Фаз A, B, E
- **tester** (регрессия): vitest full suite после Фаз A, B, E
- **mcp-researcher** (DS inventory): Фаза D.1 только
- **ui-tester, designer, request-analyst** — НЕ НУЖНЫ (нет UI/design/spec tasks)

**КРИТИЧЕСКИЙ GOTCHA:** `tsc --noEmit` на composite project (root tsconfig с `files:[]`+`references`) = no-op, всегда ExitCode 0. 56 errors были невидимы 2+ недели. Использовать только `tsc -b --force` или `npm run typecheck`.

**Что НЕ делать:** рефакторить large files, менять state management, трогать backend, включать strict строже, доверять "tsc clean" без указания команды.

### hubs

- src/api/client.ts — центральный HTTP-клиент, импортируется всеми pages/hooks/SpeechLab
- src/context/AnalysisContext.tsx — глобальный state через reducer
- src/types/api.ts — TS-зеркало backend моделей
- src/hooks/useSpeechLabState.ts — агрегирует api + context
- backend/app/main.py — FastAPI app + регистрация всех роутеров и middleware
- backend/app/models.py — все pydantic-модели
- backend/app/services/llm.py — LLM-провайдеры (BeelineProvider=glm-xlarge, BeelineFastProvider=glm-xlarge-fast, Qwen35Provider=qwen-medium, Qwen36Provider=qwen-medium-preview, Ollama/YandexGPT/GigaChat fallback) + CircuitBreaker + per-provider asyncio.Semaphore (GLM shared 2, Qwen 3 each, total 8) + LLMOrchestrator parallel mode (asyncio.gather) + smart task→model routing + _resolve_system_prompt (YAML with inline fallback)
- backend/app/services/llm_utils.py — extract_json (regex, last-valid-wins) + extract_json_array + safe_parse_model (Pydantic with fallback)
- backend/app/services/llm_validator.py — generic LLMResultValidator[T]: validate/validate_list/validate_with_fallback, enum RU→EN mapping, length-mismatch tolerance
- backend/app/services/llm_limits.py — dynamic LLM concurrency limits via GET /api/v3/me/limits?model=... (5min cache, observability-only, startup hook)
- backend/app/services/dict_utils.py — normalize_phrase, find_duplicates (full/soft with is_exact in key), word_frequency (configurable stop-words), dictionary_stats, stratified_sample (LexiCore thresholds), validate_dictionary
- backend/app/services/xml_serializer.py — serialize_dictionary_to_xml (round-trip, fixes B1/B5/B6: root Tokens empty + child Requests, inter-word WS WD=2, 7-digit fractional seconds, preserves Attributes/ExtraLimitations/SavedState)
- backend/app/services/dictionary_ai.py — analyze_dictionary (LLM, AI_SYSTEM_PROMPT) + suggest_phrases (LLM, SUGGEST_SYSTEM_PROMPT, Pydantic-validated)
- backend/app/services/bm25.py — BM25Scorer (Robertson IDF, configurable k1/b, razdel+pymorphy3, RU stop-words)
- backend/app/services/fusion.py — reciprocal_rank_fusion / convex_fusion / log_odds_fusion (dynamic sigmoid calibration per-query) + fuse() dispatcher
- backend/app/services/explainer.py — explain_match (LIME-style permutation masking), explain_match_morph (no embeddings), explain_dict_match (combined)
- backend/app/services/domain_ner.py — GLiNER zero-shot NER (15 telecom labels, graceful fallback to [])
- backend/app/services/topics.py — TopicModeler (networkx communities + BM25 IDF labels, unsupervised)
- backend/app/services/prompt_manager.py — PromptManager (YAML-driven prompts, lazy load, str.replace for safe JSON-brace handling, output_model path resolution)
- backend/app/services/dialogue_annotator.py — DialogueAnnotator (5 layers: sentiment/profanity/conflict/topic/quality, chainable API, length-mismatch tolerance)
- backend/app/services/search.py — run_hierarchical_search + evaluate_phrase_logic_tree (logic tree И/ИЛИ/НЕ, NOT>AND>OR) + _apply_time_gap_filter (ExtraLimitations: StartEnd First/Last, Parent Before/After, OnlyInGaps/ExcludeGaps) + remainder flag (DictMatch.is_remainder) + precompute _tokenize/_find_word_positions per node + cascade GATE
- backend/app/services/logic_builder.py — build_phrase_groups + build_phrase_logic_tree (recursive descent, NOT>AND>OR precedence) + build_attribute_tree + decode_attribute + detect_warnings + _ALL_LEXEME_SEPARATORS
- backend/app/services/xml_parser.py — parse_xml_bytes + _parse_extra_limitations (real time-gap structure) + group_into_display_tokens + resolve_phrase_channel + _parse_without_list (DEPRECATED) + _detect_cycles + asyncio.to_thread
- backend/app/services/morph_matcher.py — match_phrase_morphological_detailed + BOW morph/exact (free order) + _compute_match_span + precompute cache + aspectual pairs + lru_cache
- backend/app/services/rtf_parser.py — parse_rtf_bytes + _parse_timestamp_to_seconds
- backend/app/services/hybrid_search.py — HybridSearchService (RRF k=60 + NER boost Natasha) + search_enhanced (BM25 + fusion strategies + token explainability, graceful degradation)
- backend/app/prompts/*.yaml — dialogue.yaml (5 prompts), quality.yaml (1 prompt + 16-cat rubric + 4 domains), validation.yaml (3 prompts), rag.yaml (1 prompt), dictionary.yaml (2 prompts). 12 total prompts, byte-identical to inline constants.
- backend/app/utils/session.py — фабрика session_store + batch_store

### cycles

cycles: [] (циклических зависимостей не обнаружено)

### layers.entry

- src/main.tsx — точка входа React, createRoot + StrictMode
- backend/app/main.py — FastAPI app, lifespan, CORS, structured logging, 11 роутеров

### layers.app_shell

- src/App.tsx — BrowserRouter + Routes, lazy-импорт pages, ThemeToggler, ErrorBoundary, AnalysisProvider, SnackbarProvider

Routes (source of truth — `src/App.tsx` lines 126-132):

| Path | Page | Notes |
|------|------|-------|
| `/` | UploadPage | Stepper wizard (auto-advance on upload success) |
| `/results` | ResultsPage | sessionId from AnalysisContext (NOT from URL) |
| `/batch-results/:batchId` | BatchResultsPage | batchId from useParams, polling 2s |
| `/history` | HistoryPage | LocalStorage-backed |
| `/speechlab` | SpeechLabPage | 3-panel resizable layout |
| `/speechlab/:sessionId` | SpeechLabPage | preloaded session |
| `/dictionary/:sessionId` | DictionaryEditorPage | CRUD + AI + Mining + XML export |

> **⚠️ Doc sync note:** Internal `navigate()` calls in UploadPage, HistoryPage, BatchResultsPage are consistent with these paths. `submitBatch` exists in `api/client.ts` but is **not wired to UI** on UploadPage (feature gap — see TODO_AND_ROADMAP.md §Batch Upload UI).

### layers.pages

- src/pages/UploadPage.tsx
- src/pages/ResultsPage.tsx
- src/pages/BatchResultsPage.tsx
- src/pages/HistoryPage/HistoryPage.tsx
- src/pages/SpeechLabPage.tsx

### layers.components

- src/components/DictionaryPhraseItem.tsx
- src/components/DictionaryPhraseList.tsx
- src/components/HighlightedTextView.tsx
- src/components/HighlightRenderer.tsx
- src/components/MatchLegend.tsx
- src/components/RestructuredDialogue.tsx
- src/components/SummaryView.tsx
- src/components/DictionaryTree/ (DictionaryTree.tsx + index.ts)
- src/components/DropZone/ (DropZone.tsx + index.ts)
- src/components/ErrorBoundary/ (ErrorBoundary.tsx + index.ts)
- src/components/MatchCounter/ (MatchCounter.tsx)
- src/components/PhrasePopover/ (PhrasePopover.tsx + index.ts)
- src/components/QualityScorePanel/ (QualityScorePanel.tsx + index.ts)
- src/components/SemanticSearchPanel/ (SemanticSearchPanel.tsx + index.ts)
- src/components/StatusBadge/ (StatusBadge.tsx + index.ts)
- src/components/ui/ (animated-circular-progress-bar, animated-list, animated-theme-toggler, blur-fade, border-beam, file-tree, number-ticker, typing-animation)
- src/components/SpeechLab/FoundRecordsTab/
- src/components/SpeechLab/KeywordsDisplay/ (KeywordsDisplay + TokenBadge)
- src/components/SpeechLab/LeftPanel/ (LeftPanel + SpeechLabTree + treeDataMapper)
- src/components/SpeechLab/QueryTab/
- src/components/SpeechLab/SpeechLabLayout/
- src/components/SpeechLab/SpeechLabRtfDialog.tsx
- src/components/SpeechLab/SpeechLabTopBar.tsx

### layers.hooks

- src/hooks/useLocalStorage.ts
- src/hooks/useSpeechLabState.ts — агрегирует api + context, экспортирует state/derived/actions
- src/hooks/useTheme.ts

### layers.context

- src/context/AnalysisContext.tsx — reducer + Provider, экспортирует AnalysisState/Action/useAnalysisContext
- src/context/HoverContext.tsx
- src/context/SnackbarContext.tsx

### layers.api

- src/api/client.ts — единый HTTP-клиент, ~20 экспортированных функций: checkHealth, uploadRtf, uploadDictionary, analyze, getResults, getProviders, getProviderStatus, submitBatch, getBatchStatus, getBatchResults, exportExcel, exportPdf, indexDialogue, searchSemantic, searchHybrid, getEmbeddingStatus, submitFeedback, getQualityScore + ApiError

### layers.storage

- src/storage/history.ts — LocalStorage persistence history entries + cleanup

### layers.types

- src/types/api.ts — зеркало backend/app/models.py. **⚠️ DRIFT (UI-3 action needed):** BE `DictMatch` имеет `is_remainder: bool` и `dict_level: int`, FE `DictMatch` их НЕ имеет (FE игнорирует unknown fields — non-breaking, но drift нужно закрыть перед UI-3). FE `DialogueTurn` НЕ имеет `start_offset`/`end_offset` (нужно для UI-3 time-gap UI, опционально). `PhraseGroupVisual` matches BE shape `{words, is_or_group, is_exception}`. `DictionaryCondition` matches BE (phrase_groups: PhraseGroupVisual[], extra_limitations отсутствует в FE — non-blocking).
- src/types/speechlab.ts — DisplayToken (type = WORD|PHRASE|LEXEME|BRACKET) и UI-типы. DisplayToken.type — ЗАПРЕЩЕНО менять.

### contracts

BE↔FE контракт-дрифт и критические инварианты (источник: models.py + api.ts):

- `DictMatch` (FE-контракт — НЕ менять field names/types): BE имеет `is_remainder: bool` и `dict_level: int` — **ТЕПЕРЬ В FE api.ts** (добавлены как optional: `is_remainder?: boolean`, `dict_level?: number`). Non-breaking.
- `DictionaryCondition`: BE имеет `extra_limitations: List[ExtraLimitation]` — **ТЕПЕРЬ В FE api.ts** (optional: `extra_limitations?: ExtraLimitation[]`). Non-breaking.
- `DialogueTurn`: BE имеет `start_offset: Optional[float]`, `end_offset: Optional[float]` — **ТЕПЕРЬ В FE api.ts** (optional). Non-breaking.
- `SpeechLabLayout.handleLayoutChanged` undefined — **ИСПРАВЛЕНО** (useCallback no-op + Layout type cast).
- BE dictionary editing endpoints — **ДОБАВЛЕНЫ** (14 endpoints в routers/dictionary.py).
- XML round-trip serializer — **ДОБАВЛЕН** (services/xml_serializer.py, canonical SmartLogger format).
- LLM model codes: glm-5.1 DECOMMISSIONED → glm-xlarge/glm-xlarge-fast (GLM-5.2 family per docs.ai.beeline.ru). Added qwen-medium (Qwen3.5), qwen-medium-preview (Qwen3.6).
- YAML-driven prompts — **ДОБАВЛЕНЫ** (backend/app/prompts/*.yaml, 12 prompts via PromptManager).
- BM25 + LogOdds fusion + token explainability + GLiNER NER + topic modeling — **ДОБАВЛЕНЫ** (Phase 3).
- `PhraseGroupVisual`: `{words: string[], is_or_group: bool, is_exception: bool}` — BE/FE совпадают.
- `PhraseGroup` (внутренняя BE модель, не FE-контракт): `{words, channel, word_distance, is_exact, is_negated, operator}`. `operator: str` добавлен в UI-2.6 для logic tree ('' | 'AND' | 'OR', НЕ хранит 'НЕ' — для этого есть `is_negated`).
- `DisplayToken.type`: `WORD | PHRASE | LEXEME | BRACKET` — ЗАПРЕЩЕНО менять (FE-контракт, рендерится в speechlab.ts).
- `DictMatch.match_type`: значения `'morph_bow'` (морф. BOW) или `'exact_bow'` (точная форма, free order). Символьные литералы поменялись в UI-2.5: было `'exact'`/`'sliding_window'`.
- `DictionaryNode.phrase_groups: List[PhraseGroup]` (внутренняя, для search/logic tree) ≠ `DictionaryCondition.phrase_groups: List[PhraseGroupVisual]` (FE-контракт, для visualization). Разные поля, разные типы — НЕ путать.
- `without_list: List[str]` в `DictionaryCondition`: DEPRECATED, всегда `[]` (V2: `_parse_without_list` неверен для реальных XML). Suppression via `is_exception` на PhraseGroup.
- `exception_phrases: List[str]` в `DictionaryCondition`: DEPRECATED, всегда `[]` (UI-2.6 BUG-8). Suppression via `is_exception`.
- `extra_limitations`: real XML time-gap limits (EventType/SearchSpecifier/Settings/Limits/Limit), НЕ phrase-WITHOUT. `_parse_without_list` — deprecated.

### layers.utils

- src/utils/xmlParser.ts — XML → tree
- src/lib/utils.ts

### layers.config_fe

- vite.config.ts
- tsconfig.json, tsconfig.app.json, tsconfig.node.json
- eslint.config.js
- package.json
- .npmrc
- index.html
- nginx.conf

### layers.config_be

- backend/app/config.py — pydantic BaseSettings, env-driven
- backend/pyproject.toml
- backend/requirements.txt
- backend/.env, backend/.env.example

### layers.models

- backend/app/models.py — все pydantic-модели:
  - RTF: DialogueTurn (поля start_offset/end_offset: Optional[float] для time-gap filtering), ParsedDialog, UploadRtfResponse
  - Dictionary: SavedState, SearchAttribute, AttributeTokenModel, AttributeSection, TokenModel, TokenSection, PhraseGroup (поля: words, channel, word_distance, is_exact, is_negated, operator — operator: str, для logic tree И/ИЛИ), DisplayToken (type=WORD|PHRASE|LEXEME|BRACKET — НЕ МЕНЯТЬ), LogicNode (AND/OR/NOT/ATTRIBUTE/PHRASE/GROUP), DecodedAttribute, ExtraLimitationLimit (value/value_type/channel/enabled/limit_type/event_selector/search_direction), ExtraLimitation (event_type/search_specifier/settings/limits), PhraseGroupVisual ({words, is_or_group, is_exception} — FE contract), DictionaryCondition (поля: text, word_distance, word_count, channel_constraint, without_list [], is_exact, phrase_groups: List[PhraseGroupVisual], nested_phrases, is_exception, exception_phrases DEPRECATED [], extra_limitations: List[ExtraLimitation]), DictionaryNode, DictionaryValidation, UploadDictionaryResponse
  - Analysis: TextSegment, DictMatch (фронтенд-контракт — НЕ менять имена/типы; поля: phrase_text, matched_text, matched_start, matched_end, quarter, turn_index, speaker, match_type='morph_bow'|'exact_bow', word_distance_used, cascade_order, is_exact_match, word_distance, channel_constraint, dict_level, is_remainder), AnalysisRequest, SearchResult, AnalysisResponse
  - LLM: LLMResult, ClientSentiment, Resolution, UtteranceSentiment, SentimentAnalysisResult, EscalationPoint, ConflictAnalysisResult, ProfanityInstance, ProfanityAnalysisResult, DetectedTopic, TopicAnalysisResult
  - Quality: QualityLevel, QualityCategory, CategoryScore, QualityScoreResult, QUALITY_CATEGORY_LABELS
  - Annotation: ProgressInfo, AnalysisAnnotation
  - Providers/Batch/Feedback/Embedding/Vector/Chunk/Hybrid: ProviderInfo, BatchAnalysisRequest/Response/ItemStatus, FeedbackRequest/Response, EmbeddingRequest/Response, VectorSearchResult, ChunkMetadata, Chunk, HybridSearchResult

### layers.routers

- backend/app/routers/upload.py — RTF upload (`POST /api/upload/rtf` → parse_rtf_bytes + start_offset/end_offset extraction) + Dictionary upload (`POST /api/upload/dictionary` → parse_xml_bytes + group_into_display_tokens)
- backend/app/routers/analysis.py — анализ диалога: llm + search (logic tree + time-gap) + session
- backend/app/routers/batch.py — batch-обработка
- backend/app/routers/dictionary.py — 14 endpoints: GET /{session_id}/tokens (legacy display tokens) + POST/PATCH/DELETE /{session_id}/nodes/{node_id} (CRUD nodes) + POST/PATCH/DELETE .../conditions/{idx} (CRUD conditions) + POST .../conditions/reorder + POST .../analyze-ai + POST .../suggest-phrases + POST .../duplicates + POST .../statistics + POST .../validate + POST .../export-xml (canonical XML StreamingResponse)
- backend/app/routers/embeddings.py
- backend/app/routers/export.py — Excel/PDF via openpyxl/reportlab
- backend/app/routers/feedback.py
- backend/app/routers/health.py
- backend/app/routers/pii.py — Presidio PII masking
- backend/app/routers/providers.py — LLM провайдеры
- backend/app/routers/rag.py

### layers.services

- backend/app/services/llm.py — LLMProvider ABC + Ollama/YandexGPT/GigaChat/Beeline + CircuitBreaker + LLMResultHandler + LLMOrchestrator (последовательный: summary → sentiment → conflict → profanity → topic)
- backend/app/services/search.py — run_hierarchical_search + evaluate_phrase_logic_tree (logic tree И/ИЛИ/НЕ, NOT>AND>OR) + _apply_time_gap_filter (ExtraLimitations: StartEnd First/Last, Parent Before/After; OnlyInGaps/ExcludeGaps) + remainder flag (DictMatch.is_remainder) + precompute _tokenize/_find_word_positions per node + cascade GATE
- backend/app/services/chunker.py — Chunker class (razdel + Natasha NER)
- backend/app/services/embedding.py — FridaEmbeddingService
- backend/app/services/vector_store.py — VectorStore + VectorStoreMigration (FAISS)
- backend/app/services/hybrid_search.py — HybridSearchService + _MorphResult (RRF + NER boost)
- backend/app/services/rag.py — RAGService
- backend/app/services/morph_matcher.py — pymorphy3 лемматизация + BOW morph (_bag_of_words_match_morph) / exact (_bag_of_words_match_exact) free order + _compute_match_span (min/max matched indices) + precompute cache + aspectual pairs (_ASPECTUAL_PAIRS, hardcoded) + lru_cache (maxsize=50000)
- backend/app/services/logic_builder.py — build_phrase_groups (PhraseGroup) + build_phrase_logic_tree (recursive descent, NOT>AND>OR precedence) + build_attribute_tree (LogicNode AND/OR/NOT/ATTRIBUTE) + decode_attribute (Duration/CallDirection/RemotePhoneNumber/UserDef5/ExternalDictionary/Channel/WordDistance) + detect_warnings + _ALL_LEXEME_SEPARATORS (И/AND/ИЛИ/OR/НЕ/NOT)
- backend/app/services/xml_parser.py — lxml parse_xml_bytes + _parse_extra_limitations (real time-gap structure: EventType/SearchSpecifier/Settings/Limits/Limit) + group_into_display_tokens (DisplayToken) + resolve_phrase_channel (first non-empty non-ANY) + _parse_without_list (DEPRECATED, returns []) + _detect_cycles (by ID) + asyncio.to_thread + _MAX_RECURSION_DEPTH=20
- backend/app/services/rtf_parser.py — striprtf parse_rtf_bytes + _parse_timestamp_to_seconds (H:MM:SS / HH:MM:SS / MM:SS / bare seconds / None)
- backend/app/services/pii_masking.py — presidio + custom recognizers (RussianPhoneRecognizer, PassportRecognizer, SNILSRecognizer, INNRecognizer, ContractRecognizer, BillingAccountRecognizer, RussianEmailRecognizer)
- backend/app/services/session_store_base.py — ABC
- backend/app/services/session_store_memory.py — in-memory имплементация
- backend/app/services/session_store_sqlite.py — SqliteSessionStore + BatchStore (активная имплементация)

### layers.utils_be

- backend/app/utils/session.py — фабрика session_store/batch_store через SqliteSessionStore

### layers.middleware_be

- backend/app/middleware/rate_limiter.py — slowapi Limiter
- backend/app/middleware/structured_logging.py — JsonFormatter + StructuredLoggingMiddleware

### layers.tests_fe

pattern: src/**/*.test.tsx|ts
count: ~45 файлов
includes: App.a11y.test.tsx, App.test.tsx, smoke.test.tsx, api/client.test.ts, парные тесты для всех компонентов/hooks/context/storage/utils

### layers.tests_be

- backend/tests/ — pytest suite, ~1154 pass (3 pre-existing failures: FastAPI `_IncludedRouter.path` in test_error_classifier / test_quality_scoring / test_resolution_sentiment — version compat, NOT related to UI-2.5/2.6)
- Ключевые XML-parser/search test files:
  - test_aspectual_pairs.py, test_container_nodes.py, test_dict_analyzer_integration.py, test_display_token.py, test_domain_analysis.py, test_extra_limitations.py (23 tests — time-gap parsing), test_logic_tree.py (logic tree И/ИЛИ/НЕ), test_morph_and_wd.py, test_perf_optimization.py (precompute cache), test_remainder.py (DictMatch.is_remainder), test_search_fallback.py (full rewrite — BOW _fallback_match), test_search_hierarchy.py, test_time_gap_filtering.py (33 tests — _apply_time_gap_filter all 4 combos), test_timestamps.py (17 tests — _parse_timestamp_to_seconds H:MM:SS / HH:MM:SS / MM:SS / seconds / None)
- Прочие: test_batch_api, test_batch_upload, test_chunker, test_dialogue_validation, test_embedding, test_embeddings_router, test_error_classifier, test_graceful_degradation, test_health, test_hybrid_search, test_llm_analysis_prompts, test_llm_orchestrator, test_llm_result_handler, test_pii_integration, test_pii_masking, test_pii_router, test_quality_scoring, test_rag_pipeline, test_resolution_sentiment, test_saved_state_fix, test_session_export, test_session_store_persistent, test_ui_rework_extensions, test_vector_store

### layers.static

- src/assets/
- public/

### layers.infra

- Dockerfile.frontend
- Dockerfile.backend
- docker-compose.yml
- nginx.conf
- scripts/start-chrome-debug.ps1
- scripts/dump-openapi-spec.ps1

### external_deps_fe

- @beeline/design-system-react
- @beeline/design-tokens
- react
- react-dom
- react-router-dom
- react-resizable-panels
- motion
- @modelcontextprotocol/server-memory (dev)

### external_deps_be

- fastapi
- uvicorn
- python-multipart
- lxml
- httpx
- pydantic
- pydantic-settings
- python-dotenv
- striprtf
- pymorphy3
- pymorphy3-dicts-ru
- faiss-cpu
- numpy
- razdel
- natasha
- slowapi
- tenacity
- openpyxl
- reportlab
- aiosqlite
- presidio-analyzer
- presidio-anonymizer

### deps_graph (key consumers)

src/main.tsx:
  deps_in: []
  deps_out: [src/App.tsx, src/index.scss]
  exports: []

src/App.tsx:
  deps_in: [src/context/AnalysisContext.tsx, src/context/SnackbarContext.tsx, src/components/ErrorBoundary, src/components/ui/animated-theme-toggler, src/hooks/useTheme, src/pages/* (lazy)]
  deps_out: []
  exports: [App (default)]

src/api/client.ts:
  deps_in: [src/types/api.ts, src/types/speechlab.ts]
  deps_out: [src/hooks/useSpeechLabState.ts, src/pages/*, src/components/SpeechLab/*]
  exports: [checkHealth, uploadRtf, uploadDictionary, analyze, getResults, getProviders, getProviderStatus, submitBatch, getBatchStatus, getBatchResults, exportExcel, exportPdf, indexDialogue, searchSemantic, searchHybrid, getEmbeddingStatus, submitFeedback, getQualityScore, ApiError]

src/context/AnalysisContext.tsx:
  deps_in: [src/types/api.ts]
  deps_out: [src/App.tsx, src/hooks/useSpeechLabState.ts]
  exports: [AnalysisState, initialState, AnalysisAction, AnalysisProvider, useAnalysisContext]

src/hooks/useSpeechLabState.ts:
  deps_in: [src/context/AnalysisContext.tsx, src/api/client.ts, src/types/speechlab.ts, src/types/api.ts]
  deps_out: [src/pages/SpeechLabPage.tsx, src/components/SpeechLab/*]
  exports: [SpeechLabState, SpeechLabDerived, SpeechLabActions, useSpeechLabState]

src/storage/history.ts:
  deps_in: [src/types/api.ts]
  deps_out: [src/pages/HistoryPage/HistoryPage.tsx]
  exports: [getAll, add, remove, clearAll, getStorageUsage, isStorageNearCapacity, cleanupOldEntries]

backend/app/main.py:
  deps_in: [backend/app/config.py, backend/app/middleware/rate_limiter.py, backend/app/middleware/structured_logging.py, backend/app/routers/* (11)]
  deps_out: []
  exports: [app]

backend/app/models.py:
  deps_in: []
  deps_out: [backend/app/routers/*, backend/app/services/*, backend/app/utils/session.py]
  exports: [все pydantic-модели]

backend/app/services/llm.py:
  deps_in: [backend/app/config.py, backend/app/models.py]
  deps_out: [backend/app/routers/analysis.py, backend/app/routers/batch.py, backend/app/routers/providers.py]
  exports: [LLMProvider, OllamaProvider, YandexGPTProvider, GigaChatProvider, BeelineProvider, LLMOrchestrator, CircuitBreaker, LLMResultHandler, get_provider, get_all_providers, get_circuit_breaker_stats]

backend/app/services/search.py:
  deps_in: [backend/app/models.py, backend/app/services/morph_matcher.py, backend/app/services/logic_builder.py]
  deps_out: [backend/app/routers/analysis.py, backend/app/routers/batch.py]
  exports: [run_hierarchical_search, evaluate_phrase_logic_tree, _apply_time_gap_filter, _filter_start_end, _filter_parent, _apply_gap_filter, _find_channel_gaps]

backend/app/services/logic_builder.py:
  deps_in: [backend/app/models.py]
  deps_out: [backend/app/services/xml_parser.py, backend/app/services/search.py]
  exports: [build_phrase_groups, build_phrase_logic_tree, build_attribute_tree, decode_attribute, detect_warnings, _ALL_LEXEME_SEPARATORS]

backend/app/services/xml_parser.py:
  deps_in: [backend/app/models.py, backend/app/services/logic_builder.py]
  deps_out: [backend/app/routers/upload.py, backend/app/routers/dictionary.py]
  exports: [parse_xml_bytes, group_into_display_tokens, _parse_extra_limitations, _parse_without_list (DEPRECATED), resolve_phrase_channel, _detect_cycles]

backend/app/services/morph_matcher.py:
  deps_in: [backend/app/models.py]
  deps_out: [backend/app/services/search.py, backend/app/services/hybrid_search.py]
  exports: [match_phrase_morphological_detailed, _bag_of_words_match_morph, _bag_of_words_match_exact, _compute_match_span, _tokenize, _find_word_positions, _ASPECTUAL_PAIRS]

backend/app/services/rtf_parser.py:
  deps_in: [backend/app/models.py]
  deps_out: [backend/app/routers/upload.py]
  exports: [parse_rtf_bytes, _parse_timestamp_to_seconds, _map_turns]

backend/app/utils/session.py:
  deps_in: [backend/app/services/session_store_base.py, backend/app/services/session_store_sqlite.py]
  deps_out: [backend/app/routers/* (analysis, batch, dictionary, export, health, upload)]
  exports: [session_store, batch_store, create_session_store]

> **Архив:** tsc_build_recovery + memory scheme (строки 427-634 оригинала) перенесены в
> `docs/archive/project-map-audit-history.md` (208 строк). Auditor concerns и tech debt
> зафиксированы в `TODO_AND_ROADMAP.md` §Tech Debt. Memory graph description — не primary storage
> (canonical в `pipeline-state.yaml` + `docs/specs/*`).
