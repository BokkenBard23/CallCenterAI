// Quick verification screenshots for bug fixes
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };

async function shot(page, name) {
  const file = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  console.log(`SHOT ${name} -> size=${fs.statSync(file).size}`);
  return file;
}
async function wait(ms) { await new Promise(r => setTimeout(r, ms)); }

async function clickFirst(page, candidates) {
  for (const sel of candidates) {
    try {
      const loc = typeof sel === 'string' ? page.locator(sel).first() : sel;
      await loc.click({ timeout: 3000 });
      return true;
    } catch (e) { /* try next */ }
  }
  return false;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEWPORT });
  const page = await ctx.newPage();

  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('PAGEERROR: ' + e.message));

  // ---- BUG 1: NavBar tab navigation ----
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await shot(page, 'bugfix-navbar-home');

  // Click "Результаты" tab (now has role="tab")
  const resultsClicked = await clickFirst(page, [
    page.getByRole('tab', { name: 'Результаты' }),
    page.locator('[role=tab]:has-text("Результаты")'),
    page.locator('button:has-text("Результаты")'),
  ]);
  console.log('Results tab clicked:', resultsClicked);
  await wait(2000);
  const url1 = page.url();
  console.log('URL after Results click:', url1);
  await shot(page, 'bugfix-navbar-results');

  // Click "SpeechLab" tab
  const speechClicked = await clickFirst(page, [
    page.getByRole('tab', { name: 'SpeechLab' }),
    page.locator('[role=tab]:has-text("SpeechLab")'),
    page.locator('button:has-text("SpeechLab")'),
  ]);
  console.log('SpeechLab tab clicked:', speechClicked);
  await wait(2000);
  const url2 = page.url();
  console.log('URL after SpeechLab click:', url2);
  await shot(page, 'bugfix-navbar-speechlab');

  // Click "Словари" tab
  const dictClicked = await clickFirst(page, [
    page.getByRole('tab', { name: 'Словари' }),
    page.locator('[role=tab]:has-text("Словари")'),
    page.locator('button:has-text("Словари")'),
  ]);
  console.log('Dictionary tab clicked:', dictClicked);
  await wait(2000);
  const url3 = page.url();
  console.log('URL after Dictionary click:', url3);
  await shot(page, 'bugfix-navbar-dictionary');

  // Click "История" tab
  const histClicked = await clickFirst(page, [
    page.getByRole('tab', { name: 'История' }),
    page.locator('[role=tab]:has-text("История")'),
    page.locator('button:has-text("История")'),
  ]);
  console.log('History tab clicked:', histClicked);
  await wait(2000);
  const url4 = page.url();
  console.log('URL after History click:', url4);
  await shot(page, 'bugfix-navbar-history');

  // ---- BUG 2: Breadcrumbs on sub-pages (direct URL) ----
  await page.goto(APP + '/results', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await shot(page, 'bugfix-breadcrumbs-results');

  await page.goto(APP + '/speechlab', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await shot(page, 'bugfix-breadcrumbs-speechlab');

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await shot(page, 'bugfix-breadcrumbs-history');

  await page.goto(APP + '/dictionary', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await shot(page, 'bugfix-dictionary-landing');

  // ---- BUG 5: Dashboard CTA ----
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(2000);
  // Click SpeechLab card CTA (RouterLink)
  const ctaClicked = await clickFirst(page, [
    page.locator('a:has-text("Открыть")').first(),
    page.getByText('Открыть').first(),
  ]);
  console.log('SpeechLab CTA clicked:', ctaClicked);
  await wait(2000);
  const url5 = page.url();
  console.log('URL after CTA click:', url5);
  await shot(page, 'bugfix-dashboard-cta');

  console.log('CONSOLE_ERRORS:', consoleErrors.length);
  consoleErrors.forEach(e => console.log('  ERR:', e.substring(0, 200)));

  await page.close();
  await browser.close();
  console.log('DONE');
}

main().catch(e => { console.error('ERR', e); process.exit(1); });
