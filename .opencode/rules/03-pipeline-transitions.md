# Протокол переходов OpenCode Pipeline

> OpenCode не использует RooCode `switch_mode`. В MVP happy path управляется `pipeline-orchestrator`: он вызывает stage agents через `Task` / `@<slug>`, проверяет артефакты, обновляет `pipeline-state.yaml` и сам выбирает следующий этап. Текстовая строка `Переключись на OpenCode agent <slug>` остаётся как audit/fallback, но не требует ручного действия пользователя. Служебный helper `mcp-researcher` вызывается через `Task` / `@mcp-researcher` и **не** является основным этапом графа.

Этот документ фиксирует все переходы между этапами конвейера, условия переключения, формат передачи данных и правила обратной связи.

## Референс-изображения (кратко)

- Скрины/PDF хранятся в репозитории (`docs/assets/...`); пути — в **`design_input_artifacts`** и **`reference_evidence`**.
- **Автоматического pixel-pass нет.** Структура макета — в **тексте** запроса, `spec.md` / chunk spec и design-spec fidelity checklist.
- Пути к макетам — **от корня проекта**; надёжный способ — **скопировать вложение в `docs/assets/`**.
- Сообщение **`model does not support image input`** **не** означает «файл не существует»; продолжай по текстовым артефактам или запроси описание у пользователя.

**Лидерский контракт brief:** каждый запуск stage-agent оркестратором сопровождается блоком **`orchestrator_directive`** в brief (фокус, глубина, память между chunk-ами, цена ошибки, запрет тихих упрощений). Ответ stage-agent завершается **`directive_ack`** в `stage_result`. Политика заполнения, fallback для старых ответов и блокировки переходов — в `.opencode/agents/pipeline-orchestrator.md` и в разделе [Блокировки переходов (orchestrator directive)](#блокировки-переходов-orchestrator-directive).

## Схема пайплайна

```
Пользователь
    │
    ▼
┌────────────────────────┐
│ pipeline-orchestrator  │  default_agent; автоматический запуск stage agents
└───────────┬────────────┘
            │ Task / @request-analyst
            ▼
┌──────────────────────┐
│  request-analyst     │  Вход: сырое ТЗ / bugs / уточнения
│  → analysis/profile  │  Выход: routing + pipeline-state
└──────┬───────────────┘
       │
       ├─── проект не готов ──► ┌─────────────────┐
       │                        │  project-setup   │
       │                        └────────┬────────┘
       │                                 │
       ├── analysis_mode=product ────────┤
       │                                 ▼
       │                     ┌────────────────────────────┐
       │                     │ request-analyst-product    │
       │                     │ → spec.md hub + spec-chunk-* │
       │                     └────────────┬───────────────┘
       │                                  │
       └── analysis_mode=marketing ───────┤
                                          ▼
                            ┌────────────────────────────┐
                            │ request-analyst-marketing  │
                            │ → spec.md hub + spec-chunk-* │
                            └────────────┬───────────────┘
                                         │
                                         ▼
                            ┌──────────────────────┐
                            │  designer            │  Вход: spec hub + spec-chunk-*
                            │  → design-spec hub   │  Выход: design-spec.md hub +
                            │  + design-spec-chunk │    design-spec-chunk-* +
                            │                      │    user-scenarios.json +
                            │                      │    scratchpad hub + chunk
                            └──────────┬───────────┘
                                       │
                                       ▼
                  ┌────────────────────────────────────┐
                  │ pipeline-orchestrator              │
                  │ UI intent lock-in gate             │
                  │ → docs/specs/ui-implementation-brief.md
                  └──────────┬─────────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  ui-coder            │  Вход: ui-implementation-brief + design/spec hub/chunk
                  │                      │  (после lock-in; без design-verifier)
                  │  → src/ + tests      │  Выход: src/ + tests + implementation-chunk-*
                  │  + chrome-devtools   │  Итеративно: код→тест→fix (max 3)
                  └──────────┬───────────┘
                             │
                     ┌───────┴───────┐
                     ▼               ▼
              ┌────────────┐  ┌───────────┐
              │ ui-tester  │  │  coder    │  (если нужна бизнес-логика)
              │ profile-gate│  └─────┬─────┘
              └─────┬──────┘        │
                    └───────┬───────┘
                            ▼
                  ┌──────────────────────┐
                  │  reviewer            │  DS-compliance, React patterns,
                  │                      │  coverage > 80%
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  tester              │  Vitest + RTL + Playwright
                  │  → test report       │  Coverage > 80%
                  └──────────┬───────────┘
                             │
                             ▼
                        ✅ ЗАВЕРШЕНО
```

**Внутри agent-а `pipeline-orchestrator`:** это единственная happy-path точка входа. Он запускает `request-analyst` и следующие stage agents через `Task` / `@<slug>`, проверяет `stage_result`, обновляет orchestrator-поля в `pipeline-state` и продолжает граф без ручного переключения OpenCode agent-а. Референс-изображения — пути в state + текстовое описание downstream; см. `.opencode/agents/pipeline-orchestrator.md`. Подробности: `.opencode/agents/pipeline-orchestrator.md`.

**Внутри agent-а `request-analyst`:** это лёгкий роутер. Он определяет `analysis_mode` (`product` / `marketing`), начальный `quality_profile` (`lean` / `product` / `hardened`) и `design_input` (`generative` / `reference_static` / `structured_mcp`), обновляет `pipeline-state` и возвращает orchestrator-у следующий stage: либо `project-setup`, либо нужный специализированный аналитический agent. Полный **Adaptive Scope Planner** (`scope_class`, `depth_mode`, `complexity_vector`, `chunk_strategy`) заполняют только `request-analyst-product` / `request-analyst-marketing` (см. ниже). Подробности: `.opencode/agents/request-analyst.md`.

**Внутри agent-а `request-analyst-product`:** фазы **A → D HQG**; после HQG — hub **`docs/specs/spec.md`** и **`docs/specs/spec-chunk-{N}.md`** на каждый chunk с **domain boundary** полями и **`acceptance_group_id`**; синхронно заполняет в `pipeline-state` блоки **`scope_class`**, **`depth_mode`**, **`complexity_vector`**, **`chunk_strategy`**. Подробности: `.opencode/agents/request-analyst-product.md`.

**Внутри agent-а `request-analyst-marketing`:** тот же цикл и тот же контракт Adaptive Scope Planner; hub + per-chunk spec-файлы; матрица контента в hub. Подробности: `.opencode/agents/request-analyst-marketing.md`.

**Внутри agent-а `designer`:** по chunk — **R → S → V (DQG)**; пишет **`docs/specs/design-spec-chunk-{N}.md`**, поддерживает hub **`design-spec.md`**; **`user-scenarios.json`**; hub **`design-scratchpad.md`** + **`design-scratchpad-chunk-{N}.md`**. Handoff **`### UI Coder — краткий handoff`** в chunk-файле. Legacy: монолитные spec/design без `*-chunk-*`. Подробности: `.opencode/agents/designer.md`.

**Reference `design-verifier`:** временно **не** включён в `opencode.json` (экономия токенов). Чеклист **DVG** и прежний поток остаются в `.opencode/rules/design-verifier-disabled-reference.md` как справочник для возможного повторного включения.

**Helper `mcp-researcher`:** служебный on-demand helper, а не отдельный шаг графа. Его вызывают `designer`, `ui-coder` и `reviewer` через `Task / @mcp-researcher`, когда нужен пакетный DS research bundle; `pipeline-orchestrator` может вызвать его только для диагностики blocked MCP / DS bundle. Helper пишет `docs/specs/mcp-research/*.md`, может обновить helper-поля в `pipeline-state`, завершает работу через короткий subagent result, но не заменяет основной handoff и не обрабатывает chunks вместо stage agents. Если helper вернул `partial` / `blocked`, основной agent не должен трактовать такой bundle как готовый к коду без повторного helper-вызова или явного controlled fallback.

## Таблица переходов

| Из | В | Условие | Артефакт передачи |
|----|---|---------|-------------------|
| pipeline-orchestrator | request-analyst | Новая пользовательская задача, bugs re-entry или explicit resume без активного stage | User brief + `pipeline-state.yaml` |
| request-analyst | project-setup | Проект не инициализирован; `analysis_mode` уже определён | `pipeline-state.yaml` |
| request-analyst | request-analyst-product | Выбран трек `product` | `pipeline-state.yaml` |
| request-analyst | request-analyst-marketing | Выбран трек `marketing` | `pipeline-state.yaml` |
| project-setup | request-analyst-product | Проект готов, `analysis_mode: product`, spec.md ещё нет | `pipeline-state.yaml` |
| project-setup | request-analyst-marketing | Проект готов, `analysis_mode: marketing`, spec.md ещё нет | `pipeline-state.yaml` |
| project-setup | request-analyst | Проект готов, `analysis_mode` ещё не определён | `pipeline-state.yaml` |
| project-setup | designer | Проект готов, `spec.md` уже есть, но `design-spec.md` ещё нет | `spec.md` |
| project-setup | pipeline-orchestrator | Проект готов, дальше нужен выбор по готовности spec/design и lock-in gate | `pipeline-state.yaml` + найденные артефакты |
| request-analyst-product | designer | spec hub + `spec-chunk-*` готовы, задача с UI-дизайном | `spec.md` + `spec-chunk-*.md` (обзор design_task в hub) |
| request-analyst-product | pipeline-orchestrator | spec готов; orchestrator решает: `designer` или lock-in перед `ui-coder` | `spec.md` + `spec-chunk-*.md` |
| request-analyst-marketing | designer | spec hub + chunk-файлы готовы, задача с UI-дизайном | `spec.md` + `spec-chunk-*.md` |
| request-analyst-marketing | pipeline-orchestrator | spec готов; orchestrator решает: `designer` или lock-in перед `ui-coder` | `spec.md` + `spec-chunk-*.md` |
| designer | pipeline-orchestrator | hub `design-spec.md`, `design-spec-chunk-*`, `user-scenarios.json`, scratchpad hub + `design-scratchpad-chunk-*`, **DQG** пройден | design hub/chunk + JSON + scratchpad hub/chunk + spec hub/chunk; legacy — монолиты |
| pipeline-orchestrator | ui-coder | UI surface есть, lock-in пройден: `ui-implementation-brief.md` существует, обязательные секции заполнены, для marketing/landing заполнены `marketing_visual_contract` + `corporate_style_basis` + `brand_expression_plan` + `expressive_style_allowlist` + `motion_policy` + `style_failure_modes` + `seo_intent`, пройдён rubric-threshold, для product/app заполнены `product_decision_record` и `vpc_fit_note` (или `N/A + reason` в point-policy) | `ui-implementation-brief.md` + spec/design artifacts + `pipeline-state.yaml` |
| pipeline-orchestrator | designer | lock-in провален из-за пробелов/конфликтов в дизайн-решениях | `pipeline-state.yaml` + conflict notes |
| pipeline-orchestrator | request-analyst-product / request-analyst-marketing | lock-in провален из-за конфликтов или недостатка требований в spec | `pipeline-state.yaml` + conflict notes |
| designer | request-analyst | Нужно уточнение по spec.md или переанализ | Вопросы |
| ui-coder | ui-tester | Chunk реализован, self-check пройден, UI surface требует visual smoke/profile gate (`quality_profile: lean` с UI, `product` visual-heavy, всегда `hardened`) | Код в `src/` + **`docs/specs/implementation-chunk-{N}.md`** + dev server URL / route |
| ui-coder | reviewer | Chunk реализован, self-check пройден, build/type/lint/test checks OK, visual gate не нужен или уже пройден | Код в `src/` + **`docs/specs/implementation-chunk-{N}.md`** (тот же контент, что Implementation Report) + при необходимости сверка с `user-scenarios.json` |
| ui-coder | designer | Проблема в design-spec.md | Описание проблемы |
| ui-coder | coder | Нужна бизнес-логика | Типизированные заглушки |
| ui-tester | coder | approved, но в `spec.md`/коде ещё остались типизированные logic stubs или явно нужен logic handoff | `ui_test_result` + заметка о незавершённой логике |
| ui-tester | reviewer | approved, UI готов и отдельный logic handoff не нужен | `ui_test_result` |
| ui-tester | ui-coder | rejected, iteration < 3 | Issues list |
| coder | reviewer | Все заглушки заменены, build/type/lint checks OK | Код |
| reviewer | tester | approved | `review_result` |
| reviewer | designer | rejected, проблемы дизайна | Issues + `rework_assignments` |
| reviewer | ui-coder | rejected, проблемы вёрстки/DS | Issues + `rework_assignments` |
| reviewer | coder | rejected, проблемы логики | Issues + `rework_assignments` |
| tester | (завершено) | passed | `test_report` |
| tester | request-analyst | failed + critical bugs, `iteration_critical_bug_reentry < 2` | `bugs_found` |

### Increment / re-entry transitions after `done`

`next_agent: done` закрывает текущий lifecycle unit. Для multi-chunk задач это может быть только `completion.task_status: chunk_done`, пока `completion.remaining_chunks` не пустой.

| Ситуация | `work_intent.kind` | Следующий шаг | Блокировки |
|----------|--------------------|---------------|------------|
| Пользователь после `done` пишет «продолжай», `remaining_chunks` непустой | `continue_chunk` | `current_chunk = next remaining chunk`; дальше `designer` / lock-in / `ui-coder` по готовности артефактов | Если chunk не определяется однозначно → `needs_user` |
| Малая UI/text/visual правка результата | `small_change` | Scoped brief в `ui-coder`; focused `visual_gate` / `reviewer` по `change_request` | Direct edit orchestrator-а запрещён; CSS/DS/layout/CTA не micro bypass |
| Изменение иерархии, CTA, секций, композиции или design intent | `small_change` или `rework` | `designer` → orchestrator lock-in → `ui-coder` | Нельзя запускать `ui-coder` без обновления lock-in, если меняется intent |
| Баг формы/API/логики после результата | `bug_reentry` | `coder` → `reviewer` / `tester`; при критичных требованиях возможен `request-analyst` re-entry | Не понижать `quality_profile`; high-risk → `hardened` |
| Result-audit screenshot / замечания к готовому результату | `rework` | Route по типу дефекта; failures должны стать reject cases в `reference_evidence` | Нельзя трактовать плохой результат как fidelity target |
| Независимая новая задача | `new_pipeline` | `request-analyst` и новый spec cycle | Не переиспользовать старый scope как silent continuation |
| Неясно: продолжить chunk, исправить результат или начать новое | `unknown` / `clarification` | `needs_user` с коротким выбором | Не угадывать и не редактировать код |

Orchestrator может выполнять напрямую только `state_audit`, `stage_brief`, `lock_in_synthesis`, `preview`, `update_check`. Любые изменения `src/`, routes, styles, DS props, API, hooks, stores, tests или runtime behavior должны идти через stage-agent.

## Формат handoff (передачи данных)

В orchestrated MVP текущий stage-agent не требует от пользователя ручного переключения. Он обязан завершить артефакт, вернуть `stage_result`, а `pipeline-orchestrator` решает следующий запуск. Для debug/fallback stage-agent может дополнительно оставить старую строку `Переключись на OpenCode agent <slug>`.

Orchestrator передаёт в каждый stage brief блок **`orchestrator_directive`** (см. `.opencode/agents/pipeline-orchestrator.md` → Stage Brief Template). Stage-agent **обязан** завершить ответ полем **`directive_ack`**: подтвердить, что директива получена и применена; при любом отклонении от `lead_intent` или от режима `strict_no_shortcuts` — заполнить **`deviations`** непустым списком.

При handoff на следующий OpenCode stage текущий stage-agent обязан:

1. Завершить свой артефакт (routing / spec hub + `spec-chunk-*` / design hub + `design-spec-chunk-*` / scratchpad hub+chunk / `implementation-chunk-*` / `src/`).
2. Обновить **`docs/specs/pipeline-state.yaml`** (или `.json` с теми же полями) **только в своей ownership-зоне** — см. [Pipeline state edit protocol](#pipeline-state-edit-protocol). Stage-agent **не** пишет orchestrator-routing поля (`orchestrator_status`, `next_agent`, `last_stage_result`, `orchestrator_directive.*`); next route передаёт в `stage_result.next_agent`. При `blocked` — **append** в `blockers`, не затирая чужие строки без Read.
3. Вернуть orchestrator-у короткий `stage_result`:

```yaml
stage_result:
  status: done | blocked | needs_user | rejected
  stage: "<slug>"
  directive_ack:
    received: boolean
    applied: boolean
    deviations: string[]
  artifact_paths:
    - docs/specs/...
  next_agent: "<slug>" | done | null
  blockers: []
  quality_gate:
    name: string
    passed: boolean
  requirement_preservation:
    explicit_requirements_checked: boolean
    silent_scope_cuts: string[]
    approved_fallbacks: string[]
  reference_evidence:
    artifacts_checked: boolean
    result_audit_failures_promoted: boolean
  ui_intent_lock:
    required: boolean
    status: pending | locked | not_applicable
    artifact_path: docs/specs/ui-implementation-brief.md | ""
    files_read: string[]
    conflicts: []
    rubric_total_score: number | null
    rubric_blockers: string[]
    marketing_visual_contract_present: boolean | null
    corporate_style_basis_present: boolean | null
    brand_expression_plan_present: boolean | null
    expressive_style_allowlist_present: boolean | null
    brand_invariants_ack: boolean | null
    creative_freedom_budget_ack: boolean | null
    seo_intent_present: boolean | null
    layout_typology_count: number | null
  visual_gate:
    required: boolean
    status: passed | failed | skipped_mcp_unavailable | blocked | not_applicable
    screenshots_or_notes: string[]
    blocking_issues: string[]
  implementation_evidence:
    app_root: string
    files_claimed: string[]
    files_verified: string[]
    missing_files: string[]
    key_sections_verified: string[]
    report_matches_filesystem: boolean
  policy:
    analysis_mode: product | marketing | null
    quality_profile: lean | product | hardened | null
    design_input: generative | reference_static | structured_mcp | null
    risk_acceptance_required: boolean
    scope_class: point | subsystem | application | null
    depth_mode: lean | standard | deep | null
    chunk_strategy_type: screen_based | domain_based | hybrid | null
  work_intent:
    kind: new_pipeline | small_change | rework | continue_chunk | bug_reentry | clarification | unknown
    selected_agent: string | ""
  completion:
    task_status: active | chunk_done | all_done | blocked
    completed_chunks: number[]
    remaining_chunks: number[]
    last_completed_chunk: number | null
    resume_policy: ask_user | continue_next_chunk | stop
  change_request:
    scope_delta:
      files_allowed: string[]
      surfaces_affected: string[]
      acceptance_group_ids: string[]
    ui_surface_change: boolean
    behavior_change: boolean
    data_or_access_risk: boolean
  summary: string
```

Для перехода в `ui-coder` при UI surface обязательно `ui_intent_lock.status: locked`.
Для `analysis_mode: marketing` дополнительно обязателен `ui_intent_lock.rubric_total_score >= 7.0`, наличие `marketing_visual_contract` + `corporate_style_basis` + `brand_expression_plan` + `expressive_style_allowlist` + `motion_policy` + `style_failure_modes` + `seo_intent` + `requirement_preservation` + `reference_evidence`, и отсутствие блокера по `section_rhythm` / `above_fold_credibility`; иначе нужен re-route или явный `risk_acceptance` с причинами.
Для `analysis_mode: product` lock-in дополнительно требует в brief секции `product_decision_record` и `vpc_fit_note`; для `point` допустим `product_decision_record: N/A` только с явной причиной.
После `ui-coder` переход в `reviewer`/`tester` запрещён, если `implementation_evidence.report_matches_filesystem=false`, есть `missing_files`, или UI surface имеет `visual_gate.required=true` без `status=passed` / явного `risk_acceptance`.
Для `small_change` / `rework` переход запрещён, если фактические файлы/поверхности выходят за `change_request.scope_delta` без re-route или явного расширения scope через `request-analyst-*`.

### Блокировки переходов (orchestrator directive)

`pipeline-orchestrator` **не** переходит к следующему stage «молча», если применение директивы не подтверждено или нарушено:

| Условие | Действие orchestrator-а |
|---------|-------------------------|
| `directive_ack.received=false` или `applied=false` | Зафиксировать в `pipeline-state.orchestrator_directive.last_ack`, не продолжать happy-path; см. soft-retry и эскалацию в промпте orchestrator-а |
| `depth_expectation=deep` и результат не покрывает `cross_chunk_memory.required_decisions` или явно поверхностный | Блокировать переход; re-route или `needs_user` |
| `strict_no_shortcuts=true` | Запретить молчаливое пропускание обязательных quality gates и сужение scope без `risk_acceptance` или `needs_user` |
| `failure_cost.level=high` | Запретить fallback «минимально достаточно» без явного решения пользователя (`needs_user`) |
| Отклонение от директивы без записей в `directive_ack.deviations` | Трактовать как несогласованность; блокировать переход или потребовать повтор stage |

Если `directive_ack` отсутствует в ответе старого agent-промпта, orchestrator выполняет **один** soft-retry с требованием вернуть блок; при повторном отсутствии — эскалация по политике high-risk / hardened (см. orchestrator prompt).

Если `designer` пропущен, orchestrator всё равно обязан:
- заполнить `docs/specs/ui-implementation-brief.md` на основе `spec.md` + `spec-chunk-*`;
- отметить в `ui_intent_lock.conflicts` и/или notes, какие assumptions приняты из-за отсутствия design-артефактов;
- заполнить `requirement_preservation` и `reference_evidence`; при отсутствии оснований для scope cut или при потерянных референсах вернуть re-route вместо silent fallback;
- для marketing/landing явно заполнить `marketing_visual_contract`, `corporate_style_basis`, `brand_expression_plan`, `expressive_style_allowlist`, `motion_policy`, `style_failure_modes` и `seo_intent`; если не хватает данных, вернуть re-route в `request-analyst-marketing` или `designer` вместо silent fallback;
- при недостатке данных вернуть маршрут в `request-analyst-*` (или `designer`), а не запускать `ui-coder` по сырым chunk-файлам.

4. Опционально указать fallback-инструкцию: **«Переключись на OpenCode agent {slug}»**. Orchestrator может извлечь из неё `next_agent`, если старый stage-agent ещё не вернул structured result.
5. Кратко пояснить причину перехода и статус артефакта.

После возврата `stage_result` **`pipeline-orchestrator`** обновляет **только routing-зону** state (и intake/compatibility fill при необходимости) — не дублирует StrReplace по planner-полям, которые stage уже записал. Подробности — в [Pipeline state edit protocol](#pipeline-state-edit-protocol).

### Pipeline state edit protocol

Единый протокол edit для **всех** agents, пишущих `docs/specs/pipeline-state.yaml`. Цель — избежать `Could not find oldString` из‑за patch по шаблонным `null` / `""` / `[]`, когда на диске уже другой YAML.

#### Ownership matrix

| Зона | Writer | Поля |
|------|--------|------|
| **Stage domain** | Каждый stage-agent | Поля своей зоны (см. таблицу ниже), свой `last_mode`, chunk-локальное (`current_chunk` у designer/ui-coder), профильные артефакты, **инкремент своего** `iteration_*` |
| **Orchestrator routing** | `pipeline-orchestrator` после `stage_result` | `orchestrator_status`, `active_stage`, `next_agent`, `last_stage_result`, `orchestrator_directive.*`, `decision_log`, `ui_intent_lock` (lock-in), intake: `work_intent`, `completion`, `change_request` |
| **Shared append** | Stage добавляет; orchestrator merge | `blockers` — append/merge, не затирать чужие строки без Read |
| **Orchestrator verify-only** | Orchestrator post-stage | Stage-owned поля **не StrReplace**, если на диске заполнены и согласованы с `stage_result` + артефактами |

**Stage-owned зоны (кратко):**

| Stage | Пишет в state |
|-------|----------------|
| `request-analyst` | `analysis_mode`, `quality_profile`, `design_input`, `design_input_artifacts`, `reference_evidence`, `risk_acceptance`, `work_intent`, `completion`, `change_request`, `last_mode`, `blockers` |
| `request-analyst-product` / `-marketing` | Adaptive Scope Planner: `scope_class`, `depth_mode`, `complexity_vector`, `chunk_strategy`, `confidence_*`, `request_id`, `last_mode`, `blockers` |
| `project-setup` | `last_mode`, релевантные blockers |
| `designer` | `current_chunk`, `last_mode`, `blockers` |
| `ui-coder` | `current_chunk`, `last_mode`, `blockers` |
| `ui-tester` | `last_mode`, `iteration_ui` (при rejected), `visual_gate`, `blockers` |
| `coder` | `last_mode`, `blockers` |
| `reviewer` | `last_mode`, `iteration_review` (при rejected), `style_telemetry` (при style-regression), `blockers` |
| `tester` | `last_mode`, `iteration_critical_bug_reentry` (при bug re-entry), `blockers` |
| `mcp-researcher` | **только** `last_helper_mode`, `latest_mcp_research_artifact` |

Stage-agent **не** пишет: `orchestrator_status`, `active_stage`, `next_agent`, `last_stage_result`, `orchestrator_directive.*`, `decision_log`, `ui_intent_lock`.

#### Edit rules (все agents)

1. **Read** `docs/specs/pipeline-state.yaml` с диска **перед** любым edit (не использовать шаблон из памяти или начала хода).
2. **StrReplace:** `old_string` — дословно из последнего Read (отступы, inline-комментарии, кавычки).
3. **Fail StrReplace** → Read снова; не повторять тот же `old_string`; максимум **2** попытки → **safe Write** (см. ниже).
4. Stage: правь только свою зону; next route — в `stage_result.next_agent`.
5. Orchestrator post-stage: правь только routing-зону; **не** patch planner-поля по предполагаемым `null` / `""` / `[]`.

#### Safe Write (whole file)

При Write целого `pipeline-state.yaml`:

- Начать с полного **Read** актуального файла.
- **Сохранить** stage-owned блоки без изменений, если они не входят в текущую операцию.
- Менять только ключи из своей ownership-зоны (+ явный compatibility fill).
- **Запрещено** собирать файл из install-шаблона или памяти.

#### Partial failure guardrail (orchestrator)

После `stage_result.status: done`:

1. Read state + проверить ожидаемые stage-owned поля для этого stage (таблица выше + артефакты на диске).
2. Если stage-owned поля **пустые/null**, но артефакты **есть** → orchestrator **может заполнить только недостающие** ключи (compatibility fill), не full re-write всех planner-полей.
3. Если и state, и артефакты неполные → `orchestrator_status: blocked`, re-route или soft-retry stage; **не** silent continue.

**Legacy:** если ключей Adaptive Scope Planner нет, orchestrator выставляет compatibility defaults из раздела [Adaptive Scope Planner](#adaptive-scope-planner-pipeline-state--spec-chunks) — **единственный** случай записи planner-полей orchestrator-ом при отсутствии stage-записи.

#### Orchestrator modes (когда что писать)

| Режим | Когда | Что писать |
|-------|-------|------------|
| **Post-stage audit** | После возврата stage-agent | Verify stage-owned → write **routing-only** → route |
| **Intake gate** | Новый пользовательский ход / post-done | `work_intent`, `completion`, `change_request` |
| **Compatibility fill** | Legacy или partial failure | Только **missing** planner/routing keys |

### Поля `pipeline-state` (контракт)

| Поле | Назначение |
|------|------------|
| `request_id` | ID задачи, как в Мета `spec.md` |
| `analysis_mode` | Какой специализированный аналитик должен продолжать работу: `product` или `marketing` |
| `quality_profile` | Глубина инженерной проверки: `lean`, `product` или `hardened`; влияет на visual QA, reviewer и tester |
| `design_input` | Источник дизайна: `generative`, `reference_static` или `structured_mcp`; влияет на режим работы designer и допустимость прямого перехода к ui-coder |
| `design_input_artifacts` | Список путей/ссылок на скрины, PDF, Pixso/MCP frames и покрытие breakpoints/flow |
| `reference_evidence` | Список reference/rework артефактов: `fidelity_target`, `style_anchor`, `result_audit`, anti-clone notes |
| `design_input_fallback` | Явный fallback источника дизайна с причиной, если structured MCP или reference неполны |
| `requirement_preservation` | Audit explicit requirements: какие must-build требования сохранены, какие fallbacks approved, какие silent scope cuts блокируют handoff |
| `corporate_style_basis` | Метаданные стилевой базы для marketing/landing: `style_kit_version`, `style_kit_source`, `style_anchor_profile`, `brand_expression_budget`, `content_truth_policy`, `anti_clone_policy`, `status`, `artifact_paths`, заметки |
| `risk_acceptance` | Явное принятие риска человеком: downgrade профиля или принятие результата после лимита итераций |
| `scope_class` | Масштаб: `point` / `subsystem` / `application` / `null` (legacy: см. Adaptive Scope Planner ниже) |
| `depth_mode` | Глубина анализа/спеки: `lean` / `standard` / `deep` / `null` |
| `complexity_vector` | Объяснимые численные/risk-сигналы (`risk_level`: low/medium/high) |
| `chunk_strategy` | `strategy_type`, `rationale`, `boundaries`, `target_chunk_count`, `chunk_size_policy`; зеркалирует границы chunk-ов в spec |
| `current_chunk` | Номер активного chunk (1-based); размер одного chunk — по доменной границе, см. chunk_strategy |
| `work_intent` | Intent нового пользовательского хода или re-entry: `new_pipeline`, `small_change`, `rework`, `continue_chunk`, `bug_reentry`, `clarification`, `unknown`; включает выбранный stage и причину |
| `completion` | Lifecycle задачи/chunk: `active`, `chunk_done`, `all_done`, `blocked`; хранит completed/remaining chunks и `resume_policy` |
| `change_request` | Scoped delta для small fixes/rework: allowed files/surfaces/acceptance groups, UI/behavior/data-risk flags и требуемые gates |
| `iteration_ui` | Счётчик итераций ui-tester → ui-coder при `rejected` (0…3) |
| `iteration_review` | Счётчик итераций reviewer → исполнители при `rejected` (0…3) |
| `iteration_design_verify` | Зарезервировано под цикл design-verifier → designer (0…3); при отключённом agent-е обычно не инкрементируется |
| `iteration_critical_bug_reentry` | Счётчик возвратов tester → request-analyst при critical bugs (0…2) |
| `last_mode` | Slug последнего agent-а |
| `orchestrator_status` | `idle`, `running`, `blocked` или `done` — состояние автоматического controller-а |
| `active_stage` | Stage, который orchestrator сейчас запустил или проверяет |
| `next_agent` | Следующий stage, выбранный orchestrator-ом; `done` закрывает текущий lifecycle unit, а всю задачу — только при `completion.task_status=all_done` |
| `last_stage_result` | Краткий результат последнего stage для восстановления контекста |
| `orchestrator_directive.last_sent` | Зеркало последней отправленной в brief директивы (stage, depth, strict_no_shortcuts, failure_cost_level, lead_intent) |
| `orchestrator_directive.last_ack` | Последний `directive_ack`: received/applied/deviations |
| `orchestrator_directive.history` | Короткий append-only журнал аудита директивы и подтверждений |
| `canonical_artifacts.ui_implementation_brief` | Канонический путь lock-in артефакта (`docs/specs/ui-implementation-brief.md`) |
| `ui_intent_lock.status` | Статус lock-in: `pending`, `locked` или `not_applicable` |
| `ui_intent_lock.files_read` | Какие файлы orchestrator прочитал перед решением о запуске `ui-coder` |
| `ui_intent_lock.conflict_resolution_notes` | Как разрешены конфликты между spec/design/scratchpad |
| `ui_intent_lock.corporate_style_basis_present` | Для marketing/landing: заполнена ли секция `corporate_style_basis` в brief |
| `ui_intent_lock.brand_expression_plan_present` | Для marketing/landing: заполнен ли kit-backed `brand_expression_plan` в brief |
| `ui_intent_lock.expressive_style_allowlist_present` | Для marketing/landing: заполнен ли `expressive_style_allowlist` в brief |
| `ui_intent_lock.brand_invariants_ack` | Для marketing/landing: подтверждены ли `brand_invariants` в lock-in |
| `ui_intent_lock.creative_freedom_budget_ack` | Для marketing/landing: зафиксирован ли `creative_freedom_budget` без схлопывания в fixed template |
| `visual_gate` | Gate визуальной проверки UI: required/status/screenshots_or_notes/blocking_issues; `skipped_mcp_unavailable` не равен pass |
| `implementation_evidence` | Audit фактической реализации: `APP_ROOT`, claimed/verified files, missing files, key sections, report/filesystem match |
| `last_helper_mode` | Последний helper-agent, вызванный через `Task / @mcp-researcher` (`mcp-researcher` или пусто) |
| `latest_mcp_research_artifact` | Путь к последнему актуальному `docs/specs/mcp-research/*.md` |
| `style_telemetry` | Лёгкая телеметрия style-regressions, счётчики и последние rubric-оси для периодического тюнинга промптов/гейтов |
| `blockers` | Список строк — что мешает продолжить (пусто = нет) |

### Политика `quality_profile`

| Профиль | Минимум | Сокращения | Нельзя сокращать |
|---------|---------|------------|------------------|
| `lean` | build/typecheck, sanity CTA/form, один **blocking** visual smoke для UI surface | полный регресс, расширенный e2e | DS compliance, первый экран/CTA, явные ошибки форм, `visual_gate` |
| `product` | unit/component tests, RTL для изменённого поведения, reviewer → tester | полный e2e на все edge cases | основные состояния UI, ошибки/API, acceptance criteria |
| `hardened` | visual QA на 375/768/1440, e2e happy+negative, recovery/error/focus, regression | почти ничего без human sign-off | ui-tester, reviewer, tester, negative/recovery checks |

Если задача содержит платежи, KYC, договоры, роли/доступы, персональные данные или юридически значимое действие, `quality_profile` должен быть `hardened`, либо в `risk_acceptance.profile_downgrade` должна быть явная причина и `approved_by`.
Для любого UI surface `lean` сокращает глубину QA, но не отменяет `visual_gate`: skipped/blocked visual smoke не считается successful handoff без явного `risk_acceptance.result_after_iteration_limit`.

### Политика `design_input`

| Источник | Поведение |
|----------|-----------|
| `generative` | `designer` выполняет полный R→S→V цикл: DS mapping, wireframes, states, DQG |
| `reference_static` | `designer` формализует референс: фиксирует эталоны, fidelity checklist, DS mapping и допущения; творческий цикл можно сократить, но не убрать mapping |
| `structured_mcp` | Сначала MCP evidence / imported frames; `designer` делает быстрый skeleton + DS mapping. Если MCP неполон — заполнить `design_input_fallback`, `blockers` / `risks`, не превращать молча в `generative` |

### Пример handoff (Роутер → Аналитик лендингов)

```
## Результат маршрутизации

Трек анализа определён: `marketing`
Состояние пайплайна обновлено: `docs/specs/pipeline-state.yaml` (`analysis_mode`, `last_mode`, blockers)

Причина выбора:
- один conversion-focused surface
- в запросе акцент на hero / CTA / proof

**→ Переключись на OpenCode agent request-analyst-marketing**
```

### Пример handoff (Аналитик → Дизайнер)

```
## Результат анализа

Спецификация готова: `docs/specs/spec.md` (hub) + `docs/specs/spec-chunk-1.md`, `spec-chunk-2.md`
Состояние пайплайна обновлено: `docs/specs/pipeline-state.yaml` (`request_id`, `analysis_mode`, `current_chunk`, счётчики и т.д.)

Содержит:
- 3 экрана в 2 chunks (детали в chunk-файлах)
- design_task / frontend_task: обзор в hub, детали по chunk в `spec-chunk-*`

**→ Переключись на OpenCode agent designer**
Spec.md полный, задача требует проектирования UI.
```

### Пример handoff (Дизайнер → UI Coder)

```
## Результат дизайна

Design-spec hub: `docs/specs/design-spec.md`; chunk: `docs/specs/design-spec-chunk-1.md`
Сценарии: `docs/specs/user-scenarios.json`
Scratchpad: `docs/specs/design-scratchpad.md` + `docs/specs/design-scratchpad-chunk-1.md`

Chunk 1 обработан (внутри agent-а: Phase R → Phase S → Phase V):
- Phase R/S/V записаны в **`design-spec-chunk-1.md`** ✅
- user-scenarios.json: минимум 3 сценария на задачу ✅
- scratchpad chunk + hub актуальны ✅
- DQG V1–V11 в **`design-spec-chunk-1.md`** ✅
- **UI Coder — краткий handoff** в конце **`design-spec-chunk-1.md`** ✅
- Для `marketing` / `landing`: primary conversion, critical proof blocks и AIDA переданы в handoff ✅
- Component mapping: 8 DS-компонентов ✅
- Строка Page layout (контейнер / max-width) в mapping ✅
- Wireframes: 3 breakpoints ✅
- Nielsen score: 4.2/5.0 ✅
- DS gaps: 0

**→ Переключись на OpenCode agent ui-coder**
DQG пройден, дизайн готов к реализации Chunk 1 (отдельный agent design-verifier в пайплайне отключён).
```

### Пример helper-brief (UI Coder → MCP Researcher)

Это **не** handoff по основному графу, а служебный helper-вызов через `Task / @mcp-researcher`:

```yaml
consumer: ui-coder
scope: "Chunk 1 DS bundle for billing form"
request_id: TASK-2026-042
chunk: 1
analysis_mode: product
surface_type: app
questions_to_answer:
  - "Какие ключевые props у TextField, Select и InlineAlert нужны для текущего chunk?"
  - "Есть ли nested API или guideline caveats, которые важно учесть до JSX?"
required_components:
  - TextField
  - Select
  - InlineAlert
required_outputs:
  - component_name
  - import_path
  - nested
  - key_props
  - guidelines
artifact_hint: "docs/specs/mcp-research/chunk-1-ui-coder.md"
reuse_existing_artifact: true
```

### Пример возврата helper-а

```markdown
## MCP Research Result

- artifact_path: `docs/specs/mcp-research/chunk-1-ui-coder.md`
- coverage_status: ready
- components_checked: 3
- gaps: 0

Ключевые выводы:
- `TextField` и `Select` подтверждены для chunk
- спорных nested API нет
- для `InlineAlert` зафиксированы key props и guideline caveats
```

### Пример handoff (UI Coder → Reviewer)

```
## Результат реализации Chunk 1

Код и тесты в `src/`, build OK.

Implementation Report: `docs/specs/implementation-chunk-1.md` (или путь в проекте)
- DS Usage Registry — заполнен
- Отклонения от design-spec — нет (или таблица с причинами)
- Self-check: layout checklist ✅, grep цветов ✅
- Для `marketing` / `landing`: primary conversion, proof / CTA hierarchy, reading order и desktop composition check зафиксированы ✅

**→ Переключись на OpenCode agent reviewer**
```

## Обратные связи (Feedback Loops)

### Цикл 1: UI Тестировщик → UI Coder

| Параметр | Значение |
|----------|---------|
| Триггер | verdict == "rejected" |
| Макс. итераций | 3 |
| Передаваемые данные | Issues list (critical, major, minor) + DS compliance |
| Эскалация | После 3-й итерации → уведомление пользователя |

### Цикл 2: Reviewer → Designer / UI Coder / Coder

| Параметр | Значение |
|----------|---------|
| Триггер | verdict == "rejected" |
| Макс. итераций | 3 |
| Маршрутизация | По типу issues (дизайн / вёрстка / логика) |
| Передаваемые данные | Issues + rework_assignments |
| Эскалация | После 3-й итерации → уведомление пользователя |

### Цикл 2a (опционально): Design Verifier → Designer

| Параметр | Значение |
|----------|----------|
| Статус | Только если agent `design-verifier` снова включён в `opencode.json` |
| Триггер | verdict == "rejected" |
| Макс. итераций | 3 (`iteration_design_verify`) |
| Передаваемые данные | Issues из `design-verification.md` |
| Эскалация | После 3-й итерации → уведомление пользователю + `blockers` |

### Цикл 3: Тестировщик → Аналитика

| Параметр | Значение |
|----------|---------|
| Триггер | verdict == "failed" + critical bugs |
| Макс. итераций | 2 |
| Передаваемые данные | bugs_found |
| Эскалация | После 2-й итерации → уведомление пользователя |

## Правила эскалации

1. Каждый цикл обновляет соответствующий счётчик в `docs/specs/pipeline-state.yaml`: `iteration_ui`, `iteration_review` или `iteration_design_verify`.
2. При достижении максимума итераций — выход из цикла, уведомление пользователя.
3. Уведомление содержит: историю итераций, нерешённые проблемы, рекомендации.
4. Пользователь решает: продолжить, изменить требования или принять текущий результат.
5. Для `quality_profile: hardened` принятие результата после лимита итераций допустимо только при `risk_acceptance.result_after_iteration_limit: true`, непустых `reason` и `approved_by`.

### Adaptive Scope Planner (`pipeline-state` + spec chunks)

Цель — не дробить **subsystem/application** искусственно по «счётчику экранов», а резать по **domain boundary** (flow / feature / use-case), сохраняя целостную **acceptance traceability**.

**Нормы для новых прогонов (пишут `request-analyst-product` / `request-analyst-marketing`):**

1. **`scope_class`**: для `subsystem`/`application` использовать **`strategy_type=domain_based`** или **`hybrid`** с явной **`rationale`**; **чисто `screen_based` как единственная стратегия запрещена** для subsystem/application (см. HQG этих agents).
2. **`depth_mode`** согласован с риском: если `complexity_vector.risk_level=high`, то не ниже **`standard`**; hardened-сигнал (`quality_profile: hardened` или `risk_level=high`) — **`deep`** по умолчанию либо явный `risk_acceptance` на меньшую глубину.
3. В каждом **`spec-chunk-{N}.md`**: блок **Domain boundary** — `domain_goal`, `in_scope_flows`, `out_of_scope_flows`, **`acceptance_group_id`**, `dependencies`. Список **`chunk_strategy.boundaries`** отражает те же номера/`acceptance_group_id` без рассинхрона hub vs chunk vs state.

**Backward compatibility:** если в живом проекте **нет** ключей Adaptive Scope Planner (старый `pipeline-state`): `pipeline-orchestrator` трактует **compatibility mode** — `scope_class=point`, `depth_mode=standard`, `strategy_type=screen_based` (если нужно восстановить маршрутизацию downstream). Если по артефактам видно признаки **subsystem/application**, но ключей всё равно нет — **не делать silent downgrade**: `needs_user` или ре-analyze через `request-analyst-*`.

**Backward compatibility for increments:** если в живом проекте нет `work_intent` / `completion` / `change_request`, orchestrator трактует новый пользовательский ход как `work_intent.kind=unknown` и сначала классифицирует intent. Если есть `spec-chunk-*` или `chunk_strategy.boundaries`, но нет `completion.remaining_chunks`, orchestrator восстанавливает remaining chunks из границ только для выбора маршрута и пишет это в `decision_log`; при конфликте — `needs_user`, не direct edit.

`designer` / `ui-coder` всё так же выполняют **по одному chunk за invocation** контроллера, но содержание chunk задаёт доменная граница, а не «максимум 2 экрана».

## Общие правила для всех агентов

- Язык ответа: русский
- Каждый **основной graph** stage-agent (`request-analyst`, `project-setup`, специализированные аналитики, `designer`, `ui-coder`, `ui-tester`, `coder`, `reviewer`, `tester`) завершает ответ `stage_result` с блоком **`directive_ack`** (получена ли директива из brief, применена ли, какие отклонения); helper **`mcp-researcher`** возвращает короткий research-result по своему контракту и не считается stage-run оркестратора по основному графу.
- Артефакты записываются в файлы через OpenCode edit/write tools, не только в чат
- **Chunk discipline:** один **логический chunk** обрабатывается за одну активную инкарнацию контролирующего downstream stage (`designer`, `ui-coder` …); состав chunk (несколько экранов допустимо при доменном scope) задаёт Adaptive Scope Planner в `pipeline-state.yaml` и `spec-chunk-*`; гранулярность выбирай по управляемости контекста и `chunk_strategy.chunk_size_policy`, а не формальной квоте экранов
- Если агент не может выполнить задачу — уведомить пользователя с объяснением
