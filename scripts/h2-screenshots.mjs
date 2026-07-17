// H2 verification screenshots — robust single-file run
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };

const consoleErrors = [];
const consoleWarns = [];

async function newPage(ctx) {
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);
  page.on('console', m => {
    if (m.type() === 'error') consoleErrors.push(`${page.url()} :: ${m.text()}`);
    if (m.type() === 'warning') consoleWarns.push(`${page.url()} :: ${m.text()}`);
  });
  page.on('pageerror', e => consoleErrors.push(`${page.url()} :: PAGEERROR: ${e.message}`));
  return page;
}

async function shot(page, name, opts = {}) {
  const file = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: !!opts.fullPage });
  console.log(`SHOT ${name} -> ${file} (size=${fs.statSync(file).size})`);
  return file;
}
async function wait(ms) { await new Promise(r => setTimeout(r, ms)); }

async function clickFirst(page, candidates) {
  for (const sel of candidates) {
    try {
      const loc = typeof sel === 'string' ? page.locator(sel).first() : sel;
      await loc.click({ timeout: 2500 });
      return true;
    } catch (e) { /* try next */ }
  }
  return false;
}

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctxs = browser.contexts();
  const ctx = ctxs[0];
  let page = await newPage(ctx);

  // ---- H2.1 NavBar ----
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await shot(page, 'h2-navbar-home');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'Результаты' }),
    page.locator('[role=tab]:has-text("Результаты")'),
    'a:has-text("Результаты")', 'text="Результаты"',
  ]);
  await wait(1200);
  await shot(page, 'h2-navbar-results');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'SpeechLab' }),
    page.locator('[role=tab]:has-text("SpeechLab")'),
    'a:has-text("SpeechLab")',
  ]);
  await wait(1200);
  await shot(page, 'h2-navbar-speechlab');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'Словари' }),
    page.locator('[role=tab]:has-text("Словари")'),
    'a:has-text("Словари")', 'text="Словари"',
  ]);
  await wait(1200);
  await shot(page, 'h2-navbar-dictionary');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'История' }),
    page.locator('[role=tab]:has-text("История")'),
    'a:has-text("История")', 'text="История"',
  ]);
  await wait(1200);
  await shot(page, 'h2-navbar-history');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'Главная' }),
    page.locator('[role=tab]:has-text("Главная")'),
    'a:has-text("Главная")', 'text="Главная"',
  ]);
  await wait(1200);
  await shot(page, 'h2-navbar-back-home');

  // ---- H2.2 Dashboard ----
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await shot(page, 'h2-dashboard-initial', { fullPage: true });

  // Upload card CTA: find card containing "Загрузить" or "RTF/XML"
  const uploadClicked = await clickFirst(page, [
    page.locator('article:has-text("Загрузить"), section:has-text("Загрузить")').getByRole('button').first(),
    page.locator('text="Загрузить"').first(),
    page.getByRole('button', { name: /Загрузить|Начать анализ|Перейти/i }).first(),
  ]);
  console.log('upload CTA clicked:', uploadClicked);
  await wait(1500);
  await shot(page, 'h2-dashboard-upload-cta', { fullPage: true });

  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  const speechClicked = await clickFirst(page, [
    page.locator('article:has-text("SpeechLab"), section:has-text("SpeechLab")').getByRole('button').first(),
    page.locator('article:has-text("SpeechLab"), section:has-text("SpeechLab")').getByRole('link').first(),
  ]);
  console.log('speech CTA clicked:', speechClicked);
  await wait(1500);
  await shot(page, 'h2-dashboard-speechlab-cta', { fullPage: true });

  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  const histClicked = await clickFirst(page, [
    page.locator('article:has-text("История"), section:has-text("История")').getByRole('button').first(),
    page.locator('article:has-text("История"), section:has-text("История")').getByRole('link').first(),
  ]);
  console.log('history CTA clicked:', histClicked);
  await wait(1500);
  await shot(page, 'h2-dashboard-history-cta', { fullPage: true });

  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await shot(page, 'h2-dashboard-recent', { fullPage: true });

  // ---- H2.3 Breadcrumbs ----
  await page.goto(APP + '/results', { waitUntil: 'domcontentloaded' });
  await wait(1200);
  await shot(page, 'h2-breadcrumbs-results');

  await page.goto(APP + '/speechlab', { waitUntil: 'domcontentloaded' });
  await wait(1200);
  await shot(page, 'h2-breadcrumbs-speechlab');

  await page.goto(APP + '/dictionary/test-session-0001', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await shot(page, 'h2-breadcrumbs-dictionary');

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await wait(1200);
  await shot(page, 'h2-breadcrumbs-history');

  // Click "Главная" in breadcrumbs on /history
  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await wait(800);
  await clickFirst(page, [
    page.getByRole('link', { name: 'Главная' }).first(),
    page.locator('nav[aria-label*=readcrumb i], ol, [class*=readcrumb]').getByText('Главная').first(),
    page.locator('text="Главная"').first(),
  ]);
  await wait(1200);
  await shot(page, 'h2-breadcrumbs-click-home');

  // ---- H2.4 Speaker labels ----
  // /results requires session in URL or via store; try direct URL with session
  await page.goto(APP + '/results?session=test-session-0001', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await clickFirst(page, [
    page.getByRole('tab', { name: 'Выделенный текст' }),
    page.locator('[role=tab]:has-text("Выделенный")'),
    page.getByText('Выделенный текст').first(),
  ]);
  await wait(1500);
  // Expand first matching utterance
  await clickFirst(page, [
    page.locator('[class*=match], [class*=Match], [data-match]').first(),
    page.getByText('Сотрудник', { exact: false }).first(),
    page.getByText('Клиент', { exact: false }).first(),
  ]);
  await wait(1000);
  await shot(page, 'h2-speaker-labels');

  const cssVars = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const pick = (n) => {
      let v = root.getPropertyValue(n).trim();
      // resolve to rgb
      return v;
    };
    return {
      operator: pick('--dict-channel-operator'),
      client: pick('--dict-channel-client'),
      any: pick('--dict-channel-any'),
    };
  });
  console.log('CSS_VARS', JSON.stringify(cssVars));
  fs.writeFileSync(path.join(OUT_DIR, 'h2-speaker-css-vars.json'), JSON.stringify(cssVars, null, 2));
  await shot(page, 'h2-speaker-css-vars');

  // ---- H2.5 Modal mutex ----
  await page.goto(APP + '/dictionary/test-session-0001', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await shot(page, 'h2-dictionary-page-init', { fullPage: true });

  // Expand tree by clicking parent nodes; then click a leaf
  await clickFirst(page, [
    page.getByText('Переключение', { exact: false }).first(),
    page.locator('[class*=tree] :text("Переключение")').first(),
  ]);
  await wait(500);
  await clickFirst(page, [
    page.getByText('заявка', { exact: false }).first(),
    page.getByText('заявка', { exact: false }).nth(1),
  ]);
  await wait(800);

  // Open AI анализ
  await clickFirst(page, [
    page.getByRole('button', { name: /AI анализ|AI-анализ/ }),
    page.locator('button:has-text("AI анализ")').first(),
    page.getByText('AI анализ').first(),
  ]);
  await wait(1500);
  await shot(page, 'h2-modal-ai-open');

  // Without closing — click Mining
  await clickFirst(page, [
    page.getByRole('button', { name: /Mining|Майнинг/ }),
    page.locator('button:has-text("Mining")').first(),
    page.getByText('Mining').first(),
  ]);
  await wait(1500);
  await shot(page, 'h2-modal-mutex-test');

  // Reverse: open Mining → click AI
  await page.keyboard.press('Escape').catch(() => {});
  await wait(600);
  await clickFirst(page, [
    page.getByRole('button', { name: /Mining|Майнинг/ }),
    page.locator('button:has-text("Mining")').first(),
  ]);
  await wait(1500);
  await clickFirst(page, [
    page.getByRole('button', { name: /AI анализ|AI-анализ/ }),
    page.locator('button:has-text("AI анализ")').first(),
    page.getByText('AI анализ').first(),
  ]);
  await wait(1500);
  await shot(page, 'h2-modal-mutex-reverse');

  // ---- H2.6 Tree tooltip ----
  await page.keyboard.press('Escape').catch(() => {});
  await wait(500);
  // Hover over a node — try locator for tree items
  const nodeCandidates = [
    page.locator('[class*=reeNode], [class*=TreeItem], [class*=tree-item]').first(),
    page.locator('text="Переключение"').first(),
    page.locator('[role=treeitem]').first(),
  ];
  for (const c of nodeCandidates) {
    try { await c.hover({ timeout: 2500 }); break; } catch (e) {}
  }
  await wait(2000);
  await shot(page, 'h2-tree-tooltip');

  // Dump console
  fs.writeFileSync(path.join(OUT_DIR, 'h2-console-errors.json'),
    JSON.stringify({ errors: consoleErrors, warns: consoleWarns.slice(0, 30) }, null, 2));
  console.log('CONSOLE_ERRORS', consoleErrors.length);
  console.log('CONSOLE_WARNS', consoleWarns.length);
  await page.close();
  await browser.close();
  console.log('DONE');
}

main().catch(e => { console.error('ERR', e); process.exit(1); });
