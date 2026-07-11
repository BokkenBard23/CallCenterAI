/**
 * validate-pipeline-state.mjs
 *
 * Валидация docs/specs/pipeline-state.yaml перед коммитом и в CI.
 * Ловит:
 *   1. YAML-синтаксические ошибки (отступы, orphaned keys, misplaced sequences)
 *   2. Дубликаты top-level ключей (last-wins молчаливая перезапись)
 *   3. Отсутствие обязательных routing-ключей
 *   4. Типы ключей (blockers — массив, last_stage_result — object, ...)
 *
 * Exit codes:
 *   0 — файл валиден
 *   1 — найдены ошибки (блокирует коммит / CI red)
 *
 * Использование:
 *   node scripts/validate-pipeline-state.mjs
 *   npm run validate:state
 */

import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATE_PATH = resolve(__dirname, '..', 'docs', 'specs', 'pipeline-state.yaml');

// Ключи, которые должны встречаться ровно 1 раз (routing snapshot, не append-only).
// Если встречаются 2+ — last-wins перезаписывает молча, оркестратор читает неверные данные.
const SINGLE_OCCURRENCE_KEYS = [
  'request_id',
  'analysis_mode',
  'quality_profile',
  'design_input',
  'design_input_artifacts',
  'reference_evidence',
  'requirement_preservation',
  'corporate_style_basis',
  'design_input_fallback',
  'risk_acceptance',
  'scope_class',
  'depth_mode',
  'complexity_vector',
  'chunk_strategy',
  'current_chunk',
  'blockers',
  'work_intent',
  'completion',
  'change_request',
  'orchestrator_status',
  'active_stage',
  'next_agent',
  'last_mode',
  'last_stage_result',
  'ui_intent_lock',
  'visual_gate',
  'implementation_evidence',
  'orchestrator_directive',
  'canonical_artifacts',
  'design_stage_all_chunks_done',
  'design_stage_artifacts',
  'design_dqg_status',
  'phase_10_verification',
  'mcp_ds_inventory',
  'last_helper_mode',
  'latest_mcp_research_artifact',
  'mcp_researcher',
  'style_telemetry',
  'ai_builder',
  'confidence_min',
  'confidence_below_threshold',
  'backlog_loop',
  'intake_reentry',
];

// Ключи, которые ДОПУСТИМО встречать多次 (append-only по контракту).
const APPEND_OK_KEYS = new Set([
  'decision_log', // orchestrator-owned append-only журнал
]);

// Обязательные routing-ключи (должны присутствовать).
const REQUIRED_KEYS = [
  'request_id',
  'analysis_mode',
  'quality_profile',
  'design_input',
  'blockers',
  'work_intent',
  'completion',
  'change_request',
  'orchestrator_status',
  'active_stage',
  'next_agent',
  'last_mode',
  'last_stage_result',
];

// Типовые проверки для ключей.
const TYPE_CHECKS = {
  blockers: (v) => Array.isArray(v),
  work_intent: (v) => v !== null && typeof v === 'object' && !Array.isArray(v),
  completion: (v) => v !== null && typeof v === 'object' && !Array.isArray(v),
  change_request: (v) => v !== null && typeof v === 'object' && !Array.isArray(v),
  last_stage_result: (v) => v !== null && typeof v === 'object' && !Array.isArray(v),
  visual_gate: (v) => v !== null && typeof v === 'object' && !Array.isArray(v),
  'visual_gate.status': (v) => ['passed', 'failed', 'skipped_mcp_unavailable', 'blocked', 'not_applicable'].includes(v),
  'visual_gate.blocking_issues': (v) => Array.isArray(v),
};

const errors = [];
const warnings = [];

// ─── 1. Чтение файла ────────────────────────────────────────────

let source;
try {
  source = readFileSync(STATE_PATH, 'utf8');
} catch (e) {
  console.error(`\u274C Cannot read ${STATE_PATH}: ${e.message}`);
  process.exit(1);
}

const lines = source.split(/\r?\n/);

// ─── 2. Подсчёт top-level ключей (regex, без парсера) ───────────

const keyOccurrences = new Map();

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  // Column-0 key: `word:` или `word: value` (не комментарий, не последовательность)
  const match = line.match(/^([a-zA-Z_][a-zA-Z0-9_]*)\s*:/);
  if (match) {
    const key = match[1];
    if (!keyOccurrences.has(key)) keyOccurrences.set(key, []);
    keyOccurrences.get(key).push(i + 1);
  }
}

// ─── 3. Проверка дублей ─────────────────────────────────────────

for (const [key, lineNumbers] of keyOccurrences) {
  if (lineNumbers.length > 1) {
    if (APPEND_OK_KEYS.has(key)) {
      // append-only ключи могут встречаться многократно — warning
      warnings.push(
        `Append-only key "${key}" appears ${lineNumbers.length} times (lines: ${lineNumbers.join(', ')}). ` +
          `This is allowed for ${key}, verify it is intentional.`,
      );
    } else {
      errors.push(
        `DUPLICATE top-level key "${key}" appears ${lineNumbers.length} times at lines: ${lineNumbers.join(', ')}. ` +
          `In YAML, last occurrence wins — orchestrator reads STALE data from earlier occurrences. ` +
          `Use StrReplace to update the existing key, not append a new one.`,
      );
    }
  }
}

// ─── 4. YAML-парсинг (если доступен пакет yaml) ─────────────────

let doc = null;
try {
  const YAML = await import('yaml');
  doc = YAML.parse(source, { uniqueKeys: true });
  // Если parse не упал — файл синтаксически валиден
} catch (e) {
  // Различаем: пакет yaml недоступен vs YAML-синтаксическая ошибка
  if (e.code === 'ERR_MODULE_NOT_FOUND' || e.message.includes('Cannot find package')) {
    warnings.push(
      'Package "yaml" not available — skipping full YAML parse validation. ' +
        'Install with: npm install --save-dev yaml',
    );
  } else {
    errors.push(
      `YAML PARSE ERROR: ${e.message}. ` +
        `File is structurally invalid — standard YAML parsers (yaml-js, pyyaml) cannot read it. ` +
        `Check indentation, orphaned keys, misplaced sequences.`,
    );
  }
}

// ─── 5. Проверка обязательных ключей ────────────────────────────

if (doc !== null && typeof doc === 'object') {
  for (const key of REQUIRED_KEYS) {
    if (!(key in doc)) {
      errors.push(`MISSING required key "${key}" — orchestrator cannot determine routing state.`);
    } else if (doc[key] === null || doc[key] === undefined) {
      warnings.push(`Required key "${key}" is present but null/undefined.`);
    }
  }

  // ─── 6. Проверка типов ───────────────────────────────────────

  for (const [path, check] of Object.entries(TYPE_CHECKS)) {
    const parts = path.split('.');
    let value = doc;
    let exists = true;
    for (const part of parts) {
      if (value === null || typeof value !== 'object') {
        exists = false;
        break;
      }
      if (!(part in value)) {
        exists = false;
        break;
      }
      value = value[part];
    }
    if (exists && !check(value)) {
      errors.push(
        `TYPE ERROR: "${path}" has invalid value/type. Expected specific type, got: ${JSON.stringify(value)?.slice(0, 80) ?? 'undefined'}`,
      );
    }
  }
}

// ─── 7. Отчёт ──────────────────────────────────────────────────

if (warnings.length > 0) {
  console.warn('\n\u26A0\uFE0F  Warnings (non-blocking):');
  for (const w of warnings) console.warn('  ' + w);
}

if (errors.length > 0) {
  console.error('\n\u274C pipeline-state.yaml validation FAILED with ' + errors.length + ' error(s):');
  for (const e of errors) console.error('  \u2022 ' + e);
  console.error('\nFix: remove duplicate keys (use StrReplace, not append) and fix YAML syntax.');
  process.exit(1);
}

console.log('\u2705 pipeline-state.yaml: valid, 0 duplicate keys, all required fields present.');
process.exit(0);
