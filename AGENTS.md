# OpenCode Pipeline для @beeline/design-system-react

## Source Of Truth

- Runtime config: `opencode.json`.
- Agent prompts: `.opencode/agents/<slug>.md`.
- Shared rules: `.opencode/rules/01-design-system-first.md`, `.opencode/rules/02-mcp-protocol.md`, `.opencode/rules/03-pipeline-transitions.md`, `.opencode/rules/04-ai-builder-updates.md`, `.opencode/rules/05-vision-gate.md`, `.opencode/rules/06-ux-research-first.md`.
- State template: `docs/specs/pipeline-state.yaml`.

### Delivery Model

- **Installer / updater:** `install.sh` / `update.sh` (Unix) and `install.cmd` / `update.cmd` (Windows) вызывают **`yellowbe-opencode-pipeline.mjs`** (или через `npx @beeline/yellowbe-opencode-pipeline`).
- **Публикуемый CLI:** bin **`yellowbe-opencode-pipeline`** → `yellowbe-opencode-pipeline.mjs` (реализация в **`cli.mjs`**) — команды `install`, `update`, `diff`, `doctor`, `rollback`, **`check-update`**, **`safe-update`**. Флаг **`--merge`** (по умолчанию в **`update.sh`** / **`safe-update`**) deep-merge **`pipeline-state.yaml`** и section-merge **`ui-implementation-brief.md`** без потери живых значений; prune **`retiredManagedPaths`**. Локально изменённые **agent / rule / opencode.json** по умолчанию **перезаписываются**; **`--preserve-local`** — оставить свои правки (conflict).
- **Managed files:** `opencode.json`, `.opencode/`, `AGENTS.md`, `docs/brand/beeline-marketing-expression-kit.md`, `docs/marketing-landing-quality-regression.md`, `docs/specs/pipeline-state.yaml`, `docs/specs/ui-implementation-brief.md` (см. `pipeline.manifest.json`).
- Regression fixtures: `docs/marketing-landing-quality-regression.md`, `docs/iterative-pipeline-regression.md`.
- **Lock:** `docs/specs/opencode-pipeline.lock.json`.
- **Backups:** `.opencode-pipeline/backups/<timestamp>/`.
- **MCP:** безопасный merge только allowlisted серверов из `mcp.json` фрагмента пакета (те же id, что у Roo-пайплайна).
- **Корпоративный TLS (remote MCP):** Node не обязан доверять только OS trust store. Перед запуском OpenCode задайте `NODE_EXTRA_CA_CERTS` на абсолютный путь к `.opencode-pipeline/certs/ca-bundle.pem` (создаётся при `install`; `update` управляемые файлы обновляет, но **не** перезаписывает CA bundle — при необходимости снова выполните `install`). Команды см. в выводе `doctor` и в [README.md](README.md).
- **RooCode customModes:** не синхронизируются этим CLI (ставка `skipped` в отчёте); конфигурация агентов — через проектный `opencode.json`.
- **AI Builder (актуальность доставки):** состояние и политика в `docs/specs/pipeline-state.yaml` → ключ **`ai_builder`**; оркестратор выполняет проверку обновлений только на **границе пользовательского хода** и по правилам в **`04-ai-builder-updates.md`**, не на каждом переходе между stage agents.

OpenCode MVP uses `pipeline-orchestrator` as the default primary agent. All delivery stages are callable worker/subagents; the orchestrator invokes them via `Task` / `@<slug>`, reads `stage_result`, updates `pipeline-state.yaml`, and continues the graph without manual agent switching. On every user follow-up after `done`, the orchestrator first runs an Increment Intake Gate: classify the request as `small_change`, `rework`, `continue_chunk`, `bug_reentry`, `new_pipeline`, `clarification` or `unknown`, then route to an existing stage-agent instead of editing code/UI/logic directly.

## Agent Set

| Slug | OpenCode mode | Purpose |
|------|---------------|---------|
| `pipeline-orchestrator` | `primary` | Единая точка входа: автоматически запускает stage agents, проверяет артефакты и ведёт `pipeline-state.yaml`. Референс-изображения — пути в state + текстовое описание downstream. |
| `request-analyst` | `subagent` | Лёгкий входной stage: выбирает `analysis_mode`, `quality_profile`, `design_input`, обновляет `pipeline-state` и возвращает next stage orchestrator-у; **Adaptive Scope Planner** (`scope_class`, `chunk_strategy`, …) заполняют специализированные аналитики при выпуске `spec.md`. |
| `request-analyst-product` | `subagent` | Product/app аналитика: hub `spec.md` + `spec-chunk-{N}.md`; **Adaptive Scope Planner** в `pipeline-state` (`scope_class`, `depth_mode`, `complexity_vector`, `chunk_strategy`). |
| `request-analyst-marketing` | `subagent` | Marketing/landing аналитика: hub `spec.md` + `spec-chunk-{N}.md`, messaging, матрица и compact `corporate_style_basis` из локального `docs/brand/beeline-marketing-expression-kit.md`; **Adaptive Scope Planner** в `pipeline-state`. |
| `project-setup` | `subagent` | Инициализация или валидация проекта и подготовка окружения перед следующим этапом пайплайна. |
| `designer` | `subagent` | UI/UX на Beeline DS: hub + `design-spec-chunk-{N}.md`, scratchpad hub/chunk, JSON, DQG. |
| `ui-coder` | `subagent` | React/TS на Beeline DS: hub+chunk артефакты, `implementation-chunk-{N}.md`, код/тесты, build/devtools loop. |
| `ui-tester` | `subagent` | Визуальная и a11y-проверка UI через browser/devtools на 375 / 768 / 1440. |
| `coder` | `subagent` | Бизнес-логика: API, hooks, stores, валидация, замена типизированных UI-заглушек. |
| `reviewer` | `subagent` | Код-ревью: spec compliance, DS compliance, build/type/lint checks, tests и rework routing. |
| `mcp-researcher` | `subagent` | Служебный helper для scoped DS discovery: собирает MCP evidence bundle, пишет research-артефакт и не участвует в основном графе. |
| `tester` | `subagent` | Финальный QA: test plan, unit/component/e2e tests, coverage и bugs report. |


## Handoff Graph

Happy path starts with `pipeline-orchestrator`, which runs the graph below automatically. Rows show logical stage transitions, not manual user switches.

### Визуальная схема (основной поток)

Детальные ветвления и условия — в таблице ниже и в `.opencode/rules/03-pipeline-transitions.md`. Пунктир: helper вне основного графа.

```
┌────────────┐    ┌─────────────────────────────┐
│Пользователь├───►│ 0. Pipeline orchestrator     │
└────────────┘    │    Task / @slug + state      │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │ 1. Аналитик-роутер           │
                  │    request-analyst           │
                  └──────────────┬───────────────┘
                                 │
                   ┌─────────────┴─────────────┐
                   │                           │
                   ▼                           ▼
        ┌────────────────────┐      ┌────────────────────┐
        │ 2. Настройка       │      │ сразу к аналитикам │
        │    проекта         │      │ (если проект ОК)   │
        │  project-setup     │      └─────────┬──────────┘
        └─────────┬──────────┘                  │
                  │                           │
                  └─────────────┬───────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
   ┌───────────────────────┐         ┌───────────────────────┐
   │ 1a. Аналитик продукта │         │ 1b. Аналитик лендингов│
   │  → spec.md + chunks   │         │  → spec.md + chunks   │
   └───────────┬───────────┘         └───────────┬───────────┘
               │                                 │
               └────────────────┬────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
        ┌────────────────────┐    ┌────────────────────┐
        │ 3. Дизайнер        │    │ обход дизайна      │
        │ → design-spec hub  │    │ (простая задача)   │
        │ + scenarios JSON   │    └──────────┬─────────┘
        │ + scratchpad       │               │
        └─────────┬──────────┘               │
                  │                        │
                  └────────────┬───────────┘
                               ▼
                  ┌──────────────────────────────┐
                  │ 3.5 Orchestrator lock-in     │
                  │ → ui-implementation-brief.md │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │ 4. UI Coder                  │
                  │   → src/ + tests             │
                  │   → implementation-chunk-*   │◄──── browser / devtools
                  └──────────────┬─────────────┘      (итеративно, max 3)
                                 │
                   ┌─────────────┴─────────────┐
                   ▼                           ▼
            ┌─────────────┐           ┌─────────────┐
            │ UI Tester   │           │ 5. Coder    │
            │ (по профилю │           │  (логика)    │
            │  качества)  │           └──────┬──────┘
            └──────┬──────┘                  │
                   │                         │
                   └────────────┬────────────┘
                                ▼
                  ┌──────────────────────────────┐
                  │ 6. Reviewer                  │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │ 7. Тестировщик               │
                  │   → test report              │
                  └──────────────────────────────┘

  designer / ui-coder / reviewer ···► mcp-researcher  (helper DS bundle, не stage графа)
```

### Обратные связи (кратко)

```
UI Tester    ──(вердикт rejected, max 3)──► UI Coder
Reviewer     ──(rejected, max 3)──────────► Designer / UI Coder / Coder
Tester       ──(critical bugs, max 2)────► request-analyst
Designer     ──(уточнение spec)──────────► request-analyst
UI Coder     ──(проблема design-spec)────► Designer
```

| From | To | Condition |
|------|----|-----------|
| `request-analyst` | `project-setup` | project is not initialized and `analysis_mode` is known |
| `request-analyst` | `request-analyst-product` | product/app track selected |
| `request-analyst` | `request-analyst-marketing` | marketing/landing track selected |
| `project-setup` | `request-analyst-product` / `request-analyst-marketing` / `request-analyst` | project ready, route by `analysis_mode` and existing artifacts |
| `request-analyst-product` | `designer` / `pipeline-orchestrator` | spec hub + `spec-chunk-*` ready (или legacy монолит), depending on design need |
| `request-analyst-marketing` | `designer` / `pipeline-orchestrator` | spec hub + `spec-chunk-*` ready (или legacy), depending on design need |
| `designer` | `pipeline-orchestrator` | design hub + `design-spec-chunk-*`, JSON, scratchpad hub/chunk ready, DQG passed (legacy: монолит) |
| `pipeline-orchestrator` | `ui-coder` | UI intent lock-in пройден, `docs/specs/ui-implementation-brief.md` актуален; для marketing/landing заполнены `marketing_visual_contract` + `corporate_style_basis` + `brand_expression_plan` + `expressive_style_allowlist` + `motion_policy` + `style_failure_modes` + `seo_intent` и пройдён rubric-threshold |
| `pipeline-orchestrator` | `designer` / `request-analyst-*` | lock-in провален: конфликт артефактов или не заполнены обязательные секции brief |
| `ui-coder` | `ui-tester` / `reviewer` / `designer` / `coder` | implementation complete, profile visual gate needed, design issue, or business logic needed |
| `ui-tester` | `coder` / `reviewer` / `ui-coder` | visual approval or rejection loop |
| `coder` | `reviewer` / `ui-coder` | logic complete or UI adjustment needed |
| `reviewer` | `tester` / `designer` / `ui-coder` / `coder` | approved or rework routed by issue type |
| `tester` | done / `request-analyst` | passed or critical bugs found |


## Data Contracts

| Artifact | Created By | Consumed By | Notes |
|----------|------------|-------------|-------|
| `docs/specs/pipeline-state.yaml` | `pipeline-orchestrator` (routing) + all stage agents (domain) | all agents | **Edit protocol:** `.opencode/rules/03-pipeline-transitions.md` → Pipeline state edit protocol. Stage-agents пишут domain/planner-зону; orchestrator после `stage_result` — routing (`next_agent`, `last_stage_result`, `orchestrator_directive.*`). Read с диска перед edit. Partial failure: orchestrator verify-and-fill missing keys или blocked. Also: analysis mode, quality profile, adaptive scope, blockers (append), chunk, iterations, lock-in, visual gate |
| `docs/specs/spec.md` | `request-analyst-product`, `request-analyst-marketing` | `designer`, `ui-coder`, `tester` | hub: мета, контекст, индекс chunks; **Adaptive scope & chunk strategy** (краткое зеркало `pipeline-state`); для marketing — `corporate_style_basis` from local kit; для product — PDR + mini-VPC |
| `docs/specs/spec-chunk-{N}.md` | `request-analyst-product`, `request-analyst-marketing` | `designer`, `ui-coder`, `tester`, `reviewer` | экраны/секции, **Domain boundary** (`domain_goal`, flows, **`acceptance_group_id`**, `dependencies`), chunk-scoped tasks |
| `docs/specs/design-spec.md` | `designer` | `ui-coder`, `reviewer` | hub: оглавление chunk-файлов, сводка ds_gaps |
| `docs/specs/design-spec-chunk-{N}.md` | `designer` | `ui-coder`, `reviewer` | Phase R/S/V, DQG, wireframes, mapping, chunk-level `brand_expression_plan` for marketing, UI Coder handoff |
| `docs/specs/user-scenarios.json` | `designer` | `ui-coder`, `tester` | machine-readable scenarios, minimum 3 per task |
| `docs/specs/design-scratchpad.md` | `designer` | `ui-coder`, `reviewer` | hub: индекс, task-level риски |
| `docs/specs/design-scratchpad-chunk-{N}.md` | `designer` | `ui-coder`, `reviewer` | rationales, матрица, решения по chunk |
| `docs/specs/ui-implementation-brief.md` | `pipeline-orchestrator` | `ui-coder`, `reviewer` | канонический lock-in артефакт перед реализацией UI; фиксирует интегральный intent, source_map, `requirement_preservation`, `reference_evidence`, decision records (landing/product), `marketing_visual_contract`, `corporate_style_basis`, `brand_expression_plan`, `expressive_style_allowlist`, `motion_policy`, `style_failure_modes`, `seo_intent`, VPC fit-note и quality rubric |
| `docs/specs/implementation-chunk-{N}.md` | `ui-coder` | `reviewer`, `tester` | DS registry, отклонения, brand expression execution (recipes, token/fallback basis, content truth, anti-clone/motion notes), `implementation_evidence` (APP_ROOT, claimed/verified files, missing files, key sections), `visual_gate` status, self-check, coverage (канонический отчёт по chunk) |
| `docs/specs/mcp-research/*.md` | `mcp-researcher` | `designer`, `ui-coder`, `reviewer` | scoped DS evidence bundle; не handoff и не chunk-processing artifact |

## Orchestrator directive contract

`pipeline-orchestrator` передаёт в **каждый** stage brief машиночитаемый блок **`orchestrator_directive`** (лидерский фокус, ожидаемая глубина `fast|standard|deep`, память между chunk-ами, уровень цены ошибки, флаг `strict_no_shortcuts`). Это **не** заменяет lock-in, rubric и `risk_acceptance`, а задаёт приоритеты и запреты на «тихие» упрощения.

Каждый **основной** stage-agent в **`stage_result`** возвращает **`directive_ack`**: `received`, `applied`, `deviations[]`. Helper **`mcp-researcher`** не является stage графа и использует свой короткий результат. Отсутствие `directive_ack` у основного stage при новых промптах: orchestrator делает один soft-retry, затем эскалирует при high-risk / `hardened` (см. `.opencode/agents/pipeline-orchestrator.md` и `.opencode/rules/03-pipeline-transitions.md`).

В `docs/specs/pipeline-state.yaml` orchestrator поддерживает аудит: `orchestrator_directive.last_sent`, `last_ack`, append-only `history`.

## Increment Intake Gate

После `next_agent: done` pipeline не переходит в свободный чат-режим. Новый пользовательский ход сначала классифицируется в `docs/specs/pipeline-state.yaml`:

| Field | Purpose |
|-------|---------|
| `work_intent.kind` | `new_pipeline`, `small_change`, `rework`, `continue_chunk`, `bug_reentry`, `clarification`, `unknown` |
| `completion` | Отличает `chunk_done` от `all_done`, хранит `completed_chunks`, `remaining_chunks`, `last_completed_chunk`, `resume_policy` |
| `change_request` | Ограничивает scoped fix: allowed files/surfaces/acceptance groups, UI/behavior/data-risk flags and required gates |

Policy:

- Orchestrator can directly perform only state audit, stage brief, lock-in synthesis, preview and update check.
- Any code/UI/styles/routes/DS props/API/hooks/stores/tests behavior change must be delegated to an existing stage-agent.
- `small_change` is scoped, not unsafe: UI/text/visual changes go to `ui-coder`, design-intent changes go to `designer` then lock-in, logic/API bugs go to `coder`.
- If `completion.remaining_chunks` is not empty, `done` means `chunk_done`; user “continue” resumes the next chunk deterministically or asks one short clarification.
- Ambiguous follow-up becomes `needs_user`, not a guessed edit.

## Profile-Aware Routing Contract

`pipeline-orchestrator` treats `analysis_mode`, `quality_profile` and `design_input` as three independent decisions:

| Field | Values | Purpose |
|-------|--------|---------|
| `analysis_mode` | `product` / `marketing` | Which specialized analyst creates `spec.md` and chunks. |
| `quality_profile` | `lean` / `product` / `hardened` | How deep visual QA, review and tests must be. |
| `design_input` | `generative` / `reference_static` / `structured_mcp` | How designer uses or formalizes source design. |

**Adaptive Scope Planner** (ортогонально трём полям выше): `scope_class`, `depth_mode`, `complexity_vector`, `chunk_strategy` задают доменную декомпозицию и **`acceptance_group_id`** трассировку; заполняют `request-analyst-product` / `request-analyst-marketing` и **`pipeline-state.yaml`** (совместимость legacy — см. **`03-pipeline-transitions.md`**).

Policy summary:

- `lean`: build/typecheck and focused smoke are allowed, but UI surfaces still need visual smoke for the key screen/CTA/form.
- `product`: keep the normal `reviewer` → `tester` tail; require unit/component tests for changed behavior.
- `hardened`: do not shorten `ui-tester`, `reviewer` or `tester`; require e2e happy+negative, error/recovery/focus states and explicit `risk_acceptance` for any downgrade.
- `reference_static`: designer may use a shortened formalization path, but must preserve reference fidelity checklist and DS mapping.
- `structured_mcp`: MCP/frame evidence must be recorded; partial/blocked MCP requires explicit `design_input_fallback`, not silent generative redesign.
- Если есть UI surface, перед `ui-coder` всегда обязателен orchestrator lock-in: проверка входных артефактов + обновление `docs/specs/ui-implementation-brief.md`.
- После `done` любой follow-up проходит Increment Intake Gate; `small_change`/`rework` не bypass-ят DS compliance, visual gate, implementation evidence, reviewer/tester gates.
- Явные требования пользователя проходят `requirement_preservation`: stage не может молча перенести их в `non_goals`; нужен approval, blocker или documented fallback с acceptance impact.
- Скриншоты/референсы проходят `reference_evidence`: `fidelity_target`, `style_anchor`, `result_audit` имеют разные правила, а result-audit failures становятся reject cases.
- Для UI surface `visual_gate` обязателен даже при `lean`; `skipped_mcp_unavailable` не считается pass без явного `risk_acceptance`.
- После `ui-coder` orchestrator/reviewer проверяют `implementation_evidence`: self-report без реальных файлов или ключевых секций блокирует happy path.
- Для `analysis_mode: marketing` lock-in дополнительно проверяет `marketing_visual_contract` (`section_typology`, `proof_placement_plan`), `corporate_style_basis` (`style_kit_source`, `style_kit_version`, `brand_expression_budget`, `brand_invariants`, `creative_freedom_budget`, `content_truth_policy`, `anti_clone_policy`, `content_coverage_map`), `brand_expression_plan`, `expressive_style_allowlist`, `motion_policy`, `style_failure_modes`, `seo_intent` и quality rubric (`clarity_5s`, `action_focus`, `product_truth`, `structure_rationale`, `section_rhythm`, `above_fold_credibility`); до порога — re-route вместо прямого запуска `ui-coder`.
- Для `analysis_mode: product` lock-in дополнительно требует зеркалирование `Product Decision Record` в `product_decision_record` brief + `vpc_fit_note`; для point допускается `N/A + reason`, иначе re-route.
- Если `designer` был пропущен, orchestrator всё равно обязан заполнить brief; при нехватке оснований перехода к `ui-coder` — re-route в `request-analyst-*` (или `designer`) вместо «кодить по сырым chunk-данным».
- Периодический тюнинг style-правил выполняется по `style_telemetry` (рекомендуемый интервал `tuning_interval_days`), без фиксации жёсткого шаблона секций.

## Marketing Expression Kit Contract

`docs/brand/beeline-marketing-expression-kit.md` — локальный источник brand-safe expression для marketing/landing track. Это не новый stage, не graph node и не runtime internet dependency.

Поток compact fields:

- `request-analyst-marketing` переносит в `spec.md` только compact `corporate_style_basis`: kit source/version, anchor profile, `brand_expression_budget`, invariants, creative budget, content truth и anti-clone policy.
- `designer` превращает это в chunk-level `brand_expression_plan`: section id, DS base components, selected recipe, reason, allowed enhancements, hard limits, motion/reduced-motion и content truth notes.
- `pipeline-orchestrator` переносит план в `docs/specs/ui-implementation-brief.md` вместе с `expressive_style_allowlist`, `motion_policy` и `style_failure_modes`; при `visual_energy: medium|high` отсутствие expression plan блокирует `ui-coder`.
- `ui-coder` реализует styling только как `DS component + documented enhancement recipe` и записывает recipes, token/fallback basis, content truth, anti-clone и motion notes в `implementation-chunk-{N}.md`.
- `ui-tester` и `reviewer` отклоняют `too_dry_app_like`, `off_brand_overstyled`, `recipe_not_documented`, `motion_without_purpose`, `token_claim_without_evidence`, `fake_or_unverified_marketing_claim`, `clone_reference_page`.

## OpenCode Differences From RooCode

- `customModes` became OpenCode `agent` entries and `.opencode/agents/*.md` files.
- RooCode `groups` became OpenCode `permission` rules in `opencode.json`: операции, которые раньше были `ask`, выставлены в `allow`, чтобы не блокировать поток подтверждениями; у оркестратора и shell-capable stages по-прежнему `deny` на `git push*` и `rm *`, у аналитиков/дизайнера/mcp-researcher — без произвольного `bash`/`Task` (как в графе пайплайна).
- RooCode `modeApiConfigs` is not copied. Use OpenCode global `model`, provider config, or per-agent `model` overrides.
- RooCode `switch_mode` became OpenCode-native orchestration: `pipeline-orchestrator` invokes worker stage agents via `Task` / `@<slug>`. The explicit handoff line `Переключись на OpenCode agent <slug>` is now fallback / audit trail, not the primary UX.
- RooCode `new_task` / `attempt_completion` became OpenCode `Task` / `@mcp-researcher` helper invocation and short subagent result for scoped DS evidence only.

## Disabled Reference

`design-verifier` is not an active agent in this port. Keep `.opencode/rules/design-verifier-disabled-reference.md` only as reference for a future DVG re-enable.
