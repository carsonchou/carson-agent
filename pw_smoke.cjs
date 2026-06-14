const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ headless: true });
  const p = await b.newPage();
  try {
    await p.goto('https://www.tradingview.com/', { timeout: 45000, waitUntil: 'domcontentloaded' });
    const title = await p.title();
    console.log('TV_REACHABLE title=' + title);
    await p.screenshot({ path: 'pw_tv_smoke.png' });
    console.log('screenshot saved pw_tv_smoke.png');
  } catch (e) {
    console.log('ERR ' + e.message);
  } finally { await b.close(); }
})();
