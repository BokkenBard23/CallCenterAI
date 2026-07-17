// Quick fix v2: click on root tree node to select it
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

  // Click on the FIRST (root) treeitem — visible one
  const rootInfo = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('[role="treeitem"]'));
    const visible = items.find(i => {
      const r = i.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
    if (!visible) return null;
    const r = visible.getBoundingClientRect();
    return { text: visible.innerText?.substring(0, 80), x: r.x, y: r.y, w: r.width, h: r.height };
  });
  console.log('Root node:', rootInfo);

  if (rootInfo) {
    // Click on text part of node (avoid expand arrow on left)
    await page.mouse.click(rootInfo.x + 100, rootInfo.y + rootInfo.h / 2);
    await new Promise(r => setTimeout(r, 2000));

    const selected = await page.evaluate(() => {
      const s = document.querySelector('[role="treeitem"][aria-selected="true"]');
      return s ? s.innerText?.substring(0, 100).replace(/\n/g, ' | ') : null;
    });
    console.log('Selected:', selected);

    // Screenshot QueryTab with selected node
    await page.screenshot({ path: `${OUT_DIR}/m-keywords.png` });
    await page.screenshot({ path: `${OUT_DIR}/m-query-tab.png` });

    // Inspect QueryTab content
    const qTabInfo = await page.evaluate(() => {
      const right = document.querySelector('.speechlab-layout__panel--right');
      return {
        text: (right?.innerText || '').substring(0, 1200).replace(/\n/g, ' | '),
        badges: Array.from(right?.querySelectorAll('[class*="adge"], [class*="oken"]') || []).map(b => ({
          text: b.innerText?.substring(0, 30),
          cls: (b.className || '').substring(0, 80),
          bg: getComputedStyle(b).backgroundColor,
        })),
        inputs: Array.from(right?.querySelectorAll('input, textarea') || []).map(i => ({
          type: i.type || i.tagName, placeholder: i.placeholder?.substring(0, 40),
        })),
      };
    });
    fs.writeFileSync(`${OUT_DIR}/m-keywords-content.json`, JSON.stringify(qTabInfo, null, 2));
    console.log('QueryTab content:', JSON.stringify(qTabInfo, null, 2));

    // Expand the root node to reveal children, then click a leaf
    console.log('\n--- Expanding root and selecting leaf ---');
    // Click on expand arrow (left side of node, ~x+10)
    await page.mouse.click(rootInfo.x + 12, rootInfo.y + rootInfo.h / 2);
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m-tree-expanded.png` });

    // Now find visible leaf node
    const leafInfo = await page.evaluate(() => {
      const items = Array.from(document.querySelectorAll('[role="treeitem"]'));
      // Leaves are nodes with no expand arrow (or last children)
      const visibleLeaves = items.filter(i => {
        const r = i.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.y > 440; // below root
      });
      return visibleLeaves.map(i => {
        const r = i.getBoundingClientRect();
        return { text: i.innerText?.substring(0, 80), x: r.x, y: r.y, w: r.width, h: r.height };
      });
    });
    console.log('Leaves after expand:', JSON.stringify(leafInfo, null, 2));

    if (leafInfo.length > 0) {
      const target = leafInfo[leafInfo.length - 1]; // last visible leaf
      await page.mouse.click(target.x + 50, target.y + target.h / 2);
      await new Promise(r => setTimeout(r, 2000));
      const selLeaf = await page.evaluate(() => {
        const s = document.querySelector('[role="treeitem"][aria-selected="true"]');
        return s ? s.innerText?.substring(0, 100).replace(/\n/g, ' | ') : null;
      });
      console.log('Selected leaf:', selLeaf);

      await page.screenshot({ path: `${OUT_DIR}/m-keywords-leaf.png` });
      const leafContent = await page.evaluate(() => {
        const right = document.querySelector('.speechlab-layout__panel--right');
        return {
          text: (right?.innerText || '').substring(0, 1200).replace(/\n/g, ' | '),
          badges: Array.from(right?.querySelectorAll('[class*="adge"], [class*="oken"]') || []).map(b => ({
            text: b.innerText?.substring(0, 30),
            cls: (b.className || '').substring(0, 80),
          })),
        };
      });
      fs.writeFileSync(`${OUT_DIR}/m-keywords-leaf-content.json`, JSON.stringify(leafContent, null, 2));
      console.log('Leaf QueryTab content:', JSON.stringify(leafContent, null, 2));
    }

    // Try search input if present
    try {
      const q = page.locator('input[type="search"], input[placeholder*="поиск" i]').first();
      await q.waitFor({ state: 'visible', timeout: 3000 });
      await q.fill('сотрудник');
      await new Promise(r => setTimeout(r, 500));
      await page.screenshot({ path: `${OUT_DIR}/m-query-input.png` });
      await page.locator('button:has-text("Поиск"), button:has-text("Найти"), button:has-text("Искать")').first().click({ timeout: 3000 }).catch(() => {});
      await new Promise(r => setTimeout(r, 4000));
      await page.screenshot({ path: `${OUT_DIR}/m-query-results.png` });
    } catch (e) { console.log('no search input:', e.message.split('\n')[0]); }
  }

  // Found Records tab
  await page.locator('button.dsb_tab-new:has-text("Найденные записи")').first().click({ timeout: 4000 });
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: `${OUT_DIR}/m-found-records.png` });

  const records = await page.evaluate(() => {
    const cards = document.querySelectorAll('[class*="ecordCard"], [class*="ound-records"] [class*="card"], [class*="ound-records"] [role="button"], [class*="ound-records"] [class*="item"]');
    return cards.length;
  });
  console.log('Found records count:', records);
  if (records > 0) {
    await page.locator('[class*="ecordCard"], [class*="ound-records"] [class*="card"], [class*="ound-records"] [role="button"]').first().click({ timeout: 3000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 1500));
    await page.screenshot({ path: `${OUT_DIR}/m-found-record-click.png` });
  }

  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
