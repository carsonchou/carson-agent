// 一次性登入：開一個「持久化」Chromium，讓你手動登入 TradingView 一次。
// 之後 tv_backtest.mjs 會沿用同一個 profile，自動回測不需再登入。
// 用法（醒來時跑一次）：  node tv_login.mjs
//
// 重要：本腳本【絕不自動關閉視窗】。TradingView 連訪客都會發 sessionid cookie，
// 用 cookie 自動判斷會誤判、提早關窗打斷登入。所以改成：你登好後【自己關掉視窗】
// （或在這個終端按 Ctrl+C），session 會自動寫入持久化 profile。最多等 20 分鐘。
import { chromium } from 'playwright';

const USER_DATA = 'D:/carson-agent/.pw_tvprofile';

const ctx = await chromium.launchPersistentContext(USER_DATA, {
  headless: false,
  viewport: { width: 1600, height: 900 },
  args: ['--start-maximized'],
});
const page = ctx.pages()[0] || await ctx.newPage();
await page.goto('https://www.tradingview.com/#signin', { waitUntil: 'domcontentloaded' }).catch(() => {});

console.log('====================================================');
console.log(' 請在打開的瀏覽器中手動登入 TradingView（建議用 Email + 密碼）。');
console.log(' 【登完後請自己關掉瀏覽器視窗】——這個腳本不會自動關你，');
console.log(' session 會自動寫入持久化 profile，關掉就完成。最多等 20 分鐘。');
console.log('====================================================');

// 只等「使用者自己關閉視窗」或逾時，期間絕不主動關閉。
let closedByUser = false;
ctx.on('close', () => { closedByUser = true; });
const start = new Date().getTime();
let loggedInSeen = false;
while (new Date().getTime() - start < 1200000 && !closedByUser) {
  await page.waitForTimeout(5000).catch(() => {});
  // 僅「觀測並回報」登入狀態，方便你知道有沒有登成功；但【不據此關閉視窗】。
  // 用 sessionid_sign（已登入才有的簽章 cookie）來區分真正登入 vs 訪客 sessionid。
  let cookies = [];
  try { cookies = await ctx.cookies('https://www.tradingview.com'); } catch { break; }
  const signed = cookies.find(c => c.name === 'sessionid_sign' && c.value && c.value.length > 5);
  if (signed && !loggedInSeen) { loggedInSeen = true; console.log('OK_LOGGED_IN_DETECTED（已偵測到登入；你登完自己關視窗即可）'); }
}
console.log(closedByUser ? 'WINDOW_CLOSED_BY_USER' : 'LOGIN_WAIT_TIMEOUT');
console.log((loggedInSeen ? 'LOGIN_CONFIRMED (sessionid_sign present)' : 'LOGIN_UNCONFIRMED (沒偵測到 sessionid_sign，可能沒登成功)'));
console.log('LOGIN_PROFILE_SAVED at ' + USER_DATA);
try { await ctx.close(); } catch {}
