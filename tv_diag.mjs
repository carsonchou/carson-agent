// 診斷：登入態開圖表，dump 出頁面真實的 data-name 屬性與按鈕文字，找出正確選擇器。
// 用法：node tv_diag.mjs [symbol] [tf]
import { chromium } from 'playwright';
import fs from 'fs';
const [symbol = 'BINANCE:BTCUSDT', tf = '240'] = process.argv.slice(2);
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
const page = ctx.pages()[0] || await ctx.newPage();
const out = { dataNames: [], buttons: [], bottomTabs: [] };
try {
  await page.goto(`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}&interval=${tf}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(12000); // 給足時間載入重型圖表 UI

  // 所有 data-name 屬性（去重）
  out.dataNames = await page.evaluate(() => {
    const s = new Set();
    document.querySelectorAll('[data-name]').forEach(e => s.add(e.getAttribute('data-name')));
    return [...s].sort();
  });
  // 所有可見按鈕的文字 / aria-label（過濾空白、取前 120 個）
  out.buttons = await page.evaluate(() => {
    const arr = [];
    document.querySelectorAll('button,[role="button"]').forEach(e => {
      const t = (e.innerText || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
      if (t && t.length < 40) arr.push(t);
    });
    return [...new Set(arr)].slice(0, 120);
  });
  await page.screenshot({ path: 'tv_diag.png' });
} catch (e) { out.error = e.message; }
finally {
  fs.writeFileSync('tv_diag.json', JSON.stringify(out, null, 2));
  console.log('dataNames=' + out.dataNames.length + ' buttons=' + out.buttons.length + (out.error ? ' ERR=' + out.error : ''));
  await ctx.close();
}
