// Quick re-test of dashboard CTA navigation with corrected selectors.
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const APP = 'http://localhost:5173';
const OUT_DIR = path.resolve('docs/specs/screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };

async function wait(ms) { await new Promise(r => setTimeout(r, ms)); }

async function main() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.setViewportSize(VIEWPORT);

  // Test 1: SpeechLab card CTA via href
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await page.locator('a[href="/speechlab"]').first().click({ timeout: 3000 });
  await wait(1500);
  const url1 = page.url();
  await page.screenshot({ path: path.join(OUT_DIR, 'h2r-cta-speechlab-v2.png') });
  console.log('SpeechLab CTA URL:', url1);

  // Test 2: Dictionary card CTA via href
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await page.locator('a[href="/dictionary"]').first().click({ timeout: 3000 });
  await wait(1500);
  const url2 = page.url();
  await page.screenshot({ path: path.join(OUT_DIR, 'h2r-cta-dictionary-v2.png') });
  console.log('Dictionary CTA URL:', url2);

  // Test 3: History card CTA via href
  await page.goto(APP + '/', { waitUntil: 'domcontentloaded' });
  await wait(1500);
  await page.locator('a[href="/history"]').first().click({ timeout: 3000 });
  await wait(1500);
  const url3 = page.url();
  await page.screenshot({ path: path.join(OUT_DIR, 'h2r-cta-history-v2.png') });
  console.log('History CTA URL:', url3);

  fs.writeFileSync(path.join(OUT_DIR, 'h2r-cta-results.json'),
    JSON.stringify({ speechlab: url1, dictionary: url2, history: url3 }, null, 2));
  await page.close();
  await browser.close();
  console.log('DONE');
}
main().catch(e => { console.error('ERR', e); process.exit(1); });
