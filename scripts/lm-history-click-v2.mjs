// Inspect deeper: log network + click via JS to call React handler
import { chromium } from 'playwright';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT = 'docs/specs/screenshots';

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1440, height: 900, deviceScaleFactor: 1 });

  const errs = [];
  const reqs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(`[ERR] ${m.text()}`); if (m.type() === 'warning') errs.push(`[WARN] ${m.text()}`); });
  page.on('pageerror', e => errs.push(`PAGEERR: ${e.message}`));
  page.on('request', r => { if (r.url().includes('/api/')) reqs.push(`${r.method()} ${r.url()}`); });
  page.on('response', r => { if (r.url().includes('/api/')) reqs.push(`RESP ${r.status()} ${r.url()}`); });

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2500));

  // Try clicking on the filename Typography text
  const filename = page.locator('text=sample-dialog.rtf').first();
  try {
    await filename.click({ timeout: 5000 });
    console.log('clicked filename');
  } catch (e) {
    console.log('filename click failed:', e.message);
    // fallback: click anywhere on card body using offset
    const card = page.locator('.dsb_card').first();
    const box = await card.boundingBox();
    if (box) {
      await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
      console.log('clicked card center');
    }
  }

  // wait longer for navigation/API
  await new Promise(r => setTimeout(r, 8000));
  console.log('URL after click:', page.url());

  await page.screenshot({ path: `${OUT}/lm-history-after-click-v2.png`, fullPage: false });
  fs.writeFileSync(`${OUT}/lm-history-network.json`, JSON.stringify({ url: page.url(), errs, reqs }, null, 2));
  console.log('Errors:', errs.length);
  console.log('Requests:', reqs.length);
  reqs.forEach(r => console.log('  REQ:', r));
  errs.forEach(e => console.log('  ERR:', e));

  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
