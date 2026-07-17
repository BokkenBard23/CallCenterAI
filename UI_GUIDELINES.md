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

> **✅ Tech debt resolved (Track B, 2026-07-07):** `ViewMode` union расширен, cast `'structure' as ViewMode` убран из `ResultsPage.tsx`. Три режима (`summary` | `highlighted` | `structure`) работают без type assertion.

---

## 5. Highlight Colors (P0-2 rework)

> **⚠️ ВНИМАНИЕ:** Цветовая палитра подсветки была полностью переработана в P0-2 rework.
> Источник правды: `src/components/highlight.scss`.

### 5.1. Depth-based палитра (актуальная)

| Depth | Название | Light bg | Dark bg | Border style |
|-------|----------|----------|---------|--------------|
| 1 | Критический | `rgba(211,47,47,0.15)` (red) | `rgba(239,83,80,0.25)` (red) | solid |
| 2 | Важный | `rgba(230,81,0,0.15)` (orange) | `rgba(255,112,67,0.25)` (orange) | dashed |
| 3 | Умеренный | `rgba(249,168,37,0.20)` (amber) | `rgba(255,202,40,0.25)` (amber) | dotted |
| 4 | Информационный | `rgba(0,137,123,0.15)` (teal) | `rgba(29,233,182,0.20)` (teal) | double |
| 5 | Справочный | `rgba(21,101,192,0.15)` (blue) | `rgba(66,165,245,0.25)` (blue) | dashed |
| 6 | Legacy | `#ffe0b2` (light orange) | `#5d4037` (brown) | dashed top |

### 5.2. Формула уровня

```
highlight_level = (cascade_order - 1) * 2 + word_distance_used
depth = min(cascade_order, 5)  // cascade > 5 → depth=5
```

### 5.3. Speaker card backgrounds

| Speaker | Light bg | Dark bg |
|---------|----------|---------|
| Клиент | `#e3f2fd` (light blue) | `#1a2a3e` (dark navy) |
| Сотрудник | `#f3e5f5` (light purple) | `#2a1a3e` (dark purple) |

> **⚠️ Known gap:** Speaker labels (`Сотрудник`/`Клиент`) используют `color-text-primary`, не channel-specific colors. Различение только через фон карточки.

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

### 8.1. Pages & Routes

> **Источник правды:** `src/App.tsx` — routes defined lines 126-132.

| Route | Page | Назначение |
|-------|------|-----------|
| `/` | `UploadPage.tsx` | Загрузка RTF + XML (Stepper wizard + DropZone, auto-advance) |
| `/results` | `ResultsPage.tsx` | Результаты анализа (Grid responsive + TabPanel, 3 ViewMode). sessionId из AnalysisContext, не из URL. |
| `/batch-results/:batchId` | `BatchResultsPage.tsx` | Пакетные результаты (DS Table + AnimatedProgress, polling) |
| `/history` | `HistoryPage.tsx` | История анализов (LocalStorage, Pagination + Search) |
| `/speechlab` | `SpeechLabPage.tsx` | SpeechLab (3-panel resizable layout, XML tree, channel colors) |
| `/speechlab/:sessionId` | `SpeechLabPage.tsx` | SpeechLab с предзагруженной сессией |
| `/dictionary/:sessionId` | `DictionaryEditorPage.tsx` | Редактор словарей (CRUD + AI + Mining + XML export) |

> **⚠️ Внимание:** Ранее документация упоминала `/results/:sessionId`, `/batch/:batchId` и `/speech-lab`. Эти пути **не существуют** в `App.tsx`. Реальные пути — в таблице выше. Код и внутренняя навигация (`navigate(...)`) консистентны с реальными путями.

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
