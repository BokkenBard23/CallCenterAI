// Inspect ResultsPage DOM to find right selectors
import { chromium } from 'playwright';
import fs from 'node:fs';

const APP = 'http://localhost:5173';

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  // Go directly to /results — but the context state may have been lost on new page.
  // Use existing tab if possible.
  const existingPages = ctx.pages();
  let target = existingPages.find(p => p.url().includes('/results'));
  if (!target) {
    console.log('No /results tab open. Will restore from /history.');
    target = page;
    await target.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
    await new Promise(r => setTimeout(r, 2500));
    await target.locator('text=sample-dialog').first().click({ timeout: 5000 });
    for (let i = 0; i < 25; i++) {
      await new Promise(r => setTimeout(r, 1000));
      if (target.url().includes('/results')) break;
    }
    await new Promise(r => setTimeout(r, 3000));
  } else {
    console.log('Found existing /results tab');
  }

  await target.setViewportSize({ width: 1440, height: 900 });
  await new Promise(r => setTimeout(r, 1500));

  const info = await target.evaluate(() => {
    const out = {};
    // Tabs
    out.tabs = Array.from(document.querySelectorAll('[role=tab], .dsb_tabs__tab, button[class*="tab"]')).map(t => ({
      text: t.innerText?.substring(0, 40),
      ariaLabel: t.getAttribute('aria-label'),
      cls: t.className?.substring(0, 80),
    }));
    // All buttons in header
    out.buttons = Array.from(document.querySelectorAll('button')).slice(0, 30).map(b => ({
      text: (b.innerText || '').substring(0, 30),
      ariaLabel: b.getAttribute('aria-label'),
      cls: (b.className || '').substring(0, 60),
    }));
    // Mark elements
    out.marksCount = document.querySelectorAll('mark, [class*="highlight"], [class*="phrase-mark"]').length;
    out.markSample = Array.from(document.querySelectorAll('mark')).slice(0, 3).map(m => ({
      cls: m.className?.substring(0, 80),
      text: m.innerText?.substring(0, 60),
      parent: m.parentElement?.tagName,
    }));
    // Inputs
    out.inputs = Array.from(document.querySelectorAll('input, textarea')).slice(0, 20).map(i => ({
      type: i.type || i.tagName,
      placeholder: i.placeholder?.substring(0, 40),
      ariaLabel: i.getAttribute('aria-label'),
      cls: i.className?.substring(0, 60),
    }));
    // Quality score panel presence
    out.qualityPanelText = (document.querySelector('[class*="ualityScore"], [class*="quality-score"]')?.innerText || '').substring(0, 100);
    // Top-level structure
    out.h1 = Array.from(document.querySelectorAll('h1, h2, h3')).slice(0, 10).map(h => h.innerText?.substring(0, 60));
    out.url = location.href;
    return out;
  });
  console.log(JSON.stringify(info, null, 2));
  fs.writeFileSync('docs/specs/screenshots/l-dom-inspect.json', JSON.stringify(info, null, 2));
  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
