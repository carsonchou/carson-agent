// 輕量探針：只檢查持久化 profile 是否真的登入了 TradingView（有沒有 sessionid_sign）。
// 不開可見視窗、不動任何東西。用法：node tv_probe.mjs
import { chromium } from 'playwright';
const USER_DATA = 'D:/carson-agent/.pw_tvprofile';
const ctx = await chromium.launchPersistentContext(USER_DATA, { headless: true });
let cookies = [];
try { cookies = await ctx.cookies('https://www.tradingview.com'); } catch {}
const names = cookies.map(c => c.name);
const signed = cookies.find(c => c.name === 'sessionid_sign' && c.value && c.value.length > 5);
const sid = cookies.find(c => c.name === 'sessionid' && c.value && c.value.length > 10);
console.log('HAS_sessionid=' + !!sid + ' HAS_sessionid_sign=' + !!signed);
console.log('LOGGED_IN=' + (!!signed));
console.log('cookie_names=' + names.join(','));
await ctx.close();
