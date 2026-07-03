# Архитектура CallCenterAI

Система анализа диалогов колл-центра: поиск фраз из иерархических словарей в расшифровках разговоров, с морфологическим сопоставлением и визуализацией результатов.

---

## Общая схема

```
┌─────────────────────────────────────────────────────────────────┐
│  Пользователь (браузер)                                         │
│  ┌──────────────┐    ┌──────────────────┐                       │
│  │  UploadPage  │───►│   ResultsPage    │                       │
│  │  RTF + XML   │    │  Совпадения + HL │                       │
│  └──────┬───────┘    └────────┬─────────┘                       │
│         │  REST API          ▲  REST API                        │
└─────────┼────────────────────┼──────────────────────────────────┘
          │                    │
          ▼                    │
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite + Beeline DS)     localhost:5173       │
│  src/                                                          │
│  ├── api/client.ts        — HTTP-клиент к backend              │
│  ├── context/             — AnalysisContext (сессия, состояние) │
│  ├── pages/               — UploadPage, ResultsPage             │
│  ├── components/          — HighlightedTextView, MatchLegend  │
│  └── types/api.ts         — TypeScript-типы ответов API        │
│                                                                 │
│  Vite proxy: /api/* → localhost:8000                           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI + Python 3.12)          localhost:8000       │
│  backend/                                                       │
│  ├── app/main.py          — Точка входа, CORS, lifespan         │
│  ├── app/config.py        — Настройки (.env / pydantic)         │
│  ├── app/models.py        — Pydantic-модели (запрос/ответ)      │
│  ├── app/routers/                                              │
│  │   ├── upload.py        — POST /rtf, POST /dictionary         │
│  │   ├── analysis.py      — POST /analyze, GET /results/{id}    │
│  │   └── providers.py     — GET /providers (LLM-провайдеры)     │
│  ├── app/services/                                              │
│  │   ├── rtf_parser.py    — RTF → ParsedDialog (через striprtf) │
│  │   ├── xml_parser.py    — XML → DictionaryNode (иерархия)     │
│  │   ├── search.py        — Иерархический поиск Q1→Q2→Q3         │
│  │   ├── morph_matcher.py — Морфологический BOW + sliding window│
│  │   ├── logic_builder.py — Канал/WordDistance из фраз-групп    │
│  │   └── llm.py           — LLM-анализ (Ollama, Yandex, GigaChat)│
│  ├── app/utils/session.py — In-memory хранилище сессий          │
│  └── tests/               — 102 теста (pytest + asyncio)         │
└──────────────────────────────┬──────────────────────────────────┘
                               │ import
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Transcrib (Python-модуль)                                      │
│  Transcrib/                                                     │
│  ├── smartlogger/           — Ядро матчинга из SmartLogger       │
│  │   ├── tokenizer.py       — tokenize() — авторитетный токенизатор│
│  │   ├── matcher.py         — Оригинальный алгоритм сопоставления│
│  │   ├── dictionary.py      — Структуры данных словаря           │
│  │   ├── rtf_parser.py      — Альтернативный RTF-парсер          │
│  │   ├── xml_exporter.py    — Экспорт результатов в XML          │
│  │   ├── validator.py       — Валидация словарей                 │
│  │   ├── metrics.py         — Метрики качества                   │
│  │   └── reporter.py        — Генерация отчётов                  │
│  ├── data/                                                       │
│  │   ├── input/rtf/         — RTF-файлы транскрипций         │
│  │   ├── input/ins/         — Исходные XML-словари (старые)      │
│  │   └── output/production_xml/ — Production XML-словари (актуальные)│
│  └── scripts/               — Аналитические и отладочные скрипты│
└─────────────────────────────────────────────────────────────────┘
```

---

## Поток данных

### 1. Загрузка диалога (RTF)

```
RTF-файл  →  upload.py  →  rtf_parser.py  →  ParsedDialog
                                                     │
                                            DialogueTurn[]:
                                              [{turn_index, speaker, text}, ...]
                                                     │
                                              session.dialog
```

Парсинг через `striprtf`: убирает RTF-разметку, извлекает реплики с ролями «Клиент» / «Сотрудник».

### 2. Загрузка словаря (XML)

```
XML-файл  →  upload.py  →  xml_parser.py  →  DictionaryNode (дерево)
                                                    │
                                           ┌────────┴────────┐
                                           │                  │
                                    conditions[]         children[]
                                   (фразы + wd + канал)  (вложенные узлы)
                                           │                  │
                                    phrase_groups[]      рекурсия
                                    (из Token-секции)
                                    attribute_tree
                                    (AND/OR/NOT логика)
```

XML-формат: `<SpeechLabRequest>` содержит `<Tokens>` (фразы) и вложенные `<Requests>/<SpeechLabRequest>` (подкатегории).

### 3. Поиск совпадений (ядро системы)

```
ParsedDialog + DictionaryNode[]
         │
         ▼
   run_hierarchical_search()
         │
         ├── Q1 (Риск расторжения):
         │     morph_matcher → ALL turns → matches[]
         │
         ├── Q2 gate: Q1 has matches? ── NO → skip Q2
         │                        │ YES
         │                        ▼
         │     Q2 (Клиент отказывается от диагностики):
         │     morph_matcher → ALL turns → matches[]
         │
         ├── Q3 gate: Q1 AND Q2 have matches? ── NO → skip Q3
         │                              │ YES
         │                              ▼
         │     Q3 (Переключение/заявка):
         │     morph_matcher → ALL turns → matches[]
         │
         ▼
   SearchResult { matches[], total, by_level }
```

**Ключевые алгоритмы:**

| Алгоритм | Где | Суть |
|-----------|-----|------|
| Морфологический BOW | `morph_matcher.py` | pymorphy3 лемматизация + аспектуальные пары глаголов |
| Sliding window | `morph_matcher.py` | Окно по токенам диалога с WordDistance |
| GATE model | `search.py` (INV-7) | Q2 ищется только если Q1 ≥ 1 совпадение (gate passed) |
| Level assignment | `search.py` (INV-6) | Контейнерные узлы без фраз не занимают уровень |
| Morph override | `search.py` (INV-8) | `is_exact` из XML игнорируется; всегда морфологический BOW |
| Channel filter | `search.py` | CLIENT / OPERATOR / ANY — фильтр по спикеру реплики |

### 4. Визуализация (Frontend)

```
SearchResult → ResultsPage → HighlightedTextView
                                  │
                           Подсветка по уровням:
                           Q1 → жёлтый (L1)
                           Q2 → зелёный (L2)
                           Q3 → голубой (L3)
                           ...
                           Формула: highlight_level = (cascade-1)*2 + word_distance_used
```

---

## Модели данных

### ParsedDialog (результат парсинга RTF)

| Поле | Тип | Описание |
|------|-----|----------|
| `filename` | str | Имя исходного RTF-файла |
| `turns` | DialogueTurn[] | Реплики по порядку |
| `total_turns` | int | Количество реплик |
| `client_turns` | int | Реплики клиента |
| `employee_turns` | int | Реплики сотрудника |

### DialogueTurn (одна реплика)

| Поле | Тип | Описание |
|------|-----|----------|
| `turn_index` | int | Порядковый номер (0-based) |
| `speaker` | str | «Клиент» или «Сотрудник» |
| `text` | str | Текст реплики |
| `timestamp` | str? | Временная метка (если есть) |

### DictionaryNode (узел словаря)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | str | Уникальный ID из XML |
| `name` | str | Название (напр. «Риск расторжения») |
| `conditions` | DictionaryCondition[] | Фразы для поиска |
| `children` | DictionaryNode[] | Вложенные подкатегории |
| `phrase_groups` | PhraseGroup[] | Группы фраз с per-word свойствами |
| `attribute_tree` | LogicNode? | Логическое дерево AND/OR/NOT |

### DictionaryCondition (одна фраза для поиска)

| Поле | Тип | Описание |
|------|-----|----------|
| `text` | str | Текст фразы |
| `word_distance` | int | Допустимое расстояние между словами |
| `channel_constraint` | str | CLIENT / OPERATOR / ANY |
| `is_exact` | bool | Флаг цитирования из XML (НЕ влияет на поиск!) |
| `without_list` | str[] | Фразы-исключения |

### DictMatch (результат совпадения)

| Поле | Тип | Описание |
|------|-----|----------|
| `phrase_text` | str | Фраза из словаря |
| `matched_text` | str | Реальный текст из диалога |
| `matched_start/end` | int | Смещение символов в реплике |
| `quarter` | str | Имя узла словаря |
| `turn_index` | int | Номер реплики |
| `speaker` | str | Спикер реплики |
| `word_distance_used` | int | Уровень иерархии (1=Q1, 2=Q2, 3=Q3) |
| `cascade_order` | int | Порядок словаря в каскаде |
| `is_exact_match` | bool | Был ли exact match (для UI) |

---

## Данные (data)

| Путь | Содержимое | Объём |
|------|-----------|-------|
| `input/rtf/` | RTF-транскрипции звонков | <N> файлов |
| `input/ins/` | Исходные XML-словари (старая версия) | 2 файла |
| `output/production_xml/` | Актуальные production XML-словари | 3 файла |

**Production словари:**

| Файл | Условий | Иерархия |
|------|---------|-----------|
| sample_dictionary.xml | 1,232 | Q1(900) → Q2(29) → Q3(303) |
| Риск расторжения.xml | 839 | Q1(839) → Q2 |
| Клиент отказывается от диагностики.xml | 29 | Один уровень |

---

## Сессии (backend)

In-memory хранилище (`app/utils/session.py`):
- Каждый upload создаёт или обновляет сессию по `session_id`
- Сессия содержит: `ParsedDialog` + `DictionaryNode[]`
- Анализ запускается по `session_id`
- TTL сессий: 2 часа (очистка при shutdown)

---

## LLM-интеграция (опционально)

| Провайдер | Настройка | Модель по умолчанию |
|-----------|----------|-------------------|
| Ollama | `OLLAMA_BASE_URL` | llama3.2 |
| YandexGPT | `YANDEXGPT_API_KEY` + `FOLDER_ID` | yandexgpt-lite |
| GigaChat | `GIGACHAT_AUTH_KEY` | — |
| Beeline AI | `BEELINE_API_KEY` | glm-5.1 |

LLM используется для:
- Краткого саммари диалога
- Реструктуризации диалога (чередование коротких реплик)
- Оценки тональности и резолюции

---

## Ключевые инварианты поиска

| ID | Инвариант | Суть |
|----|-----------|------|
| INV-6 | Level assignment | Контейнерные узлы без фраз не занимают уровень; дети наследуют уровень родителя |
| INV-7 | GATE model | Иерархия — prerequisite gate: Q2 ищется только если Q1 ≥ 1 match; поиск по ВСЕМ репликам, не только по Q1-совпавшим |
| INV-8 | Morph override | Флаг `is_exact` из XML игнорируется при поиске; всегда морфологический BOW-matching через pymorphy3 + аспектуальные пары |

---

## Запуск

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
npm install
npm run dev          # → http://localhost:5173

# Тесты
cd backend && pytest tests/ -v        # 102 теста
npm run test                          # 127 тестов
```

---

## Технологический стек

| Слой | Технологии |
|------|-----------|
| Frontend | React 18, TypeScript, Vite 7, @beeline/design-system-react |
| Backend | Python 3.12, FastAPI, Pydantic, lxml |
| Морфология | pymorphy3, аспектуальные пары глаголов |
| RTF-парсинг | striprtf |
| LLM | Ollama / YandexGPT / GigaChat / Beeline AI |
| Тесты | pytest + asyncio (backend), Vitest + Testing Library (frontend) |
