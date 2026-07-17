// PHASE M (refined v3): SpeechLabPage audit — research only.
// Proper flow: Import Dialog → select file → click "Загрузить" to upload to backend (auto-close)
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
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(`[${m.type()}] ${m.text().substring(0, 250)}`); });
  page.on('pageerror', e => consoleErrors.push(`PAGEERR: ${e.message}`));
  page.on('response', r => { if (r.url().includes('/api/')) requests.push(`${r.status()} ${r.url().split('/').slice(3).join('/')}`); });

  // Restore session
  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2500));
  await page.locator('text=sample-dialog').first().click({ timeout: 5000 });
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    if (page.url().includes('/results')) break;
  }
  await new Promise(r => setTimeout(r, 3000));

  // Navigate to /speechlab
  await page.goto(APP + '/speechlab', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 3000));
  console.log('SpeechLab URL:', page.url());

  // ============== M.1 Initial state ==============
  await page.screenshot({ path: `${OUT_DIR}/m-speechlab-initial.png` });

  // ============== M.7 RTF Dialog (3 close methods) ==============
  // Open via "Загрузить диалог" button (TopBar)
  await page.locator('button:has-text("Загрузить диалог")').first().click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-dialog.png` });
  console.log('RTF dialog open');

  // Close via "Отмена" button (the proper Cancel/Close button per DS Dialog pattern)
  await page.locator('[role="dialog"] button:has-text("Отмена")').first().click({ timeout: 4000 });
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-close-btn.png` });
  const closed1 = await page.evaluate(() => !document.querySelector('[role="dialog"]'));
  console.log('closed via Отмена button:', closed1);

  // Open again
  await page.locator('button:has-text("Загрузить диалог")').first().click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-dialog-2.png` });

  // Try closing via backdrop click (click on dimmed area outside dialog)
  // Get dialog bounding rect
  const dlgBox = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"]');
    if (!d) return null;
    const r = d.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  console.log('dialog box:', dlgBox);
  if (dlgBox) {
    // Click at corner far from dialog
    await page.mouse.click(5, 5);
    await new Promise(r => setTimeout(r, 1500));
  }
  await page.screenshot({ path: `${OUT_DIR}/m-rtf-close-backdrop.png` });
  const closed2 = await page.evaluate(() => !document.querySelector('[role="dialog"]'));
  console.log('closed via backdrop click:', closed2);

  // If still open, close via Escape
  if (!closed2) {
    await page.keyboard.press('Escape');
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m-rtf-close-esc.png` });
    console.log('closed via Escape (after backdrop failed)');
  } else {
    // Open dialog again and close via Escape to capture that screenshot too
    await page.locator('button:has-text("Загрузить диалог")').first().click({ timeout: 5000 });
    await new Promise(r => setTimeout(r, 1500));
    await page.keyboard.press('Escape');
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m-rtf-close-esc.png` });
  }

  // ============== M.8 TopBar ==============
  await page.screenshot({ path: `${OUT_DIR}/m-topbar.png` });

  // ============== Upload dictionary XML ==============
  await page.locator('button:has-text("Импорт XML")').first().click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-import-dialog.png` });

  // Select XML file
  const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
  await page.locator('input[type="file"]').first().click({ timeout: 3000 });
  const fc = await fileChooserPromise;
  await fc.setFiles(XML_PATH);
  console.log('XML file selected');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-import-after-select.png` });

  // Check if "Загрузить" button is now enabled
  const uploadBtnState = await page.evaluate(() => {
    const dlg = document.querySelector('[role="dialog"]');
    if (!dlg) return null;
    const btns = Array.from(dlg.querySelectorAll('button'));
    return btns.map(b => ({ text: b.innerText?.substring(0, 30), disabled: b.disabled }));
  });
  console.log('Upload dialog buttons state:', JSON.stringify(uploadBtnState));

  // Click "Загрузить" to upload to backend (this triggers onDictionaryUploaded and auto-closes)
  try {
    await page.locator('[role="dialog"] button:has-text("Загрузить")').first().click({ timeout: 5000 });
    // Wait for upload (may take time)
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const stillUploading = await page.evaluate(() => {
        const dlg = document.querySelector('[role="dialog"]');
        return !!dlg;
      });
      const treeCount = await page.evaluate(() => document.querySelectorAll('[role="treeitem"], [class*="reeNode"]').length);
      console.log(`upload wait ${i*2}s: dialog=${stillUploading}, tree=${treeCount}`);
      if (!stillUploading) break;
    }
  } catch (e) { console.log('upload click fail:', e.message.split('\n')[0]); }

  await page.screenshot({ path: `${OUT_DIR}/m-after-xml-upload.png` });

  // ============== M.2 LeftPanel with tree (now persistent) ==============
  await page.screenshot({ path: `${OUT_DIR}/m-left-panel.png` });

  // Inspect tree DOM
  const treeInfo = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('[role="treeitem"]'));
    return {
      count: items.length,
      sample: items.slice(0, 8).map(i => ({
        text: (i.innerText || '').substring(0, 80).replace(/\n/g, ' / '),
        ariaExpanded: i.getAttribute('aria-expanded'),
        ariaSelected: i.getAttribute('aria-selected'),
        cls: (i.className || '').substring(0, 60),
      })),
    };
  });
  fs.writeFileSync(`${OUT_DIR}/m-tree-info.json`, JSON.stringify(treeInfo, null, 2));
  console.log('TREE:', JSON.stringify(treeInfo, null, 2));

  // ============== M.2 Tree expanded ==============
  await clickFirstExpandable(page);
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-tree-expanded.png` });

  // Expand more
  for (let i = 0; i < 5; i++) {
    const found = await clickFirstExpandable(page);
    if (!found) break;
    await new Promise(r => setTimeout(r, 700));
  }
  await page.screenshot({ path: `${OUT_DIR}/m-tree-expanded-more.png` });

  // ============== M.2 Tree collapsed ==============
  await clickFirstCollapsible(page);
  await new Promise(r => setTimeout(r, 800));
  await page.screenshot({ path: `${OUT_DIR}/m-tree-collapsed.png` });

  // ============== M.5 KeywordsDisplay — click a tree leaf ==============
  await clickFirstLeaf(page);
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-keywords.png` });

  // Inspect keywords
  const kwInfo = await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll('button.dsb_tab-new')).map(t => ({
      text: (t.innerText || '').replace(/\n/g, ' / ').substring(0, 60),
      sel: t.classList.contains('dsb_tab-new--selected'),
    }));
    const right = document.querySelector('.speechlab-layout__panel--right');
    return {
      tabs,
      rightText: (right?.innerText || '').substring(0, 600),
    };
  });
  fs.writeFileSync(`${OUT_DIR}/m-keywords-info.json`, JSON.stringify(kwInfo, null, 2));
  console.log('KEYWORDS:', JSON.stringify(kwInfo, null, 2));

  // ============== M.4 QueryTab (default) ==============
  await page.screenshot({ path: `${OUT_DIR}/m-query-tab.png` });

  // Try to find query input
  try {
    const qInput = page.locator('input[type="search"], input[placeholder*="поиск" i], input[placeholder*="запрос" i], textarea[placeholder*="поиск" i]').first();
    await qInput.waitFor({ state: 'visible', timeout: 4000 });
    await qInput.fill('сотрудник');
    await new Promise(r => setTimeout(r, 500));
    await page.screenshot({ path: `${OUT_DIR}/m-query-input.png` });
    await clickFirst(page, [
      page.locator('button:has-text("Поиск"), button:has-text("Найти"), button:has-text("Искать")').first(),
    ], 'btn-search-query');
    await new Promise(r => setTimeout(r, 4000));
    await page.screenshot({ path: `${OUT_DIR}/m-query-results.png` });
  } catch (e) { console.log('query input fail:', e.message.split('\n')[0]); }

  // ============== M.3 FoundRecordsTab ==============
  await clickFirst(page, [
    page.locator('button.dsb_tab-new:has-text("Найденные записи")'),
    page.locator('text=Найденные записи').first(),
  ], 'tab-found-records');
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: `${OUT_DIR}/m-found-records.png` });

  // Click first record
  await clickFirst(page, [
    page.locator('[class*="ecordCard"], [class*="ound-records"] [class*="card"], [class*="ound-records"] [role="button"]').first(),
    page.locator('[class*="ound-records"] [class*="item"]').first(),
  ], 'found-record-click');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m-found-record-click.png` });

  // ============== M.6 Resize (decorative) ==============
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

  await page.screenshot({ path: `${OUT_DIR}/m-speechlab-fullpage.png`, fullPage: true });

  fs.writeFileSync(`${OUT_DIR}/m-console-errors.json`, JSON.stringify({ errors: consoleErrors, requests }, null, 2));
  console.log('PHASE M3 DONE. Errors:', consoleErrors.length, 'Requests:', requests.length);
  consoleErrors.slice(0, 10).forEach(e => console.log('  ERR:', e));
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

async function clickFirstExpandable(page) {
  const candidates = [
    page.locator('[role="treeitem"] [aria-expanded="false"]').first(),
    page.locator('[role="treeitem"][aria-expanded="false"]').first(),
    page.locator('[class*="reeNode"] [aria-expanded="false"]').first(),
  ];
  for (const sel of candidates) {
    try { await sel.click({ timeout: 2500 }); console.log('EXPAND ok'); await new Promise(r => setTimeout(r, 400)); return true; }
    catch (e) { /* try next */ }
  }
  console.log('EXPAND FAILED'); return false;
}

async function clickFirstCollapsible(page) {
  const candidates = [
    page.locator('[role="treeitem"] [aria-expanded="true"]').first(),
    page.locator('[role="treeitem"][aria-expanded="true"]').first(),
    page.locator('[class*="reeNode"] [aria-expanded="true"]').first(),
  ];
  for (const sel of candidates) {
    try { await sel.click({ timeout: 2500 }); console.log('COLLAPSE ok'); await new Promise(r => setTimeout(r, 400)); return true; }
    catch (e) { /* try next */ }
  }
  console.log('COLLAPSE FAILED'); return false;
}

async function clickFirstLeaf(page) {
  const candidates = [
    page.locator('[role="treeitem"]:not([aria-expanded])').last(),
    page.locator('[role="treeitem"]').last(),
  ];
  for (const sel of candidates) {
    try { await sel.click({ timeout: 2500 }); console.log('LEAF click ok'); await new Promise(r => setTimeout(r, 400)); return true; }
    catch (e) { /* try next */ }
  }
  console.log('LEAF click FAILED'); return false;
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
