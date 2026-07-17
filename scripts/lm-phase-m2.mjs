// PHASE M (refined): SpeechLabPage audit — research only.
// Fixes: explicit dialog closing, better tab selectors.
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
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(`[${m.type()}] ${m.text().substring(0, 200)}`); });
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
  await page.screenshot({ path: `${OUT_DIR}/m2-speechlab-initial.png` });

  // ============== M.7 SpeechLabRtfDialog — open then close (3 ways) ==============
  // Click "Загрузить диалог" button (TopBar)
  await page.locator('button:has-text("Загрузить диалог")').first().click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m2-rtf-dialog.png` });
  console.log('rtf dialog open');

  // Inspect dialog
  const dlgInfo = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"]');
    return d ? {
      text: d.innerText?.substring(0, 200),
      hasCloseBtn: !!d.querySelector('button[aria-label="Close"], button[aria-label="Закрыть"]'),
      btns: Array.from(d.querySelectorAll('button')).map(b => ({ text: (b.innerText || '').substring(0, 20), ariaLabel: b.getAttribute('aria-label'), disabled: b.disabled })),
    } : null;
  });
  console.log('DIALOG:', JSON.stringify(dlgInfo, null, 2));
  fs.writeFileSync(`${OUT_DIR}/m2-rtf-dialog-info.json`, JSON.stringify(dlgInfo, null, 2));

  // Close via button
  if (dlgInfo?.hasCloseBtn) {
    await page.locator('[role="dialog"] button[aria-label="Close"], [role="dialog"] button[aria-label="Закрыть"]').first().click({ timeout: 3000 });
  } else {
    await page.keyboard.press('Escape');
  }
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT_DIR}/m2-rtf-close-btn.png` });
  console.log('rtf closed via btn');

  // Open again via JS click (in case locator click triggers different state)
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText?.includes('Загрузить диалог'));
    if (btn) btn.click();
  });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m2-rtf-dialog-2.png` });

  // Close via backdrop — click outside dialog (top-left corner, far from dialog)
  await page.mouse.click(5, 5);
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m2-rtf-close-backdrop.png` });

  // Check if closed
  const stillOpen = await page.evaluate(() => !!document.querySelector('[role="dialog"]'));
  console.log('after backdrop click, dialog open:', stillOpen);

  // Open again, close via Escape
  if (!stillOpen) {
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText?.includes('Загрузить диалог'));
      if (btn) btn.click();
    });
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m2-rtf-dialog-3.png` });
    await page.keyboard.press('Escape');
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m2-rtf-close-esc.png` });
  } else {
    // dialog still open after backdrop attempt — close via Escape and capture
    await page.keyboard.press('Escape');
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m2-rtf-close-esc.png` });
    console.log('NOTE: backdrop click did NOT close dialog — flagged as issue');
  }

  // ============== M.8 TopBar ==============
  await page.screenshot({ path: `${OUT_DIR}/m2-topbar.png` });

  // ============== Upload dictionary XML via Import Dialog ==============
  await page.locator('button:has-text("Импорт XML")').first().click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m2-import-dialog.png` });

  // Upload XML via file chooser
  try {
    const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
    await page.locator('input[type="file"]').first().click({ timeout: 3000 });
    const fc = await fileChooserPromise;
    await fc.setFiles(XML_PATH);
    console.log('XML file selected');
    // Wait for upload + tree population
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const treeCount = await page.evaluate(() => document.querySelectorAll('[role="treeitem"], [class*="reeNode"]').length);
      console.log(`tree wait ${i*2}s: ${treeCount} nodes`);
      if (treeCount > 0) break;
    }
    await page.screenshot({ path: `${OUT_DIR}/m2-after-xml-upload.png` });

    // Close import dialog if still open
    const importOpen = await page.evaluate(() => !!document.querySelector('[role="dialog"]'));
    if (importOpen) {
      // Try Escape first, then Close button, then click outside
      await page.keyboard.press('Escape');
      await new Promise(r => setTimeout(r, 1000));
      const stillOpen2 = await page.evaluate(() => !!document.querySelector('[role="dialog"]'));
      if (stillOpen2) {
        await page.locator('[role="dialog"] button[aria-label="Close"], [role="dialog"] button[aria-label="Закрыть"]').first().click({ timeout: 3000 }).catch(() => {});
        await new Promise(r => setTimeout(r, 1000));
      }
    }
  } catch (e) { console.log('XML upload fail:', e.message.split('\n')[0]); }

  // ============== M.2 LeftPanel with tree ==============
  await page.screenshot({ path: `${OUT_DIR}/m2-left-panel.png` });

  // Inspect tree DOM
  const treeInfo = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('[role="treeitem"], [class*="reeNode"]'));
    return {
      count: items.length,
      sample: items.slice(0, 5).map(i => ({
        text: (i.innerText || '').substring(0, 80),
        cls: (i.className || '').substring(0, 80),
        ariaExpanded: i.getAttribute('aria-expanded'),
        ariaSelected: i.getAttribute('aria-selected'),
      })),
    };
  });
  fs.writeFileSync(`${OUT_DIR}/m2-tree-info.json`, JSON.stringify(treeInfo, null, 2));
  console.log('TREE:', JSON.stringify(treeInfo, null, 2));

  // ============== M.2 Tree expanded ==============
  // Click on first expandable (aria-expanded=false) toggle button
  await clickFirstExpandable(page);
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m2-tree-expanded.png` });

  // Expand more
  for (let i = 0; i < 4; i++) {
    await clickFirstExpandable(page);
    await new Promise(r => setTimeout(r, 800));
  }
  await page.screenshot({ path: `${OUT_DIR}/m2-tree-expanded-more.png` });

  // ============== M.2 Tree collapsed ==============
  await clickFirstCollapsible(page);
  await new Promise(r => setTimeout(r, 800));
  await page.screenshot({ path: `${OUT_DIR}/m2-tree-collapsed.png` });

  // ============== M.5 KeywordsDisplay (select a leaf node) ==============
  // Click on a tree leaf (treeitem without aria-expanded)
  await clickFirstLeaf(page);
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m2-keywords.png` });

  // ============== M.4 QueryTab ==============
  // Already on Query tab by default. Take screenshot.
  await page.screenshot({ path: `${OUT_DIR}/m2-query-tab.png` });

  // Try to find query input
  const qInput = page.locator('input[type="search"], input[placeholder*="поиск" i], input[placeholder*="запрос" i], textarea[placeholder*="поиск" i]').first();
  try {
    await qInput.waitFor({ state: 'visible', timeout: 4000 });
    await qInput.fill('сотрудник');
    await new Promise(r => setTimeout(r, 500));
    await page.screenshot({ path: `${OUT_DIR}/m2-query-input.png` });
    await clickFirst(page, [
      page.locator('button:has-text("Поиск"), button:has-text("Найти"), button:has-text("Искать")').first(),
    ], 'btn-search-query');
    await new Promise(r => setTimeout(r, 4000));
    await page.screenshot({ path: `${OUT_DIR}/m2-query-results.png` });
  } catch (e) { console.log('query input fail:', e.message.split('\n')[0]); }

  // ============== M.3 FoundRecordsTab ==============
  await clickFirst(page, [
    page.locator('button.dsb_tab-new:has-text("Найденные записи")'),
    page.locator('text=Найденные записи').first(),
  ], 'tab-found-records');
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: `${OUT_DIR}/m2-found-records.png` });

  // Click first record
  await clickFirst(page, [
    page.locator('[class*="ecordCard"], [class*="ound-records"] [class*="card"], [class*="ound-records"] [role="button"]').first(),
  ], 'found-record-click');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: `${OUT_DIR}/m2-found-record-click.png` });

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
  await page.screenshot({ path: `${OUT_DIR}/m2-resize.png` });

  // ============== M.9 Scroll down ==============
  await page.evaluate(() => {
    const c = document.querySelector('[class*="peechLab"], main, [class*="ontent"]') || document.documentElement;
    c.scrollTop = c.scrollHeight;
    window.scrollTo(0, document.body.scrollHeight);
  });
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT_DIR}/m2-scrolled-down.png` });

  await page.screenshot({ path: `${OUT_DIR}/m2-speechlab-fullpage.png`, fullPage: true });

  fs.writeFileSync(`${OUT_DIR}/m2-console-errors.json`, JSON.stringify({ errors: consoleErrors, requests }, null, 2));
  console.log('PHASE M2 DONE. Errors:', consoleErrors.length, 'Requests:', requests.length);
  consoleErrors.slice(0, 10).forEach(e => console.log('  ERR:', e));
  requests.slice(0, 20).forEach(r => console.log('  REQ:', r));

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
  // DS Tree may render expand toggle as button or click on treeitem itself
  const candidates = [
    page.locator('[role="treeitem"] [aria-expanded="false"]').first(),
    page.locator('[role="treeitem"][aria-expanded="false"]').first(),
    page.locator('[class*="reeNode"] [aria-expanded="false"]').first(),
    page.locator('[class*="reeNode"] button:has-text("expand"), [class*="reeNode"] [class*="expand"]').first(),
  ];
  for (const sel of candidates) {
    try {
      await sel.click({ timeout: 2500 });
      console.log('EXPAND ok');
      await new Promise(r => setTimeout(r, 400));
      return true;
    } catch (e) { /* try next */ }
  }
  console.log('EXPAND FAILED');
  return false;
}

async function clickFirstCollapsible(page) {
  const candidates = [
    page.locator('[role="treeitem"] [aria-expanded="true"]').first(),
    page.locator('[role="treeitem"][aria-expanded="true"]').first(),
    page.locator('[class*="reeNode"] [aria-expanded="true"]').first(),
  ];
  for (const sel of candidates) {
    try {
      await sel.click({ timeout: 2500 });
      console.log('COLLAPSE ok');
      await new Promise(r => setTimeout(r, 400));
      return true;
    } catch (e) { /* try next */ }
  }
  console.log('COLLAPSE FAILED');
  return false;
}

async function clickFirstLeaf(page) {
  const candidates = [
    page.locator('[role="treeitem"]:not([aria-expanded])').last(),
    page.locator('[role="treeitem"]').last(),
    page.locator('[class*="reeNode"]').last(),
  ];
  for (const sel of candidates) {
    try {
      await sel.click({ timeout: 2500 });
      console.log('LEAF click ok');
      await new Promise(r => setTimeout(r, 400));
      return true;
    } catch (e) { /* try next */ }
  }
  console.log('LEAF click FAILED');
  return false;
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
