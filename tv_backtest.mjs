// 自動回測抓數據（v3，注入已驗證可行）：
//   連進常駐視窗(CDP 9222) → 開乾淨圖表 → 確保 Pine 面板開 → insertText 注入策略 →
//   行號指示器驗證注入 → Add to chart → Strategy Tester → 行解析 Performance。
// 前置：先 node tv_browser.mjs 開常駐視窗並登入(需 sessionid_sign)。
// 用法：node tv_backtest.mjs <pineFile> [symbol] [timeframe] [outJson]
import { chromium } from 'playwright';
import fs from 'fs';

const [pineFile, symbol = 'BINANCE:BTCUSDT', tf = '240', outJson = 'metrics.json'] = process.argv.slice(2);
if (!pineFile || !fs.existsSync(pineFile)) { console.log('ERR no pine file: ' + pineFile); process.exit(1); }
const code = fs.readFileSync(pineFile, 'utf8');
const codeLines = code.split('\n').length;
const expectTitle = (code.match(/strategy\s*\(\s*["']([^"']+)["']/) || [])[1] || null;
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';

// 單進程設計：直接開已登入的持久化 profile（一次只跑一個，免 CDP、免雙視窗衝突）。
// 前置：確保沒有其他進程佔用 profile（tv_browser/舊視窗都要先關）。
const browser = null, ownCtx = true;
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const _pages = ctx.pages();
const page = _pages.find(p => p.url().includes('/chart')) || _pages[_pages.length - 1] || await ctx.newPage();
await page.bringToFront().catch(() => {});
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const result = { pineFile, symbol, tf, expectTitle, codeLines, ok: false, loggedIn: false, editorHasCode: false, injectedLine: null, metrics: {}, notes: [], reusedWindow: !ownCtx };
const editorVisible = async () => { try { return (await page.locator('.monaco-editor').count()) > 0 && await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };

try {
  await page.goto(`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}&interval=${tf}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);

  let cookies = []; try { cookies = await ctx.cookies('https://www.tradingview.com'); } catch {}
  result.loggedIn = !!cookies.find(c => c.name === 'sessionid_sign' && c.value && c.value.length > 5);
  if (!result.loggedIn) { result.notes.push('未登入：找不到 sessionid_sign'); fs.writeFileSync(outJson, JSON.stringify(result, null, 2)); console.log('NEED_LOGIN'); if (ownCtx) await ctx.close(); else if (browser) await browser.close(); process.exit(2); }

  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 800 }).catch(() => {}); }

  // 確保 Pine 編輯器開著——導航後 UI 重置，需重試開啟並驗證
  for (let attempt = 0; attempt < 4 && !(await editorVisible()); attempt++) {
    await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(3500);
  }
  result.editorOpened = await editorVisible();
  if (!result.editorOpened) result.notes.push('Pine 編輯器仍未顯示(4 次重試後)');
  await page.screenshot({ path: outJson.replace(/\.json$/, '') + '_pre.png' }).catch(() => {}); // 注入前診斷截圖

  // 聚焦 Monaco、全選清空、insertText 注入
  await page.locator('.monaco-editor').first().click({ timeout: 12000 }).catch(() => result.notes.push('Monaco 聚焦失敗'));
  await page.waitForTimeout(500);
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(400);
  await page.keyboard.insertText(code);
  await page.waitForTimeout(2000);

  // 鐵證：行號指示器 Line N 應 ≈ codeLines
  const lineInd = await page.locator('text=/Line \\d+, Col \\d+/').first().innerText().catch(() => '');
  const lm = lineInd.match(/Line\s+(\d+)/); result.injectedLine = lm ? +lm[1] : null;
  result.editorHasCode = result.injectedLine != null && result.injectedLine >= Math.floor(codeLines * 0.8);
  if (!result.editorHasCode) result.notes.push('注入未確認(lineInd=' + lineInd + ')');

  // Add to chart
  await page.locator('button:has-text("Add to chart"), [data-name="add-script-to-chart"]').first().click({ timeout: 15000 }).catch(() => result.notes.push('點不到 Add to chart'));
  await page.waitForTimeout(13000); // 編譯 + 回測

  // 開 Strategy Tester
  const stTab = page.locator('[data-name="backtesting"], button:has-text("Strategy Tester"), [role="tab"]:has-text("Strategy Tester"), text=/Strategy Tester/i').first();
  await stTab.click({ timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(3500);

  // 抓全頁文字
  const bodyText = await page.locator('body').innerText().catch(() => '');
  fs.writeFileSync(outJson.replace(/\.json$/, '') + '_panel.txt', bodyText);

  // 行解析（TradingView「Key stats」：標籤一行、數值在下一行）
  const lines = bodyText.split('\n').map(s => s.trim()).filter(Boolean);
  const PCT = /-?[0-9][0-9,]*\.?[0-9]*\s*%/;
  const NUM = /-?[0-9][0-9,]*\.?[0-9]+/;
  const idxOf = (re) => lines.findIndex(l => re.test(l));
  const nextMatch = (i, re) => { if (i < 0) return null; for (let j = i + 1; j < Math.min(i + 6, lines.length); j++) { const mm = lines[j].match(re); if (mm) return mm[0].replace(/\s/g, ''); } return null; };
  result.metrics.netProfit = nextMatch(idxOf(/^Total PnL$/), PCT);
  result.metrics.maxDrawdown = nextMatch(idxOf(/^Max drawdown$/), PCT);
  result.metrics.percentProfitable = nextMatch(idxOf(/^Profitable trades$/), PCT);
  result.metrics.profitFactor = nextMatch(idxOf(/^Profit factor$/), NUM);
  result.metrics.sharpe = nextMatch(idxOf(/^Sharpe ratio$/), NUM);
  result.metrics.sortino = nextMatch(idxOf(/^Sortino ratio$/), NUM);
  result.metrics.returnOverMaxDD = nextMatch(idxOf(/^Return of max drawdown$/), NUM);
  const wl = lines.find(l => /^\d+\/\d+$/.test(l));
  if (wl) { const [w, t] = wl.split('/'); result.metrics.winningTrades = w; result.metrics.totalTrades = t; }
  else { result.metrics.totalTrades = nextMatch(idxOf(/^Total trades$/), NUM); }

  // 比對策略標題（防殘留污染）：tester 文字是否含我們的 title
  if (expectTitle) result.titleMatch = bodyText.includes(expectTitle);

  await page.screenshot({ path: outJson.replace(/\.json$/, '') + '_tester.png' }).catch(() => {});
  result.ok = result.editorHasCode && Object.values(result.metrics).some(v => v != null);
  if (!result.ok) result.notes.push('未取得有效數值——見 _panel.txt / _tester.png。');
} catch (e) { result.notes.push('EXCEPTION: ' + e.message); }
finally {
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result.metrics) + ' editorHasCode=' + result.editorHasCode + ' injectedLine=' + result.injectedLine + ' titleMatch=' + result.titleMatch);
  console.log('SAVED ' + outJson + ' ok=' + result.ok);
  // 重用常駐視窗時【絕不關閉】——browser.close() 在 connectOverCDP 下可能殺掉視窗。只在自己開的後備 context 才關。
  if (ownCtx) { await ctx.close().catch(() => {}); }
  // 重用時不做任何關閉動作，process 結束自然斷線、視窗保留。
}
