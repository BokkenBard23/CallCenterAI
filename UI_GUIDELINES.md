# UI Guidelines

Дизайн-система, правила фронтенда, контракты BE↔FE, 3-tier context loading policy.

> **Источник правды:** код (`src/types/speechlab.ts`, `src/types/api.ts`, `src/components/`).
> **DS-справка:** `@beeline/design-system-react` 2.5.
> **Архитектурный обзор:** `ARCHITECTURE.md`.

---

## 1. Design System

### 1.1. Базовая DS

- **Пакет:** `@beeline/design-system-react` 2.5.0
- **Токены:** `@beeline/design-tokens`
- **Custom UI components FORBIDDEN** — ds_gaps решаются minimal DS-styled wrappers (например, `ChannelTag`, `TokenBadge`)
- **47 DS компонентов** инвентаризировано (`docs/specs/mcp-research/track-d-ds-prop-inventory.md`)

### 1.2. DS prop drift detection

- **Скрипт:** `scripts/check-ds-drift.ts` — regex `.d.ts` parser + `src/` grep
- **CI:** `.github/workflows/ds-drift.yml` — weekly Sunday cron + GitHub issue on drift
- **Команда:** `npm run check:ds-drift` (exit 1 = inventory gap, не blocker)

### 1.3. Известные DS gotchas (v2.5)

| Gotcha | Решение |
|--------|---------|
| `Slider` infinite loop | Fixed in LexiCore Phase 2 |
| `TableCell` ≠ `TableData` | Использовать `TableData` |
| `InlineEdit` requires `forwardRef` | Обернуть компонент в `forwardRef` |
| `Button.variant="text"` removed | Использовать `variant="ghost"` |
| `Icons.LoadingPlaceholder` removed | Использовать `Icons.Hourglass` |
| `Icon` не принимает `inactive={true}` (boolean) | Использовать `style={{opacity:0.5}}` или string |
| `Dialog.title` prop removed | Использовать `<Typography>` внутри Dialog |
| `Tree.TreeData` не экспортируется через barrel | Использовать локальный interface |

---

## 2. Channel Color-Coding

### 2.1. CSS custom properties

Цвета каналов задаются через CSS custom properties (с fallback):

| Channel | CSS variable | Fallback | Цвет |
|---------|-------------|----------|------|
| `OPERATOR` | `--dict-channel-operator` | `#81c784` / `#e8f5e9` / `#2e7d32` | Зелёный |
| `CLIENT` | `--dict-channel-client` | `#4fc3f7` / `#e1f5fe` / `#0277bd` | Синий |
| `ANY` | `--dict-channel-any` | `#ffb74d` / `#fff3e0` / `#e65100` | Оранжевый |

Источник: `src/types/speechlab.ts:CHANNEL_COLORS`.

### 2.2. Где используется

- `HighlightRenderer.tsx` — подсветка совпадений в тексте диалога
- `DictionaryPhraseItem.tsx` — цветовая точка рядом с фразой
- `DictionaryTree.tsx` — цвет узла дерева
- `PhrasePopover.tsx` — цвет popover
- `TokenBadge.tsx` — Badge с channel-color styling
- `ChannelTag.tsx` — semantic color mapping

### 2.3. Channel → DS Badge semantic (Dictionary Editor)

В Dictionary Editor channel-color-coding реализован через Badge semantic:

| Channel | Badge type | Семантика |
|---------|-----------|-----------|
| ANY | neutral | Нейтральный |
| OPERATOR | violet | Оператор |
| CLIENT | success | Клиент |
| SYSTEM | hidden | BE gap (не отображается) |

---

## 3. DisplayToken (FE-контракт)

### 3.1. Тип

```typescript
type DisplayTokenType = 'WORD' | 'PHRASE' | 'LEXEME' | 'BRACKET';
```

> **ЗАПРЕЩЕНО менять значения.** Это FE-контракт, рендерится в `speechlab.ts` и компонентах.

### 3.2. Interface

```typescript
interface DisplayToken {
  text: string;
  type: DisplayTokenType;
  channel: 'OPERATOR' | 'CLIENT' | 'ANY';
  word_distance: number;  // max of group
  is_error: boolean;
  is_exact: boolean;      // True если фраза была в кавычках (TERMINAL ")
}
```

### 3.3. Маппинг XML → DisplayToken

| XML Token Type | DisplayToken type | Примечание |
|----------------|-------------------|------------|
| WORD | WORD (если 1 слово) или PHRASE (если группа) | Группировка по Channel |
| LEXEME (`И`, `ИЛИ`, `НЕ`) | LEXEME | Рендерится как badge с оператором |
| TERMINAL (`(`, `)`) | BRACKET | Скобки для группировки |
| TERMINAL (`"`) | absorbed into PHRASE | `is_exact=True` на PHRASE |
| WHITESPACE | не отображается | Разделитель |

---

## 4. ViewMode

```typescript
type ViewMode = 'summary' | 'highlighted' | 'structure';
```

| Mode | Что показывает | Где используется |
|------|---------------|----------------|
| `summary` | LLM-саммари диалога | ResultsPage |
| `highlighted` | Текст диалога с подсветкой совпадений | ResultsPage (default) |
| `structure` | Структурированный вид (дерево словаря) | ResultsPage |

> **⚠️ Known tech debt:** `ResultsPage.tsx:178` содержит cast `'structure' as ViewMode` — type-system врёт. Нужно расширить `ViewMode` union (см. TODO_AND_ROADMAP.md).

---

## 5. DictMatch: Highlight Level Formula

Подсветка совпадений по уровням:

```typescript
highlight_level = (cascade_order - 1) * 2 + word_distance_used
```

| cascade_order | word_distance_used (level) | highlight_level | Цвет |
|---------------|---------------------------|-----------------|------|
| 1 | 1 (root) | L1 | Yellow |
| 1 | 2 (child) | L2 | Green |
| 2 | 1 (root) | L3 | Cyan |
| 2 | 2 (child) | L4 | Pink |
| 3 | 1 (root) | L5 | Purple |
| 3 | 2 (child) | L6 | Orange |

`match_type` определяет стиль подсветки:
- `morph_bow` — морфологическое совпадение
- `exact_bow` — точная словоформа (кавычки)

---

## 6. BE↔FE Контракты (критичные)

| Контракт | Правило |
|----------|--------|
| `DictMatch` | FE-контракт — НЕ менять field names/types. Все 15 полей синхронизированы BE↔FE |
| `DisplayToken.type` | `WORD` / `PHRASE` / `LEXEME` / `BRACKET` — **ЗАПРЕЩЕНО менять** |
| `PhraseGroupVisual` | `{words: string[], is_or_group: bool, is_exception: bool}` — BE/FE совпадают |
| `DialogueTurn` | BE имеет `start_offset`/`end_offset` (optional в FE) |
| `DictionaryCondition` | BE имеет `extra_limitations` (optional в FE) |
| `is_exact` | **Влияет на поиск** (INV-8 removed): True=exact form BOW, False=morph BOW |
| `without_list` | DEPRECATED, всегда `[]` |
| `exception_phrases` | DEPRECATED, всегда `[]` |
| `PhraseGroup` (internal) ≠ `PhraseGroupVisual` (FE) | Разные поля, разные типы |

---

## 7. Quality Score UI

12 категорий качества с цветовой кодировкой:

| Quality | Цвет | Hex |
|---------|------|-----|
| High | Зелёный | `#4caf50` |
| Medium | Жёлтый | `#ff9800` |
| Low | Красный | `#f44336` |

Компонент: `src/components/QualityScorePanel/QualityScorePanel.tsx`

---

## 8. Структура Frontend

### 8.1. Pages

| Page | Назначение |
|------|-----------|
| `UploadPage.tsx` | Загрузка RTF + XML (Stepper + DropZone) |
| `ResultsPage.tsx` | Результаты анализа (Grid responsive + TabPanel, 3 ViewMode) |
| `BatchResultsPage.tsx` | Пакетные результаты (DS Table + AnimatedProgress) |
| `HistoryPage.tsx` | История анализов (Pagination + Search) |
| `SpeechLabPage.tsx` | SpeechLab (3-panel layout, XML tree, channel colors) |
| `DictionaryEditorPage.tsx` | Редактор словарей (CRUD + AI + Mining + XML export) |

### 8.2. Key components

| Component | Назначение |
|-----------|-----------|
| `HighlightedTextView` | Текст диалога с подсветкой совпадений |
| `HighlightRenderer` | Рендеринг подсветки (channel colors) |
| `MatchLegend` | Легенда цветов подсветки |
| `MatchCounter` | Счётчик совпадений |
| `StatusBadge` | Badge статуса (forwardRef для Tooltip) |
| `ErrorBoundary` | Error boundary на каждый роут |
| `QualityScorePanel` | 12 категорий качества |
| `SemanticSearchPanel` | Семантический поиск |
| `DictionaryEditor/` | 21+ компонент (Tree, ConditionsTable, AIAnalysis, Duplicates, etc.) |
| `MiningPanel/` | 3 tabs: Similar, FalseNegatives, LLM Audit |

### 8.3. State management

- `AnalysisContext.tsx` — глобальный state через `useReducer`
- `SnackbarContext.tsx` — toast-уведомления
- `HoverContext.tsx` — hover state
- `useSpeechLabState.ts` — агрегирует api + context
- `useMiningState.ts` — state mining panel

### 8.4. API client

`src/api/client.ts` — единый HTTP-клиент, ~20 экспортированных функций:
`checkHealth`, `uploadRtf`, `uploadDictionary`, `analyze`, `getResults`, `getProviders`, `getProviderStatus`, `submitBatch`, `getBatchStatus`, `getBatchResults`, `exportExcel`, `exportPdf`, `indexDialogue`, `searchSemantic`, `searchHybrid`, `getEmbeddingStatus`, `submitFeedback`, `getQualityScore` + `ApiError`

---

## 9. 3-Tier Context Loading Policy

Оптимизация контекстного окна AI-агентов через трёхъярусную классификацию документов.

### Tier 1 — Always Load (<5KB each)

| Файл | Назначение |
|------|-----------|
| `docs/specs/pipeline-state.yaml` | Единый источник правды для состояния пайплайна |
| `docs/specs/spec.md` | Hub-обзор спецификации |
| `docs/specs/backlog.json` | Бэклог задач |
| `ARCHITECTURE.md` | Архитектура системы |
| `DOMAIN_LOGIC.md` | Доменная логика |
| `UI_GUIDELINES.md` | Этот файл |
| `TODO_AND_ROADMAP.md` | Текущие задачи |

### Tier 2 — On Demand (по current_chunk)

| Файл | Когда загружать |
|------|----------------|
| `docs/specs/design-spec.md` | designer, ui-coder, reviewer |
| `docs/specs/design-spec-chunk-{N}.md` | При `current_chunk = N` |
| `docs/specs/spec-chunk-{N}.md` | При `current_chunk = N` |
| `docs/specs/implementation-chunk-{N}.md` | reviewer, tester |
| `docs/specs/ui-implementation-brief.md` | ui-coder (lock-in) |
| `docs/specs/user-scenarios.json` | ui-coder, tester |

### Tier 3 — Archive

Не загружается в стандартном потоке. Хранится в `docs/archive/`.

---

## 10. Environment Constraints

| Constraint | Правило |
|------------|--------|
| **OS** | Windows + corporate SSL proxy (McAfee) |
| **Shell** | PowerShell 5.1 — NO `&&`; use `;` or separate commands |
| **Python** | 3.12; `uv` NOT installed — use `pip`+`venv` |
| **Encoding** | ALWAYS `encoding='utf-8'`; `$env:PYTHONIOENCODING="utf-8"` for CLI |
| **Set-Content** | ALWAYS `-Encoding UTF8`; never bare `>` redirect (produces UTF-16LE) |
| **tsc** | `tsc -b --force` (NOT `tsc --noEmit` — composite project gotcha) |
| **Vite dev** | `npm run dev` → `http://localhost:5173` |
| **Backend** | `http://localhost:8000`, Vite proxy `/api` → `localhost:8000` |

### tsc Composite Project Gotcha

Root `tsconfig.json` имеет `files: []` + `references`. `tsc --noEmit` (без `-b`) проверяет 0 файлов → всегда ExitCode 0. 

**Использовать только:**
- `npm run typecheck` (== `tsc -b --noEmit`)
- `npx tsc -b --force`

---

## 11. Animation Components

8 MagicUI-адаптированных компонентов в `src/components/ui/`:

| Component | Назначение |
|-----------|-----------|
| `animated-circular-progress-bar` | Круговой прогресс |
| `animated-list` | Анимированный список |
| `animated-theme-toggler` | Переключатель темы |
| `blur-fade` | Blur-fade анимация |
| `border-beam` | Анимированная рамка |
| `file-tree` | Дерево файлов |
| `number-ticker` | Тикер чисел |
| `typing-animation` | Печатающийся текст |

---

## 12. Testing

| Framework | Что покрывает | Где |
|-----------|--------------|-----|
| Vitest + Testing Library | Все components/hooks/context/storage/utils | `src/**/*.test.{ts,tsx}` (54 файла) |
| a11y tests | Accessibility проверка | `App.a11y.test.tsx` |
| Smoke tests | Базовый рендеринг | `smoke.test.tsx` |

**Команды:**
```bash
npm run test         # vitest run
npm run typecheck    # tsc -b --noEmit
npm run lint         # eslint
npm run check:ds-drift  # DS prop drift check
```
