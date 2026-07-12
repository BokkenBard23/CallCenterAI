# 06 — UX/UI Research-First Rule

## Проблема

Агенты (особенно `ui-coder`, `designer`, `pipeline-orchestrator`) при решении UI/layout задач
часто пропускают этап исследования и сразу пишут код, деградируя до pixel-pushing.
Это приводит к:

- костылям вместо паттернов (фиксить `calc(100vh - 56px)` вместо flexbox chain)
- игнорированию накопленных аудитов и референсов
- бесконечным итерациям с конкретными разрешениями вместо универсальных решений
- изобретанию решений, для которых уже есть best practices

## Правило

Перед написанием CSS/layout кода для **любой нетривиальной UI-задачи** (не точечная правка текста/пропса),
агент ОБЯЗАН выполнить следующую цепочку:

### Step 1: Проверить существующие артефакты проекта

Прочитать (через Read/Grep/Glob) релевантные артефакты:

| Тип задачи | Где искать |
|------------|-------------|
| Layout/responsive | `docs/archive/specs/ui-reference-patterns-analysis.md` (flexbox, panel layout, viewport-fill) |
| Component patterns | `docs/archive/specs/ui-reference-discovery-v3.md` (DS component mapping, patterns) |
| DS component usage | `docs/archive/specs/ui-reference-discovery-v3-audit.md` (verified props, gaps) |
| Any UI task | `docs/archive/specs/ui-reference-session-final-summary.md` (сводка всех исследований) |
| Any UI task | `.opencode/rules/01-design-system-first.md` (DS-first принципы, layout primitives) |
| Any UI task | `PROJECT_MAP.md` (текущий стек, known issues, pre-existing bugs) |

### Step 2: Проверить MCP-инструменты UX

Использовать доступные UX MCP-инструменты для best practices:

- `ux-mcp-server_check_responsive` — проверить HTML/CSS на responsive issues
- `ux-mcp-server_suggest_pattern` — найти подходящий UI pattern по use_case
- `ux-mcp-server_review_usability` — проверить UI против Nielsen heuristics
- `ui-ux-pro-mcp_search_patterns` — найти layout/ux/product patterns
- `ui-ux-pro-mcp_search_styles` — найти style/color/typography patterns
- `ui-ux-pro-mcp_search_platforms` — platform-specific guidelines (iOS/Android)
- `ui-ux-pro-mcp_search_stack` — framework-specific guidelines (React, etc.)

### Step 3: Применить найденное

Только после Step 1 и Step 2 — писать код, опираясь на найденные паттерны.
В `implementation-chunk-{N}.md` указать источник паттерна.

## Что считается «нетривиальной UI-задачей»

- Любой layout, использующий `height`, `calc()`, `100vh`, `flex`, `grid`, `position: fixed/sticky`
- Responsive поведение (viewport-fill, panel resize, overflow management)
- Новый компонент (не точечная замена текста/пропса)
- Изменение существующего layout
- Любая задача, где можно написать «универсальное решение» вместо «хардкода под разрешение»

## Что НЕ требует research

- Точечная замена текста в компоненте
- Изменение пропса (color, size, variant)
- Исправление typo/импорта
- Добавление/удаление `startIcon` (если паттерн уже известен)

## Антипаттерны (ЗАПРЕЩЕНЫ)

1. **Pixel-pushing** — менять `height: calc(100vh - 56px)` на `height: calc(100vh - 48px)` 
   вместо перехода на `height: 100%` + flexbox chain.

2. **Resolution-specific fixes** — добавлять `@media (max-width: Npx)` для конкретного разрешения
   вместо универсального flexbox/grid решения.

3. **Skip research** — писать CSS без проверки существующих паттернов и аудитов.

4. **Manual iteration loop** — делать скриншот → измерять пиксели → подгонять значение → повторять.
   Вместо этого: найти паттерн → применить → проверить один раз.

5. **Hardcoded magic numbers** — `56px`, `24px` в layout вычислениях без связи с DS tokens
   или flexbox chain.

## Универсальный layout-паттерн (проверен аудитами)

Для web app shell, заполняющего viewport БЕЗ фиксированных высот:

```
html, body → height: 100% (НЕ 100vh)
#root → height: 100%
.app-root → height: 100%; display: flex; flex-direction: column; min-height: 0
  header → flex-shrink: 0 (фиксированная высота шапки, не участвует в calc)
  .app-main → flex: 1; min-height: 0; overflow-y: auto (занимает остаток)
    .page → height: 100%; display: flex; flex-direction: column; min-height: 0
      .page-topbar → flex-shrink: 0
      .page-content → flex: 1; min-height: 0; overflow: auto
```

**Ключевые принципы:**
- `height: 100%` на каждом уровне (не `100vh`)
- `min-height: 0` на flex-children, чтобы `overflow` работал
- `flex: 1` + `min-height: 0` + `overflow: auto` на scrollable-контейнере
- `flex-shrink: 0` на фиксированных элементах (header, topbar)
- НИКАКИХ `calc(100vh - Npx)` — flexbox сам распределяет пространство

## Источники (reference index)

| Артефакт | Содержание |
|----------|------------|
| `docs/archive/specs/ui-reference-patterns-analysis.md` | 8 reference repos analyzed, feature-mapping, risk analysis, Wave 1-4 plan |
| `docs/archive/specs/ui-reference-patterns-audit.md` | Reviewer audit (6.5/10), corrections to analysis |
| `docs/archive/specs/ui-reference-discovery-v3.md` | DS component discovery, 16 components mapped |
| `docs/archive/specs/ui-reference-discovery-v3-audit.md` | Audit of DS discovery |
| `docs/archive/specs/ui-reference-session-final-summary.md` | Final summary of all UI research sessions |
| `docs/archive/specs/ui-3-quick-reference.md` | Quick reference for DS components |
| `docs/archive/specs/ui-3-readiness-audit.md` | UI readiness audit pre-Track-B |
| `docs/specs/screenshots/vision-benchmark/VISION_BENCHMARK_RESULTS.md` | Vision model benchmark (gpt-5.4 winner) |
| `PROJECT_MAP.md` | Canonical project map, stack, known issues |
| `.opencode/rules/01-design-system-first.md` | DS-first principles, layout primitives |
| `.opencode/rules/05-vision-gate.md` | Vision-анализ mandatory rule |

## Инвариант

Если агент пишет CSS/layout код для нетривиальной UI-задачи без проверки п.1 и п.2,
а результат содержит hardcoded heights/resolution-specific fixes — это **blocker**.
Reviewer обязан вернуть в `ui-coder` / `designer` с пометкой `research_first_violation`.
