# Domain Logic — SmartLogger

Доменная логика системы: правила матчинга фраз, логическое дерево, инварианты, XML-формат словарей.

> **Источник правды:** код (`search.py`, `morph_matcher.py`, `logic_builder.py`, `xml_parser.py`).
> **Каноническая XML-спецификация:** `docs-archive/chat/chat-Спецификация XML словаря SmartLogger.txt` (479 строк, составлена из чата с заказчиком).
> **Архитектурный обзор:** `ARCHITECTURE.md`.

---

## 1. XML-формат словаря (SmartLogger)

### 1.1. Корневая структура

```xml
<SpeechLabRequest type="SpeechLabRequest">
  <Id>{GUID}</Id>
  <Name>{Отображаемое имя}</Name>
  <State>SAVED</State>
  <SavedState>...</SavedState>
  <Temporary>False</Temporary>
  <OrderIndex>{0, 1, 2...}</OrderIndex>
  <IsThemed>False</IsThemed>
  <Attributes><AttributeTokens /></Attributes>
  <Tokens>{последовательность токенов или пустой}</Tokens>
  <ExtraLimitations>{time-gap limits}</ExtraLimitations>
  <ComplexCompleted>False</ComplexCompleted>
  <Requests>
    {дочерние SpeechLabRequest или SpeechLabRemainderRequest}
  </Requests>
</SpeechLabRequest>
```

**Корневой узел** имеет пустой `<Tokens />` — он служит контейнером. Поисковые выражения находятся в дочерних узлах.

### 1.2. Иерархия уровней

```
Корень (Пустой словарь, пустой Tokens)
├── Уровень 1a (содержит Tokens с выражением)
│   ├── Уровень 2a (подуровень — лист)
│   └── Уровень 2b (подуровень — родитель)
│       └── Уровень 3b (подподуровень — лист)
├── Уровень 1b
│   └── Уровень 2 (1b)
│       └── Уровень 3 (1b-2 (1b))
└── Остаток (SpeechLabRemainderRequest)
    └── Уровень 2 (ост)
```

`OrderIndex` определяет порядок узлов среди соседних (начиная с 0).

### 1.3. Remainder (Остаток)

`SpeechLabRemainderRequest` — специальный тип узла для диалогов, **не совпавших** с словарями предыдущего уровня:

- **Не имеет:** `<Tokens>`, `<Attributes>`, `<ExtraLimitations>`, `<ComplexCompleted>`
- Может быть на любом уровне вложенности
- Может содержать свои подуровни
- В коде: `DictionaryNode.is_remainder=True`, matches помечаются `DictMatch.is_remainder=True`

### 1.4. Формат данных

- **Id:** GUID формата `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
- **Дата:** ISO 8601, UTC: `2026-06-27T17:37:06.0150613Z`
- **Boolean:** `True`/`False` (заглавная) в основных полях; `true`/`false` (строчные) в SavedState
- **Операторы:** кириллицей, ВЕРХНИМ регистром: `И`, `ИЛИ`, `НЕ`

---

## 2. Система токенов

### 2.1. Четыре типа токенов

| Тип | Назначение | Channel | WordDistance | Примеры Text |
|-----|-----------|---------|-------------|-------------|
| **WORD** | Искомое слово | ANY/CLIENT/OPERATOR | 0–3 | любое слово |
| **LEXEME** | Логический оператор | Всегда ANY | Всегда 2 | `И`, `ИЛИ`, `НЕ` |
| **TERMINAL** | Структурный символ | Всегда ANY | Всегда 2 | `"`, `(`, `)` |
| **WHITESPACE** | Разделитель | Всегда ANY | Всегда 2 | ` ` (один пробел) |

### 2.2. Определение фразы

**Фраза** = последовательность WORD-токенов с **одинаковым Channel**, идущих подряд без разделяющих LEXEME-токенов. WHITESPACE между словами фразы присутствует, но **не разрывает** фразу.

```xml
<!-- Это одна фраза "Фраза шесть" -->
<Token><Text>Фраза</Text><Type>WORD</Type><Properties Channel="CLIENT" WordDistance="2" /></Token>
<Token><Text> </Text><Type>WHITESPACE</Type><Properties Channel="ANY" WordDistance="2" /></Token>
<Token><Text>шесть</Text><Type>WORD</Type><Properties Channel="CLIENT" WordDistance="2" /></Token>
```

**LEXEME разрывает** фразу на отдельные операнды.

### 2.3. Правила вставки WHITESPACE

WHITESPACE вставляется между **каждой парой** значимых токенов.

**Единственное исключение** (отсутствие WHITESPACE): между кавычкой `"` и словом **внутри** закавыченной фразы.

| Левый токен | Правый токен | WHITESPACE |
|---|---|---|
| `"` (открывающая) | WORD (внутри) | **НЕТ** |
| WORD (внутри) | `"` (закрывающая) | **НЕТ** |
| Любой токен (снаружи) | `"` (открывающая) | **ДА** |
| `"` (закрывающая) | Любой токен (снаружи) | **ДА** |
| `(` | Любой следующий токен | **ДА** |
| Любой токен | `)` | **ДА** |
| `)` | `)` | **ДА** |
| WORD | WORD | **ДА** |
| WORD | LEXEME | **ДА** |
| LEXEME | WORD | **ДА** |

---

## 3. Channel (канал поиска)

| Значение | Смысл |
|----------|-------|
| `CLIENT` | Искать только в речи клиента |
| `OPERATOR` | Искать только в речи оператора |
| `ANY` | Искать в речи обоих участников |

**Правило:** все слова **одной фразы** имеют одинаковый Channel. Невозможно, чтобы одно слово фразы было CLIENT, а другое OPERATOR.

Однако в **одном выражении** через логические операторы можно комбинировать слова с разными каналами (например: `слово1 (OPERATOR) ИЛИ слово2 (CLIENT)`).

---

## 4. WordDistance

Определяет количество **промежуточных слов**, допустимых между словами одной фразы. Применяется между **каждой парой** слов фразы.

| WordDistance | Поведение |
|---|---|
| `0` | Нет промежуточных слов (валидное значение, не fallback) |
| `1` | Допускается 1 промежуточное слово |
| `2` | Допускается 2 промежуточных слова (значение по умолчанию) |
| `3` | Допускается 3 промежуточных слова |

Может быть любым числом, но на практике не используется более 3.

---

## 5. Механика поиска

### 5.1. Фраза БЕЗ кавычек (обычные WORD-токены, `is_exact=False`)

- **Морфология:** свободная — совпадение по любой словоформе (лемматизация через pymorphy3)
- **Порядок слов:** свободный — слова могут идти в любом порядке
- **Промежуточные слова:** по WordDistance
- **Алгоритм:** `morph_bow` (morphological bag-of-words)

Пример: фраза `поменял тариф` с WordDistance=2 найдёт:
- "поменяю тариф" ✓ (морфология)
- "тариф поменялся" ✓ (порядок + морфология)
- "тариф мой зачем поменяете" ✓ (WordDistance=2, морфология, порядок)

### 5.2. Фраза В кавычках (`is_exact=True`)

- **Морфология:** точная — только указанная словоформа (без лемматизации)
- **Порядок слов:** свободный
- **Промежуточные слова:** по WordDistance — те же правила, что и без кавычек
- **Алгоритм:** `exact_bow` (exact form bag-of-words)

Пример: `"Перешёл к вам"` с WordDistance=2:
- "Перешёл к вам" ✓ (точная форма)
- "к вам Перешёл" ✓ (порядок свободный)
- "Перешёл уже к вам" ✓ (WordDistance=2)
- "Перешла к вам" ✗ (форма изменена)

### 5.3. Критическое правило кавычек

| Параметр | Что контролирует |
|----------|-----------------|
| **Кавычки** (`is_exact`) | Только **морфологию** — точная словоформа vs лемматизация |
| **WordDistance** | Только **количество промежуточных слов** между словами фразы |
| **Порядок слов** | Всегда **свободный** (неуправляемый параметр, и с кавычками, и без) |

---

## 6. Логические операторы (LEXEME)

| Оператор | Позиция | Функция |
|----------|---------|---------|
| `И` / `AND` | Инфиксный | Оба условия обязательны |
| `ИЛИ` / `OR` | Инфиксный | Любое из условий |
| `НЕ` / `NOT` | Префиксный | Исключение следующего операнда из результатов |

### 6.1. Различие `НЕ` и `не`

- **`НЕ`** — Type=LEXEME, верхний регистр, Channel=ANY — **исключает** следующий операнд из результатов поиска
- **`не`** — Type=WORD, нижний регистр, Channel=любой — **искомое слово** в речи (часть фразы)

### 6.2. Паттерн "И НЕ"

`И НЕ` = обязательное отсутствие. Оператор `НЕ` может стоять в начале запроса (исключающий узел) или после `И`.

### 6.3. Скобки и приоритет

Скобки `()` группируют выражения для управления приоритетом. Вложенные скобки допустимы (минимум 2 уровня).

**Предполагаемый приоритет без скобок:**
1. `НЕ` — высший (применяется к ближайшему операнду)
2. `И` — средний
3. `ИЛИ` — низший

**На практике рекомендуется всегда использовать скобки** для сложных выражений.

### 6.4. Формальная грамматика

```
Выражение  := Операнд ((И | ИЛИ) [НЕ] Операнд)*
Операнд    := [НЕ] (Слово | Фраза | "(" Выражение ")" | '"' Фраза '"')
Фраза      := Слово (Слово)*
Слово      := WORD-токен с Channel и WordDistance
```

---

## 7. Инварианты поиска

| ID | Инвариант | Суть | Статус |
|----|-----------|------|--------|
| **INV-6** | Level assignment | Контейнерные узлы (без conditions) **не занимают уровень**; дети наследуют уровень родителя | ✅ Preserved |
| **INV-7** | GATE model | Дочерний уровень ищется **только если** родительский узел matched. Поиск по **всем репликам** диалога, не только по родительским | ✅ Preserved |
| **INV-8** | ~~Morph override~~ | ~~is_exact игнорируется; всегда морфологический BOW~~ | ❌ **REMOVED** — is_exact уважается, `exact_bow` vs `morph_bow` |

> **Важно:** `INV-8` был удалён в UI-2.5 parser rewrite. Флаг `is_exact` из XML **влияет на поиск**: `True` = exact form BOW (без лемматизации), `False` = morphological BOW (с лемматизацией). Порядок слов **всегда свободный** в обоих режимах.

---

## 8. GATE model (каскадный поиск)

### 8.1. Принцип

Каждый словарь в каскаде ищется только если все предыдущие словари совпали (`cascade_order` = 1, 2, 3...).

Внутри словаря: дочерний уровень ищется только если родительский узел matched.

### 8.2. Логика GATE

```
Для каждого словаря в каскаде:
  _search_recursive(node=root, level=1):
    Если node.conditions:
      Для каждого condition:
        _match_condition() → matches
        Если condition.is_exception (НЕ-условие) и matched → suppress node
      GATE = evaluate_phrase_logic_tree(phrase_groups, matched_texts)
            → node_matched (AND=all match, OR=any match, NOT=not matched)
      Если node_matched AND NOT suppressed → gate opens for children
    
    Если node пустой (container, INV-6):
      children inherit level + GATE + parent_match_times
    
    Для каждого child:
      _search_recursive(node=child, level=level+1, 
                        allowed_turn_indices=gate_state)
```

**Ключевое:** GATE определяет, ищется ли дочерний уровень. Поиск по **всем репликам** диалога, не только по родительским.

### 8.3. Logic tree evaluation

`evaluate_phrase_logic_tree(phrase_groups, matched_texts)`:
- **AND:** все AND-children должны match
- **OR:** любой OR-child должен match
- **NOT:** NOT-child не должен match (suppression)

Приоритет: НЕ > И > ИЛИ.

---

## 9. Морфологическое сопоставление

### 9.1. pymorphy3 лемматизация

Основной алгоритм — pymorphy3 для русской лемматизации. Каждое слово приводится к нормальной форме (лемме), и сопоставление идёт по леммам.

### 9.2. Аспектуальные пары глаголов

Специальная обработка для пар глаголов совершенного/несовершенного вида:

```python
_ASPECTUAL_PAIRS = {
    "переключить": "переключать",
    "перейти": "переходить",
    "уйти": "уходить",
    "отказаться": "отказываться",
    "расторгнуть": "расторгать",
    "отключить": "отключать",
    "подключить": "подключать",
    "закрыть": "закрывать",
    "остановить": "останавливать",
    "прекратить": "прекращать",
    # ... полный список в morph_matcher.py:_ASPECTUAL_PAIRS
}
```

Если искомое слово — глагол совершенного вида, матчинг также ищет несовершенный вид (и наоборот).

### 9.3. Fallback-цепочка

```
1. morph_matcher.match_phrase_morphological_detailed (preferred)
   ↓ ImportError
2. smartlogger.matcher.match_phrase_sliding_window (fallback)
   ↓ ImportError
3. _fallback_match (regex-based BOW, last resort)
```

### 9.4. Производительность

- `lru_cache(maxsize=50000)` для `get_lemma()` 
- Precompute: `_tokenize` + `_find_word_positions` вызываются один раз на turn, переиспользуются всеми conditions одного node
- Для типичного production-словаря (~5 conditions, ~50 turns): 500 → 100 вызовов токенизатора

---

## 10. Time-gap filtering (ExtraLimitations)

### 10.1. Структура

Real XML-словари хранят time-gap limits в `<ExtraLimitations>`, а не в `<Tokens>`:

```xml
<ExtraLimitations>
  <ExtraLimitation>
    <EventType>StartEnd | Parent</EventType>
    <SearchSpecifier>OnlyInGaps | ExcludeGaps</SearchSpecifier>
    <Settings />
    <Limits>
      <Limit>
        <Value>{число}</Value>
        <ValueType>Seconds | Words</ValueType>
        <Channel>CLIENT | OPERATOR | ANY</Channel>
        <Enabled>true</Enabled>
        <!-- Только для EventType=StartEnd: -->
        <LimitType>First | Last</LimitType>
        <!-- Только для EventType=Parent: -->
        <EventSelector>Each | First</EventSelector>
        <SearchDirection>Before | After</SearchDirection>
      </Limit>
    </Limits>
  </ExtraLimitation>
</ExtraLimitations>
```

### 10.2. Два типа EventType

| EventType | Описание | Поля |
|-----------|----------|------|
| `StartEnd` | Limits относительно начала/конца диалога | `LimitType` (First/Last) |
| `Parent` | Limits относительно совпадений родительского узла | `EventSelector` (Each/First), `SearchDirection` (Before/After) |

### 10.3. SearchSpecifier

| SearchSpecifier | Описание |
|-----------------|----------|
| `OnlyInGaps` | Искать только в временных промежутках между событиями |
| `ExcludeGaps` | Исключить временные промежутки между событиями |

### 10.4. Требования

Time-gap filtering работает **только** если `DialogueTurn` содержит `start_offset`/`end_offset` (секунды от начала диалога). Если RTF не содержит временных меток → `None` → фильтрация пропускается (no-op).

---

## 11. Deprecated поля

| Поле | Статус | Причина |
|------|--------|---------|
| `DictionaryCondition.without_list` | **DEPRECATED** — всегда `[]` | Real XML stores time-gap limits в `<ExtraLimitations>`, не как phrase-WITHOUT |
| `DictionaryCondition.exception_phrases` | **DEPRECATED** — всегда `[]` | Suppression через `is_exception` на `PhraseGroup` |

---

## 12. Контракты моделей данных

### PhraseGroup (внутренняя, для search/logic tree)

```python
PhraseGroup:
    words: List[str]        # Слова фразы
    channel: str             # CLIENT / OPERATOR / ANY
    word_distance: int       # 0-3
    is_exact: bool           # True если в кавычках
    is_negated: bool         # True если preceded by НЕ (LEXEME)
    operator: str            # '' | 'AND' | 'OR' (НЕ хранится здесь — для этого есть is_negated)
```

### PhraseGroupVisual (FE-контракт, для визуализации)

```python
PhraseGroupVisual:
    words: List[str]         # Слова OR-группы
    is_or_group: bool        # Всегда True (каждая PhraseGroup — отдельная OR-альтернатива)
    is_exception: bool       # True если группа preceded by НЕ
```

> **Важно:** `PhraseGroup` (internal, для search) ≠ `PhraseGroupVisual` (FE-контракт, для визуализации). Разные поля, разные типы — НЕ путать.

### LogicNode (логическое дерево)

```python
LogicNode:
    node_type: str           # AND | OR | NOT | ATTRIBUTE | PHRASE | GROUP
    children: List[LogicNode]
    payload: Dict            # Данные для leaf-узлов (DecodedAttribute)
```

### DictMatch (FE-контракт — НЕ менять имена/типы)

```python
DictMatch:
    phrase_text: str         # Фраза из словаря
    matched_text: str        # Реальный текст из диалога
    matched_start: int       # Символьное смещение начала (-1 = не вычислено)
    matched_end: int         # Символьное смещение конца
    quarter: str             # Имя словаря
    turn_index: int          # Номер реплики
    speaker: str             # Спикер
    match_type: str          # 'morph_bow' | 'exact_bow'
    word_distance_used: int  # Уровень иерархии (1=root, 2=child, ...)
    cascade_order: int       # Порядок словаря в каскаде (1-based)
    is_exact_match: bool     # True если exact (кавычки)
    word_distance: int        # Оригинальный word_distance из condition
    channel_constraint: str  # Channel из condition
    dict_level: int          # Уровень (1=Q1, 2=Q2, 3=Q3)
    is_remainder: bool       # True если из SpeechLabRemainderRequest
```

---

## 13. Минимальный валидный словарь

```xml
<?xml version="1.0"?>
<SpeechLabRequest type="SpeechLabRequest">
  <Id>xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx</Id>
  <Name>Мой словарь</Name>
  <State>SAVED</State>
  <SavedState>
    <TotalFound>0</TotalFound>
    <LastUpdateTime>2026-01-01T00:00:00.0000000Z</LastUpdateTime>
    <ExecutionTime>00:00:00</ExecutionTime>
    <IsActual>true</IsActual>
    <IsCancelled>false</IsCancelled>
  </SavedState>
  <Temporary>False</Temporary>
  <OrderIndex>0</OrderIndex>
  <IsThemed>False</IsThemed>
  <Attributes><AttributeTokens /></Attributes>
  <Tokens />
  <ExtraLimitations />
  <ComplexCompleted>False</ComplexCompleted>
  <Requests>
    <SpeechLabRequest type="SpeechLabRequest">
      <Id>yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy</Id>
      <Name>Запрос 1</Name>
      <State>SAVED</State>
      <SavedState>...</SavedState>
      <Temporary>False</Temporary>
      <OrderIndex>0</OrderIndex>
      <IsThemed>False</IsThemed>
      <Attributes><AttributeTokens /></Attributes>
      <Tokens>
        <Token><Text>слово1</Text><Type>WORD</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2" /></Token>
        <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2" /></Token>
        <Token><Text>ИЛИ</Text><Type>LEXEME</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2" /></Token>
        <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2" /></Token>
        <Token><Text>слово2</Text><Type>WORD</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2" /></Token>
      </Tokens>
      <ExtraLimitations />
      <ComplexCompleted>False</ComplexCompleted>
      <Requests />
    </SpeechLabRequest>
  </Requests>
</SpeechLabRequest>
```

---

## 14. Сводка ключевых правил

1. Каждый узел имеет уникальный GUID
2. Корневой узел — пустой `<Tokens />`, содержит дочерние в `<Requests>`
3. Токены идут строго последовательно с WHITESPACE между значимыми токенами
4. Единственное исключение по WHITESPACE — внутри кавычек (между `"` и словом)
5. Все слова одной фразы — одинаковый Channel и одинаковый WordDistance
6. LEXEME/TERMINAL/WHITESPACE всегда Channel="ANY", WordDistance="2"
7. Операторы записываются ВЕРХНИМ регистром (И, ИЛИ, НЕ), искомые слова — как есть
8. OrderIndex нумерует узлы одного уровня начиная с 0
9. **Кавычки `"` контролируют только морфологию** (точная форма vs лемматизация)
10. **WordDistance контролирует только количество промежуточных слов**
11. **Порядок слов всегда свободный** (неуправляемый параметр)
12. Остаток (SpeechLabRemainderRequest) не имеет Tokens/Attributes/ExtraLimitations/ComplexCompleted
13. `Attributes`/`AttributeTokens` — специфика SmartLogger, можно игнорировать (оставлять пустым)
14. Остаток может быть на любом уровне и может содержать подуровни
