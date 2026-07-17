// PHASE M: SpeechLabPage audit — research only.
// 1. Restore session via /history (test-session-0002)
// 2. Navigate to /speechlab
// 3. Upload dictionary XML
// 4. Capture all M.* screenshots
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };
const XML_PATH = path.resolve('data/output/production_xml/sample_dictionary.xml');

const consoleErrors = [];
const requests = [];

async function main() {
  if (!fs.existsSync(XML_PATH)) {
    console.log('XML file not found:', XML_PATH);
    process.exit(1);
  }

  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(`[${m.type()}] ${m.text()}`); });
  page.on('pageerror', e => consoleErrors.push(`PAGEERR: ${e.message}`));
  page.on('response', r => { if (r.url().includes('/api/')) requests.push(`${r.status()} ${r.url().split('/').slice(3).join('/')}`); });

  // ============== Restore session via /history ==============
  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2500));
  await page.locator('text=sample-dialog').first().click({ timeout: 5000 });
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    if (page.url().includes('/results')) break;
  }
  await new Promise(r => setTimeout(r, 3000));
  console.log('Restored. URL:', page.url());

  // Navigate to /speechlab
  await page.goto(APP + '/speechlab', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 3000));
  console.log('SpeechLab URL:', page.url());

  // ============== M.1 Initial state ==============
  await page.screenshot({ path: `${OUT_DIR}/m-speechlab-initial.png` });

  // Inspect initial state
  const initState = await page.evaluate(() => {
    return {
      url: location.href,
      hasLeftPanel: !!document.querySelector('[class*="left-panel"], .speechlab-layout__panel--left'),
      hasRightPanel: !!document.querySelector('.speechlab-layout__panel--right'),
      hasSeparator: !!document.querySelector('[data-separator]'),
      tabs: Array.from(document.querySelectorAll('button.dsb_tab-new')).map(t => ({
        text: (t.innerText || '').substring(0, 50),
        sel: t.classList.contains('dsb_tab-new--selected'),
      })),
      buttons: Array.from(document.querySelectorAll('button')).slice(0, 20).map(b => ({
        text: (b.innerText || '').substring(0, 40),
        ariaLabel: b.getAttribute('aria-label'),
      })),
      h1: Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.innerText?.substring(0, 80)),
      body: document.body.innerText.substring(0, 600),
    };
  });
  fs.writeFileSync(`${OUT_DIR}/m-init-state.json`, JSON.stringify(initState, null, 2));
  console.log('INIT:', JSON.stringify(initState, null, 2));

  // ============== M.2 LeftPanel ==============
  await page.screenshot({ path: `${OUT_DIR}/m-left-panel.png` });

  // ============== M.7 SpeechLabRtfDialog — open ==============
  // Find button to open RTF dialog
  const rtfDialogBtnFound = await clickFirst(page, [
    page.locator('button:has-text("RTF"), button:has-text("Загрузить RTF"), button:has-text("диалог")'),
    page.locator('[aria-label*="RTF" i]'),
  ], 'btn-rtf-dialog');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-dialog.png` });

  // Close via button
  await clickFirst(page, [
    page.locator('[role="dialog"] button:has-text("Закрыть"), [role="dialog"] button:has-text("Отмена")'),
    page.locator('[role="dialog"] button[aria-label="Close"], [role="dialog"] button[aria-label="Закрыть"]'),
  ], 'rtf-close-btn');
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-close-btn.png` });

  // Open again, close via backdrop
  await clickFirst(page, [
    page.locator('button:has-text("RTF"), button:has-text("Загрузить RTF"), button:has-text("диалог")'),
    page.locator('[aria-label*="RTF" i]'),
  ], 'btn-rtf-dialog-2');
  await new Promise(r => setTimeout(r, 1500));
  await page.mouse.click(20, 20); // click top-left backdrop
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-close-backdrop.png` });

  // Open again, close via Escape
  await clickFirst(page, [
    page.locator('button:has-text("RTF"), button:has-text("Загрузить RTF"), button:has-text("диалог")'),
    page.locator('[aria-label*="RTF" i]'),
  ], 'btn-rtf-dialog-3');
  await new Promise(r => setTimeout(r, 1500));
  await page.keyboard.press('Escape');
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-close-esc.png` });

  // ============== M.8 SpeechLabTopBar ==============
  await page.screenshot({ path: `${OUT_DIR}/m-topbar.png` });

  // ============== Upload dictionary XML ==============
  // Click "Импорт XML" button to open dialog
  const importClicked = await clickFirst(page, [
    page.locator('button:has-text("Импорт XML")'),
    page.locator('text=Импорт XML'),
  ], 'btn-import-xml');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-import-dialog.png` });

  // Upload XML file via DropZone — use filechooser
  try {
    // Trigger file chooser via clicking DropZone
    const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
    await page.locator('input[type="file"], [class*="ropzone"]').first().click({ timeout: 3000 });
    const fc = await fileChooserPromise;
    await fc.setFiles(XML_PATH);
    await new Promise(r => setTimeout(r, 3000));
    console.log('XML uploaded');
    await page.screenshot({ path: `${OUT_DIR}/m-after-xml-upload.png` });
  } catch (e) { console.log('XML upload via DropZone fail:', e.message.split('\n')[0]); }

  // Wait for tree to load (dictionary endpoint may be slow)
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const treeCount = await page.evaluate(() => document.querySelectorAll('[class*="tree-node"], [class*="reeNode"], [role="treeitem"]').length);
    console.log(`tree wait ${i*2}s: ${treeCount} nodes`);
    if (treeCount > 0) break;
  }

  // ============== M.2 LeftPanel with tree ==============
  await page.screenshot({ path: `${OUT_DIR}/m-left-panel.png` });

  // ============== M.2 Tree expanded ==============
  // Click first expandable node
  await clickFirst(page, [
    page.locator('[class*="tree"] button:has-text("expand"), [class*="tree"] [aria-expanded="false"]').first(),
    page.locator('[role="treeitem"] [aria-expanded="false"]').first(),
    page.locator('[class*="reeNode"] button, [class*="reeNode"] [class*="expand"]').first(),
  ], 'tree-expand');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-tree-expanded.png` });

  // Expand more nodes
  for (let i = 0; i < 3; i++) {
    await clickFirst(page, [
      page.locator('[role="treeitem"] [aria-expanded="false"]').nth(i),
      page.locator('[class*="reeNode"] [aria-expanded="false"]').nth(i),
    ], `tree-expand-${i}`);
    await new Promise(r => setTimeout(r, 800));
  }
  await page.screenshot({ path: `${OUT_DIR}/m-tree-expanded-more.png` });

  // ============== M.2 Tree collapsed ==============
  await clickFirst(page, [
    page.locator('[role="treeitem"] [aria-expanded="true"]').first(),
    page.locator('[class*="reeNode"] [aria-expanded="true"]').first(),
  ], 'tree-collapse');
  await new Promise(r => setTimeout(r, 800));
  await page.screenshot({ path: `${OUT_DIR}/m-tree-collapsed.png` });

  // ============== M.3 FoundRecordsTab ==============
  await clickFirst(page, [
    page.locator('button.dsb_tab-new:has-text("Найденные записи")'),
    page.locator('text=Найденные записи'),
  ], 'tab-found-records');
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: `${OUT_DIR}/m-found-records.png` });

  // Click first record
  await clickFirst(page, [
    page.locator('[class*="ecordCard"], [class*="ound-records"] [class*="card"]').first(),
    page.locator('[class*="ound-records"] [class*="item"]').first(),
  ], 'found-record-click');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-found-record-click.png` });

  // ============== M.4 QueryTab ==============
  await clickFirst(page, [
    page.locator('button.dsb_tab-new:has-text("Запрос")'),
    page.locator('text=Запрос').first(),
  ], 'tab-query');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-query-tab.png` });

  // Find query input
  const qInput = page.locator('input[type="search"], input[placeholder*="поиск" i], input[placeholder*="запрос" i], textarea[placeholder*="поиск" i]').first();
  try {
    await qInput.waitFor({ state: 'visible', timeout: 4000 });
    await qInput.fill('сотрудник');
    await new Promise(r => setTimeout(r, 500));
    await page.screenshot({ path: `${OUT_DIR}/m-query-input.png` });

    // Click search button
    await clickFirst(page, [
      page.locator('button:has-text("Поиск"), button:has-text("Найти"), button:has-text("Искать")').first(),
      page.getByRole('button', { name: /Найти|Поиск|Search|Искать/i }).first(),
    ], 'btn-search-query');
    await new Promise(r => setTimeout(r, 4000));
    await page.screenshot({ path: `${OUT_DIR}/m-query-results.png` });
  } catch (e) { console.log('query input fail:', e.message.split('\n')[0]); }

  // ============== M.5 KeywordsDisplay + TokenBadge ==============
  // Switch to QueryTab and click on a tree node to display tokens
  await clickFirst(page, [
    page.locator('button.dsb_tab-new:has-text("Запрос")'),
  ], 'tab-query-2');
  await new Promise(r => setTimeout(r, 1000));
  // Click first tree leaf node to show its keywords
  await clickFirst(page, [
    page.locator('[role="treeitem"]:not(:has([aria-expanded]))').first(),
    page.locator('[class*="reeNode"]:not(:has([aria-expanded]))').first(),
    page.locator('[role="treeitem"]').last(),
  ], 'tree-leaf');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-keywords.png` });

  // ============== M.6 Resize (decorative only) ==============
  // Drag the separator
  try {
    const sep = page.locator('[data-separator]').first();
    const box = await sep.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x - 80, box.y + box.height / 2, { steps: 10 });
      await page.mouse.up();
      await new Promise(r => setTimeout(r, 500));
    }
  } catch (e) { console.log('resize fail:', e.message.split('\n')[0]); }
  await page.screenshot({ path: `${OUT_DIR}/m-resize.png` });

  // ============== M.9 Scroll down ==============
  await page.evaluate(() => {
    const c = document.querySelector('[class*="peechLab"], main, [class*="ontent"]') || document.documentElement;
    c.scrollTop = c.scrollHeight;
    window.scrollTo(0, document.body.scrollHeight);
  });
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT_DIR}/m-scrolled-down.png` });

  // Full page
  await page.screenshot({ path: `${OUT_DIR}/m-speechlab-fullpage.png`, fullPage: true });

  fs.writeFileSync(`${OUT_DIR}/m-console-errors.json`, JSON.stringify({ errors: consoleErrors, requests }, null, 2));
  console.log('PHASE M DONE. Errors:', consoleErrors.length, 'Requests:', requests.length);
  consoleErrors.slice(0, 30).forEach(e => console.log('  ERR:', e));
  requests.slice(0, 30).forEach(r => console.log('  REQ:', r));

  await page.close();
  process.exit(0);
}

async function clickFirst(page, candidates, label = '') {
  for (const sel of candidates) {
    try {
      const loc = typeof sel === 'string' ? page.locator(sel).first() : sel;
      await loc.click({ timeout: 3500 });
      console.log(`CLICK[${label}] ok`);
      await new Promise(r => setTimeout(r, 400));
      return true;
    } catch (e) { /* try next */ }
  }
  console.log(`CLICK[${label}] FAILED`);
  return false;
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
