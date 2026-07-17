// Phase L/M discovery: inspect localStorage history and the /results page availability
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
  page.on('console', m => { if (m.type() === 'error') errs.push(`[${page.url()}] ${m.text()}`); });
  page.on('pageerror', e => errs.push(`[${page.url()}] PAGEERR: ${e.message}`));

  await page.goto(APP + '/history', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: `${OUT}/lm-inspect-history.png`, fullPage: false });

  // Inspect localStorage history entries
  const hist = await page.evaluate(() => {
    try {
      const raw = localStorage.getItem('callcenter-analysis-history');
      if (!raw) return { present: false };
      const parsed = JSON.parse(raw);
      const list = Array.isArray(parsed) ? parsed : (parsed?.entries ?? parsed?.items ?? []);
      return {
        present: true,
        rawLen: raw.length,
        count: list.length,
        keys: parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? Object.keys(parsed) : null,
        entries: list.map(e => ({
          id: e?.id, analysisId: e?.analysisId, sessionId: e?.sessionId,
          status: e?.status, hasSR: !!e?.searchResult, hasLLM: !!e?.llmResult,
          srKeys: e?.searchResult ? Object.keys(e.searchResult).slice(0, 12) : null,
          llmKeys: e?.llmResult ? Object.keys(e.llmResult).slice(0, 12) : null,
          title: e?.title ?? e?.fileName ?? null,
          ts: e?.timestamp ?? e?.createdAt ?? null,
        })),
      };
    } catch (e) {
      return { present: false, err: String(e) };
    }
  });

  console.log('HISTORY:', JSON.stringify(hist, null, 2));
  fs.writeFileSync(`${OUT}/lm-inspect-history.json`, JSON.stringify(hist, null, 2));
  fs.writeFileSync(`${OUT}/lm-inspect-console.json`, JSON.stringify({ url: page.url(), errors: errs }, null, 2));
  console.log('URL after /history:', page.url());
  console.log('Console errors:', errs.length);
  await page.close();
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
