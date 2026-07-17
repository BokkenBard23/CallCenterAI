// Debug: check what onClick receives
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

  // Check the React fiber to see what onClick handler is attached
  const reactInfo = await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll('[data-testid=Tab]'))
      .find(t => t.textContent?.includes('Результаты'));
    if (!tab) return 'no tab found';

    // Get React fiber
    const key = Object.keys(tab).find(k => k.startsWith('__reactFiber'));
    if (!key) return 'no fiber';
    const fiber = tab[key];
    
    // Try to find the onClick prop
    let props = fiber.memoizedProps;
    return {
      onClickType: typeof props.onClick,
      value: props.value,
      role: props.role,
      label: props.label,
      // Check if onClick is a function we can call
      onClickExists: !!props.onClick,
    };
  });
  console.log('React props on Результаты tab:', JSON.stringify(reactInfo));

  // Try calling the onClick directly via React
  console.log('--- Checking if navigate works via window ---');
  const navResult = await page.evaluate(() => {
    // Try to find the React Router navigate function
    // Check if there's a history object we can inspect
    return {
      pathname: window.location.pathname,
      hash: window.location.hash,
    };
  });
  console.log('Current location:', JSON.stringify(navResult));

  // Monkey-patch the button to log onClick
  await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll('[data-testid=Tab]'))
      .find(t => t.textContent?.includes('Результаты'));
    if (tab) {
      const origClick = tab.onclick;
      tab.addEventListener('click', (e) => {
        console.log('BUTTON CLICK EVENT fired');
        console.log('defaultPrevented:', e.defaultPrevented);
      }, true);
    }
  });

  // Click and capture
  console.log('--- Clicking tab ---');
  await page.locator('[data-testid=Tab]:has-text("Результаты")').click({ timeout: 5000 });
  await new Promise(r => setTimeout(r, 1000));
  console.log('URL after click:', page.url());

  // Print all console messages
  console.log('--- Console messages ---');
  consoleMessages.forEach(m => console.log(m));

  await browser.close();
}

main().catch(e => { console.error('ERR', e); process.exit(1); });
