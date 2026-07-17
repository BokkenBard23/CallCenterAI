// Run vision_analysis.py on all h2-*.png screenshots in parallel batches.
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
4. Кнопки/иконки: не битые, правильные DS-варианты, иконки не рендерятся как строки поверх подписей
5. Пустые блоки: нет ли незаполненных областей
6. Ошибки: нет ли red-ошибок, пустых ответов API, белых экранов
7. A11y: виден ли focus-visible, контрастность текста
8. Layout: нет ли наложения текста, обрезания за пределами кнопок/контейнеров, склеенных tab-ов

Дополнительный контекст скриншота: ${ctx}

Опиши все недочёты подробно на русском.`;

const CTX = {
  'h2-navbar-home':             'Главная страница с NavBar: 5 табов (Главная, Результаты, SpeechLab, Словари, История). Активный: Главная. URL: /',
  'h2-navbar-results':          'После клика по табу Результаты. Активный: Результаты. URL: /results',
  'h2-navbar-speechlab':        'После клика по табу SpeechLab. URL: /speechlab',
  'h2-navbar-dictionary':       'После клика по табу Словари. URL: /dictionary или /dictionary/:id',
  'h2-navbar-history':          'После клика по табу История. URL: /history',
  'h2-navbar-back-home':        'После клика по табу Главная. URL: должен быть /',
  'h2-dashboard-initial':       'Dashboard hub: heading "Анализ диалогов", 4 feature cards (Upload/SpeechLab/Dictionary/History), Stepper Card "Быстрая загрузка", Recent analyses секция',
  'h2-dashboard-upload-cta':    'После клика CTA на Upload card — должен быть скролл к Stepper',
  'h2-dashboard-speechlab-cta': 'После клика CTA на SpeechLab card — должен быть переход на /speechlab',
  'h2-dashboard-history-cta':   'После клика CTA на History card — должен быть переход на /history',
  'h2-dashboard-recent':        'Recent analyses секция — должны быть записи или empty state',
  'h2-breadcrumbs-results':     'Страница /results с breadcrumbs "Главная › Результаты"',
  'h2-breadcrumbs-speechlab':   'Страница /speechlab с breadcrumbs "Главная › SpeechLab"',
  'h2-breadcrumbs-dictionary':  'Страница /dictionary/test-session-0001 с breadcrumbs "Главная › Словари › ..."',
  'h2-breadcrumbs-history':     'Страница /history с breadcrumbs "Главная › История"',
  'h2-breadcrumbs-click-home':   'После клика по "Главная" в breadcrumbs — должен быть переход на /',
  'h2-speaker-labels':          'Вкладка "Выделенный текст" на /results. "Сотрудник"=зелёный label, "Клиент"=синий label, должны различаться',
  'h2-speaker-css-vars':        'CSS vars check — operator=#43a047 зелёный, client=#1e88e5 синий',
  'h2-modal-ai-open':           'На /dictionary/test-session-0001 после выбора leaf-узла и клика "AI анализ" — должен быть открыт modal AI анализа',
  'h2-modal-mutex-test':        'После открытия AI анализа — клик по "Mining". AI должен закрыться, Mining — открыться. Mutex test',
  'h2-modal-mutex-reverse':     'После открытия Mining — клик по "AI анализ". Mining должен закрыться, AI анализ — открыться',
  'h2-tree-tooltip':            'Hover на обрезанный узел дерева (с многоточием) — должен появиться tooltip с полным именем',
  'h2-dictionary-page-init':    'DictionaryEditorPage /dictionary/test-session-0001 в начальном состоянии',
};

function listShots() {
  return fs.readdirSync(SHOTS)
    .filter(f => f.startsWith('h2-') && f.endsWith('.png'))
    .map(f => f.replace(/\.png$/, ''))
    .sort();
}

function runOne(name) {
  const img = path.join(SHOTS, name + '.png');
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
      console.log(`[${name}] exit=${code} output=${ok} ${ok ? '' : '\n--- STDERR ---\n' + stderr}`);
      resolve({ name, code, ok, stderr, stdout });
    });
  });
}

async function main() {
  const names = listShots();
  console.log('Found', names.length, 'screenshots');
  const BATCH = 4;
  const results = [];
  for (let i = 0; i < names.length; i += BATCH) {
    const batch = names.slice(i, i + BATCH);
    console.log(`--- Batch ${i / BATCH + 1}: ${batch.join(', ')}`);
    const res = await Promise.all(batch.map(runOne));
    results.push(...res);
  }
  const summary = results.map(r => ({ name: r.name, code: r.code, ok: r.ok }));
  fs.writeFileSync(path.join(SHOTS, 'h2-vision-summary.json'), JSON.stringify(summary, null, 2));
  console.log('--- Summary ---');
  for (const r of summary) console.log(`${r.ok ? 'OK ' : 'FAIL'} ${r.name} code=${r.code}`);
}

main().catch(e => { console.error(e); process.exit(1); });
