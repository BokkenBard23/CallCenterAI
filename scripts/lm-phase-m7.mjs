// Quick fix v4: click on treenode_title (the actual label) to trigger DS Tree selection
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2500));
  await page.locator('text=sample-dialog').first().click({ timeout: 5000 });
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    if (page.url().includes('/results')) break;
  }
  await new Promise(r => setTimeout(r, 3000));

  await page.goto(APP + '/speechlab', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 3000));

  await page.locator('button:has-text("Импорт XML")').first().click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1500));
  const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
  await page.locator('input[type="file"]').first().click({ timeout: 3000 });
  const fc = await fileChooserPromise;
  await fc.setFiles(path.resolve('data/output/production_xml/sample_dictionary.xml'));
  await new Promise(r => setTimeout(r, 1500));
  await page.locator('[role="dialog"] button:has-text("Загрузить на сервер")').first().click({ timeout: 5000 });
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const dlg = await page.evaluate(() => !!document.querySelector('[role="dialog"]'));
    if (!dlg) break;
  }
  await new Promise(r => setTimeout(r, 2000));

  // Strategy 1: click on the treenode_title element (the visible label <p>)
  try {
    await page.locator('.treenode_title').first().click({ timeout: 4000 });
    await new Promise(r => setTimeout(r, 1500));
    const sel = await page.evaluate(() => document.querySelector('[role="treeitem"][aria-selected="true"]')?.innerText?.substring(0, 80));
    console.log('After click on .treenode_title — selected:', sel);
  } catch (e) { console.log('click .treenode_title fail:', e.message.split('\n')[0]); }

  // Strategy 2: Use keyboard navigation. Focus tree then press Tab/Arrow to select first item, then Enter.
  if (!await page.evaluate(() => !!document.querySelector('[role="treeitem"][aria-selected="true"]'))) {
    await page.locator('[role="treeitem"]').first().click({ timeout: 3000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 800));
    // Try pressing Space or Enter
    await page.keyboard.press('Enter');
    await new Promise(r => setTimeout(r, 800));
    const sel = await page.evaluate(() => document.querySelector('[role="treeitem"][aria-selected="true"]')?.innerText?.substring(0, 80));
    console.log('After Enter — selected:', sel);
  }

  // Strategy 3: Direct JS click on the treenode_title (React handler should fire)
  if (!await page.evaluate(() => !!document.querySelector('[role="treeitem"][aria-selected="true"]'))) {
    await page.evaluate(() => {
      const title = document.querySelector('.treenode_title');
      if (title) {
        // Try simulating a real mousedown+click event sequence
        const evt = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
        title.dispatchEvent(evt);
      }
    });
    await new Promise(r => setTimeout(r, 1500));
    const sel = await page.evaluate(() => document.querySelector('[role="treeitem"][aria-selected="true"]')?.innerText?.substring(0, 80));
    console.log('After JS dispatchEvent — selected:', sel);
  }

  // Strategy 4: Use DS Tree keyboard arrow navigation
  if (!await page.evaluate(() => !!document.querySelector('[role="treeitem"][aria-selected="true"]'))) {
    // Focus the tree
    await page.locator('[role="tree"]').first().click({ timeout: 3000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 500));
    await page.keyboard.press('ArrowDown');
    await new Promise(r => setTimeout(r, 500));
    await page.keyboard.press('Space');
    await new Promise(r => setTimeout(r, 1000));
    const sel = await page.evaluate(() => document.querySelector('[role="treeitem"][aria-selected="true"]')?.innerText?.substring(0, 80));
    console.log('After Arrow+Space — selected:', sel);
  }

  await page.screenshot({ path: `${OUT_DIR}/m-keywords.png` });
  await page.screenshot({ path: `${OUT_DIR}/m-query-tab.png` });

  // Inspect QueryTab content
  const qTabInfo = await page.evaluate(() => {
    const right = document.querySelector('.speechlab-layout__panel--right');
    return {
      text: (right?.innerText || '').substring(0, 1500).replace(/\n/g, ' | '),
      badges: Array.from(right?.querySelectorAll('[class*="adge"], [class*="oken"]') || []).map(b => ({
        text: b.innerText?.substring(0, 30),
        cls: (b.className || '').substring(0, 100),
      })),
    };
  });
  fs.writeFileSync(`${OUT_DIR}/m-keywords-content.json`, JSON.stringify(qTabInfo, null, 2));
  console.log('QueryTab:', JSON.stringify(qTabInfo, null, 2).substring(0, 800));

  // Try search input if any
  try {
    const q = page.locator('input[type="search"], input[placeholder*="поиск" i]').first();
    await q.waitFor({ state: 'visible', timeout: 3000 });
    await q.fill('сотрудник');
    await new Promise(r => setTimeout(r, 500));
    await page.screenshot({ path: `${OUT_DIR}/m-query-input.png` });
    await page.locator('button:has-text("Поиск"), button:has-text("Найти")').first().click({ timeout: 3000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 4000));
    await page.screenshot({ path: `${OUT_DIR}/m-query-results.png` });
  } catch (e) { console.log('no search input:', e.message.split('\n')[0]); }

  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
