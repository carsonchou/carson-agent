// 找「策略選擇器」與「圖表圖例移除鈕」的選擇器，解決殘留污染。
import { chromium } from 'playwright';
import fs from 'fs';
const code = fs.readFileSync('triple_supertrend_v4_champion_r5.pine', 'utf8');
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = { legend: [], testerHeader: [], strategyNames: [] };
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
try {
  await page.goto('https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT&interval=240', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }
  // 注入並加圖表
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  const ed = page.locator('.monaco-editor').first(); const box = await ed.boundingBox().catch(() => null);
  if (box) await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(400);
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(300);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(() => {});
  await page.keyboard.press('Control+V'); await page.waitForTimeout(3000);
  await page.locator('[title="Add to chart" i]').first().click({ timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(11000);
  // dump 圖表圖例(legend)所有 data-name + 含 strategy/source 字眼的元素
  out.legend = await page.evaluate(() => {
    const r = new Set();
    document.querySelectorAll('[data-name*="legend" i], [class*="legend" i] [data-name], [data-name*="source" i]').forEach(e => { const dn = e.getAttribute('data-name'); if (dn) r.add(dn); });
    return [...r].slice(0, 30);
  });
  // dump Strategy Tester 標頭區（找策略下拉選擇器）
  out.testerHeader = await page.evaluate(() => {
    const r = [];
    const bt = document.querySelector('[data-name="backtesting"]') || document.body;
    bt.querySelectorAll('button,[role="button"],[class*="select" i],[data-name]').forEach(e => { const t = (e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40); const dn = e.getAttribute('data-name') || ''; if (t || dn) r.push({ t, dn }); });
    return r.slice(0, 30);
  });
  // 頁面上出現的策略名稱（含 SuperTrend / 3ST / Triple）
  out.strategyNames = await page.evaluate(() => {
    const r = new Set();
    document.querySelectorAll('*').forEach(e => { if (e.children.length === 0) { const t = (e.innerText || '').trim(); if (/SuperTrend|3ST|Triple|Evo|TRANSCEND/i.test(t) && t.length < 60) r.add(t); } });
    return [...r].slice(0, 20);
  });
  await page.screenshot({ path: 'tv_seldiag.png' });
} catch (e) { out.err = e.message; }
fs.writeFileSync('tv_seldiag.json', JSON.stringify(out, null, 2));
console.log('legend=' + out.legend.length + ' testerHeader=' + out.testerHeader.length + ' names=' + JSON.stringify(out.strategyNames));
await ctx.close();
