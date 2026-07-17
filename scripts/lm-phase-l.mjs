// PHASE L: ResultsPage audit — research only, NO code changes.
// Uses localStorage history entry (analysisId=test-analysis-0001, session=test-session-0002).
// NOTE: Backend /api/analysis/results/{id} takes ~12s. Allow 25s for restore.
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };

const consoleErrors = [];
const consoleAll = [];
const requests = [];

async function newPage(ctx) {
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);
  page.on('console', m => {
    const entry = `${page.url().split('/').slice(3).join('/')} :: [${m.type()}] ${m.text()}`;
    consoleAll.push(entry);
    if (m.type() === 'error') consoleErrors.push(entry);
  });
  page.on('pageerror', e => consoleErrors.push(`${page.url()} :: PAGEERROR: ${e.message}`));
  page.on('response', r => { if (r.url().includes('/api/')) requests.push(`${r.status()} ${r.url().split('/').slice(3).join('/')}`); });
  return page;
}

async function shot(page, name, opts = {}) {
  const file = path.join(OUT_DIR, `${name}.png`);
  try {
    await page.screenshot({ path: file, fullPage: !!opts.fullPage });
    console.log(`SHOT ${name} size=${fs.statSync(file).size}`);
    return file;
  } catch (e) { console.log(`SHOT-FAIL ${name}: ${e.message}`); return null; }
}

async function wait(ms) { await new Promise(r => setTimeout(r, ms)); }

async function clickFirst(page, candidates, label = '') {
  for (const sel of candidates) {
    try {
      const loc = typeof sel === 'string' ? page.locator(sel).first() : sel;
      await loc.click({ timeout: 3000 });
      console.log(`CLICK[${label}] ok`);
      await wait(400);
      return true;
    } catch (e) { /* try next */ }
  }
  console.log(`CLICK[${label}] FAILED`);
  return false;
}

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  let page = await newPage(ctx);

  // ============== Restore session via /history ==============
  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await wait(2500);

  // Click filename (proven to work in v2 script — just need longer wait)
  const clicked = await clickFirst(page, [
    page.locator('text=sample-dialog.rtf').first(),
  ], 'history-entry');
  console.log('waiting up to 25s for navigation...');
  for (let i = 0; i < 25; i++) {
    await wait(1000);
    if (page.url().includes('/results')) { console.log(`navigated after ${i+1}s`); break; }
  }
  console.log('URL:', page.url());
  await wait(3000); // let ResultsPage settle

  if (!page.url().includes('/results')) {
    console.log('ABORT: not on /results, cannot continue L phase');
    await shot(page, 'l-ABORT-no-restore');
    fs.writeFileSync(path.join(OUT_DIR, 'l-console-errors.json'), JSON.stringify({ errors: consoleErrors, allCount: consoleAll.length, requests }, null, 2));
    await page.close(); process.exit(1);
  }

  // ============== Default state screenshot ==============
  await shot(page, 'l-results-default');

  // ============== L.7 ViewMode Summary (initial) ==============
  await clickFirst(page, [
    page.getByRole('tab', { name: /Сводка|сводка|summary/i }).first(),
    page.locator('[role=tab]:has-text("Сводка")').first(),
  ], 'tab-summary');
  await wait(1500);
  await shot(page, 'l-viewmode-summary');

  // ============== L.7 ViewMode Highlighted ==============
  await clickFirst(page, [
    page.getByRole('tab', { name: /Выделен|выделен|highlighted/i }).first(),
    page.locator('[role=tab]:has-text("Выделен")').first(),
  ], 'tab-highlighted');
  await wait(1800);
  await shot(page, 'l-viewmode-highlighted');

  // ============== L.6 Highlight levels (highlighted view) ==============
  await shot(page, 'l-highlight-levels');

  // ============== L.7 ViewMode Structure ==============
  await clickFirst(page, [
    page.getByRole('tab', { name: /Структура|структура|structure/i }).first(),
    page.locator('[role=tab]:has-text("Структура")').first(),
  ], 'tab-structure');
  await wait(1500);
  await shot(page, 'l-viewmode-structure');

  // ============== L.1 QualityScorePanel ==============
  // Try opening QualityScorePanel via button
  const qsClicked = await clickFirst(page, [
    page.getByRole('button', { name: /Оценка качества|качества|quality/i }).first(),
    page.locator('button:has-text("Оценка качества"), button:has-text("Качество")').first(),
    page.locator('text=Оценка качества').first(),
    page.locator('[class*="uality"]').first(),
  ], 'btn-quality-score');
  await wait(3000); // animation
  await shot(page, 'l-quality-score-initial');
  await wait(2500); // more animation
  await shot(page, 'l-quality-score');

  // ============== L.2 SemanticSearchPanel ==============
  // Try "Векторизовать" button (mentioned in ResultsPage.tsx:293)
  const semClicked = await clickFirst(page, [
    page.getByRole('button', { name: /Векториз|Семант|semantic/i }).first(),
    page.locator('button:has-text("Векториз"), button:has-text("Векторизовать")').first(),
    page.locator('text=Семантический поиск').first(),
    page.locator('[class*="emantic"]').first(),
  ], 'btn-semantic');
  await wait(2500);
  await shot(page, 'l-semantic-initial');

  // Type query
  try {
    const queryInput = page.locator('input[placeholder*="поиск" i], input[placeholder*="запрос" i], input[type="search"], textarea[placeholder*="поиск" i]').first();
    await queryInput.fill('тариф', { timeout: 3000 });
    await wait(500);
    await shot(page, 'l-semantic-query');
  } catch (e) { console.log('QUERY-INPUT fail:', e.message); }

  // Search button
  await clickFirst(page, [
    page.getByRole('button', { name: /Найти|Поиск|Search|Искать/i }).first(),
    page.locator('button:has-text("Поиск"), button:has-text("Найти"), button:has-text("Искать")').first(),
  ], 'btn-search');
  await wait(4000);
  await shot(page, 'l-semantic-results');

  // Hybrid toggle (optional)
  await clickFirst(page, [
    page.locator('[role=switch], label:has-text("ибрид"), [class*="witch"]:has-text("ybrid")').first(),
    page.locator('text=Гибридный').first(),
    page.locator('label:has-text("Гибрид")').first(),
  ], 'toggle-hybrid');
  await wait(2000);
  await shot(page, 'l-semantic-hybrid');

  // Close semantic panel (Sidesheet)
  await clickFirst(page, [
    page.locator('[class*="idesheet"] button[aria-label="Close"], [class*="idesheet"] button[aria-label="Закрыть"]').first(),
    page.locator('[class*="idesheet"] button').first(),
    page.keyboard.press.bind(page.keyboard, 'Escape'), // last resort
  ], 'close-semantic');
  await wait(1200);

  // ============== L.3 PhrasePopover ==============
  // Switch back to highlighted view
  await clickFirst(page, [
    page.getByRole('tab', { name: /Выделен|выделен|highlighted/i }).first(),
    page.locator('[role=tab]:has-text("Выделен")').first(),
  ], 'tab-highlighted-2');
  await wait(1500);

  // Click on a highlighted phrase (mark element)
  await clickFirst(page, [
    page.locator('mark, [class*="highlight"], [class*="mark-phrase"]').first(),
  ], 'mark-phrase');
  await wait(1500);
  await shot(page, 'l-phrase-popover');

  // Close via close button
  await clickFirst(page, [
    page.locator('[class*="opover"] button[aria-label="Close"], [class*="opover"] button[aria-label="Закрыть"]').first(),
    page.locator('[class*="opover"] button').first(),
  ], 'popover-close-btn');
  await wait(800);
  await shot(page, 'l-popover-close-btn');

  // Open again, close via outside click
  await clickFirst(page, [ page.locator('mark, [class*="highlight"], [class*="mark-phrase"]').first() ], 'mark-phrase-2');
  await wait(1200);
  await page.mouse.click(20, 200);
  await wait(800);
  await shot(page, 'l-popover-close-outside');

  // Open again, close via Escape
  await clickFirst(page, [ page.locator('mark, [class*="highlight"], [class*="mark-phrase"]').first() ], 'mark-phrase-3');
  await wait(1200);
  await page.keyboard.press('Escape');
  await wait(800);
  await shot(page, 'l-popover-close-esc');

  // ============== L.4 Export ==============
  await clickFirst(page, [
    page.getByRole('button', { name: /^Excel$|^excel$/i }).first(),
    page.locator('button:has-text("Excel"), a:has-text("Excel")').first(),
  ], 'btn-export-excel');
  await wait(3000);
  await shot(page, 'l-export-excel');

  await clickFirst(page, [
    page.getByRole('button', { name: /^PDF$|^pdf$/i }).first(),
    page.locator('button:has-text("PDF"), a:has-text("PDF")').first(),
  ], 'btn-export-pdf');
  await wait(3000);
  await shot(page, 'l-export-pdf');

  // ============== L.5 Feedback ==============
  const feedbackFound = await clickFirst(page, [
    page.getByRole('button', { name: /Отзыв|Feedback|обратная связь/i }).first(),
    page.locator('button:has-text("Отзыв"), button:has-text("обратная связь"), [class*="eedback"]').first(),
  ], 'btn-feedback');
  await wait(1500);
  await shot(page, 'l-feedback-open');
  if (feedbackFound) {
    try {
      const ta = page.locator('textarea, input[type="text"]').first();
      await ta.fill('Test feedback');
      await wait(500);
      await shot(page, 'l-feedback-filled');
      await clickFirst(page, [
        page.getByRole('button', { name: /Отправить|Send|Сохранить/i }).first(),
        page.locator('button:has-text("Отправить"), button:has-text("Сохранить")').first(),
      ], 'btn-feedback-send');
      await wait(2000);
      await shot(page, 'l-feedback-sent');
    } catch (e) { console.log('FILL-feedback fail:', e.message); }
  } else {
    // Try via nav menu or another path
    console.log('FEEDBACK: not found via direct button');
  }

  // ============== L.8 Scroll down ==============
  await page.evaluate(() => {
    const c = document.querySelector('[class*="esultsPage"], main, [class*="ontent"]') || document.documentElement;
    c.scrollTop = c.scrollHeight;
    window.scrollTo(0, document.body.scrollHeight);
  });
  await wait(1000);
  await shot(page, 'l-scrolled-down');

  // Full page
  await shot(page, 'l-results-fullpage', { fullPage: true });

  fs.writeFileSync(path.join(OUT_DIR, 'l-console-errors.json'), JSON.stringify({ errors: consoleErrors, allCount: consoleAll.length, requests }, null, 2));
  console.log('PHASE L DONE. Errors:', consoleErrors.length, 'Requests:', requests.length);

  await page.close();
  process.exit(0);
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
