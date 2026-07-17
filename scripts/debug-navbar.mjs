// Debug: check if Tab onClick fires
import { chromium } from 'playwright';

const APP = 'http://localhost:5173';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2000));

  // Check what elements exist
  const tabs = await page.locator('[role=tab]').count();
  console.log('role=tab count:', tabs);

  const tabButtons = await page.locator('button[data-testid=Tab]').count();
  console.log('data-testid=Tab count:', tabButtons);

  // Get tab text and attributes
  const tabInfo = await page.locator('[data-testid=Tab]').evaluateAll(els =>
    els.map(e => ({ text: e.textContent?.trim(), role: e.getAttribute('role'), value: e.getAttribute('value') }))
  );
  console.log('Tab info:', JSON.stringify(tabInfo));

  // Add a click listener on the nav to verify clicks bubble
  await page.evaluate(() => {
    const nav = document.querySelector('.app-navbar');
    if (nav) {
      nav.addEventListener('click', (e) => {
        console.log('NAV CLICK:', e.target.textContent?.trim(), e.target.tagName);
      }, true);
    }
  });

  // Listen for console messages
  page.on('console', msg => console.log('PAGE CONSOLE:', msg.text()));

  // Click the "Результаты" tab
  console.log('--- Clicking Результаты ---');
  await page.locator('[data-testid=Tab]:has-text("Результаты")').click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 2000));
  console.log('URL after click:', page.url());

  // Check if React Router history changed
  const historyLength = await page.evaluate(() => window.history.length);
  console.log('History length:', historyLength);

  // Try clicking via JavaScript directly
  console.log('--- Direct JS click ---');
  const clicked = await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll('[data-testid=Tab]'))
      .find(t => t.textContent?.includes('Результаты'));
    if (tab) {
      tab.click();
      return true;
    }
    return false;
  });
  console.log('Direct click:', clicked);
  await new Promise(r => setTimeout(r, 2000));
  console.log('URL after direct click:', page.url());

  await browser.close();
}

main().catch(e => { console.error('ERR', e); process.exit(1); });
