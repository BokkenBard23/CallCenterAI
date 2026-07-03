# Протокол работы с MCP дизайн-системы

MCP-сервер `design-system` предоставляет инструменты для `@beeline/design-system-react`, иконок (`Icons`), глобальных токенов и **заглушек изображений** (внешний [static.photos](https://static.photos/) или локальная папка).

Все tools сервера поддерживают два agent-а:
- **single** — обычный payload инструмента;
- **bulk** — `bulk: [...]`, где каждый элемент массива повторяет обычный payload этого же инструмента.

Bulk возвращает один **glued response** и полезен для нескольких однотипных lookup того же метода. Если нужен многошаговый bundle из разных tools, всё ещё предпочитай delegated MCP через `mcp-researcher`.

## Доступные инструменты

| Инструмент | Параметры | Назначение |
|-----------|-----------|-----------|
| `mcp-usage-guide` | — | Краткий порядок вызовов (компоненты vs иконки vs токены); вызывай при сомнении |
| `list-components` | `category?` (enum: form/display/feedback/layout/navigation/interactive/overlay/other) | Каталог компонентов; неверная категория → ошибка с допустимыми значениями |
| `search-component` | `query` (рус/англ), `limit?`, `category?` (тот же enum) | Поиск компонента; при пустом результате — сводка по категориям и подсказка повторить с `category` |
| `search-icon` | `query?`, `limit?`, `category?` | Только глифы `<Icon />` из `@beeline/design-tokens`; **не** для React-компонентов |
| `get-component` | `name` | Обзор: описание, import path, nested, related |
| `get-component-props` | `name`, `filter?`, `requiredOnly?` | Полный список пропсов (required/optional/deprecated) |
| `get-component-guidelines` | `name` | Рекомендации: do/don't, варианты, размеры, состояния |
| `get-component-examples` | `name`, `exampleId?`, `limit?` | Примеры из Storybook (args + JSX-код) |
| `list-categories` | — | Все категории с полным перечнем имён (тяжелее, чем `list-components`) |
| `get-global-design-tokens` | `format`, `category?`, `filter?`, `limit?`, `includeRaw?` | Токены дизайна (не компоненты и не иконки) |
| `get-placeholder-image` | `source` (`static` \| `local`), `width?`, `height?`, `category?`, `seed?`, `nameContains?` | Заглушки-картинки: `static` → URL WebP на [static.photos](https://static.photos/) (`https://static.photos/{category}/{width}x{height}/{seed}.webp` или без `category`); **slug категорий** — в описании инструмента (46 значений). `local` → случайный файл из `data/placeholder-images` или `PLACEHOLDER_IMAGES_DIR` |

### Разделение доменов

- **Иконки** (`Icon`, `Icons.*`) — только `search-icon`. Не использовать `search-component`.
- **React-компоненты** — `search-component` / `list-components` / `get-component*`. Не путать с иконками.
- **Глобальные токены** — только `get-global-design-tokens`. Не использовать его как замену `get-component-props`; это вспомогательный источник для цветов, типографики, elevation и части layout/styling, но не единственный способ принять хорошее визуальное решение.
- **Заглушки изображений** — только `get-placeholder-image`. Не путать с `search-icon` (глифы `Icons.*`) и не подставлять произвольные stock-URL «с потолка»: для согласованных placeholder-фото используй `source: static` и **slug категории** из описания tool; для офлайн/брендированных — `source: local`.

## Разделение по ролям

| Роль | Минимум MCP | Не вызывать по умолчанию |
|------|-------------|---------------------------|
| **Дизайнер** | `search-component` + `get-component` (по уникальным группам UI); `get-component-guidelines` — только если нужен variant / do-don't; при ссылках на **фото-заглушки** в макете/спеке — `get-placeholder-image` (static/local) | `get-component-props`, `get-component-examples` |
| **UI Coder** | полный Discovery по компонентам из Component Mapping / `REQUIRED_COMPONENTS`: минимум `get-component` + `get-component-props` перед JSX; для цветов/типографики/elevation и спорного styling — `get-global-design-tokens` как preferred source; для `<img>` / фоновых placeholder — `get-placeholder-image` вместо выдуманных URL | — |
| **Reviewer** | `get-component-props` для сверки спорных или массово используемых DS-компонентов; `get-global-design-tokens` как evidence для token names, когда команда реально заявляет опору на DS token source | `get-component-examples`, если спор не касается паттерна использования |
| **MCP Researcher** | пакетный delegated Discovery по brief от родительского agent-а; пишет `docs/specs/mcp-research/*.md` | broad discovery без списка потребностей |

Файл **`docs/specs/user-scenarios.json`** (Дизайнер) не заменяет MCP: трассировка сценариев и экранов для согласованности с spec (**hub `spec.md` + `spec-chunk-*`** или монолит) и тестов; компоненты сверяются через инструменты выше.

Полный цикл ниже относится к **реализации кода (UI Coder)**, не к проектированию макета.

## Direct MCP vs delegated MCP

Используй два agent-а работы:

### 1. Direct MCP

Допустим, если:
- нужен один быстрый lookup;
- спор касается одного пропса / одного nested API;
- данные уже почти собраны и нужен only-one confirmation.

### 1a. Bulk same-tool MCP

Предпочтителен, если:
- нужно выполнить несколько однотипных lookup одного и того же tool;
- достаточно одного glued response без запуска helper;
- не нужен multi-step bundle из разных инструментов.

Примеры:
- `get-component({ bulk: [{ name: "Button" }, { name: "Tabs" }] })`
- `get-component-props({ bulk: [{ name: "Button" }, { name: "TextField", filter: "icon" }] })`
- `search-icon({ bulk: [{ query: "search", limit: 5 }, { query: "warning", limit: 5 }, { query: "profile", limit: 5 }] })`
- `get-global-design-tokens({ bulk: [{ format: "scss", category: "colors" }, { format: "scss", category: "sizes" }] })`

Для иконок: один glyph / одно назначение → direct `search-icon`; несколько иконок для одного экрана, sidebar или status taxonomy → `search-icon` bulk. Не используй `mcp-researcher` для обычного подбора иконок.

### 2. Delegated MCP через `mcp-researcher`

Предпочтителен, если:
- нужно пройти 2+ последовательных MCP шага по нескольким компонентам, обычно 3+ компонентов или спорный multi-step bundle;
- ожидается bundle `component + props + optional examples + optional guidelines + type depth`;
- основной agent рискует раздуть контекст сырыми MCP-ответами;
- нужен повторно используемый research-артефакт для chunk / review.

`mcp-researcher` — служебный helper-agent, а не обязательный этап графа. Родительский agent запускает его через `Task / @mcp-researcher`, helper возвращает результат через короткий subagent result и пишет обязательный артефакт в `docs/specs/mcp-research/`.

Не используй `mcp-researcher` для chunk processing, decomposition, design writing, implementation, review routing или тестирования. Он собирает только scoped DS evidence; текущий stage-agent остаётся владельцем своей работы.

Если текущий bundle оказался `partial` / `blocked`, либо после него всё ещё не хватает usage pattern или смысла alias/custom type, основной agent обязан сделать повторный `Task / @mcp-researcher` в `mcp-researcher`, а не silently уходить в локальное чтение библиотеки.

## Brief для delegated MCP

Когда основной agent делегирует DS-исследование helper-у, `Task / @mcp-researcher` brief должен содержать минимум:

```yaml
consumer: designer | ui-coder | reviewer
scope: string
request_id: string | null
chunk: number | null
questions_to_answer:
  - string
required_components:
  - string
required_outputs:
  - component_name
  - import_path
  - nested
  - key_props
  - examples # только если usage pattern реально нужен
  - guidelines # только если нужен variant / do-don't / state guidance
  - type_depth # если alias/custom type влияет на решение
artifact_hint: string | null
reuse_existing_artifact: true
```

Правила:
- `required_components` не должен быть «весь каталог DS»;
- `required_outputs` подстраивай под роль;
- при повторной работе по тому же chunk сначала читай существующий `docs/specs/mcp-research/*.md`.
- `examples` не обязательны globally: включай их в brief только если текущего bundle недостаточно без реального usage pattern.
- `type_depth` добавляй, если alias/custom type влияет на API-решение (`BoxSpacing`, `KeyLogosImgList`, literal unions и т.п.).

## Артефакт delegated MCP

По умолчанию helper пишет:

```text
docs/specs/mcp-research/chunk-<chunk>-<consumer>.md
```

или:

```text
docs/specs/mcp-research/request-<request_id>-<consumer>.md
```

Артефакт должен содержать:
- контекст brief;
- coverage status (`ready` / `partial` / `blocked`);
- `usage_pattern_status`, `type_depth_status`, `source_of_truth`;
- список проверенных компонентов;
- только полезные prop / example / guideline excerpts;
- `gaps`, `blockers`, `follow_up_queries_if_needed`.

## Обязательный протокол Discovery (UI Coder / реализация)

Перед написанием JSX с DS-компонентом из **Component Mapping** выполни последовательно:

```
1. search-component({ query: "<что нужно>" })           → если имя ещё не зафиксировано в `design-spec-chunk-{N}.md` / монолитном design-spec
2. get-component({ name: "<ComponentName>" })            → Обзор: import, nested, related
3. get-component-props({ name: "<ComponentName>" })      → Пропсы: required, optional, deprecated
4. get-component-examples({ name: "<ComponentName>" })   → по сложности: рабочий JSX из Storybook
5. get-component-guidelines({ name: "<ComponentName>" }) → по сложности: do/don't, варианты
6. Реализовать компонент на основе полученных данных
```

**Дизайнер:** достаточно шагов 1–2 (и пункт 5 опционально); шаги 3–4 не выполнять без необходимости согласования API — это раздувает число запросов и дублирует работу UI Coder.

Для **multi-call** discovery дизайнеру предпочтительно делегировать поиск через `mcp-researcher`, а в основном контексте держать только сжатый результат и ссылку на research-артефакт. Исключение: несколько однотипных lookup одного и того же tool можно собрать через его `bulk`.

## Оптимизация: подход REQUIRED_COMPONENTS

Для предотвращения зацикливания и экономии контекста:

1. **ДО начала кода** составь список `REQUIRED_COMPONENTS` (максимум 15 компонентов)
2. **Источник истины для UI Coder:** колонка **DS-компонент** в **Component Mapping** файла **`design-spec-chunk-{N}.md`** (legacy: секция chunk в монолитном `design-spec.md`) **копируется** в `REQUIRED_COMPONENTS` (уникальные имена). Не добавляй компоненты вне mapping без явной причины (новый UI-элемент → согласование с дизайн-артефактом или `ds_gap`).
3. Для `REQUIRED_COMPONENTS` предпочитай delegated MCP через `mcp-researcher`, если bundle больше одного-двух компонентов или нужны `examples/guidelines`
4. Пройди Discovery для каждого компонента из `REQUIRED_COMPONENTS`
5. Сохрани полученную информацию как `componentRegistry` или используй research-артефакт как источник истины для chunk
6. Пиши код, используя `componentRegistry`; дополнительные MCP-запросы — только для компонентов **вне** изначального списка (например исправление ошибки типов)

### Обязательный минимум перед вёрсткой (компоненты из mapping)

Для каждого компонента из **Component Mapping** (строка в `design-spec-chunk-{N}.md` или legacy-монолите):

- **Запрещено** писать JSX с этим компонентом, пока не выполнен минимум: `get-component` + `get-component-props` (имена и типы пропсов из MCP).
- Если bundle собирался через `mcp-researcher`, эти данные можно брать из свежего research-артефакта вместо повторного MCP в основном контексте.
- `get-component-examples` и `get-component-guidelines` — по усложнённости (вложенный API, нестандартный паттерн).
- Если свежий research-артефакт помечен `partial` / `blocked`, кодить по нему как по `ready` запрещено: сначала повторный helper-вызов или явный controlled fallback с записью в артефакт.

## Tokens Flow (UI Coder / Reviewer)

Если стиль нельзя выразить DS props и нужен кастомный styling:

```
1. Сначала проверить, можно ли решить задачу через DS component props или layout primitives (`Box`, `Stack`, `Grid`, `GridItem`)
2. Если нужен цвет / типографика / elevation / surfaces — вызвать get-global-design-tokens({ format, category, filter?, limit? }) и по возможности опереться на DS token source
3. Для spacing/layout сначала выбрать композиционно сильное решение; если DS token source помогает — использовать его, если нет — допускается controlled fallback ради результата
4. Если MCP дал полезный token name — зафиксировать точное имя токена и способ использования
5. Если MCP не помог или данные неполны — не деградировать в бедный layout; зафиксировать выбранный fallback в отчёте или review notes
```

Рекомендации по вызову:

- `format: "css"` — для CSS custom properties и `var(--token-name)`
- `format: "scss"` — для SCSS variables / imports
- `format: "js"` — для runtime/TS интеграций
- `category: "colors"` / `"palettes"` — цвет, фон, бордер, градиент
- `category: "sizes"` — spacing, размеры, радиусы, отступы, layout constants, если они реально помогают композиции
- `category: "fonts"` — типографика
- `category: "elevation"` — тени и уровни поверхности

Политика:

- `get-global-design-tokens` **не заменяет** `get-component-props`; это отдельный помощник для visual system и части styling.
- Для цветов, typography, surfaces и elevation DS tokens остаются предпочтительным источником при доступном MCP.
- Для spacing/layout не нужно превращать MCP tokens в обязательный шлагбаум: если DS layout props и handoff дают лучший результат, они имеют приоритет.
- Не выдумывать псевдо-DS custom properties как будто они подтверждены MCP: если токен не найден, лучше честный controlled fallback, чем ложная имитация DS token name.
- Reviewer использует тот же flow для проверки token claims в коде, `Implementation Report` и `docs/specs/mcp-research/*.md`, но оценивает и визуальный результат, а не только формальную token-чистоту.

## Placeholder images (designer / ui-coder)

Когда в wireframe, `design-spec` или коде нужны **реалистичные фото-заглушки** (не иконки и не DS-компоненты):

1. Вызвать `get-placeholder-image` с `source: static` и при необходимости **`category`** — slug темы с [static.photos](https://static.photos/) (полный список slug в **описании инструмента** MCP: `nature`, `office`, `technology`, …).
2. Опционально **`seed`** (целое) — стабильная картинка при тех же `category` / размере.
3. **`width` / `height`** — под нужный layout (по умолчанию 800×600).
4. Без категории: `category` опустить — URL вида `https://static.photos/{width}x{height}/{seed}.webp` (любая тематическая коллекция + тот же seed).
5. Для локальных ассетов проекта: `source: local`, опционально `nameContains` для фильтра по имени файла.

Не делегировать сбор placeholder-URL в `mcp-researcher` без явной необходимости — обычно достаточно **одного** вызова `get-placeholder-image`.

## Политика переиспользования research-файлов

- Один chunk / один consumer → один актуальный research-файл, который можно дозаполнять.
- Перед новым delegated MCP сначала читай последний `latest_mcp_research_artifact` из `pipeline-state.yaml`, если он относится к текущему scope.
- Не пересобирай полный bundle заново, если достаточно дозаполнить 1-2 поля.
- Если данные устарели из-за смены mapping / chunk, явно фиксируй это в `Reuse Notes`.

### Антипаттерны (ЗАПРЕЩЕНО)

- Перебирать ВСЕ компоненты через `list-components` без цели
- Зацикливаться на поиске «идеального» компонента
- Повторно вызывать `get-component` для уже изученного компонента
- Добавлять новые компоненты в список после начала кодирования (без явной команды или без обновления `ds_gaps`)
- Дублировать полный MCP bundle и в research-файле, и в ответе основного agent-а
- Заставлять `designer` / `ui-coder` / `reviewer` повторять один и тот же multi-call discovery, если есть свежий research-артефакт

### Именованные классы нарушений (для Reviewer / post-mortem)

- `layout_no_container` — контент без ограничения ширины / без сетки там, где в wireframe есть колонки.
- `theme_override_hex` — произвольные `#`/`rgb`/`hsl` в стилях поверх темы без `// DS gap`.
- `component_substitution_without_ds_gap` — в коде другой DS-компонент или паттерн, чем в mapping (например `Link` вместо `Tabs`), без явной секции «Отклонения от design-spec» и пометки `ds_gap`.

## Правила

- НЕ угадывать имена пропсов — всегда проверять через `get-component-props`
- Русскоязычные запросы поддерживаются в `search-component` (кнопка, модалка, поле ввода)
- Если MCP-сервер недоступен — уведомить пользователя проверить настройки MCP в Cursor/OpenCode Settings
- При ошибке MCP — retry до 3 раз с паузой, затем уведомление пользователю
- Локальный fallback к `.d.ts` / исходникам допустим только после повторного helper-вызова или исчерпания MCP по текущему scope, и только с явной записью в `docs/specs/mcp-research/*.md` / `Implementation Report`

## Референс-изображения

Референс-скрины/PDF — файлы в репозитории (`design_input_artifacts.path_or_ref`, обычно `docs/assets/...`) плюс **текстовое** описание структуры в запросе, `spec.md` / chunk spec или design-spec fidelity checklist. Автоматического разбора пикселей в пайплайне нет.
