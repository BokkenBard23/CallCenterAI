#!/usr/bin/env tsx
/**
 * DS Drift Check
 * ==============
 * Compares the snapshot of Beeline Design System component props
 * (`docs/specs/ds-prop-inventory.json`) against the actual TypeScript
 * declaration files shipped in `node_modules/@beeline/design-system-react/types`.
 *
 * Behaviour:
 * - Exit code 0 → no drift detected (inventory matches installed DS types).
 * - Exit code 1 → drift detected (added or removed props). The CI workflow
 *   converts this report into a GitHub issue.
 *
 * The script is intentionally dependency-free (only Node `fs`/`path`) so it
 * can run inside `npx tsx` without extra installs.
 *
 * Source of truth: `.opencode/rules/03-pipeline-transitions.md` — Track D.2.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

interface InventoryComponent {
  import_path: string;
  source_file: string;
  interface: string;
  extends?: string[];
  type_depth?: 'expanded' | 'alias_only';
  props: Record<string, string>;
  type_aliases?: Record<string, string>;
  drift_warnings?: string[];
}

interface Inventory {
  snapshot_at: string;
  ds_version: string;
  ds_package: string;
  source: string;
  source_method: string;
  components_total: number;
  not_found: string[];
  components: Record<string, InventoryComponent>;
}

interface DriftItem {
  kind: 'added_in_ds' | 'removed_in_ds';
  prop: string;
  detail: string;
  used_in_files: string[];
}

interface ComponentDrift {
  component: string;
  drift: DriftItem[];
  unresolved_extends: string[];
  source_file: string;
}

// ---- Configuration ---------------------------------------------------------

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const INVENTORY_PATH = path.join(
  PROJECT_ROOT,
  'docs',
  'specs',
  'ds-prop-inventory.json',
);
const DS_TYPES_ROOT = path.join(
  PROJECT_ROOT,
  'node_modules',
  '@beeline',
  'design-system-react',
);
const SRC_ROOT = path.join(PROJECT_ROOT, 'src');

const SRC_SCAN_EXTENSIONS = ['.ts', '.tsx'];
const MAX_PARSE_DEPTH = 12;

/**
 * Common React / DOM props that come from `HTMLAttributes` / `React.*` and
 * therefore appear in any component whose `.types.d.ts` extends those types.
 *
 * When such a prop surfaces as drift (in actual but not in inventory, or vice
 * versa) AND the component has at least one unresolved external extends
 * (HTMLAttributes, React.*, etc.), we downgrade it to "likely inherited from
 * React/DOM" rather than real DS drift. This eliminates the most common
 * false-positive category caused by the mcp-researcher inventory snapshot
 * being conservative about external inheritance.
 */
const COMMON_REACT_PROPS = new Set<string>([
  'children',
  'className',
  'style',
  'id',
  'key',
  'ref',
  'role',
  'tabIndex',
  'title',
  'hidden',
  'dir',
  'lang',
  'translate',
  'contentEditable',
  'draggable',
  'spellCheck',
  'autoFocus',
  'disabled',
  'form',
  'name',
  'type',
  'value',
  'defaultValue',
  'placeholder',
  'readOnly',
  'required',
  'autoComplete',
  'autoCapitalize',
  'autoCorrect',
  'inputMode',
  'pattern',
  'min',
  'max',
  'step',
  'maxLength',
  'minLength',
  'multiple',
  'size',
  'checked',
  'defaultChecked',
  'selected',
  'src',
  'alt',
  'width',
  'height',
  'href',
  'target',
  'rel',
  'download',
  'loading',
  'onClick',
  'onChange',
  'onInput',
  'onSubmit',
  'onReset',
  'onFocus',
  'onBlur',
  'onKeyDown',
  'onKeyUp',
  'onKeyPress',
  'onMouseEnter',
  'onMouseLeave',
  'onMouseOver',
  'onMouseOut',
  'onMouseDown',
  'onMouseUp',
  'onMouseMove',
  'onPointerEnter',
  'onPointerLeave',
  'onPointerDown',
  'onPointerUp',
  'onPointerMove',
  'onTouchStart',
  'onTouchEnd',
  'onTouchMove',
  'onScroll',
  'onWheel',
  'onDragStart',
  'onDragEnd',
  'onDragOver',
  'onDrop',
  'onAnimationStart',
  'onAnimationEnd',
  'onTransitionEnd',
  'onCopy',
  'onCut',
  'onPaste',
  'onSelect',
  'onContextMenu',
  'onError',
  'onLoad',
  'onInvalid',
  'onBeforeInput',
  'onAbort',
  'onCanPlay',
  'onCanPlayThrough',
  'onDurationChange',
  'onEmptied',
  'onEncrypted',
  'onEnded',
  'onLoadedData',
  'onLoadedMetadata',
  'onLoadStart',
  'onPause',
  'onPlay',
  'onPlaying',
  'onProgress',
  'onRateChange',
  'onSeeked',
  'onSeeking',
  'onStalled',
  'onSuspend',
  'onTimeUpdate',
  'onVolumeChange',
  'onWaiting',
]);

function isCommonReactProp(prop: string): boolean {
  if (COMMON_REACT_PROPS.has(prop)) return true;
  if (prop.startsWith('aria-')) return true;
  if (prop.startsWith('data-')) return true;
  if (/^on[A-Z]/.test(prop)) return true;
  return false;
}

// ---- Utilities -------------------------------------------------------------

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Strip block comments and JSDoc comments from .d.ts content. */
function stripComments(content: string): string {
  return content.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** Strip the generic parameter list `<...>` from a type name. */
function stripGenerics(name: string): string {
  let depth = 0;
  let result = '';
  for (let i = 0; i < name.length; i++) {
    const c = name[i];
    if (c === '<') depth++;
    else if (c === '>') {
      if (depth > 0) depth--;
    } else if (depth === 0) result += c;
  }
  return result.trim();
}

/**
 * Returns true for type names that originate from packages external to the DS
 * package (React, @types/react, @beeline/design-tokens, etc.). Such types
 * cannot be resolved by relative file reads and are reported as
 * `unresolved_extends` rather than treated as drift.
 */
function isExternalType(name: string): boolean {
  const base = stripGenerics(name).trim();
  if (!base) return true;
  // React.* / React namespace
  if (base.startsWith('React.')) return true;
  // HTMLAttributes<...>, AnchorHTMLAttributes<...>, ButtonHTMLAttributes<...>
  if (/^(React\.)?HTMLAttributes$/.test(base)) return true;
  if (/^[A-Za-z]+HTMLAttributes$/.test(base)) return true;
  if (base === 'TestComponentProps') return true;
  if (base === 'AllStatuses' || base === 'ColorTypes' || base === 'ColorType') return true;
  if (base === 'Icons' || base === 'Placement') return true;
  if (base === 'ReactNode' || base === 'ReactElement') return true;
  // Anything that still contains `<` or `&` after stripping generics is a complex expression
  if (/[&<>]/.test(base)) return true;
  return false;
}

/**
 * Extract the body of the first `{ ... }` block starting from index `start`
 * (which must point one char after the opening brace). Handles nested braces.
 */
function extractBracedBlock(content: string, start: number): string {
  let depth = 1;
  let i = start;
  while (i < content.length && depth > 0) {
    const c = content[i];
    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) return content.slice(start, i);
    }
    i++;
  }
  return content.slice(start);
}

/**
 * Parse a single `interface XProps { ... }` or `type XProps = ...;` declaration
 * from `content`. Returns the list of own (explicitly-declared) prop names and
 * the list of `extends`/intersection operands.
 *
 * Own props are extracted by matching identifiers at the start of a statement
 * followed by `:` or `?:` (TS prop signature syntax).
 */
function parseTypeDeclaration(
  content: string,
  typeName: string,
): { props: Set<string>; extendsNames: string[] } | null {
  const stripped = stripComments(content);
  const baseName = escapeRegex(stripGenerics(typeName));

  // 1. interface declaration (with optional generic params and extends clause)
  //    `interface FooProps<T> extends A, B<C> {`
  const ifaceRe = new RegExp(
    `(?:export\\s+)?(?:declare\\s+)?interface\\s+${baseName}\\b\\s*(?:<[^{]*?>)?\\s*(?:extends\\s+([^{]+?))?\\s*\\{`,
    'g',
  );
  const ifaceMatch = ifaceRe.exec(stripped);
  if (ifaceMatch) {
    const extendsStr = (ifaceMatch[1] ?? '').trim();
    const extendsNames = extendsStr
      ? extendsStr.split(',').map((s) => s.trim()).filter(Boolean)
      : [];
    const bodyStart = ifaceMatch.index + ifaceMatch[0].length;
    const body = extractBracedBlock(stripped, bodyStart);
    const props = extractPropNames(body);
    return { props, extendsNames };
  }

  // 2. type alias: `type XProps = A & B & C;` or `type XProps = SomeUnion;`
  //    Split RHS by both `&` (intersection) and `|` (union) — DS uses both
  //    (e.g. `type ButtonGroupProps = ButtonGroupPropsAlwaysSelected | ButtonGroupPropsOptionalSelected;`
  //     and `type TypographyProps = TypographyBaseProps | NativeLink | RoutedLink | ContextualLink;`).
  const typeRe = new RegExp(
    `(?:export\\s+)?(?:declare\\s+)?type\\s+${baseName}\\b\\s*(?:<[^;]*?>)?\\s*=\\s*([\\s\\S]+?);`,
    'g',
  );
  const typeMatch = typeRe.exec(stripped);
  if (typeMatch) {
    const rhs = typeMatch[1].trim();
    const extendsNames = rhs
      .split(/[&|]/)
      .map((s) => s.trim())
      .filter((s) => /^[A-Za-z_$][\w$<>[\],\s|.-]*$/.test(s));
    return { props: new Set<string>(), extendsNames };
  }

  return null;
}

/**
 * Extract prop names from an interface body.
 *
 * Matches identifiers at the start of a (semicolon- or newline-terminated)
 * statement, optionally preceded by `readonly`. Quoted names like
 * `'aria-label'` are also accepted. The matcher respects `{}` nesting depth
 * so that nested object-type literals (`scroll?: { x?: ...; y?: ...; }`)
 * don't leak their inner fields as fake props of the outer interface.
 */
function extractPropNames(body: string): Set<string> {
  const props = new Set<string>();
  // Walk the body char-by-char, tracking brace depth AT LINE START.
  // Only lines that began at depth 0 are prop declarations; lines inside a
  // nested object-type literal (`scroll?: { x?: ...; y?: ...; }`) are skipped.
  let depth = 0;
  let lineStart = 0;
  let depthAtLineStart = 0;

  const flushLine = (line: string) => {
    const stripped = line.replace(/^\s*(?:readonly\s+)?/, '');
    // Quoted name: 'aria-label'?: string;
    const quotedMatch = /^['"]([^'"]+)['"]\s*(?:\[.*?\])?\s*[?:]/.exec(stripped);
    if (quotedMatch) {
      props.add(quotedMatch[1]);
      return;
    }
    // Identifier name
    const identMatch = /^([A-Za-z_$][\w$]*)\s*(?:\[.*?\])?\s*[?:]/.exec(stripped);
    if (identMatch) {
      const name = identMatch[1];
      if (
        name !== 'constructor' &&
        name !== 'new' &&
        name !== 'get' &&
        name !== 'set'
      ) {
        props.add(name);
      }
    }
  };

  for (let i = 0; i < body.length; i++) {
    const c = body[i];
    if (c === '{') {
      depth++;
    } else if (c === '}') {
      depth = Math.max(0, depth - 1);
    } else if (c === '\n') {
      if (depthAtLineStart === 0) {
        flushLine(body.slice(lineStart, i));
      }
      lineStart = i + 1;
      depthAtLineStart = depth;
    }
  }
  if (lineStart < body.length && depthAtLineStart === 0) {
    flushLine(body.slice(lineStart));
  }
  return props;
}

/** Resolve an extends identifier to a relative import path declared in `content`. */
function resolveExtendsImport(
  content: string,
  typeName: string,
): string | null {
  const base = stripGenerics(typeName).trim();
  if (!base) return null;
  const stripped = stripComments(content);
  // `import type { A, B } from './path';` or `import { A } from 'path';`
  const re = new RegExp(
    `import\\s+(?:type\\s+)?\\{[^}]*\\b${escapeRegex(base)}\\b[^}]*\\}\\s*from\\s*['"]([^'"]+)['"]`,
    'g',
  );
  const m = re.exec(stripped);
  return m ? m[1] : null;
}

/** Try several file resolutions for a relative import inside the DS package. */
function resolveRelativeFile(
  fromFile: string,
  relImport: string,
): string | null {
  const dir = path.dirname(fromFile);
  const candidates = [
    path.resolve(dir, relImport + '.d.ts'),
    path.resolve(dir, relImport + '.types.d.ts'),
    path.resolve(dir, relImport + '.ts'),
    path.resolve(dir, relImport, 'index.d.ts'),
    path.resolve(dir, relImport),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  }
  return null;
}

interface ParsedResult {
  props: Set<string>;
  unresolvedExtends: string[];
}

/**
 * Recursively collect prop names for `typeName` starting from `filePath`,
 * following relative `import type` references and locally-declared types.
 */
function getActualProps(
  filePath: string,
  typeName: string,
  visited: Set<string>,
  depth: number,
): ParsedResult {
  const key = `${filePath}::${typeName}`;
  if (visited.has(key)) {
    return { props: new Set<string>(), unresolvedExtends: [] };
  }
  visited.add(key);

  if (depth >= MAX_PARSE_DEPTH) {
    return { props: new Set<string>(), unresolvedExtends: [`${typeName} (max depth)`] };
  }

  if (!fs.existsSync(filePath)) {
    return {
      props: new Set<string>(),
      unresolvedExtends: [`${typeName} (file missing: ${filePath})`],
    };
  }

  const content = fs.readFileSync(filePath, 'utf-8');
  const parsed = parseTypeDeclaration(content, typeName);
  if (!parsed) {
    return {
      props: new Set<string>(),
      unresolvedExtends: [`${typeName} (not declared in ${path.relative(DS_TYPES_ROOT, filePath)})`],
    };
  }

  const allProps = new Set<string>(parsed.props);
  const unresolved: string[] = [];

  for (const ext of parsed.extendsNames) {
    if (isExternalType(ext)) {
      unresolved.push(stripGenerics(ext).trim());
      continue;
    }

    const baseName = stripGenerics(ext).trim();

    // 1. Try local declaration in the same file
    const localParsed = parseTypeDeclaration(content, baseName);
    if (localParsed) {
      const child = getActualProps(filePath, baseName, visited, depth + 1);
      child.props.forEach((p) => allProps.add(p));
      child.unresolvedExtends.forEach((u) => unresolved.push(u));
      continue;
    }

    // 2. Try relative import
    const relImport = resolveExtendsImport(content, baseName);
    if (relImport && relImport.startsWith('.')) {
      const resolved = resolveRelativeFile(filePath, relImport);
      if (resolved) {
        const child = getActualProps(resolved, baseName, visited, depth + 1);
        child.props.forEach((p) => allProps.add(p));
        child.unresolvedExtends.forEach((u) => unresolved.push(u));
        continue;
      }
      unresolved.push(`${baseName} (relative import "${relImport}" not found)`);
    } else if (relImport && !relImport.startsWith('.')) {
      // Package import — external, skip
      unresolved.push(`${baseName} (package import: ${relImport})`);
    } else {
      unresolved.push(`${baseName} (cannot resolve)`);
    }
  }

  return { props: allProps, unresolvedExtends: unresolved };
}

// ---- src/ scanning ----------------------------------------------------------

interface SrcFile {
  path: string; // path relative to SRC_ROOT
  content: string;
}

function walkSrc(root: string): SrcFile[] {
  const out: SrcFile[] = [];
  if (!fs.existsSync(root)) return out;

  const stack: string[] = [root];
  while (stack.length > 0) {
    const dir = stack.pop()!;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.git') continue;
        stack.push(full);
      } else if (entry.isFile()) {
        if (SRC_SCAN_EXTENSIONS.includes(path.extname(entry.name))) {
          out.push({
            path: path.relative(SRC_ROOT, full).replace(/\\/g, '/'),
            content: fs.readFileSync(full, 'utf-8'),
          });
        }
      }
    }
  }
  return out;
}

/** Find the index of the closing `>` of a JSX opening tag, respecting `{}`. */
function findTagEnd(s: string): number {
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === '{') depth++;
    else if (c === '}') depth = Math.max(0, depth - 1);
    else if (c === '>' && depth === 0) {
      // Self-closing `/>` — return position of `>`
      return i;
    }
  }
  return s.length;
}

/**
 * Find files/lines in `srcFiles` where `<ComponentName ... propName ...>`
 * appears (propName as a word boundary inside the JSX opening tag).
 */
function findUsageInSrc(
  srcFiles: SrcFile[],
  componentName: string,
  propName: string,
): string[] {
  const tagRe = new RegExp(`<${escapeRegex(componentName)}\\b`, 'g');
  const propRe = new RegExp(`\\b${escapeRegex(propName)}\\b`);
  const out: string[] = [];
  const seenFiles = new Set<string>();
  for (const sf of srcFiles) {
    tagRe.lastIndex = 0;
    let m: RegExpExecArray | null;
    let found = false;
    while ((m = tagRe.exec(sf.content)) !== null) {
      const rest = sf.content.slice(m.index, m.index + 4096);
      const end = findTagEnd(rest);
      const tagContent = rest.slice(0, end);
      if (propRe.test(tagContent)) {
        found = true;
        break;
      }
    }
    if (found) {
      // Find first line with the prop name mentioned near the component
      const lines = sf.content.split('\n');
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].includes(`<${componentName}`) && propRe.test(lines[i])) {
          out.push(`src/${sf.path}:${i + 1}`);
          seenFiles.add(sf.path);
          break;
        }
      }
      if (!seenFiles.has(sf.path)) {
        out.push(`src/${sf.path}`);
        seenFiles.add(sf.path);
      }
    }
  }
  return out;
}

// ---- Main ------------------------------------------------------------------

function readInventory(): Inventory {
  if (!fs.existsSync(INVENTORY_PATH)) {
    throw new Error(`Inventory not found: ${INVENTORY_PATH}`);
  }
  const raw = fs.readFileSync(INVENTORY_PATH, 'utf-8');
  return JSON.parse(raw) as Inventory;
}

interface CheckResult {
  componentCount: number;
  driftCount: number;
  driftByComponent: ComponentDrift[];
  inventory: Inventory;
}

function runDriftCheck(): CheckResult {
  const inventory = readInventory();
  const componentNames = Object.keys(inventory.components);
  const srcFiles = walkSrc(SRC_ROOT);
  const driftByComponent: ComponentDrift[] = [];

  for (const componentName of componentNames) {
    const comp = inventory.components[componentName];
    const relativePath = comp.source_file;
    const absPath = path.join(DS_TYPES_ROOT, relativePath);
    const parsed = getActualProps(absPath, comp.interface, new Set(), 0);

    const inventoryProps = new Set(Object.keys(comp.props ?? {}));
    const actualProps = parsed.props;

    const drift: DriftItem[] = [];
    const hasUnresolvedExternal = parsed.unresolvedExtends.length > 0;

    // Added in DS (in actual, not in inventory) — potential new props in DS version.
    // Filter common React/DOM props when external extends exist (likely inherited
    // from HTMLAttributes and merely absent from the mcp-researcher snapshot).
    for (const prop of actualProps) {
      if (!inventoryProps.has(prop)) {
        if (hasUnresolvedExternal && isCommonReactProp(prop)) {
          continue;
        }
        const usage = findUsageInSrc(srcFiles, componentName, prop);
        drift.push({
          kind: 'added_in_ds',
          prop,
          detail: comp.props[prop] ?? 'new prop in DS types',
          used_in_files: usage,
        });
      }
    }
    // Removed from DS (in inventory, not in actual) — prop disappeared from DS types.
    for (const prop of inventoryProps) {
      if (!actualProps.has(prop)) {
        if (hasUnresolvedExternal && isCommonReactProp(prop)) {
          continue;
        }
        const usage = findUsageInSrc(srcFiles, componentName, prop);
        drift.push({
          kind: 'removed_in_ds',
          prop,
          detail: comp.props[prop] ?? '',
          used_in_files: usage,
        });
      }
    }

    driftByComponent.push({
      component: componentName,
      drift,
      unresolved_extends: parsed.unresolvedExtends,
      source_file: relativePath,
    });
  }

  const driftCount = driftByComponent.reduce(
    (sum, c) => sum + c.drift.length,
    0,
  );

  return {
    componentCount: componentNames.length,
    driftCount,
    driftByComponent,
    inventory,
  };
}

function formatReport(result: CheckResult): string {
  const lines: string[] = [];
  lines.push('DS Drift Check Report');
  lines.push('====================');
  lines.push(`DS package:        ${result.inventory.ds_package} v${result.inventory.ds_version}`);
  lines.push(`Inventory snapshot: ${result.inventory.snapshot_at}`);
  lines.push(`Components:        ${result.componentCount}`);
  lines.push('');

  const drifted = result.driftByComponent.filter((c) => c.drift.length > 0);
  if (drifted.length === 0 && result.driftCount === 0) {
    lines.push('OK: No drift detected. Inventory matches installed DS types.');
    lines.push('');
    lines.push('Unresolved external extends (informational, not drift):');
    for (const c of result.driftByComponent) {
      if (c.unresolved_extends.length > 0) {
        lines.push(
          `  - ${c.component}: ${c.unresolved_extends.join(', ')}`,
        );
      }
    }
    return lines.join('\n');
  }

  lines.push(
    `FAIL: Drift detected — ${result.driftCount} prop(s) across ${drifted.length} component(s).`,
  );
  lines.push('');
  lines.push(
    'Legend:',
  );
  lines.push(
    '  ADDED in DS   — prop exists in installed DS types but is missing in inventory.',
  );
  lines.push(
    '                  Likely cause: DS version upgrade OR inventory gap (re-run mcp-researcher to refresh).',
  );
  lines.push(
    '  REMOVED in DS — prop was captured in inventory but is no longer in installed DS types.',
  );
  lines.push(
    '                  Likely cause: DS version upgrade removed the prop. Action: update consumers in src/.',
  );
  lines.push('');

  for (const c of drifted) {
    lines.push(`[${c.component}]  (${c.source_file})`);
    for (const d of c.drift) {
      const label =
        d.kind === 'added_in_ds'
          ? 'ADDED in DS (not in inventory)'
          : 'REMOVED from DS (in inventory, missing in actual)';
      lines.push(`  ${label}:`);
      lines.push(`    - ${d.prop}`);
      if (d.detail) lines.push(`      inventory type: ${d.detail}`);
      if (d.used_in_files.length > 0) {
        lines.push(`      used in src/:`);
        for (const f of d.used_in_files.slice(0, 20)) {
          lines.push(`        · ${f}`);
        }
      } else {
        lines.push(`      used in src/: (no usage found)`);
      }
    }
    if (c.unresolved_extends.length > 0) {
      lines.push(
        `  unresolved external extends: ${c.unresolved_extends.join(', ')}`,
      );
    }
    lines.push('');
  }

  return lines.join('\n');
}

function main(): void {
  let result: CheckResult;
  try {
    result = runDriftCheck();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    process.stderr.write(`DS Drift Check: FATAL ERROR\n${msg}\n`);
    process.exit(2);
  }

  const report = formatReport(result);
  process.stdout.write(report + '\n');
  process.stdout.write('\nExit code: ' + (result.driftCount > 0 ? 1 : 0) + '\n');

  process.exit(result.driftCount > 0 ? 1 : 0);
}

main();
