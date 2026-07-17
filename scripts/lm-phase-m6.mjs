// Quick fix v3: use page.locator to click on tree node text directly
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

  // Restore session
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

  // Upload dictionary
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
  console.log('Tree loaded.');

  // Inspect DOM structure deeply
  const domDump = await page.evaluate(() => {
    const treeContainer = document.querySelector('.speechlab-tree');
    if (!treeContainer) return { error: 'no .speechlab-tree container' };
    // Dump first treeitem HTML
    const firstItem = treeContainer.querySelector('[role="treeitem"]');
    return {
      treeContainerHTML: treeContainer.outerHTML.substring(0, 1500),
      firstItemHTML: firstItem?.outerHTML.substring(0, 800),
      firstItemChildren: Array.from(firstItem?.children || []).map(c => ({
        tag: c.tagName, cls: (c.className || '').substring(0, 80), text: (c.innerText || '').substring(0, 50),
      })),
      allClickables: Array.from(treeContainer.querySelectorAll('button, [role="button"], [class*="toggle"], [class*="row"]')).slice(0, 10).map(b => ({
        tag: b.tagName, cls: (b.className || '').substring(0, 80), text: (b.innerText || '').substring(0, 50),
      })),
    };
  });
  fs.writeFileSync(`${OUT_DIR}/m-tree-dom.json`, JSON.stringify(domDump, null, 2));
  console.log('DOM:', JSON.stringify(domDump, null, 2).substring(0, 1500));

  // Try clicking on the visible tree node text "sample_dictionary"
  try {
    await page.locator('[role="treeitem"]:has-text("sample_dictionary")').first().click({ timeout: 4000 });
    console.log('clicked treeitem with text Сотрудники');
  } catch (e) {
    console.log('treeitem click failed:', e.message.split('\n')[0]);
    // Try clicking anywhere in the speechlab-tree
    try {
      await page.locator('.speechlab-tree [role="treeitem"]').first().click({ timeout: 4000 });
      console.log('clicked speechlab-tree treeitem');
    } catch (e2) { console.log('speechlab-tree click failed:', e2.message.split('\n')[0]); }
  }
  await new Promise(r => setTimeout(r, 2000));

  const selected1 = await page.evaluate(() => {
    const s = document.querySelector('[role="treeitem"][aria-selected="true"]');
    return s ? s.innerText?.substring(0, 100).replace(/\n/g, ' | ') : null;
  });
  console.log('Selected after click:', selected1);

  await page.screenshot({ path: `${OUT_DIR}/m-keywords.png` });

  // Inspect QueryTab content
  const qTabInfo = await page.evaluate(() => {
    const right = document.querySelector('.speechlab-layout__panel--right');
    return {
      text: (right?.innerText || '').substring(0, 1500).replace(/\n/g, ' | '),
      badges: Array.from(right?.querySelectorAll('[class*="adge"], [class*="oken"]') || []).map(b => ({
        text: b.innerText?.substring(0, 30),
        cls: (b.className || '').substring(0, 100),
      })),
      inputs: Array.from(right?.querySelectorAll('input, textarea') || []).map(i => ({
        type: i.type || i.tagName, placeholder: i.placeholder?.substring(0, 40),
      })),
    };
  });
  fs.writeFileSync(`${OUT_DIR}/m-keywords-content.json`, JSON.stringify(qTabInfo, null, 2));
  console.log('QueryTab content:', JSON.stringify(qTabInfo, null, 2).substring(0, 1500));

  await page.screenshot({ path: `${OUT_DIR}/m-query-tab.png` });

  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
