// 注入診斷：把策略碼塞進 Pine 編輯器，用「Line N, Col M」行號指示器當鐵證確認有沒有進去。
import { chromium } from 'playwright';
import fs from 'fs';
const pineFile = process.argv[2] || 'triple_supertrend_v4_teamA.pine';
const code = fs.readFileSync(pineFile, 'utf8');
const codeLines = code.split('\n').length;
const browser = await chromium.connectOverCDP('http://localhost:9222');
const ctx = browser.contexts()[0];
const pages = ctx.pages();
const page = pages.find(p => p.url().includes('/chart')) || pages[pages.length - 1];
await page.bringToFront();
page.on('dialog', d => d.accept().catch(() => {}));
const log = [];
try {
  // 1. 確保 Pine 面板「開著」——只在沒開時才點開，避免盲點把它關掉
  let panel = await page.locator('[data-name="pine-dialog"]').count();
  log.push('panel_before=' + panel);
  if (!panel) { await page.locator('[data-name="pine-dialog-button"]').first().click({ timeout: 10000 }).catch(e => log.push('openErr=' + e.message)); await page.waitForTimeout(3500); }
  panel = await page.locator('[data-name="pine-dialog"]').count();
  log.push('panel_after=' + panel);
  // 2. 聚焦程式碼區
  await page.locator('[data-name="pine-dialog"] .view-lines, [data-name="pine-dialog"] .monaco-editor').first().click({ timeout: 8000 }).catch(e => log.push('focusErr=' + e.message));
  await page.waitForTimeout(500);
  // 3. 全選清空
  await page.keyboard.press('Control+A'); await page.keyboard.press('Delete'); await page.waitForTimeout(400);
  // 4. 注入
  await page.keyboard.insertText(code);
  await page.waitForTimeout(2000);
  // 5. 鐵證：行號指示器
  const lineInd = await page.locator('text=/Line \\d+, Col \\d+/').first().innerText().catch(() => '(none)');
  log.push('codeLines=' + codeLines + ' lineIndicator=[' + lineInd + ']');
  await page.keyboard.press('Control+Home'); await page.waitForTimeout(800);
  await page.screenshot({ path: 'tv_inject.png' });
} catch (e) { log.push('EXC=' + e.message); }
console.log(log.join(' | '));
await browser.close();
