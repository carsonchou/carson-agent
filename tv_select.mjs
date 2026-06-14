// 不移除舊策略——注入 champion_r5 上圖後，點「我們這支」的圖例項讓 tester 切換到它。
// 同時驗證是否編譯(沒出現在圖例=編譯失敗)。
import { chromium } from 'playwright';
import fs from 'fs';
const pineFile = process.argv[2] || 'triple_supertrend_v4_champion_clean.pine';
const code = fs.readFileSync(pineFile, 'utf8');
const expectTitle = (code.match(/strategy\s*\(\s*["']([^"']+)["']/) || [])[1] || null;
const shortTitle = (code.match(/shorttitle\s*=\s*["']([^"']+)["']/) || [])[1] || expectTitle;
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = { expectTitle, log: [], legendNames: [], clickedOurs: false, metrics: {}, titleMatch: null };
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
try {
  const symbol = process.argv[3] || 'BINANCE:BTCUSDT';
  const tf = process.argv[4] || '240';
  await page.goto('https://www.tradingview.com/chart/?symbol=' + encodeURIComponent(symbol) + '&interval=' + tf, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }

  // 注入 + 上圖
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  const ed = page.locator('.monaco-editor').first(); const ebox = await ed.boundingBox().catch(() => null);
  if (ebox) await page.mouse.click(ebox.x + ebox.width / 2, ebox.y + ebox.height / 2);
  await page.waitForTimeout(400);
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(300);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(() => {});
  await page.keyboard.press('Control+V'); await page.waitForTimeout(3000);
  await page.locator('[title="Add to chart" i], [title="Update on chart" i], [data-name="add-script-to-chart"]').first().click({ timeout: 10000 }).catch(() => out.log.push('add fail'));
  await page.waitForTimeout(14000); // 等編譯+回測

  // dump 圖例 study 名稱
  const studySel = '[class*="item-"][class*="study-"]';
  out.legendNames = await page.locator(studySel).allInnerTexts().catch(() => []);
  out.legendNames = out.legendNames.map(s => s.replace(/\s+/g, ' ').trim().slice(0, 40));
  // 找含 v15 / TRANSCEND / Triple SuperTrend 的圖例項並點它(切換 tester)
  const ours = page.locator(studySel).filter({ hasText: new RegExp((shortTitle || 'Champion').replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') }).first();
  if (await ours.count().catch(() => 0)) { await ours.click({ timeout: 4000 }).catch(() => out.log.push('click ours fail')); out.clickedOurs = true; await page.waitForTimeout(4000); }
  else out.log.push('我們的策略不在圖例→可能編譯失敗');
  await page.screenshot({ path: 'tv_select.png' }).catch(() => {});

  const bodyText = await page.locator('body').innerText().catch(() => '');
  fs.writeFileSync('tv_select_panel.txt', bodyText);
  const lines = bodyText.split('\n').map(s => s.trim()).filter(Boolean);
  const PCT = /[-−]?[0-9][0-9,]*\.?[0-9]*\s*%/, NUM = /[-−]?[0-9][0-9,]*\.?[0-9]+/;
  const idxOf = (re) => lines.findIndex(l => re.test(l));
  const nx = (i, re) => { if (i < 0) return null; for (let j = i + 1; j < Math.min(i + 6, lines.length); j++) { const m = lines[j].match(re); if (m) return m[0].replace(/\s/g, ''); } return null; };
  out.metrics = { netProfit: nx(idxOf(/^Total PnL$/), PCT), maxDrawdown: nx(idxOf(/^Max drawdown$/), PCT), sharpe: nx(idxOf(/^Sharpe ratio$/), NUM), profitFactor: nx(idxOf(/^Profit factor$/), NUM), returnOverMaxDD: nx(idxOf(/^Return of max drawdown$/), NUM) };
  const wl = lines.find(l => /^\d+\/\d+$/.test(l)); if (wl) out.metrics.totalTrades = wl.split('/')[1];
  out.titleMatch = expectTitle ? bodyText.includes(expectTitle) : null;
  const errLine = lines.find(l => /could not find|function or function reference|compilation|line \d+:/i.test(l)); if (errLine) out.compileError = errLine.slice(0, 200);
} catch (e) { out.log.push('EXC: ' + e.message); }
fs.writeFileSync('tv_select.json', JSON.stringify(out, null, 2));
console.log('legendNames=' + JSON.stringify(out.legendNames) + ' clickedOurs=' + out.clickedOurs + ' titleMatch=' + out.titleMatch + ' err=' + (out.compileError || 'none') + ' metrics=' + JSON.stringify(out.metrics));
await ctx.close();
