// Inspect: full localStorage entry + click history card precisely
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
  page.on('console', m => { if (m.type() === 'error') errs.push(`[${m.type()}] ${m.text()}`); });
  page.on('pageerror', e => errs.push(`PAGEERR: ${e.message}`));

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2500));

  // Dump full localStorage entry
  const fullEntry = await page.evaluate(() => {
    const raw = localStorage.getItem('callcenter-analysis-history');
    return raw;
  });
  fs.writeFileSync(`${OUT}/lm-history-raw.json`, fullEntry ?? 'null');

  // Get all cards info
  const cardsInfo = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('[class*="ard"]'));
    return cards.slice(0, 10).map((c, i) => {
      const r = c.getBoundingClientRect();
      return { idx: i, cls: c.className.substring(0, 80), text: c.innerText?.substring(0, 120), rect: { x: r.x, y: r.y, w: r.width, h: r.height } };
    });
  });
  console.log('CARDS:', JSON.stringify(cardsInfo, null, 2));

  await page.screenshot({ path: `${OUT}/lm-history-debug.png`, fullPage: false });

  // Find the first card with filename text and click on its top-left area (avoiding delete button)
  const targetCard = cardsInfo.find(c => c.text && c.text.length > 30);
  if (targetCard) {
    const x = targetCard.rect.x + 80; // offset right to avoid any icon on left
    const y = targetCard.rect.y + 20; // near top
    console.log('Clicking at', x, y);
    await page.mouse.click(x, y);
    await new Promise(r => setTimeout(r, 5000));
    console.log('URL after click:', page.url());
    await page.screenshot({ path: `${OUT}/lm-after-history-click.png`, fullPage: false });
  } else {
    console.log('NO card found');
  }

  fs.writeFileSync(`${OUT}/lm-history-debug-console.json`, JSON.stringify({ errors: errs, url: page.url() }, null, 2));
  console.log('Errors:', errs.length);
  errs.forEach(e => console.log('  ERR:', e));

  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
