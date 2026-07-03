# Design System First

Все UI-компоненты по умолчанию берутся из библиотеки `@beeline/design-system-react`.

## Главный принцип

`Design System First` в этом пайплайне означает не «любой ценой следовать DS», а **строить сильный визуальный результат с опорой на DS**:

- сначала добиться живой, убедительной и хорошо дышащей композиции;
- затем опираться на DS-компоненты, layout primitives и documented props;
- затем, если MCP доступен и полезен, использовать DS colors / tokens / guidelines;
- если MCP недоступен, неполон или противоречив, не деградировать в бедный интерфейс: допускается controlled fallback с явным описанием решения.

## Правила

1. **Импорт**: по умолчанию из `@beeline/design-system-react`
   ```tsx
   import { Button, TextField, Select } from '@beeline/design-system-react';
   ```

2. **Пропсы**: использовать документированные пропсы (из MCP `get-component-props`). Имена пропсов не угадывать.

3. **Варианты и composition**:
   - сначала искать решение через DS-компоненты, `Box`, `Stack`, `Grid`, `GridItem`, documented props и layout primitives;
   - для layout приоритет у композиции и читаемости экрана, а не у формальной token-purity.

4. **Вложенные компоненты**: если `get-component` показывает nested components — использовать их (например, `Select.Option`, `List.Item`).

5. **ThemeProvider**: ОБЯЗАТЕЛЕН в корне приложения:
   ```tsx
   import { ThemeProvider } from '@beeline/design-system-react';
   
   function App() {
     return (
       <ThemeProvider>
         {/* ... */}
       </ThemeProvider>
     );
   }
   ```

6. **Цвет, тема и токены** (при подключённом `ThemeProvider`):
   - Для цветов, палитр, типографики и elevation **предпочтительно** опираться на DS props и подтверждённые токены из `get-global-design-tokens`.
   - Если MCP доступен, сначала пробовать подтвердить DS token name и использовать его как основной ориентир.
   - Если MCP недоступен, возвращает неполные данные или не покрывает нужный случай, допускается tasteful fallback без выдумывания псевдо-DS custom properties.
   - Нежелательно перекрашивать интерфейс случайными палитрами, если задача не требует осознанного controlled fallback.
   - Если пришлось отойти от DS token source, это должно быть отражено в `ds_gaps`, `Implementation Report` или review notes с кратким объяснением, почему решение выбрано ради качества результата.

7. **Spacing и layout**:
   - `spacing`, контейнеры, `max-width`, section rhythm и desktop composition не должны сводиться к agent-у «только глобальные токены или ничего».
   - Для layout сначала использовать DS layout primitives и handoff от дизайнера.
   - Если для сильной композиции нужен custom spacing/layout beyond DS props, это допустимо при условии, что решение остаётся аккуратным, согласованным с DS и не ломает визуальную систему экрана.

8. **Отсутствующий компонент**: если в DS нет нужного компонента:
   - зафиксировать в `ds_gaps`;
   - создать минимальную обёртку или fallback с опорой на существующие DS-компоненты;
   - не создавать самописный клон существующего DS-компонента без необходимости.

9. **Корпоративный стиль для landing/marketing**:
   - Использовать локальный `docs/brand/beeline-marketing-expression-kit.md` как источник brand-safe recipes; kit не является stage, не требует internet/vision runtime и не копируется целиком в каждый артефакт.
   - Использовать параметризуемую базу стиля (`style_kit_source`, `brand_expression_budget`, `brand_invariants`, `creative_freedom_budget`, `content_truth_policy`, `anti_clone_policy`) из `spec.md` / `ui-implementation-brief.md`, а не fixed section-template.
   - `brand_invariants` обязательны: токены/поверхности, читаемая иерархия, заметность primary CTA, согласованный section rhythm.
   - `creative_freedom_budget` обязателен для креатива: что можно варьировать (композицию, плотность, формат proof), а что нельзя ломать (tone, token_policy, product-truth claims).
   - `ui-coder` может добавлять expressive styling только как **DS component + documented enhancement recipe** из `brand_expression_plan` / `expressive_style_allowlist`.
   - QA/review должны отклонять `too_dry_app_like`, `off_brand_overstyled`, `recipe_not_documented`, `motion_without_purpose`, `token_claim_without_evidence`, `fake_or_unverified_marketing_claim`, `clone_reference_page`.
   - QA/review должны проверять outcome, а не только наличие таблиц: слабый hero contrast, пустые offer cards, отсутствующая map-like surface при map CTA, кривой address layout и неоформленный footer — concrete `too_dry_app_like` / contract failures, даже если `brand_expression_plan` формально заполнен.
   - Для UI surface обязательны `visual_gate` и `implementation_evidence`: skipped visual smoke или отчёт без реальных файлов не может считаться DS/brand-compliant результатом.
   - Запрещено подменять «единый стиль» списком жёстко обязательных блоков (hero/faq/form и т.п.) без связи с LDR.

## Категории DS (86 компонентов)

| Категория | Назначение | Примеры |
|-----------|-----------|---------|
| form | Ввод данных | TextField, Select, Checkbox, DatePicker, PhoneInput, Rating, Switch, Radio, TextArea, Autocomplete, MaskField, Slider, FileUploader, Search, InlineEdit, TimePicker |
| display | Отображение | Avatar, Badge, Card, Chip, Counter, Icon, Label, Skeleton, Typography, Timeline, Tree |
| feedback | Уведомления | Banner, Informer, Progress, ProgressBar, Snackbar, InlineAlert, Notifications |
| layout | Разметка | Box, Divider, NavigationDrawer, NavigationRail, Toolbar |
| navigation | Навигация | Breadcrumbs, Pagination, Stepper, Tabs, TabsPrimitive, FloatingNavigation |
| interactive | Действия | Button, ButtonGroup, ButtonSet, FAB, Link, LinkRouter, IconButton |
| overlay | Всплывающие | BottomSheet, Dialog, Drawer, Dropdown, Popover, Tooltip, Sidesheet, Menu, NewDropdownMenu |
| other | Прочее | Collapse, ExpansionPanel, Header, Footer, ThemeProvider, BottomActionBar, TextfieldWithChips |
