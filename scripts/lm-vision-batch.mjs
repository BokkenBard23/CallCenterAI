// Run vision_analysis.py on l-*.png and m-*.png screenshots in parallel batches.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = '<repo>';
const SHOTS = path.join(ROOT, 'docs', 'specs', 'screenshots');
const BACKEND = path.join(ROOT, 'backend');
const PYTHON = path.join(BACKEND, '.venv', 'Scripts', 'python.exe');

const BASE_PROMPT = (ctx) => `Ты — визуальный аудитор Frontend. Проект: CallCenterAI (React + Beeline Design System v2.5).
Проверь этот скриншот по критериям:
1. Фоны: консистентность тёмной темы, нет ли разных оттенков
2. Выравнивание: элементы выровнены, отступы консистентны
3. Цвета: соответствие channel color-coding (OPERATOR=зелёный #43a047, CLIENT=синий #1e88e5, ANY=оранжевый #e08600)
4. Цвета подсветки совпадений (L1=Red, L2=Orange, L3=Amber, L4=Teal, L5=Blue)
5. Кнопки/иконки: не битые, правильные DS-варианты, иконки не рендерятся как строки поверх подписей
6. Пустые блоки: нет ли незаполненных областей
7. Ошибки: нет ли red-ошибок, пустых ответов API, белых экранов
8. A11y: виден ли focus-visible, контрастность текста
9. Layout: нет ли наложения текста, обрезания за пределами кнопок/контейнеров, склеенных tab-ов

Дополнительный контекст скриншота: ${ctx}

Опиши все недочёты подробно на русском.`;

const CTX = {
  // L phase — ResultsPage
  'l-results-default':          'ResultsPage начальное состояние после восстановления сессии. Сводка по умолчанию.',
  'l-viewmode-summary':        'ViewMode "Сводка". Ожидается LLM summary.',
  'l-viewmode-highlighted':   'ViewMode "Выделенный текст" с подсвеченными фразами. Ожидается 3+ mark элементов.',
  'l-highlight-levels':        'Та же вкладка Выделенный текст. Проверь АКТУАЛЬНУЮ палитру подсветки (L1=Red, L2=Orange, L3=Amber, L4=Teal, L5=Blue).',
  'l-phrase-popover':          'PhrasePopover открыт после клика на подсвеченную фразу. Ожидается: Канал, Расстояние, Точность, Словарь, Реплика, feedback форма (textarea + кнопка Отправить).',
  'l2-feedback-filled':        'PhrasePopover с заполненной textarea feedback (22/1000 символов). Кнопка Отправить должна быть активна.',
  'l2-feedback-sent':          'После отправки feedback. Должен быть confirmation или popover закрыт.',
  'l-popover-close-btn':       'PhrasePopover. У него нет aria-label="Close" кнопки закрытия — есть только feedback форма и клик вне popover.',
  'l-popover-close-outside':   'После клика вне popover. Popover должен быть закрыт.',
  'l-popover-close-esc':       'После нажатия Escape. Popover должен быть закрыт.',
  'l-quality-score':           'QualityScorePanel раскрыт. Ожидается: 12 категорий, 3 уровня (High=зелёный, Medium=оранжевый, Low=красный), 4 домена, animated circular progress bar.',
  'l-semantic-initial':        'SemanticSearchPanel открыт. Ожидается: статус FRIDA + FAISS, поле ввода, кнопка поиска.',
  'l-semantic-results':        'После поиска "тариф". Ожидается список результатов с ранжированием.',
  'l-semantic-hybrid':         'После переключения hybrid toggle. Ожидается hybrid search результаты.',
  'l-export-excel':            'После клика Excel. Ожидается snackbar уведомление или скачивание.',
  'l-export-pdf':              'После клика PDF. Ожидается snackbar уведомление или скачивание.',
  'l-scrolled-down':           'После прокрутки вниз. Ожидается нижняя часть страницы без пустых блоков.',
  'l-results-fullpage':        'Полный скриншот ResultsPage (full page). Общая композиция.',
  // M phase — SpeechLabPage
  'm-speechlab-initial':       'SpeechLabPage начальное состояние. Ожидается 2-panel layout (LeftPanel 320px + RightPanel с Tabs Запрос/Найденные записи). Сепаратор декоративный, НЕ resizable.',
  'm-left-panel':              'Левая панель — дерево словаря. Ожидается иерархия, иконки, channel colors.',
  'm-tree-expanded':           'Дерево после разворачивания нескольких узлов.',
  'm-tree-collapsed':          'Дерево после сворачивания.',
  'm-tree-expanded-more':      'Дерево с развёрнутыми несколькими узлами.',
  'm-found-records':           'Вкладка Found Records. Ожидается записи с цветами совпадений (L1-L5).',
  'm-found-record-click':      'После клика на запись.',
  'm-query-tab':               'Вкладка Query. Ожидается поле ввода + кнопка поиска.',
  'm-keywords':                'KeywordsDisplay + TokenBadge после выбора узла. ВАЖНО: при multiselect=false selectOnRowClick не работает (DS Tree ограничение) — узел не выбирается, контент может быть пустым "Выберите словарь в дереве".',
  'm-import-dialog':           'Import XML dialog открыт. DropZone для .xml файла.',
  'm-import-after-select':     'После выбора XML файла в Import Dialog. Ожидается preview дерева в фоне.',
  'm-after-xml-upload':        'После загрузки XML на backend. Дерево словаря должно быть populated.',
  'm-resize':                  'После перетаскивания разделителя панелей. Сепаратор декоративный (aria-hidden=true), resize не работает — это by design.',
  'm-rtf-dialog':              'SpeechLabRtfDialog открыт. Ожидается overlay, backdrop, DropZone для RTF файла, кнопки Отмена/Загрузить.',
  'm-rtf-close-btn':           'После закрытия кнопкой "Отмена".',
  'm-rtf-close-backdrop':      'После клика по backdrop. ВАЖНО: backdrop click НЕ закрывает DS Dialog — это потенциальный UX issue.',
  'm-rtf-close-esc':           'После закрытия Escape.',
  'm-topbar':                  'SpeechLabTopBar. Кнопки, заголовки, выравнивание.',
  'm-scrolled-down':           'После прокрутки вниз.',
  'm-speechlab-fullpage':      'Полный скриншот SpeechLabPage. Общая композиция.',
};

function listShots(prefix) {
  return fs.readdirSync(SHOTS)
    .filter(f => f.startsWith(prefix + '-') && f.endsWith('.png'))
    .map(f => f.replace(/\.png$/, ''))
    .sort();
}

function runOne(name) {
  const img = path.join(SHOTS, name + '.png');
  if (!fs.existsSync(img)) return Promise.resolve({ name, code: -1, ok: false, stderr: 'no img' });
  const out = path.join(SHOTS, 'ai-analysis-' + name + '.md');
  const ctx = CTX[name] || '';
  const prompt = BASE_PROMPT(ctx);
  return new Promise((resolve) => {
    const p = spawn(PYTHON, ['-m', 'app.services.vision_analysis',
      '--image', img, '--prompt', prompt, '--output', out],
      { cwd: BACKEND, env: { ...process.env, PYTHONPATH: '.', PYTHONIOENCODING: 'utf-8' } });
    let stdout = '', stderr = '';
    p.stdout.on('data', d => stdout += d.toString());
    p.stderr.on('data', d => stderr += d.toString());
    const to = setTimeout(() => { try { p.kill('SIGKILL'); } catch (e) {} }, 180000);
    p.on('exit', (code) => {
      clearTimeout(to);
      const ok = fs.existsSync(out);
      console.log(`[${name}] exit=${code} output=${ok}`);
      if (!ok) console.log(`  STDERR: ${stderr.substring(0, 300)}`);
      resolve({ name, code, ok, stderr: stderr.substring(0, 500), stdout: stdout.substring(0, 200) });
    });
  });
}

async function main() {
  // Filter to informative screenshots only (no duplicates, no debug)
  const skip = new Set([
    'l-history-list', 'l-after-restore',
    'l-viewmode-summary-2', 'l-viewmode-structure', // structure tab doesn't exist
    'l-feedback-open', 'l-feedback-sent', 'l-feedback-filled', // l2 versions preferred
    'l-quality-score-initial', // l-quality-score has full animation
    'l2-results-state', 'l2-semantic-state', 'l2-phrase-popover', // debug
    'm2-after-xml-upload', 'm2-found-records', 'm2-found-record-click',
    'm2-import-dialog', 'm2-keywords', 'm2-left-panel', 'm2-query-tab',
    'm2-resize', 'm2-rtf-close-backdrop', 'm2-rtf-close-btn', 'm2-rtf-close-esc',
    'm2-rtf-dialog', 'm2-rtf-dialog-2', 'm2-rtf-dialog-3',
    'm2-scrolled-down', 'm2-speechlab-fullpage', 'm2-speechlab-initial', 'm2-topbar',
    'm2-tree-collapsed', 'm2-tree-expanded', 'm2-tree-expanded-more',
  ]);
  const names = [...listShots('l'), ...listShots('m'), ...listShots('l2')]
    .filter(n => !skip.has(n));
  console.log('Found', names.length, 'screenshots (filtered)');
  const BATCH = 4;
  const results = [];
  for (let i = 0; i < names.length; i += BATCH) {
    const batch = names.slice(i, i + BATCH);
    console.log(`--- Batch ${i / BATCH + 1}: ${batch.join(', ')}`);
    const res = await Promise.all(batch.map(runOne));
    results.push(...res);
  }
  const summary = results.map(r => ({ name: r.name, code: r.code, ok: r.ok }));
  fs.writeFileSync(path.join(SHOTS, 'lm-vision-summary.json'), JSON.stringify(summary, null, 2));
  console.log('--- Summary ---');
  for (const r of summary) console.log(`${r.ok ? 'OK ' : 'FAIL'} ${r.name} code=${r.code}`);
}

main().catch(e => { console.error(e); process.exit(1); });
