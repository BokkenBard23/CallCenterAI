// Debug: intercept and log the navigate call
import { chromium } from 'playwright';

const APP = 'http://localhost:5173';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  const consoleMessages = [];
  page.on('console', msg => consoleMessages.push(`${msg.type()}: ${msg.text()}`));

  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2000));

  // Patch history.pushState to log calls
  await page.evaluate(() => {
    const origPush = history.pushState;
    history.pushState = function(...args) {
      console.log('HISTORY pushState called:', JSON.stringify(args));
      return origPush.apply(this, args);
    };
    const origReplace = history.replaceState;
    history.replaceState = function(...args) {
      console.log('HISTORY replaceState called:', JSON.stringify(args));
      return origReplace.apply(this, args);
    };
  });

  // Now check the Tab fiber properly — find the Tab component (not the button)
  const tabProps = await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll('[data-testid=Tab]'))
      .find(t => t.textContent?.includes('Результаты'));
    if (!button) return 'no button';

    // Walk up the fiber tree to find the Tab component
    const fiberKey = Object.keys(button).find(k => k.startsWith('__reactFiber'));
    if (!fiberKey) return 'no fiber';
    let fiber = button[fiberKey];
    
    // Walk up to find a component with `value` prop
    let current = fiber;
    let depth = 0;
    while (current && depth < 10) {
      const props = current.memoizedProps;
      if (props && props.value !== undefined) {
        return {
          depth,
          type: current.type?.displayName || current.type?.name || typeof current.type,
          value: props.value,
          hasOnClick: typeof props.onClick === 'function',
          label: props.label,
        };
      }
      current = current.return;
      depth++;
    }
    return { depth, msg: 'no value prop found in fiber chain' };
  });
  console.log('Tab component fiber props:', JSON.stringify(tabProps));

  // Click
  console.log('--- Clicking Результаты ---');
  await page.locator('[data-testid=Tab]:has-text("Результаты")').click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 2000));
  console.log('URL after click:', page.url());

  // Print console
  console.log('--- Console messages after click ---');
  consoleMessages.forEach(m => console.log(m));

  await browser.close();
}

main().catch(e => { console.error('ERR', e); process.exit(1); });
