// H2 recheck (iteration 2/3) screenshots — research only, NO code changes.
// Tests the 5 bugfixes: NavBar onClick, Breadcrumbs before early returns,
// TreeNode internal tooltip, Modal mutex conditional render, Dashboard /dictionary CTA.
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };

const consoleErrors = [];
const consoleWarns = [];
const consoleAll = [];

async function newPage(ctx) {
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);
  page.on('console', m => {
    const entry = `${page.url()} :: [${m.type()}] ${m.text()}`;
    consoleAll.push(entry);
    if (m.type() === 'error') consoleErrors.push(entry);
    if (m.type() === 'warning') consoleWarns.push(entry);
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

async function clickFirst(page, candidates, label = '') {
  for (const sel of candidates) {
    try {
      const loc = typeof sel === 'string' ? page.locator(sel).first() : sel;
      await loc.click({ timeout: 2500 });
      console.log(`CLICK[${label}] ok via`, typeof sel === 'string' ? sel : 'locator');
      return true;
    } catch (e) { /* try next */ }
  }
  console.log(`CLICK[${label}] FAILED all candidates`);
  return false;
}

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctxs = browser.contexts();
  const ctx = ctxs[0];
  let page = await newPage(ctx);

  // ============== H2.1-recheck: NavBar navigation ==============
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1800);
  await shot(page, 'h2r-navbar-home');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'Результаты' }),
    page.locator('[role=tab]:has-text("Результаты")'),
  ], 'tab-Результаты');
  await wait(1500);
  await shot(page, 'h2r-navbar-results');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'SpeechLab' }),
    page.locator('[role=tab]:has-text("SpeechLab")'),
  ], 'tab-SpeechLab');
  await wait(1500);
  await shot(page, 'h2r-navbar-speechlab');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'Словари' }),
    page.locator('[role=tab]:has-text("Словари")'),
  ], 'tab-Словари');
  await wait(1500);
  await shot(page, 'h2r-navbar-dictionary');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'История' }),
    page.locator('[role=tab]:has-text("История")'),
  ], 'tab-История');
  await wait(1500);
  await shot(page, 'h2r-navbar-history');

  await clickFirst(page, [
    page.getByRole('tab', { name: 'Главная' }),
    page.locator('[role=tab]:has-text("Главная")'),
  ], 'tab-Главная');
  await wait(1500);
  await shot(page, 'h2r-navbar-back-home');

  // ============== H2.3-recheck: Breadcrumbs ==============
  await page.goto(APP + '/results', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await shot(page, 'h2r-breadcrumbs-results');

  await page.goto(APP + '/speechlab', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await shot(page, 'h2r-breadcrumbs-speechlab');

  await page.goto(APP + '/dictionary/test-session-0001', { waitUntil: 'domcontentloaded' });
  await wait(2200);
  await shot(page, 'h2r-breadcrumbs-dictionary');

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await shot(page, 'h2r-breadcrumbs-history');

  // Click "Главная" in breadcrumbs on /history
  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await wait(900);
  await clickFirst(page, [
    page.getByRole('link', { name: 'Главная' }).first(),
    page.locator('nav[aria-label*=readcrumb i], ol, [class*=readcrumb]').getByText('Главная').first(),
    page.locator('text="Главная"').first(),
  ], 'bc-Главная');
  await wait(1500);
  await shot(page, 'h2r-breadcrumbs-click');

  // ============== H2.5-recheck: Modal mutex ==============
  await page.goto(APP + '/dictionary/test-session-0001', { waitUntil: 'domcontentloaded' });
  await wait(2500);

  // Expand tree nodes to find a leaf
  await clickFirst(page, [
    page.getByText('Переключение', { exact: false }).first(),
    page.locator('[class*=tree] :text("Переключение")').first(),
  ], 'tree-Переключение');
  await wait(500);
  await clickFirst(page, [
    page.getByText('заявка', { exact: false }).first(),
    page.getByText('заявка', { exact: false }).nth(1),
  ], 'tree-заявка');
  await wait(1000);

  // Open AI анализ
  await clickFirst(page, [
    page.getByRole('button', { name: /AI анализ|AI-анализ/ }),
    page.locator('button:has-text("AI анализ")').first(),
    page.getByText('AI анализ').first(),
  ], 'btn-AI-анализ');
  await wait(1800);
  await shot(page, 'h2r-modal-ai-open');

  // Without closing — click Mining (mutex test 1)
  await clickFirst(page, [
    page.getByRole('button', { name: /Mining|Майнинг/ }),
    page.locator('button:has-text("Mining")').first(),
    page.getByText('Mining').first(),
  ], 'btn-Mining-1');
  await wait(1800);
  await shot(page, 'h2r-modal-mutex-1');

  // Reverse mutex: open Mining → click AI
  await page.keyboard.press('Escape').catch(() => {});
  await wait(800);
  await clickFirst(page, [
    page.getByRole('button', { name: /Mining|Майнинг/ }),
    page.locator('button:has-text("Mining")').first(),
  ], 'btn-Mining-2');
  await wait(1800);
  await clickFirst(page, [
    page.getByRole('button', { name: /AI анализ|AI-анализ/ }),
    page.locator('button:has-text("AI анализ")').first(),
    page.getByText('AI анализ').first(),
  ], 'btn-AI-анализ-2');
  await wait(1800);
  await shot(page, 'h2r-modal-mutex-2');

  // ============== H2.6-recheck: Tree tooltip (no ref error) ==============
  await page.keyboard.press('Escape').catch(() => {});
  await wait(800);
  const nodeCandidates = [
    page.locator('[class*=reeNode], [class*=TreeItem], [class*=tree-item]').first(),
    page.locator('text="Переключение"').first(),
    page.locator('[role=treeitem]').first(),
  ];
  for (const c of nodeCandidates) {
    try { await c.hover({ timeout: 2500 }); break; } catch (e) {}
  }
  await wait(2500);
  await shot(page, 'h2r-tree-tooltip');

  // ============== H2.2-recheck: Dashboard CTA ==============
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1800);
  await shot(page, 'h2r-dashboard-init');

  // CTA SpeechLab card
  const speechClicked = await clickFirst(page, [
    page.locator('article:has-text("SpeechLab"), section:has-text("SpeechLab")').getByRole('button').first(),
    page.locator('article:has-text("SpeechLab"), section:has-text("SpeechLab")').getByRole('link').first(),
    page.locator('article:has-text("SpeechLab")').getByText(/Перейти|Открыть|Запустить|Начать/i).first(),
  ], 'cta-SpeechLab');
  await wait(1500);
  await shot(page, 'h2r-cta-speechlab');

  // CTA Dictionary card
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  const dictClicked = await clickFirst(page, [
    page.locator('article:has-text("Словар"), section:has-text("Словар")').getByRole('button').first(),
    page.locator('article:has-text("Словар"), section:has-text("Словар")').getByRole('link').first(),
    page.locator('article:has-text("Словар")').getByText(/Перейти|Открыть|Запустить|Начать/i).first(),
  ], 'cta-Dictionary');
  await wait(1500);
  await shot(page, 'h2r-cta-dictionary');

  // CTA History card
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  const histClicked = await clickFirst(page, [
    page.locator('article:has-text("История"), section:has-text("История")').getByRole('button').first(),
    page.locator('article:has-text("История"), section:has-text("История")').getByRole('link').first(),
    page.locator('article:has-text("История")').getByText(/Перейти|Открыть|Запустить|Начать/i).first(),
  ], 'cta-History');
  await wait(1500);
  await shot(page, 'h2r-cta-history');

  // ============== H2.4-recheck: Speaker labels ==============
  await page.goto(APP + '/results?session=test-session-0001', { waitUntil: 'domcontentloaded' });
  await wait(1800);
  await shot(page, 'h2r-results-init');
  await clickFirst(page, [
    page.getByRole('tab', { name: 'Выделенный текст' }),
    page.locator('[role=tab]:has-text("Выделенный")'),
    page.getByText('Выделенный текст').first(),
  ], 'tab-Выделенный');
  await wait(1500);
  await clickFirst(page, [
    page.locator('[class*=match], [class*=Match], [data-match]').first(),
    page.getByText('Сотрудник', { exact: false }).first(),
    page.getByText('Клиент', { exact: false }).first(),
  ], 'utterance');
  await wait(1000);
  await shot(page, 'h2r-speaker-labels');

  const cssVars = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return {
      operator: root.getPropertyValue('--dict-channel-operator').trim(),
      client: root.getPropertyValue('--dict-channel-client').trim(),
      any: root.getPropertyValue('--dict-channel-any').trim(),
    };
  });
  console.log('CSS_VARS', JSON.stringify(cssVars));
  fs.writeFileSync(path.join(OUT_DIR, 'h2r-speaker-css-vars.json'), JSON.stringify(cssVars, null, 2));

  // ============== Console errors dump ==============
  fs.writeFileSync(path.join(OUT_DIR, 'h2r-console-errors.json'),
    JSON.stringify({
      errors_count: consoleErrors.length,
      warns_count: consoleWarns.length,
      errors: consoleErrors,
      warns: consoleWarns.slice(0, 30),
      all_recent: consoleAll.slice(-50),
    }, null, 2));
  console.log('CONSOLE_ERRORS', consoleErrors.length);
  console.log('CONSOLE_WARNS', consoleWarns.length);

  // Check specifically for the ref error
  const refError = consoleErrors.find(e => /Function components cannot be given refs/i.test(e));
  console.log('REF_ERROR_FOUND', !!refError);
  if (refError) console.log('REF_ERROR:', refError);

  await page.close();
  await browser.close();
  console.log('DONE');
}

main().catch(e => { console.error('ERR', e); process.exit(1); });
