// Quick debug: dump current /results page state
import { chromium } from 'playwright';
import fs from 'node:fs';

const APP = 'http://localhost:5173';

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });
  page.on('console', m => console.log(`[c-${m.type()}]`, m.text().substring(0, 200)));
  page.on('pageerror', e => console.log('PAGEERR:', e.message));

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 3000));
  await page.locator('text=sample-dialog').first().click({ timeout: 5000 });

  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    if (page.url().includes('/results')) { console.log(`navigated at ${i+1}s`); break; }
  }
  await new Promise(r => setTimeout(r, 5000));

  const state = await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll('[role=tab]')).map(t => ({
      text: (t.innerText || '').substring(0, 50),
      sel: t.classList.contains('dsb_tab-new--selected') || t.getAttribute('aria-selected') === 'true',
    }));
    const h1 = Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.innerText?.substring(0, 60));
    const body = document.body.innerText.substring(0, 600);
    const marksCount = document.querySelectorAll('mark').length;
    return { url: location.href, tabs, h1, marksCount, bodySample: body };
  });
  fs.writeFileSync('docs/specs/screenshots/l2-results-state.json', JSON.stringify(state, null, 2));
  console.log(JSON.stringify(state, null, 2));
  await page.screenshot({ path: 'docs/specs/screenshots/l2-results-state.png' });
  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
