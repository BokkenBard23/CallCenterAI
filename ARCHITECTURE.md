# Архитектура CallCenterAI (SmartLogger)

Система анализа диалогов колл-центра: поиск фраз из иерархических XML-словарей в расшифровках разговоров с морфологическим BOW-сопоставлением, логическим деревом (И/ИЛИ/НЕ), time-gap фильтрацией, LLM-анализом, PII-маскированием (152-ФЗ) и векторным семантическим поиском (FRIDA + FAISS).

> **Источник правды:** код. Этот документ — снимок архитектуры от 2026-07-11.
> Спецификация XML-формата: `docs-archive/chat/chat-Спецификация XML словаря SmartLogger.txt`.

---

## Общая схема

```
┌─────────────────────────────────────────────────────────────────────┐
│  Пользователь (браузер)                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │  UploadPage  │  │ ResultsPage  │  │ DictionaryEditorPage     │   │
│  │  RTF + XML   │  │ Matches + HL │  │ CRUD + Mining + AI + XML │   │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬──────────────┘   │
│         │  REST API       ▲  REST API             │ REST API         │
└─────────┼─────────────────┼───────────────────────┼──────────────────┘
          │                 │                       │
          ▼                 │                       │
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend (React 18 + Vite 7 + Beeline DS 2.5)   localhost:5173    │
│  src/                                                                │
│  ├── api/client.ts        — HTTP-клиент (~20 функций)              │
│  ├── context/             — AnalysisContext (reducer), Snackbar     │
│  ├── hooks/               — useSpeechLabState, useMiningState       │
│  ├── pages/               — Upload, Results, Batch, History,       │
│  │                           SpeechLab, DictionaryEditor            │
│  ├── components/           — SpeechLab, DictionaryEditor (21+),     │
│  │                           HighlightedTextView, MatchLegend,      │
│  │                           QualityScorePanel, SemanticSearch,    │
│  │                           ErrorBoundary, ui/ (8 animated)        │
│  └── types/api.ts         — TS-зеркало backend-моделей (контракт)   │
│                                                                      │
│  Vite proxy: /api/* → localhost:8000                               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI + Python 3.12)                       localhost:8000│
│  backend/app/                                                        │
│  ├── main.py              — app, lifespan, CORS, 12 роутеров         │
│  ├── config.py            — pydantic BaseSettings (.env)             │
│  ├── models.py            — все Pydantic-модели (FE-контракт)        │
│  ├── routers/ (12)        — upload, analysis, batch, dictionary,    │
│  │                           embeddings, export, feedback, health,  │
│  │                           mining, pii, providers, rag             │
│  ├── services/ (28+)      — search, morph_matcher, logic_builder,    │
│  │                           xml_parser, xml_serializer, rtf_parser,│
│  │                           llm, prompt_manager, llm_validator,     │
│  │                           llm_limits, llm_utils, pii_masking,    │
│  │                           embedding, vector_store, hybrid_search,│
│  │                           chunker, rag, bm25, fusion, explainer, │
│  │                           domain_ner, topics, dialogue_annotator,│
│  │                           dict_utils, dictionary_ai, dict_mining, │
│  │                           session_store_sqlite, session_store_mem│
│  ├── prompts/*.yaml       — 12 YAML-промптов через PromptManager     │
│  ├── middleware/           — rate_limiter (slowapi), structured_log   │
│  └── utils/session.py     — фабрика session_store / batch_store      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ import (sys.path)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Transcrib (Python-модуль)                                          │
│  Transcrib/                                                         │
│  ├── smartlogger/           — Ядро матчинга SmartLogger              │
│  │   ├── tokenizer.py       — tokenize() — авторитетный токенизатор │
│  │   ├── matcher.py         — Оригинальный алгоритм (fallback)       │
│  │   ├── rtf_parser.py      — RTF → structured turns + timestamps   │
│  │   ├── dictionary.py      — Структуры данных словаря               │
│  │   ├── xml_exporter.py    — Экспорт результатов в XML             │
│  │   ├── validator.py       — Валидация словарей                    │
│  │   ├── metrics.py         — Метрики качества                      │
│  │   └── reporter.py        — Генерация отчётов                      │
│  ├── data/                                                          │
│  │   ├── input/rtf/         — RTF-файлы транскрипций (<size>)    │
│  │   ├── input/ins/         — Исходные XML-словари (старые)          │
│  │   └── output/production_xml/ — 3 production XML-словаря           │
│  └── scripts/               — Аналитические/отладочные скрипты     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Поток данных

### 1. Загрузка диалога (RTF)

```
RTF-файл  →  upload.py  →  rtf_parser.py  →  ParsedDialog
                                                      │
                                             DialogueTurn[]:
                                               [{turn_index, speaker, text,
                                                 timestamp, start_offset, end_offset}, ...]
                                                      │
                                               session.dialog (SQLite)
```

**Парсинг** (`rtf_parser.py`):
1. Загружает байты во временный файл.
2. Пробует `smartlogger.rtf_parser.extract_dialogue()` — структурированное извлечение (цветовые коды `\cf1` → «Клиент», `\cf2` → «Сотрудник» + timestamps).
3. Fallback на `striprtf` при ошибке — plain text extraction.
4. `_parse_timestamp_to_seconds` — парсинг `H:MM:SS` / `HH:MM:SS` / `MM:SS` / bare seconds → `start_offset`/`end_offset` (секунды от начала диалога). `None` если RTF не содержит временных меток.

**INV:** не модифицировать код `smartlogger` (`INV-6`).

### 2. Загрузка словаря (XML)

```
XML-файл  →  upload.py  →  xml_parser.py  →  DictionaryNode (дерево)
                                                     │
                                            ┌────────┴──────────────┐
                                            │                       │
                                     conditions[]              children[]
                                   (DictionaryCondition)   (вложенные DictionaryNode)
                                            │
                                     phrase_groups[]
                                     (PhraseGroup: words, channel,
                                      word_distance, is_exact,
                                      is_negated, operator)
                                            │
                                     attribute_tree
                                     (LogicNode: AND/OR/NOT/ATTRIBUTE/PHRASE/GROUP)
                                            │
                                     extra_limitations[]
                                     (ExtraLimitation: event_type,
                                      search_specifier, limits)
```

**XML-формат** (SmartLogger `SpeechLabRequest`):

```xml
<SpeechLabRequest type="SpeechLabRequest">
  <Id>{GUID}</Id>
  <Name>{Отображаемое имя}</Name>
  <State>SAVED</State>
  <SavedState>...</SavedState>
  <Tokens>                    <!-- последовательность токенов -->
    <Token>
      <Text>слово</Text>
      <Type>WORD|LEXEME|TERMINAL|WHITESPACE</Type>
      <Properties Channel="ANY|CLIENT|OPERATOR" WordDistance="0|1|2|3" />
    </Token>
    ...
  </Tokens>
  <ExtraLimitations>          <!-- time-gap limits (реальные словари) -->
    <ExtraLimitation>
      <EventType>StartEnd|Parent</EventType>
      <SearchSpecifier>OnlyInGaps|ExcludeGaps</SearchSpecifier>
      <Limits><Limit>...</Limit></Limits>
    </ExtraLimitation>
  </ExtraLimitations>
  <Requests>                  <!-- дочерние узлы (подкатегории) -->
    <SpeechLabRequest>...</SpeechLabRequest>
    <SpeechLabRemainderRequest>...</SpeechLabRemainderRequest>  <!-- catch-all -->
  </Requests>
</SpeechLabRequest>
```

**4 типа токенов** (каноническая спецификация SmartLogger):

| Тип | Назначение | Channel | WordDistance |
|-----|-----------|---------|-------------|
| **WORD** | Искомое слово | ANY/CLIENT/OPERATOR | 0–3 |
| **LEXEME** | Логический оператор (`И`, `ИЛИ`, `НЕ`) | Всегда ANY | Всегда 2 |
| **TERMINAL** | Структурный символ (`"`, `(`, `)`) | Всегда ANY | Всегда 2 |
| **WHITESPACE** | Разделитель (пробел) | Всегда ANY | Всегда 2 |

**Фраза** = последовательность WORD-токенов с одинаковым Channel без разделяющих LEXEME. LEXEME разрывает фразу на отдельные операнды.

### 3. Поиск совпадений (ядро системы)

```
ParsedDialog + DictionaryNode[]
         │
         ▼
   run_hierarchical_search()
         │
         ├── Для каждого словаря в каскаде (cascade_order = 1, 2, 3...):
         │
         │   _search_recursive(node=root_dict, level=1):
         │     ├── Если node.conditions:
         │     │     Для каждого condition:
         │     │       _match_condition() → morph_matcher / smartlogger / _fallback_match
         │     │       Если condition.is_exception (НЕ-условие) и matched → suppress node
         │     │       _apply_time_gap_filter() если extra_limitations непусты
         │     │     GATE: evaluate_phrase_logic_tree(phrase_groups, matched_texts)
         │     │           → node_matched (AND=all, OR=any, NOT=not matched)
         │     │     → DictMatch[] (match_type, dict_level, is_remainder)
         │     │
         │     └── Если node пустой (container, INV-6):
         │           children inherit level + GATE + parent_match_times
         │
         │   GATE (INV-7): child level ищется ТОЛЬКО если parent matched
         │   Поиск по ВСЕМ репликам, не только по parent-совпавшим
         │
         ▼
   SearchResult { matches[], total_matches, matches_by_level, search_source }
```

**Алгоритм матчинга** (`morph_matcher.py` + `search.py`):

| Алгоритм | Где | Суть |
|-----------|-----|------|
| **Morphological BOW** | `morph_matcher._bag_of_words_match_morph` | pymorphy3 лемматизация + аспектуальные пары глаголов. Свободный порядок слов. `is_exact=False` |
| **Exact form BOW** | `morph_matcher._bag_of_words_match_exact` | Без лемматизации, точная словоформа. Свободный порядок слов. `is_exact=True` (кавычки в XML) |
| **Sliding window** | `WordDistance` | Допустимые промежуточные слова между словами фразы (0–3). Применяется между каждой парой слов |
| **GATE model** | `search.py` (INV-7) | Дочерний уровень ищется только если родительский узел совпал. Поиск по всем репликам, не только по родительским |
| **Level assignment** | `search.py` (INV-6) | Контейнерные узлы (без conditions) не занимают уровень; дети наследуют уровень родителя |
| **Logic tree** | `search.py: evaluate_phrase_logic_tree` | AND=all match, OR=any match, NOT=suppressed. Приоритет: НЕ > И > ИЛИ |
| **Channel filter** | `morph_matcher` | CLIENT / OPERATOR / ANY — фильтр по спикеру реплики. Все слова фразы имеют одинаковый Channel |
| **Time-gap filter** | `search._apply_time_gap_filter` | EventType=StartEnd (First/Last limits), EventType=Parent (Before/After parent match). Требует `start_offset`/`end_offset` в turns |
| **Remainder** | `search.py` | `SpeechLabRemainderRequest` nodes → `DictMatch.is_remainder=True`. Включаются в results, не влияют на GATE |
| **SmartLogger fallback** | `search._do_match` | Если morph_matcher недоступен → `smartlogger.matcher.match_phrase_sliding_window` → `_fallback_match` |

**Ключевое правило кавычек:** кавычки (`is_exact=True`) фиксируют **только морфологию** (точная словоформа vs лемматизация). Порядок слов **всегда свободный**. WordDistance внутри кавычек работает как обычно.

### 4. LLM-анализ

```
ParsedDialog → analysis.py → llm.py (LLMOrchestrator)
                                │
                                ├── analyze_sentiment  (поклепочная тональность)
                                ├── analyze_conflict   (эскалация, агрессия)
                                ├── analyze_profanity  (ненормативная лексика)
                                ├── analyze_topic      (темы диалога)
                                ├── analyze_quality    (12 категорий качества)
                                ├── analyze_dialogue_validation
                                ├── analyze_resolution_sentiment
                                └── analyze_errors     (классификация ошибок)
                                │
                                ▼
                         AnalysisAnnotation (единый результат)
```

**LLMOrchestrator** (`llm.py:2429`):
- **Parallel mode** (default): `asyncio.gather` — шаги выполняются конкурентно
- **Sequential mode**: поочерёдный запуск (для тестов)
- Сбой одного шага НЕ блокирует остальные → safe default + `ProgressInfo.error_steps`
- Smart task→model routing: каждый шаг выбирает провайдера по задаче

### 5. PII-маскирование (152-ФЗ, hardened)

```
RTF upload → pii_masking.py → ParsedDialog (masked)
                    │
                    ├── Presidio AnalyzerEngine (spaCy ru_core_news_sm)
                    ├── 7 custom recognizers:
                    │     RussianPhone, Passport, SNILS, INN,
                    │     Contract, BillingAccount, RussianEmail
                    └── Variant A (strict blocking):
                          Presidio unavailable → BLOCK all processing
                          Circuit breaker: 3 failures → 60s open → 503
                          Placeholders: <PERSON>, <PHONE>, <EMAIL>, и т.д.
```

**INV-PII-1:** PII маскируется ДО попадания в session store, embeddings и логи.
**INV-PII-5/6:** `PIIDetectionPublic` и `PIIMaskingResult` не содержат raw text.

### 6. Векторный поиск (FRIDA + FAISS)

```
ParsedDialog → chunker.py (razdel + Natasha NER) → chunks[]
                                                        │
                   embedding.py (FRIDA) → vectors[]
                                                        │
                   vector_store.py (FAISS IndexFlatIP) → indexed
                                                        │
                   hybrid_search.py:
                     morphological search (search.py) → ranked morph
                     semantic search (VectorStore)    → ranked semantic
                     NER boost (Natasha)              → entity adjustment
                     RRF fusion (k=60)                → final ranking
                                                        │
                                                        ▼
                   List[HybridSearchResult]
```

**Graceful degradation:** FRIDA unavailable → morphological-only. Natasha unavailable → no NER boost. No dictionaries → semantic-only.

### 7. Mining (offline discovery, Track B)

```
Corpus RTF → dict_mining.py (DictionaryMiningService)
               ├── find_similar_to_phrase (FRIDA → top-k похожих диалогов)
               ├── find_false_negatives (search baseline → vector-close → LLM verify)
               └── llm_audit_dictionary (per PhraseGroup: recall, recommendations)
                     │
                     └── Confidence: relevant / irrelevant / uncertain + score 0-1
```

Mining — **offline discovery layer**, не production-runtime классификатор. Результат: XML-словарь, парсимый существующим `xml_parser.py` + `search.py`.

### 8. Визуализация (Frontend)

```
SearchResult → ResultsPage → HighlightedTextView
                                  │
                           Подсветка по уровням:
                           highlight_level = (cascade_order - 1) * 2 + word_distance_used
                           
                           Dict 1 root → L1 (yellow),  child → L2 (green)
                           Dict 2 root → L3 (cyan),    child → L4 (pink)
                           Dict 3 root → L5 (purple),  child → L6 (orange)
                           
                           match_type:
                             'morph_bow' — морфологическое совпадение
                             'exact_bow' — точная словоформа (кавычки)
```

---

## Ключевые инварианты

| ID | Инвариант | Суть | Статус |
|----|-----------|------|--------|
| **INV-6** | Level assignment | Контейнерные узлы (без conditions) не занимают уровень; дети наследуют уровень родителя | ✅ Preserved |
| **INV-7** | GATE model | Дочерний уровень ищется только если родительский узел matched. Поиск по ВСЕМ репликам | ✅ Preserved |
| **INV-8** | ~~Morph override~~ | ~~is_exact игнорируется; всегда морфологический BOW~~ | ❌ **REMOVED** — is_exact respected, `exact_bow` vs `morph_bow` |
| **INV-PII-1** | PII before store | PII маскируется ДО session store / embeddings / логов | ✅ Verified |
| **INV-PII-2** | No raw storage | Unmasked данные НЕ сохраняются | ✅ Verified |
| **INV-PII-3** | API contract | Существующие API-контракты не изменены | ✅ Verified |
| **INV-PII-4** | Neutral placeholders | `<PERSON>`, `<PHONE>`, `<EMAIL>` — семантически нейтральные | ✅ Verified |
| **INV-PII-5** | No text in detection | `PIIDetectionPublic` не содержит поля `text` | ✅ Verified |
| **INV-PII-6** | No original_text | `PIIMaskingResult` не содержит `original_text` | ✅ Verified |

---

## Модели данных

### DialogueTurn

| Поле | Тип | Описание |
|------|-----|----------|
| `turn_index` | int | Порядковый номер (0-based) |
| `speaker` | str | «Клиент» или «Сотрудник» |
| `text` | str | Текст реплики |
| `timestamp` | str? | Временная метка (если есть) |
| `start_offset` | float? | Секунды от начала диалога (для time-gap). `None` если RTF без timing |
| `end_offset` | float? | Секунды конца реплики |

### DictionaryNode

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | str | GUID из XML |
| `name` | str | Название (напр. «Риск расторжения») |
| `conditions` | DictionaryCondition[] | Фразы для поиска |
| `children` | DictionaryNode[] | Вложенные узлы |
| `saved_state` | SavedState? | Метаданные из `<SavedState>` |
| `attributes` | AttributeSection? | `<Attributes>` (игнорируются) |
| `is_remainder` | bool | True если `<SpeechLabRemainderRequest>` |
| `phrase_groups` | PhraseGroup[] | Группы фраз с per-word свойствами |
| `attribute_tree` | LogicNode? | Логическое дерево AND/OR/NOT |
| `token_section` | TokenSection? | Raw `<Tokens>` для DisplayToken |

### PhraseGroup (внутренняя, для search/logic tree)

| Поле | Тип | Описание |
|------|-----|----------|
| `words` | str[] | Слова фразы |
| `channel` | str | CLIENT / OPERATOR / ANY |
| `word_distance` | int | Допустимые промежуточные слова (0–3) |
| `is_exact` | bool | True если в кавычках (exact form BOW) |
| `is_negated` | bool | True если preceded by НЕ (LEXEME operator) |
| `operator` | str | `''` / `'AND'` / `'OR'` (НЕ хранится здесь — для этого есть `is_negated`) |

### DictionaryCondition (FE-контракт)

| Поле | Тип | Описание |
|------|-----|----------|
| `text` | str | Текст фразы (из concatenated WORD tokens) |
| `word_distance` | int | Sliding window distance (0–3) |
| `word_count` | int | Количество слов |
| `channel_constraint` | str | CLIENT / OPERATOR / ANY |
| `is_exact` | bool | **True = exact form BOW** (кавычки). False = morphological BOW. **Влияет на поиск** (INV-8 removed) |
| `without_list` | str[] | **DEPRECATED** — всегда `[]`. Suppression через `is_exception` |
| `phrase_groups` | PhraseGroupVisual[] | OR-группы для визуализации |
| `is_exception` | bool | True если фраза preceded by НЕ |
| `exception_phrases` | str[] | **DEPRECATED** — всегда `[]` |
| `extra_limitations` | ExtraLimitation[] | Time-gap limits из `<ExtraLimitations>` |

### DictMatch (FE-контракт — НЕ менять имена/типы)

| Поле | Тип | Описание |
|------|-----|----------|
| `phrase_text` | str | Фраза из словаря |
| `matched_text` | str | Реальный текст из диалога |
| `matched_start` | int | Символьное смещение начала (-1 = не вычислено) |
| `matched_end` | int | Символьное смещение конца |
| `quarter` | str | Имя словаря |
| `turn_index` | int | Номер реплики |
| `speaker` | str | Спикер реплики |
| `match_type` | str | `'morph_bow'` (морф. BOW) или `'exact_bow'` (точная форма) |
| `word_distance_used` | int | Уровень иерархии (1=root, 2=child, ...) |
| `cascade_order` | int | Порядок словаря в каскаде (1-based) |
| `is_exact_match` | bool | True если exact (кавычки) |
| `word_distance` | int | Оригинальный word_distance из condition |
| `channel_constraint` | str | Channel из condition |
| `dict_level` | int | Уровень в иерархии (1=Q1, 2=Q2, 3=Q3) |
| `is_remainder` | bool | True если из `<SpeechLabRemainderRequest>` |

### ExtraLimitation (time-gap limits)

| Поле | Тип | Описание |
|------|-----|----------|
| `event_type` | str | `'StartEnd'` или `'Parent'` |
| `search_specifier` | str | `'OnlyInGaps'` / `'ExcludeGaps'` / ... |
| `settings` | dict | Sub-keys (всегда пустые в реальных словарях) |
| `limits` | ExtraLimitationLimit[] | Список `<Limit>` элементов |

### LogicNode (AND/OR/NOT tree)

| Поле | Тип | Описание |
|------|-----|----------|
| `node_type` | str | `AND` / `OR` / `NOT` / `ATTRIBUTE` / `PHRASE` / `GROUP` |
| `children` | LogicNode[] | Дочерние узлы |
| `payload` | dict | Данные для leaf-узлов (DecodedAttribute) |

### DisplayToken (FE-контракт — НЕ менять type)

| Поле | Тип | Описание |
|------|-----|----------|
| `text` | str | Отображаемый текст |
| `type` | str | `WORD` / `PHRASE` / `LEXEME` / `BRACKET` — **ЗАПРЕЩЕНО менять** |
| `channel` | str | `OPERATOR` / `CLIENT` / `ANY` (для color rendering) |
| `word_distance` | int | Max of group |
| `is_exact` | bool | True если фраза была в кавычках |

---

## LLM-стек

### Провайдеры

| Класс | Provider ID | Model code | Семейство | Semaphore |
|-------|------------|------------|-----------|-----------|
| `BeelineProvider` | `beeline` | `glm-xlarge` | GLM-5.2 | 2 (shared GLM) |
| `BeelineFastProvider` | `beeline_fast` | `glm-xlarge-fast` | GLM-5.2 | 2 (shared GLM) |
| `Qwen35Provider` | `qwen35` | `qwen-medium` | Qwen 3.5 | 3 |
| `Qwen36Provider` | `qwen36` | `qwen-medium-preview` | Qwen 3.6 | 3 |
| `OllamaProvider` | `ollama` | `llama3.2` | Ollama (local) | — |
| `YandexGPTProvider` | `yandexgpt` | `yandexgpt-lite` | Yandex Cloud | — |
| `GigaChatProvider` | `gigachat` | — | Sber GigaChat | — |

> **glm-5.1 DECOMMISSIONED** → `glm-xlarge` / `glm-xlarge-fast` (GLM-5.2 family per docs.ai.beeline.ru)

**API endpoint:** `https://api.ai.beeline.ru/api/v3/chat/completions` (OpenAI-compatible)

**Concurrency:** GLM=2 shared semaphore, Qwen=3 each, total max 8 parallel (через `asyncio.Semaphore`).

**CircuitBreaker:** 3 failures → open → timeout → half-open → closed.

**Smart routing:** каждый LLM-шаг (`_resolve_preferred_provider`) выбирает провайдера по типу задачи с учётом circuit breaker state.

### PromptManager

YAML-driven промпты (`backend/app/prompts/*.yaml`), загружаются через `PromptManager`:
- `dialogue.yaml` — 5 prompts (summary, restructure, и т.д.)
- `quality.yaml` — 1 prompt + 16-category rubric + 4 domains
- `validation.yaml` — 3 prompts
- `rag.yaml` — 1 prompt
- `dictionary.yaml` — 2 prompts
- `mining.yaml` — prompts для dict_mining service
- Итого: **6 YAML-файлов, 12+ промптов**, byte-identical с inline константами

### LLMResultHandler / LLMResultValidator

- Pydantic-схема для LLMResult с enum-валидацией
- Fallback на default при невалидном JSON/полях
- Логирование невалидных ответов
- RU→EN enum mapping

---

## Хранилище

### SqliteSessionStore (production)

- `session_store_sqlite.py` — thread-safe SQLite-backed session store
- Каждая сессия = JSON blob в таблице `sessions`
- WAL mode для concurrent read
- TTL cleanup (default 7200s)
- Schema совместима с PostgreSQL (TEXT→VARCHAR, REAL→DOUBLE PRECISION)
- `backend/data/sessions.db`

### MiningStore

- `session_store_sqlite.py:MiningStore` — SQLite checkpoint для mining corpus index

### FAISS VectorStore

- `vector_store.py` — `IndexFlatIP` с L2-normalization
- Persistence: auto-save в `data/vector_store/`
- `dimension` configurable (FRIDA default)

### LocalStorage (Frontend)

- `src/storage/history.ts` — история анализов в браузере
- Cleanup старых entries при достижении лимита

---

## Роутеры (12)

| Роутер | Эндпоинтов | Назначение |
|--------|-----------|------------|
| `upload.py` | 3 | RTF upload, batch RTF upload, dictionary XML upload |
| `analysis.py` | 11 | analyze, results, sentiment, conflict, profanity, topic, quality-score, validation, full_analysis, resolution_sentiment, error_classification |
| `batch.py` | 3 | submit_batch, get_batch_status, get_batch_results |
| `dictionary.py` | 14 | CRUD nodes/conditions + display tokens + AI analyze + suggest + duplicates + statistics + validate + export-xml |
| `embeddings.py` | 5 | index, semantic search, hybrid search, status + get |
| `export.py` | 2 | export_excel, export_pdf |
| `feedback.py` | 2 | submit feedback, get feedback |
| `health.py` | 1 | health check (incl. PII subsystem) |
| `mining.py` | 6 | corpus index, find_similar, find_false_negatives, llm_audit, status, cancel |
| `pii.py` | 2 | mask, status |
| `providers.py` | 2 | list providers, provider status |
| `rag.py` | 2 | query, status |

---

## Данные (data)

| Путь | Содержимое | Объём |
|------|-----------|-------|
| `input/rtf/` | RTF-транскрипции звонков | <N> файлов, <size> |
| `input/ins/` | Исходные XML-словари (старая версия) | 2 файла |
| `output/production_xml/` | Production XML-словари | 3 файла |

---

## Технологический стек

| Слой | Технологии |
|------|-----------|
| **Frontend** | React 18, TypeScript 5.9, Vite 7, `@beeline/design-system-react` 2.5, `@beeline/design-tokens`, react-router-dom 7, `@tanstack/react-table`, react-markdown |
| **Backend** | Python 3.12, FastAPI, Pydantic 2, lxml, pydantic-settings |
| **Морфология** | pymorphy3, аспектуальные пары глаголов (совершенный/несовершенный вид) |
| **RTF-парсинг** | striprtf + smartlogger.rtf_parser |
| **NER** | Natasha (chunker, hybrid search boost), GLiNER (zero-shot domain NER, 15 telecom labels) |
| **Токенизация** | razdel (BM25, chunker), smartlogger.tokenizer (search) |
| **Embeddings** | FRIDA (FridaEmbeddingService, circuit breaker + retry) |
| **Vector store** | FAISS IndexFlatIP (L2-normalization, persistence) |
| **Hybrid search** | RRF (k=60) + NER boost + BM25 + LogOdds fusion |
| **PII** | presidio-analyzer, presidio-anonymizer, spaCy ru_core_news_sm, 7 custom recognizers |
| **LLM** | Beeline AI (GLM-5.2, Qwen 3.5/3.6), Ollama, YandexGPT, GigaChat |
| **Rate limiting** | slowapi |
| **Export** | openpyxl (Excel), reportlab (PDF) |
| **Storage** | SQLite (aiosqlite, WAL mode), FAISS, LocalStorage (FE) |
| **Тесты** | pytest + asyncio (backend, 65 test files), Vitest + Testing Library (frontend, 54 test files) |

---

## Запуск

```bash
# Backend
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
npm install
npm run dev          # → http://localhost:5173

# Тесты
cd backend && pytest tests/ -v
npm run test
npm run typecheck    # tsc -b --noEmit (НЕ tsc --noEmit — composite project gotcha)
```

**Критический gotcha:** root `tsconfig.json` имеет `files: []` + `references`. `tsc --noEmit` (без `-b`) проверяет 0 файлов → всегда ExitCode 0. Использовать только `tsc -b --force` или `npm run typecheck`.

---

## Контракты BE↔FE (критичные)

| Контракт | Правило |
|----------|--------|
| `DictMatch` | FE-контракт — НЕ менять field names/types. `match_type`: `'morph_bow'` / `'exact_bow'` |
| `DisplayToken.type` | `WORD` / `PHRASE` / `LEXEME` / `BRACKET` — **ЗАПРЕЩЕНО менять** |
| `PhraseGroupVisual` | `{words: str[], is_or_group: bool, is_exception: bool}` — BE/FE совпадают |
| `is_exact` | **Влияет на поиск** (INV-8 removed): True=exact form BOW, False=morph BOW |
| `without_list` | DEPRECATED, всегда `[]`. Suppression через `is_exception` |
| `exception_phrases` | DEPRECATED, всегда `[]` |
| `extra_limitations` | Real XML time-gap limits (EventType/SearchSpecifier/Limits), НЕ phrase-WITHOUT |
| `PhraseGroup` (internal) ≠ `PhraseGroupVisual` (FE) | Разные поля, разные типы — НЕ путать |
