# Карта проекта CallCenterAI

### meta

project: CallCenterAI
updated: 2026-07-03
version: 1.0
previous_version: null
total_files: ~115
changed_since_last: [] (первая версия)

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
pii: Presidio (pii_masking.py + routers/pii.py)

### hubs

- src/api/client.ts — центральный HTTP-клиент, импортируется всеми pages/hooks/SpeechLab
- src/context/AnalysisContext.tsx — глобальный state через reducer
- src/types/api.ts — TS-зеркало backend моделей
- src/hooks/useSpeechLabState.ts — агрегирует api + context
- backend/app/main.py — FastAPI app + регистрация всех роутеров и middleware
- backend/app/models.py — все pydantic-модели
- backend/app/services/llm.py — LLM-провайдеры + LLMOrchestrator
- backend/app/services/search.py — иерархический поиск по словарю
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

- src/types/api.ts — зеркало backend/app/models.py
- src/types/speechlab.ts — DisplayToken и UI-типы

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

- backend/app/models.py — все pydantic-модели: DialogueTurn, ParsedDialog, Chunk, ChunkMetadata, SearchResult, LLMResult, AnalysisResponse, BatchAnalysisResponse, BatchItemStatus, DisplayToken, FeedbackRequest, FeedbackResponse, RagQueryRequest, RagQueryResponse, VectorSearchResult, HybridSearchResult, HealthCheckResult, ProviderInfo, QualityScoreResult, AttributeToken, TokenSection, AttributeSection, LogicNode, DecodedAttribute, PhraseGroup, AnalysisAnnotation, ProgressInfo

### layers.routers

- backend/app/routers/upload.py — RTF upload → parse_xml + group_display_tokens
- backend/app/routers/analysis.py — анализ диалога: llm + search + session
- backend/app/routers/batch.py — batch-обработка
- backend/app/routers/dictionary.py
- backend/app/routers/embeddings.py
- backend/app/routers/export.py — Excel/PDF via openpyxl/reportlab
- backend/app/routers/feedback.py
- backend/app/routers/health.py
- backend/app/routers/pii.py — Presidio PII masking
- backend/app/routers/providers.py — LLM провайдеры
- backend/app/routers/rag.py

### layers.services

- backend/app/services/llm.py — LLMProvider ABC + Ollama/YandexGPT/GigaChat/Beeline + CircuitBreaker + LLMResultHandler + LLMOrchestrator
- backend/app/services/search.py — иерархический поиск: _search_recursive, _match_condition, _fallback_match, _build_smartlogger_turns, _build_segments
- backend/app/services/chunker.py — Chunker class
- backend/app/services/embedding.py — FridaEmbeddingService
- backend/app/services/vector_store.py — VectorStore + VectorStoreMigration (FAISS)
- backend/app/services/hybrid_search.py — HybridSearchService + _MorphResult
- backend/app/services/rag.py — RAGService
- backend/app/services/morph_matcher.py — pymorphy3 лемматизация
- backend/app/services/logic_builder.py — AttributeTree + PhraseGroup builder, парсер выражений (AND/OR/NOT)
- backend/app/services/xml_parser.py — lxml
- backend/app/services/rtf_parser.py — striprtf
- backend/app/services/pii_masking.py — presidio
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

- backend/tests/ — pytest suite

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
  deps_in: [backend/app/models.py]
  deps_out: [backend/app/routers/analysis.py, backend/app/routers/batch.py]
  exports: [run_hierarchical_search]

backend/app/utils/session.py:
  deps_in: [backend/app/services/session_store_base.py, backend/app/services/session_store_sqlite.py]
  deps_out: [backend/app/routers/* (analysis, batch, dictionary, export, health, upload)]
  exports: [session_store, batch_store, create_session_store]

### notes

- Файлы node_modules/, .git/, dist/, .venv/, venv/, coverage/, __pycache__/, .pytest_cache/ исключены из карты
- Файлы *.lock, package-lock.json игнорированы
- Тесты сгруппированы по glob-паттерну, детальные связи не выписаны
- deps_in/deps_out указаны только для hub-файлов; остальные связи выводимы из слоёв и архитектуры
