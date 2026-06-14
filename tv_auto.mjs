// 全自動回測（連進常駐 CDP 視窗）：開圖表→開Pine→直接 focus Monaco inputarea→insertText→
//   行號驗證→Add to chart→Strategy Tester→行解析。每步存截圖，process.exit 不殺視窗。
// 前置：tv_browser.mjs 開著(CDP 9222)且已登入。
// 用法：node tv_auto.mjs <pineFile> [symbol] [tf] [outJson]
import { chromium } from 'playwright';
import fs from 'fs';
const [pineFile, symbol = 'BINANCE:BTCUSDT', tf = '240', outJson = 'metrics.json'] = process.argv.slice(2);
if (!pineFile || !fs.existsSync(pineFile)) { console.log('ERR no pine: ' + pineFile); process.exit(1); }
const code = fs.readFileSync(pineFile, 'utf8');
const codeLines = code.split('\n').length;
const expectTitle = (code.match(/strategy\s*\(\s*["']([^"']+)["']/) || [])[1] || null;
const base = outJson.replace(/\.json$/, '');
const result = { pineFile, symbol, tf, expectTitle, codeLines, ok: false, loggedIn: false, editorOpened: false, editorHasCode: false, injectedLine: null, titleMatch: null, metrics: {}, notes: [], step: '' };

// 單進程：自己開已登入的持久化視窗（免 CDP、不依賴脆弱常駐窗）。前置：profile 不能被別的進程佔用。
const browser = null;
const ctx = await chromium.launchPersistentContext('D:/carson-agent/.pw_tvprofile', { headless: false, viewport: { width: 1680, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' }).catch(() => {});
const pages = ctx.pages();
const page = pages.find(p => p.url().includes('/chart')) || pages[pages.length - 1] || await ctx.newPage();
await page.bringToFront().catch(() => {});
page.on('dialog', async d => { try { await d.accept(); } catch {} });
const editorVisible = async () => { try { return await page.locator('.monaco-editor').first().isVisible(); } catch { return false; } };
const done = (codeExit) => { fs.writeFileSync(outJson, JSON.stringify(result, null, 2)); console.log('step=' + result.step + ' editorHasCode=' + result.editorHasCode + ' injectedLine=' + result.injectedLine + ' titleMatch=' + result.titleMatch + ' ok=' + result.ok + ' notes=' + result.notes.join('|')); process.exit(codeExit); };

try {
  result.step = 'nav';
  // 不導航（導航會重置編輯器並讓頁面不穩）。只在不在圖表頁時才導航一次。
  if (!page.url().includes('/chart')) {
    await page.goto(`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}&interval=${tf}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(10000);
  } else {
    await page.waitForTimeout(1500);
  }
  let ck = []; try { ck = await ctx.cookies('https://www.tradingview.com'); } catch {}
  result.loggedIn = !!ck.find(c => c.name === 'sessionid_sign' && c.value && c.value.length > 5);
  if (!result.loggedIn) { result.notes.push('未登入'); console.log('NEED_LOGIN'); done(2); }
  for (const b of await page.locator('[data-name^="toast-group-close-button"]').all()) { await b.click({ timeout: 600 }).catch(() => {}); }

  result.step = 'open-editor';
  for (let a = 0; a < 5 && !(await editorVisible()); a++) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 6000 }).catch(() => {}); await page.waitForTimeout(3000); }
  result.editorOpened = await editorVisible();
  await page.screenshot({ path: base + '_1open.png' }).catch(() => {});

  // 關鍵修正：用真實滑鼠點擊編輯器 bounding-box 中心，保證點進程式碼區、拿到焦點
  result.step = 'focus';
  const ed = page.locator('.monaco-editor').first();
  const box = await ed.boundingBox().catch(() => null);
  if (box) { await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2); result.notes.push('mouseClick @' + Math.round(box.x + box.width / 2) + ',' + Math.round(box.y + box.height / 2)); }
  else result.notes.push('editor bbox null');
  await page.waitForTimeout(500);

  // 注入：clipboard 貼上(Ctrl+V) 對大量程式比 insertText 可靠（診斷確認 1834 行 OK）
  result.step = 'inject';
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(400);
  await page.evaluate(t => navigator.clipboard.writeText(t), code).catch(() => result.notes.push('clipWrite fail'));
  await page.keyboard.press('Control+V');
  await page.waitForTimeout(3500);
  let lineInd = '';
  for (let a = 0; a < 3 && !lineInd; a++) { lineInd = await page.locator('text=/Line \\d+, Col \\d+/').first().innerText().catch(() => ''); if (!lineInd) await page.waitForTimeout(800); }
  const lm = lineInd.match(/Line\s+(\d+)/); result.injectedLine = lm ? +lm[1] : null;
  result.editorHasCode = result.injectedLine != null && result.injectedLine >= Math.floor(codeLines * 0.8);
  result.notes.push('lineInd=[' + lineInd + ']');
  await page.screenshot({ path: base + '_2inject.png' }).catch(() => {});

  result.step = 'add';
  const addSel = '[title="Add to chart" i], [title*="Add to chart" i], button:has-text("Add to chart"), [data-name="add-script-to-chart"], [aria-label*="Add to chart" i]';
  let added = false;
  try { await page.locator(addSel).first().click({ timeout: 8000 }); added = true; } catch {}
  if (!added) { // 後備：Pine 編輯器工具列第一個 play-icon 鈕
    try { await page.locator('[data-name="pine-dialog"] [class*="toolbar"] button, .pine-editor button').first().click({ timeout: 4000 }); added = true; } catch {}
  }
  if (!added) result.notes.push('Add to chart 點不到');
  result.addClicked = added;
  await page.waitForTimeout(13000);
  await page.screenshot({ path: base + '_3added.png' }).catch(() => {});

  result.step = 'tester';
  await page.locator('[data-name="backtesting"], button:has-text("Strategy Tester"), [role="tab"]:has-text("Strategy Tester")').first().click({ timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(3500);
  const bodyText = await page.locator('body').innerText().catch(() => '');
  fs.writeFileSync(base + '_panel.txt', bodyText);
  const lines = bodyText.split('\n').map(s => s.trim()).filter(Boolean);
  const PCT = /-?[0-9][0-9,]*\.?[0-9]*\s*%/, NUM = /-?[0-9][0-9,]*\.?[0-9]+/;
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
  result.titleMatch = expectTitle ? bodyText.includes(expectTitle) : null;
  await page.screenshot({ path: base + '_4tester.png' }).catch(() => {});
  result.ok = result.editorHasCode && Object.values(result.metrics).some(v => v != null);
} catch (e) { result.notes.push('EXC@' + result.step + ': ' + e.message); }
done(0);
