// Quick fix: select tree node properly + capture remaining M screenshots
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);

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

  // Upload dictionary XML
  await page.locator('button:has-text("Импорт XML")').first().click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1500));

  const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
  await page.locator('input[type="file"]').first().click({ timeout: 3000 });
  const fc = await fileChooserPromise;
  await fc.setFiles(path.resolve('data/output/production_xml/sample_dictionary.xml'));
  await new Promise(r => setTimeout(r, 1500));

  // Click "Загрузить на сервер"
  await page.locator('[role="dialog"] button:has-text("Загрузить на сервер")').first().click({ timeout: 5000 });
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const dlg = await page.evaluate(() => !!document.querySelector('[role="dialog"]'));
    if (!dlg) break;
  }
  await new Promise(r => setTimeout(r, 1500));
  console.log('Tree loaded.');

  // Inspect tree DOM (full structure)
  const fullTree = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('[role="treeitem"]'));
    return items.map(i => ({
      text: (i.innerText || '').substring(0, 80).replace(/\n/g, ' | '),
      ariaExpanded: i.getAttribute('aria-expanded'),
      ariaSelected: i.getAttribute('aria-selected'),
      rect: (() => { const r = i.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })(),
    }));
  });
  console.log('FULL TREE:', JSON.stringify(fullTree, null, 2));

  // Click on a leaf node (last treeitem, which is "sample_dictionary" leaf)
  if (fullTree.length > 0) {
    const leaf = fullTree[fullTree.length - 1];
    console.log('Clicking leaf at:', leaf.rect.x + 50, leaf.rect.y + leaf.rect.h / 2);
    // Click in the middle of the leaf node text area
    await page.mouse.click(leaf.rect.x + 80, leaf.rect.y + leaf.rect.h / 2);
    await new Promise(r => setTimeout(r, 2000));

    // Check if selected
    const selected = await page.evaluate(() => {
      const s = document.querySelector('[role="treeitem"][aria-selected="true"]');
      return s ? s.innerText?.substring(0, 80).replace(/\n/g, ' | ') : null;
    });
    console.log('Selected node:', selected);

    // Take screenshot of QueryTab (default selected)
    await page.screenshot({ path: `${OUT_DIR}/m-keywords.png` });

    // Inspect QueryTab content
    const qTabInfo = await page.evaluate(() => {
      const right = document.querySelector('.speechlab-layout__panel--right');
      return {
        text: (right?.innerText || '').substring(0, 800).replace(/\n/g, ' | '),
        tokenBadges: Array.from(right?.querySelectorAll('[class*="adge"], [class*="okenBadge"]') || []).map(b => ({
          text: b.innerText?.substring(0, 30),
          cls: (b.className || '').substring(0, 60),
        })),
      };
    });
    fs.writeFileSync(`${OUT_DIR}/m-keywords-content.json`, JSON.stringify(qTabInfo, null, 2));
    console.log('KEYWORDS CONTENT:', JSON.stringify(qTabInfo, null, 2));

    // Take individual QueryTab screenshot (with selected node)
    await page.screenshot({ path: `${OUT_DIR}/m-query-tab.png` });

    // If there's a search field in QueryTab, try entering query
    try {
      const q = page.locator('input[type="search"], input[placeholder*="поиск" i]').first();
      await q.waitFor({ state: 'visible', timeout: 4000 });
      await q.fill('сотрудник');
      await new Promise(r => setTimeout(r, 500));
      await page.screenshot({ path: `${OUT_DIR}/m-query-input.png` });

      // Click search button
      await page.locator('button:has-text("Поиск"), button:has-text("Найти"), button:has-text("Искать")').first().click({ timeout: 3000 }).catch(() => {});
      await new Promise(r => setTimeout(r, 4000));
      await page.screenshot({ path: `${OUT_DIR}/m-query-results.png` });
    } catch (e) { console.log('no search input:', e.message.split('\n')[0]); }
  }

  // Switch to FoundRecordsTab
  await page.locator('button.dsb_tab-new:has-text("Найденные записи")').first().click({ timeout: 4000 });
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: `${OUT_DIR}/m-found-records.png` });

  // Click first record (if any)
  const recordsCount = await page.evaluate(() => {
    const cards = document.querySelectorAll('[class*="ecordCard"], [class*="ound-records"] [class*="card"], [class*="ound-records"] [role="button"]');
    return cards.length;
  });
  console.log('Found records count:', recordsCount);

  if (recordsCount > 0) {
    await page.locator('[class*="ecordCard"], [class*="ound-records"] [class*="card"], [class*="ound-records"] [role="button"]').first().click({ timeout: 3000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m-found-record-click.png` });
  } else {
    console.log('No records to click');
  }

  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
