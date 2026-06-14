// 常駐瀏覽器：開一個持久化 + 遠端除錯埠(9222) 的 Chromium 並保持開著。
// 登入後【不要關】，所有回測腳本都會「連進這個視窗」跑，不再自己開關、不再搶 profile。
// 用法：node tv_browser.mjs   （登入態沿用 .pw_tvprofile；若沒登入就在這視窗手動登一次）
import { chromium } from 'playwright';
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, {
  headless: false,
  viewport: null,
  args: ['--remote-debugging-port=9222', '--start-maximized'],
});
const page = ctx.pages()[0] || await ctx.newPage();
await page.goto('https://www.tradingview.com/chart/', { waitUntil: 'domcontentloaded' }).catch(() => {});
console.log('====================================================');
console.log(' BROWSER_READY — CDP 已開在 http://localhost:9222');
console.log(' 這個視窗請【保持開著】，回測腳本會連進來跑。');
console.log(' 若還沒登入，就在這個視窗手動登入 TradingView 一次（Email 最穩）。');
console.log(' 全部跑完後，你自己關掉視窗即可。');
console.log('====================================================');
let closed = false; ctx.on('close', () => { closed = true; });
while (!closed) { await page.waitForTimeout(5000).catch(() => { closed = true; }); }
console.log('BROWSER_CLOSED');
