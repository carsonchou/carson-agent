// 右鍵圖表 → 一鍵「移除指標」清掉全部 study，再單獨上 champion_r5 抓真實數字。
import { chromium } from 'playwright';
import fs from 'fs';
const code = fs.readFileSync('triple_supertrend_v4_champion_r5.pine', 'utf8');
const expectTitle = (code.match(/strategy\s*\(\s*["']([^"']+)["']/) || [])[1] || null;
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const page = ctx.pages()[0] || await ctx.newPage();
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const out = { expectTitle, log: [], menuItems: [], legendAfter: null, metrics: {}, titleMatch: null };
const studySel = '[class*="item-"][class*="study-"]';
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
try {
  await page.goto('https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT&interval=240', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }
  out.log.push('studiesBefore=' + await page.locator(studySel).count().catch(() => 0));

  // 右鍵圖表畫布 → 開啟 context menu
  const pane = page.locator('[data-name="pane-canvas"]').first();
  const box = await pane.boundingBox().catch(() => null);
  if (box) await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5, { button: 'right' });
  await page.waitForTimeout(1500);
  // dump menu 項目
  out.menuItems = await page.evaluate(() => {
    const r = [];
    document.querySelectorAll('[role="menuitem"], [class*="menu" i] [class*="item" i], [class*="contextMenu" i] *').forEach(e => { if (e.children.length === 0) { const t = (e.innerText || '').trim(); if (t && t.length < 30) r.push(t); } });
    return [...new Set(r)].slice(0, 40);
  });
  // 點「移除指標 / Remove indicators」
  const remItem = page.locator('[role="menuitem"]:has-text("移除指標"), [role="menuitem"]:has-text("Remove indicators"), [role="menuitem"]:has-text("移除"), [role="menuitem"]:has-text("Remove")').first();
  let remClicked = false;
  try { await remItem.click({ timeout: 3000 }); remClicked = true; } catch {}
  out.log.push('remClicked=' + remClicked);
  await page.waitForTimeout(1500);
  await page.keyboard.press('Escape').catch(() => {});
  out.legendAfter = await page.locator(studySel).count().catch(() => 0);
  await page.screenshot({ path: 'tv_clean3_1.png' }).catch(() => {});

  // 注入 + 上圖
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  const ed = page.locator('.monaco-editor').first(); const ebox = await ed.boundingBox().catch(() => null);
  if (ebox) await page.mouse.click(ebox.x + ebox.width / 2, ebox.y + ebox.height / 2);
  await page.waitForTimeout(400);
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(300);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(() => {});
  await page.keyboard.press('Control+V'); await page.waitForTimeout(3000);
  await page.locator('[title="Add to chart" i]').first().click({ timeout: 10000 }).catch(() => out.log.push('add fail'));
  await page.waitForTimeout(13000);
  await page.screenshot({ path: 'tv_clean3_2.png' }).catch(() => {});

  const bodyText = await page.locator('body').innerText().catch(() => '');
  fs.writeFileSync('tv_clean3_panel.txt', bodyText);
  const lines = bodyText.split('\n').map(s => s.trim()).filter(Boolean);
  const PCT = /-?[0-9][0-9,]*\.?[0-9]*\s*%/, NUM = /-?[0-9][0-9,]*\.?[0-9]+/;
  const idxOf = (re) => lines.findIndex(l => re.test(l));
  const nx = (i, re) => { if (i < 0) return null; for (let j = i + 1; j < Math.min(i + 6, lines.length); j++) { const m = lines[j].match(re); if (m) return m[0].replace(/\s/g, ''); } return null; };
  out.metrics = { netProfit: nx(idxOf(/^Total PnL$/), PCT), maxDrawdown: nx(idxOf(/^Max drawdown$/), PCT), sharpe: nx(idxOf(/^Sharpe ratio$/), NUM), profitFactor: nx(idxOf(/^Profit factor$/), NUM), returnOverMaxDD: nx(idxOf(/^Return of max drawdown$/), NUM) };
  const wl = lines.find(l => /^\d+\/\d+$/.test(l)); if (wl) out.metrics.totalTrades = wl.split('/')[1];
  out.titleMatch = expectTitle ? bodyText.includes(expectTitle) : null;
  const errLine = lines.find(l => /could not find|function or function reference|compilation|line \d+:/i.test(l)); if (errLine) out.compileError = errLine.slice(0, 200);
} catch (e) { out.log.push('EXC: ' + e.message); }
fs.writeFileSync('tv_clean3.json', JSON.stringify(out, null, 2));
console.log('legendAfter=' + out.legendAfter + ' titleMatch=' + out.titleMatch + ' err=' + (out.compileError || 'none') + ' metrics=' + JSON.stringify(out.metrics) + ' menu=' + JSON.stringify(out.menuItems));
await ctx.close();
