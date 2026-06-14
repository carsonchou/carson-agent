// 清掉圖表上所有殘留策略/指標，再驗證 champion_r5 能否乾淨上圖、抓到「自己的」數字。
import { chromium } from 'playwright';
import fs from 'fs';
const code = fs.readFileSync('triple_supertrend_v4_champion_r5.pine', 'utf8');
const expectTitle = (code.match(/strategy\s*\(\s*["']([^"']+)["']/) || [])[1] || null;
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = { expectTitle, log: [], legendBefore: 0, legendAfter: 0, metrics: {}, titleMatch: null };
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
try {
  await page.goto('https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT&interval=240', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }

  // === 清除所有圖例研究項（study 列，class 含 item- 與 study-）===
  const legendSel = '[class*="item-"][class*="study-"]';
  out.legendBefore = await page.locator(legendSel).count().catch(() => 0);
  for (let pass = 0; pass < 15; pass++) {
    const items = page.locator(legendSel);
    const n = await items.count().catch(() => 0);
    if (n === 0) break;
    const it = items.first();
    await it.hover({ timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(400);
    // Remove 鈕是 hover 才顯示的浮動工具列、非 item 子元素→點頁面層級「可見」的那個
    const del = page.locator('button[aria-label="Remove" i]:visible, button[title="Remove" i]:visible').first();
    let clicked = false;
    try { await del.click({ timeout: 2000 }); clicked = true; } catch {}
    out.log.push('pass' + pass + ' n=' + n + ' del=' + clicked);
    await page.waitForTimeout(700);
  }
  out.legendAfter = await page.locator(legendSel).count().catch(() => 0);
  await page.screenshot({ path: 'tv_clean_1cleaned.png' }).catch(() => {});

  // === 注入 champion_r5 + Add to chart ===
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  const ed = page.locator('.monaco-editor').first(); const box = await ed.boundingBox().catch(() => null);
  if (box) await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(400);
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(300);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(() => {});
  await page.keyboard.press('Control+V'); await page.waitForTimeout(3000);
  await page.locator('[title="Add to chart" i]').first().click({ timeout: 10000 }).catch(() => out.log.push('add fail'));
  await page.waitForTimeout(13000);
  await page.screenshot({ path: 'tv_clean_2added.png' }).catch(() => {});

  const bodyText = await page.locator('body').innerText().catch(() => '');
  fs.writeFileSync('tv_clean_panel.txt', bodyText);
  const lines = bodyText.split('\n').map(s => s.trim()).filter(Boolean);
  const PCT = /-?[0-9][0-9,]*\.?[0-9]*\s*%/, NUM = /-?[0-9][0-9,]*\.?[0-9]+/;
  const idxOf = (re) => lines.findIndex(l => re.test(l));
  const nx = (i, re) => { if (i < 0) return null; for (let j = i + 1; j < Math.min(i + 6, lines.length); j++) { const m = lines[j].match(re); if (m) return m[0].replace(/\s/g, ''); } return null; };
  out.metrics = { netProfit: nx(idxOf(/^Total PnL$/), PCT), maxDrawdown: nx(idxOf(/^Max drawdown$/), PCT), sharpe: nx(idxOf(/^Sharpe ratio$/), NUM), profitFactor: nx(idxOf(/^Profit factor$/), NUM), returnOverMaxDD: nx(idxOf(/^Return of max drawdown$/), NUM) };
  const wl = lines.find(l => /^\d+\/\d+$/.test(l)); if (wl) out.metrics.totalTrades = wl.split('/')[1];
  out.titleMatch = expectTitle ? bodyText.includes(expectTitle) : null;
  // 也找錯誤
  const errLine = lines.find(l => /could not find|function or function reference|compilation error|line \d+:/i.test(l));
  if (errLine) out.compileError = errLine.slice(0, 200);
} catch (e) { out.log.push('EXC: ' + e.message); }
fs.writeFileSync('tv_clean.json', JSON.stringify(out, null, 2));
console.log('legendBefore=' + out.legendBefore + ' legendAfter=' + out.legendAfter + ' titleMatch=' + out.titleMatch + ' err=' + (out.compileError || 'none') + ' metrics=' + JSON.stringify(out.metrics));
await ctx.close();
