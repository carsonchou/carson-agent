// 精確抓 Pine 編譯錯誤：注入 champion_r5 → Add to chart → 廣捕錯誤(console/marker/廣關鍵字)。
import { chromium } from 'playwright';
import fs from 'fs';
const code = fs.readFileSync(process.argv[2] || 'triple_supertrend_v4_champion_r5.pine', 'utf8');
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = { errors: [], consoleText: '' };
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
try {
  await page.goto('https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT&interval=240', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  const ed = page.locator('.monaco-editor').first(); const ebox = await ed.boundingBox().catch(() => null);
  if (ebox) await page.mouse.click(ebox.x + ebox.width / 2, ebox.y + ebox.height / 2);
  await page.waitForTimeout(400);
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(300);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(() => {});
  await page.keyboard.press('Control+V'); await page.waitForTimeout(2500);
  await page.locator('[title="Add to chart" i]').first().click({ timeout: 10000 }).catch(() => out.errors.push('add fail'));
  await page.waitForTimeout(7000);
  // 廣捕：任何含錯誤字眼的葉節點
  out.errors = out.errors.concat(await page.evaluate(() => {
    const r = [];
    document.querySelectorAll('*').forEach(e => { if (e.children.length === 0) { const t = (e.innerText || e.textContent || '').trim(); if (t && /could not find|cannot call|undeclared|undefined|mismatch|expected|syntax|no viable|reference|line \d+:|argument/i.test(t) && t.length < 220) r.push(t); } });
    return [...new Set(r)].slice(0, 20);
  }));
  // Pine 編輯器 console 區整段文字
  out.consoleText = await page.evaluate(() => {
    const c = document.querySelector('[class*="console" i], [class*="errorWrap" i], [class*="bottomWidget" i]');
    return c ? (c.innerText || '').slice(0, 500) : '';
  });
  await page.screenshot({ path: 'tv_err2.png', clip: { x: 850, y: 60, width: 830, height: 300 } }).catch(() => {});
} catch (e) { out.errors.push('EXC: ' + e.message); }
fs.writeFileSync('tv_err2.json', JSON.stringify(out, null, 2));
console.log('errors=' + JSON.stringify(out.errors) + ' console=' + JSON.stringify(out.consoleText.slice(0, 300)));
await ctx.close();
