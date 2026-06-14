// 抓 Pine 編譯錯誤精確文字。貼 champion_r5 → Add to chart → 等 → dump 含 "function/error/reference" 的元素文字。
import { chromium } from 'playwright';
import fs from 'fs';
const pineFile = process.argv[2] || 'triple_supertrend_v4_champion_r5.pine';
const code = fs.readFileSync(pineFile, 'utf8');
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = { errors: [] };
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
try {
  await page.goto('https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT&interval=240', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  const ed = page.locator('.monaco-editor').first();
  const box = await ed.boundingBox().catch(() => null);
  if (box) await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(400);
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(400);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(() => {});
  await page.keyboard.press('Control+V');
  await page.waitForTimeout(3000);
  await page.locator('[title="Add to chart" i]').first().click({ timeout: 10000 }).catch(() => out.errors.push('add click fail'));
  await page.waitForTimeout(9000);
  // dump 所有含關鍵字的元素文字
  out.errors = out.errors.concat(await page.evaluate(() => {
    const res = [];
    document.querySelectorAll('*').forEach(e => {
      if (e.children.length === 0) { const t = (e.innerText || e.textContent || '').trim(); if (t && /could not find|function or function reference|cannot|undeclared|mismatch|line \d+:|compilation/i.test(t)) res.push(t.slice(0, 200)); }
    });
    return [...new Set(res)].slice(0, 15);
  }));
} catch (e) { out.errors.push('EXC: ' + e.message); }
fs.writeFileSync('tv_err.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify(out.errors));
await ctx.close();
