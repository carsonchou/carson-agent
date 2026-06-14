// 診斷2：開圖表 → 點開 Pine 面板 → dump 底部面板出現後的 data-name 與按鈕文字。
import { chromium } from 'playwright';
import fs from 'fs';
const [symbol = 'BINANCE:BTCUSDT', tf = '240'] = process.argv.slice(2);
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
const page = ctx.pages()[0] || await ctx.newPage();
const out = { afterPine: { dataNames: [], buttons: [] } };
try {
  await page.goto(`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}&interval=${tf}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(10000);
  // 關掉所有 toast 通知避免擋路
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 1000 }).catch(() => {}); }
  // 點開 Pine 編輯器面板
  await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 10000 }).catch(e => out.pineErr = e.message);
  await page.waitForTimeout(6000);
  out.afterPine.dataNames = await page.evaluate(() => { const s = new Set(); document.querySelectorAll('[data-name]').forEach(e => s.add(e.getAttribute('data-name'))); return [...s].sort(); });
  out.afterPine.buttons = await page.evaluate(() => { const a = []; document.querySelectorAll('button,[role="button"],[role="tab"]').forEach(e => { const t = (e.innerText || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' '); if (t && t.length < 40) a.push(t); }); return [...new Set(a)]; });
  await page.screenshot({ path: 'tv_diag2.png' });
} catch (e) { out.error = e.message; }
finally {
  fs.writeFileSync('tv_diag2.json', JSON.stringify(out, null, 2));
  console.log('afterPine dataNames=' + out.afterPine.dataNames.length + ' buttons=' + out.afterPine.buttons.length + (out.pineErr ? ' pineErr=' + out.pineErr : '') + (out.error ? ' ERR=' + out.error : ''));
  await ctx.close();
}
