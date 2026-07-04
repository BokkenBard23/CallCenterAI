# Карта проекта CallCenterAI

### meta

project: CallCenterAI
updated: 2026-07-04
version: 1.1
previous_version: 1.0 (2026-07-03)
total_files: ~117
changed_since_last:
  - UI-2.5 Parser Rewrite (14 critical bugs fixed) — f8c6903
  - UI-2.6 Wave: logic tree + ExtraLimitations (time-gap) + Remainder + FE contract fixes — 9325609
  - UI-2.6 docs cleanup — 8962c83
  - UI-2.6 BE timestamps + perf optimization + INV-6 verification — 0515a21
  - models.py: PhraseGroupVisual, ExtraLimitation, ExtraLimitationLimit, PhraseGroup.operator, DictMatch.is_remainder, DictMatch.dict_level, DialogueTurn.start_offset/end_offset
  - logic_builder.py: build_phrase_logic_tree (recursive descent, NOT>AND>OR precedence)
  - xml_parser.py: _parse_extra_limitations (time-gap), group_into_display_tokens, resolve_phrase_channel
  - search.py: evaluate_phrase_logic_tree + _apply_time_gap_filter + _find_channel_gaps
  - morph_matcher.py: BOW morph/exact free order + precompute cache + _compute_match_span
  - rtf_parser.py: _parse_timestamp_to_seconds (H:MM:SS / HH:MM:SS / MM:SS / seconds / None)
  - 7 new BE tests: test_logic_tree, test_extra_limitations, test_time_gap_filtering, test_remainder, test_timestamps, test_perf_optimization, test_container_nodes

### stack

frontend: React 18 + Vite 7 + TypeScript 5.9 + @beeline/design-system-react 2.5 + react-router-dom 7
backend: FastAPI + Pydantic 2 + FAISS + pymorphy3 + lxml + Presidio + slowapi
tests_fe: vitest + @testing-library/react
tests_be: pytest

### architecture

flow_fe: main.tsx → App.tsx (lazy routes) → pages → components/hooks → context (AnalysisContext reducer) + api/client.ts → FastAPI backend
flow_be: main.py (FastAPI app) → routers/* (HTTP) → services/* (business logic) → models.py (pydantic)
storage: SqliteSessionStore (BE sessions) + LocalStorage (FE history via storage/history.ts)
llm: multi-provider orchestrator (Ollama/YandexGPT/GigaChat/Beeline) с CircuitBreaker и fallback
search: иерархический по XML-словарю (search.py) + векторный FAISS (vector_store.py) + гибридный (hybrid_search.py)
parser: xml_parser.py (SmartLogger XML → DictionaryNode) + logic_builder.py (PhraseGroup + logic_tree) + morph_matcher.py (BOW morph/exact, free order)
search_logic: logic tree (И/ИЛИ/НЕ) на основе PhraseGroup.operator + is_exception, NOT>AND>OR precedence (build_phrase_logic_tree → evaluate_phrase_logic_tree), GATE = node_matched AND NOT suppressed
time_gap: ExtraLimitations (real XML time-gap limits, NOT phrase-WITHOUT) — _parse_extra_limitations → _apply_time_gap_filter (_filter_start_end / _filter_parent / _apply_gap_filter / _find_channel_gaps). Requires DialogueTurn.start_offset/end_offset. No-op when RTF lacks timing.
remainder: SpeechLabRemainderRequest nodes — DictMatch.is_remainder flag set; catch-all fallback suppression of siblings — TODO (not blocking UI-3 display)
pii: Presidio (pii_masking.py + routers/pii.py)

### hubs

- src/api/client.ts — центральный HTTP-клиент, импортируется всеми pages/hooks/SpeechLab
- src/context/AnalysisContext.tsx — глобальный state через reducer
- src/types/api.ts — TS-зеркало backend моделей
- src/hooks/useSpeechLabState.ts — агрегирует api + context
- backend/app/main.py — FastAPI app + регистрация всех роутеров и middleware
- backend/app/models.py — все pydantic-модели
- backend/app/services/llm.py — LLM-провайдеры + LLMOrchestrator
- backend/app/services/search.py — иерархический поиск по словарю + logic tree (И/ИЛИ/НЕ) + GATE + time-gap filtering (ExtraLimitations) + remainder catch-all flag + precompute word positions
- backend/app/services/logic_builder.py — build_phrase_groups + build_phrase_logic_tree (recursive descent, NOT>AND>OR precedence) + build_attribute_tree + detect_warnings
- backend/app/services/xml_parser.py — parse_xml_bytes + _parse_extra_limitations (time-gap, real XML structure) + group_into_display_tokens + resolve_phrase_channel + _parse_without_list (DEPRECATED, returns [])
- backend/app/services/morph_matcher.py — match_phrase_morphological_detailed + BOW morph/exact (free order) + _compute_match_span + precompute cache (tokenize + word_positions per node)
- backend/app/services/rtf_parser.py — parse_rtf_bytes + _parse_timestamp_to_seconds (H:MM:SS / HH:MM:SS / MM:SS / bare seconds / None)
- backend/app/utils/session.py — фабрика session_store + batch_store

### cycles

cycles: [] (циклических зависимостей не обнаружено)

### layers.entry

- src/main.tsx — точка входа React, createRoot + StrictMode
- backend/app/main.py — FastAPI app, lifespan, CORS, structured logging, 11 роутеров

### layers.app_shell

- src/App.tsx — BrowserRouter + Routes, lazy-импорт pages, ThemeToggler, ErrorBoundary, AnalysisProvider, SnackbarProvider

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

- `DictMatch` (FE-контракт — НЕ менять field names/types): BE имеет `is_remainder: bool` (UI-2.6) и `dict_level: int` — ОТСУТСТВУЮТ в FE api.ts. **ACTION for UI-3:** добавить `is_remainder?: boolean` и `dict_level?: number` если UI-3 рендерит remainder-матчи отдельно или использует уровень.
- `DictionaryCondition`: BE имеет `extra_limitations: List[ExtraLimitation]` — ОТСУТСТВУЕТ в FE api.ts. Non-breaking (FE игнорирует). Для UI-3 time-gap editing (если будет) — добавить.
- `DialogueTurn`: BE имеет `start_offset: Optional[float]`, `end_offset: Optional[float]` (UI-2.6, для time-gap filter input). FE api.ts `DialogueTurn` их НЕ имеет. Non-breaking для текущего UI, нужно если UI-3 отображает тайминг реплик.
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
- backend/app/routers/dictionary.py — `GET /api/dictionary/{session_id}/tokens` → display_tokens; НЕТ PATCH/PUT/DELETE для редактирования conditions (требуется для UI-3 inline editing — TODO)
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

### notes

- Файлы node_modules/, .git/, dist/, .venv/, venv/, coverage/, __pycache__/, .pytest_cache/ исключены из карты
- Файлы *.lock, package-lock.json игнорированы
- Тесты сгруппированы по glob-паттерну, детальные связи не выписаны
- deps_in/deps_out указаны только для hub-файлов; остальные связи выводимы из слоёв и архитектуры
- v1.1 (2026-07-04): актуализировано после UI-2.5 (parser rewrite) и UI-2.6 (logic tree + ExtraLimitations time-gap + Remainder + perf). См. `docs/specs/ui-3-readiness-audit.md` для audit готовности к UI-3.
- BE готов к UI-3 (0 blocker bugs). Open issues: N3 (window_size=N+WD vs spec N+(N-1)*WD — academic), N12 (break per turn — likely intentional SmartLogger behavior), S2#18 (TokenModel.word_distance: str — cosmetic).
- FE type drift: BE DictMatch `is_remainder` + `dict_level` НЕ в FE api.ts — закрыть перед UI-3.
- Pre-existing FE bug: SpeechLabLayout.handleLayoutChanged undefined (SpeechLabLayout.tsx:112) — fix recommended before UI-3.
