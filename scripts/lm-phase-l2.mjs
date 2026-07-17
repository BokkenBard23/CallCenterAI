// PHASE L (refined): ResultsPage audit — research only.
// Session already restored; vectorization already done.
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
    const entry = `[${m.type()}] ${m.text()}`;
    consoleAll.push(entry);
    if (m.type() === 'error') consoleErrors.push(entry);
  });
  page.on('pageerror', e => consoleErrors.push(`PAGEERROR: ${e.message}`));
  page.on('response', r => { if (r.url().includes('/api/')) requests.push(`${r.status()} ${r.url().split('/').slice(3).join('/')}`); });
  return page;
}

async function shot(page, name, opts = {}) {
  const file = path.join(OUT_DIR, `${name}.png`);
  try { await page.screenshot({ path: file, fullPage: !!opts.fullPage }); console.log(`SHOT ${name} size=${fs.statSync(file).size}`); return file; }
  catch (e) { console.log(`SHOT-FAIL ${name}: ${e.message}`); return null; }
}
async function wait(ms) { await new Promise(r => setTimeout(r, ms)); }
async function clickFirst(page, candidates, label = '') {
  for (const sel of candidates) {
    try {
      const loc = typeof sel === 'string' ? page.locator(sel).first() : sel;
      await loc.click({ timeout: 3500 });
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
  const page = await newPage(ctx);

  // Restore session via /history (fresh page, no context state)
  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await wait(2500);
  await page.locator('text=sample-dialog').first().click({ timeout: 5000 });
  for (let i = 0; i < 25; i++) {
    await wait(1000);
    if (page.url().includes('/results')) break;
  }
  await wait(3000);
  console.log('URL:', page.url());

  // Initial screenshot
  await shot(page, 'l-results-default');

  // ============== L.7 ViewMode Summary (already default) ==============
  await wait(1500);
  await shot(page, 'l-viewmode-summary');

  // ============== L.7 ViewMode Highlighted ==============
  await clickFirst(page, [
    page.locator('[role=tab]:has-text("Выделенный текст")'),
    page.locator('button.dsb_tab-new:has-text("Выделенный текст")'),
    page.getByText('Выделенный текст', { exact: false }).first(),
  ], 'tab-highlighted');
  await wait(2500);
  await shot(page, 'l-viewmode-highlighted');

  // ============== L.6 Highlight levels (highlighted view) ==============
  await shot(page, 'l-highlight-levels');

  // Capture match_type info (text of marks)
  const marksInfo = await page.evaluate(() => {
    const marks = Array.from(document.querySelectorAll('mark'));
    return {
      count: marks.length,
      sample: marks.slice(0, 5).map(m => ({
        cls: (m.className || '').substring(0, 120),
        text: (m.innerText || '').substring(0, 80),
        dataset: { ...m.dataset },
      })),
      // Check colors
      styles: marks.slice(0, 5).map(m => {
        const cs = getComputedStyle(m);
        return { bg: cs.backgroundColor, color: cs.color };
      }),
    };
  });
  fs.writeFileSync(path.join(OUT_DIR, 'l-marks-info.json'), JSON.stringify(marksInfo, null, 2));
  console.log('MARKS count:', marksInfo.count);
  if (marksInfo.sample.length) console.log('  sample[0]:', JSON.stringify(marksInfo.sample[0]));
  if (marksInfo.styles.length) console.log('  style[0]:', JSON.stringify(marksInfo.styles[0]));

  // ============== L.3 PhrasePopover ==============
  const markClicked = await clickFirst(page, [
    page.locator('mark').first(),
  ], 'mark-phrase');
  await wait(1800);
  await shot(page, 'l-phrase-popover');

  // Inspect popover content
  const popoverInfo = await page.evaluate(() => {
    const p = document.querySelector('[role="dialog"], [class*="opover"]');
    return p ? {
      text: (p.innerText || '').substring(0, 400),
      hasTextarea: !!p.querySelector('textarea'),
      hasCloseBtn: !!p.querySelector('button[aria-label="Close"], button[aria-label="Закрыть"]'),
      btns: Array.from(p.querySelectorAll('button')).map(b => ({ text: (b.innerText || '').substring(0, 30), ariaLabel: b.getAttribute('aria-label') })),
    } : null;
  });
  console.log('POPOVER:', JSON.stringify(popoverInfo, null, 2));
  fs.writeFileSync(path.join(OUT_DIR, 'l-popover-info.json'), JSON.stringify(popoverInfo, null, 2));

  // L.5 Feedback form INSIDE popover
  if (popoverInfo?.hasTextarea) {
    try {
      const ta = page.locator('[role="dialog"] textarea, [class*="opover"] textarea').first();
      await ta.fill('Test feedback audit L5', { timeout: 3000 });
      await wait(500);
      await shot(page, 'l-feedback-filled');

      // Find submit button
      await clickFirst(page, [
        page.locator('[role="dialog"] button:has-text("Отправить"), [class*="opover"] button:has-text("Отправить")').first(),
        page.locator('[role="dialog"] button[type="submit"], [class*="opover"] button[type="submit"]').first(),
      ], 'btn-feedback-send');
      await wait(2500);
      await shot(page, 'l-feedback-sent');
    } catch (e) { console.log('feedback-fill fail:', e.message); }
  }

  // Close popover via close button
  await clickFirst(page, [
    page.locator('[role="dialog"] button[aria-label="Close"], [role="dialog"] button[aria-label="Закрыть"]').first(),
    page.locator('[class*="opover"] button').first(),
  ], 'popover-close-btn');
  await wait(800);
  await shot(page, 'l-popover-close-btn');

  // Open again, close via outside click
  await clickFirst(page, [ page.locator('mark').first() ], 'mark-phrase-2');
  await wait(1500);
  await page.mouse.click(20, 200);
  await wait(800);
  await shot(page, 'l-popover-close-outside');

  // Open again, close via Escape
  await clickFirst(page, [ page.locator('mark').first() ], 'mark-phrase-3');
  await wait(1500);
  await page.keyboard.press('Escape');
  await wait(800);
  await shot(page, 'l-popover-close-esc');

  // ============== L.1 QualityScorePanel ==============
  await clickFirst(page, [
    page.locator('button:has-text("Оценка качества")'),
    page.locator('text=Оценка качества'),
  ], 'btn-quality-score-expand');
  await wait(2500); // animation
  await shot(page, 'l-quality-score-initial');
  await wait(2000);
  await shot(page, 'l-quality-score');

  // ============== L.2 SemanticSearchPanel ==============
  // Click semantic search IconButton (text="search" only, plain variant, small)
  await clickFirst(page, [
    page.locator('button.dsb_button__plain.dsb_button__s:has-text("search")').first(),
    page.locator('button[aria-label="Семантический поиск"]'),
    page.locator('button[aria-pressed]').filter({ hasText: /^search$/ }),
  ], 'btn-semantic-toggle');
  await wait(2500);
  await shot(page, 'l-semantic-initial');

  // Type query
  try {
    const q = page.locator('input[type="search"], input[placeholder*="поиск" i], input[placeholder*="запрос" i], textarea[placeholder*="поиск" i]').first();
    await q.waitFor({ state: 'visible', timeout: 4000 });
    await q.fill('тариф');
    await wait(500);
    await shot(page, 'l-semantic-query');
  } catch (e) { console.log('QUERY-INPUT fail:', e.message); }

  // Search button
  await clickFirst(page, [
    page.locator('button:has-text("Поиск"), button:has-text("Найти"), button:has-text("Искать")').first(),
    page.getByRole('button', { name: /Найти|Поиск|Search|Искать/i }).first(),
  ], 'btn-search');
  await wait(5000); // semantic search slow
  await shot(page, 'l-semantic-results');

  // Hybrid toggle (optional)
  await clickFirst(page, [
    page.locator('label:has-text("Гибрид"), [class*="witch"]:has-text("ибрид")').first(),
    page.locator('text=Гибридный').first(),
    page.locator('[role=switch]').first(),
  ], 'toggle-hybrid');
  await wait(2500);
  await shot(page, 'l-semantic-hybrid');

  // Close semantic panel
  await clickFirst(page, [
    page.locator('[class*="emantic"] button[aria-label="Закрыть"], [class*="emantic"] button[aria-label="Close"]').first(),
    page.locator('[class*="emantic"] button.dsb_button__plain').first(),
  ], 'close-semantic');
  await wait(1200);

  // ============== L.4 Export ==============
  await clickFirst(page, [
    page.locator('button:has-text("Excel")'),
  ], 'btn-export-excel');
  await wait(4000);
  await shot(page, 'l-export-excel');

  await clickFirst(page, [
    page.locator('button:has-text("PDF")'),
  ], 'btn-export-pdf');
  await wait(4000);
  await shot(page, 'l-export-pdf');

  // ============== L.8 Scroll down ==============
  await page.evaluate(() => {
    const c = document.querySelector('[class*="esultsPage"], main, [class*="ontent"]') || document.documentElement;
    c.scrollTop = c.scrollHeight;
    window.scrollTo(0, document.body.scrollHeight);
  });
  await wait(1500);
  await shot(page, 'l-scrolled-down');

  await shot(page, 'l-results-fullpage', { fullPage: true });

  fs.writeFileSync(path.join(OUT_DIR, 'l-console-errors.json'), JSON.stringify({ errors: consoleErrors, allCount: consoleAll.length, requests }, null, 2));
  console.log('PHASE L DONE. Errors:', consoleErrors.length, 'Requests:', requests.length);
  consoleErrors.slice(0, 20).forEach(e => console.log('  ERR:', e));
  requests.slice(0, 20).forEach(r => console.log('  REQ:', r));

  await page.close();
  process.exit(0);
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
