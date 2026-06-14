// 找圖表圖例研究項的真實結構：定位含策略名的元素，dump 其祖先 data-name 鏈 + hover 後出現的按鈕。
import { chromium } from 'playwright';
import fs from 'fs';
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = {};
try {
  await page.goto('https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT&interval=240', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }
  // 找含策略名的最內層元素，回傳其祖先鏈的 data-name/class 特徵
  out.chains = await page.evaluate(() => {
    const res = [];
    const all = document.querySelectorAll('*');
    for (const e of all) {
      if (e.children.length === 0) {
        const t = (e.innerText || '').trim();
        if (/^(3ST-v\d|Triple SuperTrend v\d)/.test(t) && t.length < 50) {
          const chain = [];
          let p = e;
          for (let i = 0; i < 6 && p; i++) { chain.push({ tag: p.tagName, dn: p.getAttribute('data-name') || '', cls: (p.className || '').toString().slice(0, 40) }); p = p.parentElement; }
          res.push({ text: t.slice(0, 30), chain });
          if (res.length >= 3) break;
        }
      }
    }
    return res;
  });
  // 對第一個策略名做 hover，dump 其圖例列出現的按鈕
  const first = page.locator('text=/^3ST-v3/').first();
  await first.hover({ timeout: 3000 }).catch(() => {});
  await page.waitForTimeout(800);
  out.hoverButtons = await page.evaluate(() => {
    const r = [];
    document.querySelectorAll('[data-name*="legend" i] button, [class*="legend" i] button, [class*="source" i] button').forEach(b => { r.push({ dn: b.getAttribute('data-name') || '', ti: b.getAttribute('title') || '', al: b.getAttribute('aria-label') || '' }); });
    return r.slice(0, 20);
  });
  await page.screenshot({ path: 'tv_legdiag.png' }).catch(() => {});
} catch (e) { out.err = e.message; }
fs.writeFileSync('tv_legdiag.json', JSON.stringify(out, null, 2));
console.log('chains=' + (out.chains ? out.chains.length : 0) + ' hoverButtons=' + (out.hoverButtons ? out.hoverButtons.length : 0));
await ctx.close();
