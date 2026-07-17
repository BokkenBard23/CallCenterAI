// PHASE L retry: feedback (via type) + semantic panel inspection
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };

const consoleErrors = [];
const requests = [];

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(`[${m.type()}] ${m.text()}`); });
  page.on('pageerror', e => consoleErrors.push(`PAGEERR: ${e.message}`));
  page.on('response', r => { if (r.url().includes('/api/')) requests.push(`${r.status()} ${r.url().split('/').slice(3).join('/')}`); });

  // Restore
  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2500));
  await page.locator('text=sample-dialog').first().click({ timeout: 5000 });
  for (let i = 0; i < 25; i++) {
    await new Promise(r => setTimeout(r, 1000));
    if (page.url().includes('/results')) break;
  }
  await new Promise(r => setTimeout(r, 5000));
  console.log('URL:', page.url());
  // Wait for tabs to appear
  await page.locator('[role=tab]').first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
  await new Promise(r => setTimeout(r, 1500));

  // Switch to highlighted view (with retry, DS tab is button.dsb_tab-new, NOT role=tab)
  for (let i = 0; i < 3; i++) {
    try {
      await page.locator('button.dsb_tab-new:has-text("Выделенный текст")').click({ timeout: 5000 });
      break;
    } catch (e) { console.log(`tab click attempt ${i+1} fail, retry`); await new Promise(r => setTimeout(r, 1500)); }
  }
  await new Promise(r => setTimeout(r, 2500));

  // Click first mark
  await page.locator('mark').first().click({ timeout: 3500 });
  await new Promise(r => setTimeout(r, 1800));
  await page.screenshot({ path: `${OUT_DIR}/l2-phrase-popover.png` });
  console.log('popover opened');

  // Try typing into the textarea via focus() + keyboard (DS Popover intercepts clicks)
  const ta = page.locator('[role="dialog"] textarea, [class*="opover"] textarea').first();
  // Focus via JS bypass
  await ta.evaluate(el => el.focus());
  await new Promise(r => setTimeout(r, 300));
  await page.keyboard.type('Test feedback audit L5', { delay: 30 });
  await new Promise(r => setTimeout(r, 800));
  await page.screenshot({ path: `${OUT_DIR}/l2-feedback-filled.png` });
  console.log('typed into textarea');

  // Check counter
  const counterText = await page.locator('[role="dialog"], [class*="opover"]').first().innerText();
  console.log('popover text after typing:', counterText.substring(0, 300));

  // Try sending feedback — button should be enabled now. Use force click to bypass overlay.
  try {
    // First try force click
    await page.locator('[role="dialog"] button:has-text("Отправить")').first().click({ timeout: 4000, force: true });
    await new Promise(r => setTimeout(r, 2500));
    await page.screenshot({ path: `${OUT_DIR}/l2-feedback-sent.png` });
    console.log('feedback sent (force click)');
  } catch (e) {
    console.log('send force click fail, trying JS click:', e.message.split('\n')[0]);
    // Try via JS evaluate
    const clickedViaJS = await page.evaluate(() => {
      const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [class*="opover"]'));
      for (const d of dialogs) {
        const btn = Array.from(d.querySelectorAll('button')).find(b => b.innerText?.includes('Отправить'));
        if (btn && !btn.disabled) { btn.click(); return { ok: true, text: btn.innerText }; }
      }
      // fallback: any disabled button?
      const allBtns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText?.includes('Отправить'));
      return { ok: false, found: allBtns.length, disabled: allBtns.map(b => b.disabled) };
    });
    console.log('JS click result:', JSON.stringify(clickedViaJS));
    await new Promise(r => setTimeout(r, 2500));
    await page.screenshot({ path: `${OUT_DIR}/l2-feedback-sent.png` });
  }

  // Close popover via Escape (DS Popover has no close button)
  await page.keyboard.press('Escape');
  await new Promise(r => setTimeout(r, 1500));

  // Now inspect semantic panel
  try {
    await page.locator('button.dsb_button__plain.dsb_button__s:has-text("search")').first().click({ timeout: 5000 });
    await new Promise(r => setTimeout(r, 2500));
    await page.screenshot({ path: `${OUT_DIR}/l2-semantic-open.png` });
    console.log('semantic opened');
  } catch (e) { console.log('semantic toggle fail:', e.message); }

  const semInfo = await page.evaluate(() => {
    const panels = Array.from(document.querySelectorAll('[class*="emantic"], [class*="semantic-panel"], [class*="ide-panel"]'));
    const result = [];
    for (const p of panels) {
      const r = p.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        result.push({
          cls: (p.className || '').substring(0, 120),
          rect: { x: r.x, y: r.y, w: r.width, h: r.height },
          text: (p.innerText || '').substring(0, 400),
          inputs: Array.from(p.querySelectorAll('input, textarea')).map(i => ({
            type: i.type || i.tagName,
            placeholder: i.placeholder?.substring(0, 50),
            ariaLabel: i.getAttribute('aria-label'),
            name: i.name,
            cls: (i.className || '').substring(0, 60),
          })),
          buttons: Array.from(p.querySelectorAll('button')).map(b => ({
            text: (b.innerText || '').substring(0, 30),
            ariaLabel: b.getAttribute('aria-label'),
            disabled: b.disabled,
          })),
        });
      }
    }
    return result;
  });
  fs.writeFileSync(`${OUT_DIR}/l2-semantic-info.json`, JSON.stringify(semInfo, null, 2));
  console.log('SEMANTIC PANELS:', JSON.stringify(semInfo, null, 2));

  await page.screenshot({ path: `${OUT_DIR}/l2-semantic-state.png` });

  // Close semantic
  await page.keyboard.press('Escape');
  await new Promise(r => setTimeout(r, 800));

  fs.writeFileSync(`${OUT_DIR}/l2-console-errors.json`, JSON.stringify({ errors: consoleErrors, requests }, null, 2));
  console.log('Errors:', consoleErrors.length, 'Requests:', requests.length);
  consoleErrors.forEach(e => console.log('  ERR:', e));
  requests.forEach(r => console.log('  REQ:', r));

  await page.close();
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
