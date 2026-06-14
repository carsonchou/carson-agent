// 連進常駐視窗(CDP 9222)截圖目前畫面，不動任何東西。用法：node tv_shot.mjs [outPng]
import { chromium } from 'playwright';
const out = process.argv[2] || 'tv_now.png';
const browser = await chromium.connectOverCDP('http://localhost:9222');
const ctx = browser.contexts()[0];
const pages = ctx.pages();
const page = pages[pages.length - 1] || await ctx.newPage();
await page.screenshot({ path: out }).catch(e => console.log('shotErr=' + e.message));
const url = page.url();
let bodyText = '';
try { bodyText = (await page.locator('body').innerText()).slice(0, 600); } catch {}
console.log('URL=' + url);
console.log('PAGES=' + pages.length);
console.log('TEXT_HEAD=' + bodyText.replace(/\n+/g, ' | '));
await browser.close(); // 只斷線，不關窗
