// 診斷3：解決大量注入 + 找 Add-to-chart 真實選擇器。
// 單進程開窗 → 開Pine → mouse-bbox聚焦 → clipboard貼上 → 驗行號 → dump Pine面板所有可點元素。
import { chromium } from 'playwright';
import fs from 'fs';
const pineFile = process.argv[2] || 'triple_supertrend_v4_champion_r5.pine';
const code = fs.readFileSync(pineFile, 'utf8');
const codeLines = code.split('\n').length;
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = { codeLines, log: [], addCandidates: [] };
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
try {
  await page.goto('https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT&interval=240', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  out.log.push('editorVisible=' + (await editorVisible()));

  // mouse-bbox 聚焦
  const ed = page.locator('.monaco-editor').first();
  const box = await ed.boundingBox().catch(() => null);
  if (box) { await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2); out.log.push('clicked@' + Math.round(box.x + box.width / 2) + ',' + Math.round(box.y + box.height / 2)); }
  await page.waitForTimeout(400);
  // 全選清空 → clipboard 貼上（native paste，對大文字比 insertText 穩）
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(400);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(e => out.log.push('clipWrite fail ' + e.message));
  await page.keyboard.press('Control+V');
  await page.waitForTimeout(3500);
  // 驗行號（耐心 retry）
  let lineInd = '';
  for (let a = 0; a < 6 && !lineInd; a++) { lineInd = await page.locator('text=/Line \\d+, Col \\d+/').first().innerText().catch(() => ''); if (!lineInd) await page.waitForTimeout(1000); }
  out.log.push('lineInd=[' + lineInd + '] (expect ~' + codeLines + ')');
  await page.screenshot({ path: 'tv_diag3.png' }).catch(() => {});

  // dump Pine 編輯器面板所有可點元素（找 Add to chart）
  out.addCandidates = await page.evaluate(() => {
    const res = [];
    // 找 Pine 編輯器容器（含 monaco 的最近祖先面板）
    const mon = document.querySelector('.monaco-editor');
    let panel = mon; for (let i = 0; i < 8 && panel; i++) panel = panel.parentElement;
    const root = panel || document.body;
    root.querySelectorAll('button,[role="button"],[data-name],[class*="button"]').forEach(e => {
      const t = (e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 30);
      const al = e.getAttribute('aria-label') || '';
      const ti = e.getAttribute('title') || '';
      const dn = e.getAttribute('data-name') || '';
      if (/add|chart|play|run|apply/i.test(t + ' ' + al + ' ' + ti + ' ' + dn)) res.push({ t, al, ti, dn });
    });
    return res.slice(0, 25);
  });
} catch (e) { out.log.push('EXC: ' + e.message); }
fs.writeFileSync('tv_diag3.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify(out.log) + ' addCandidates=' + out.addCandidates.length);
await ctx.close();
