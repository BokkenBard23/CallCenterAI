# Local State Integrity Overlay (non-managed)

> **Этот файл — non-managed overlay.** Он НЕ входит в `pipeline.manifest.json` managed-список и не перезаписывается при `safe-update`. Если `03-pipeline-transitions.md` (managed) конфликтует с этим файлом, приоритет имеет managed-файл для полей, которые он описывает; этот файл дополняет его локальными правилами целостности.

## Назначение

Локальные правила, которые предотвращают порчу `docs/specs/pipeline-state.yaml`:
- дубликаты top-level ключей (молчаливая last-wins перезапись);
- устаревшие значения, не удалённые при обновлении;
- отсутствие валидации между коммитами.

## M5: Routing keys — single occurrence rule

Следующие top-level ключи должны встречаться в `docs/specs/pipeline-state.yaml` **ровно 1 раз**. При обновлении значения — **StrReplace** существующего экземпляра, не добавление нового:

```
request_id, analysis_mode, quality_profile, design_input, design_input_artifacts,
reference_evidence, requirement_preservation, corporate_style_basis,
design_input_fallback, risk_acceptance, scope_class, depth_mode, complexity_vector,
chunk_strategy, current_chunk, blockers, work_intent, completion, change_request,
orchestrator_status, active_stage, next_agent, last_mode, last_stage_result,
ui_intent_lock, visual_gate, implementation_evidence, orchestrator_directive,
canonical_artifacts, design_stage_all_chunks_done, design_stage_artifacts,
design_dqg_status, phase_10_verification, mcp_ds_inventory,
last_helper_mode, latest_mcp_research_artifact, mcp_researcher,
style_telemetry, ai_builder, confidence_min, confidence_below_threshold,
backlog_loop, intake_reentry
```

**Append-only (многократное вхождение допустимо):**
- `decision_log` — orchestrator-owned append-only журнал.

### Правило обновления routing-ключа

1. **Read** `pipeline-state.yaml` с диска.
2. Найти существующий экземпляр ключа (grep по `^key:`).
3. **StrReplace** — заменить значение in-place.
4. Если StrReplace fail ×2 → **safe Write** (Read → merge → Write), но **не** append новый экземпляр ключа в конец файла.

### Запрет append для routing-ключей

Добавление нового top-level ключа, который уже существует в файле, **запрещено**. YAML last-wins semantics означает, что старое значение молчаливо перезаписывается, но остаётся в файле как «зомби», создавая:
- противоречивые данные для ручного чтения;
- риск, что при удалении «нового» ключа восстановится «старый» (нелинейное поведение);
- сложность отладки (какой экземпляр canonical?).

## M6: Legacy values — delete, not comment

Если значение устарело и заменено новым:

- **Неправильно:** оставить старое значение с комментарием `# legacy, не canonical, см. ниже`. Ключ остаётся в файле и участвует в last-wins.
- **Правильно:** **удалить** старый экземпляр ключа целиком. Если данные нужно сохранить для audit — перенести в `decision_log` с пометкой `relocated_from`.

Единственное исключение: если ключ пуст (`[]` или `null`) и его canonical-значение находится в другом блоке, разрешается оставить пустой заглушку **только если** canonical-блок гарантированно выигрывает last-wins (т.е. находится ниже). Но это хрупкий паттерн — предпочтительно удалить заглушку.

## M4-adapted: Commit after stage update

После обновления `pipeline-state.yaml` orchestrator-ом (post-stage audit / intake gate / compatibility fill):

1. Запустить `npm run validate:state` (или `node scripts/validate-pipeline-state.mjs`).
2. Если валидация прошла — запустить `npm run commit:state` (или `node scripts/commit-state.mjs`).
3. Скрипт делает `git add docs/specs/pipeline-state.yaml` + `git commit --no-verify` (валидация уже выполнена).

**Обоснование `--no-verify`:** валидация выполнена в шаге 1. `--no-verify` обходит pre-commit hook (который запустил бы ту же валидацию + lint-staged + typecheck), экономя время. Это безопасно, потому что state-коммит не трогает `src/` и не требует typecheck/lint.

**Обоснование обхода "commit only when requested":** `pipeline-state.yaml` commit — инфраструктурная операция (аналогично `package-lock.json` после `npm install`), не code change. Orchestrator делает это автоматически после каждого stage, чтобы:
- активировать pre-commit hook на каждом шаге (а не раз в 5 дней);
- держать git diff читаемым (5-10 строк за коммит, а не 930);
- дать git-bisect для поиска момента порчи.

## Enforcement

| Механизм | Где | Что ловит |
|----------|-----|-----------|
| `scripts/validate-pipeline-state.mjs` | pre-commit hook + CI | Дубликаты, parse errors, missing keys, type errors |
| `.husky/pre-commit` | локально перед коммитом | Блокирует коммит со сломанным state |
| `.github/workflows/ci.yml` → `state-validate` job | CI на push/PR | Ловит обход `--no-verify` или внешних контрибьюторов |
| `scripts/commit-state.mjs` | вызывается orchestrator-ом после stage | Активирует валидацию на каждом шаге, держит diff читаемым |

## Совместимость с managed rules

Этот overlay не заменяет `03-pipeline-transitions.md` (Pipeline state edit protocol), а дополняет его:
- Edit protocol описывает **кто** пишет в какую зону (ownership matrix).
- Этот overlay описывает **как** писать (single occurrence, delete-not-comment, commit-after-stage).
- При конфликте: managed-файл приоритетен для ownership-зон; overlay приоритетен для integrity-правил.
