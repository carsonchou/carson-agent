async (page) => {
  const targets = [
 {
  "vid": "tDanOnIWAfo",
  "next": "O4RrqbtFw1A",
  "q": "定投微笑曲線要等多久",
  "disc": "定投微笑",
  "nslug": "L_定投微笑曲線要等多久才會笑三次熊市實測底部平均撐了這"
 },
 {
  "vid": "0Gy7jec6Agc",
  "next": "Vd3pOcDFhFQ",
  "q": "頎邦",
  "disc": "6147",
  "nslug": "L_個股體檢頎邦6147存18年賺14倍但799暴跌風險"
 },
 {
  "vid": "p6Qvg2mC-9w",
  "next": "-n7dhw_qfLQ",
  "q": "華通",
  "disc": "2313",
  "nslug": "L_華通2313存20年翻31倍但805暴跌風險你敢抱嗎"
 },
 {
  "vid": "-_aUs0oj1o0",
  "next": "jDjuUXeSx98",
  "q": "南亞",
  "disc": "1303",
  "nslug": "L_個股體檢南亞13031303長抱20年賺8倍卻曾套牢"
 },
 {
  "vid": "l36tPQliBSc",
  "next": "WFJoOC-4izg",
  "q": "群創",
  "disc": "3481",
  "nslug": "L_群創3481存20年報酬僅598長期投資的隱藏風險個"
 },
 {
  "vid": "MTPczTWeZ74",
  "next": "u1QIf5a21K0",
  "q": "崩盤別逃崩到阱底反而",
  "disc": "0050",
  "nslug": "L_0050崩盤別逃崩到阱底反而要買新冠加2022熊市回"
 },
 {
  "vid": "B1VfToi_HdY",
  "next": "rizhPQWp3Sk",
  "q": "世芯-KY",
  "disc": "3661",
  "nslug": "L_個股體檢世芯-KY36613661上市13年暴漲10"
 },
 {
  "vid": "J5pDfPc9w7A",
  "next": "_GgxPgLzsKQ",
  "q": "凱美",
  "disc": "2375",
  "nslug": "L_個股體檢凱美2375存15年賺289年化91背後的7"
 },
 {
  "vid": "mvNh7IjgRLY",
  "next": "FYpVo6KawFE",
  "q": "台新新光金",
  "disc": "2887",
  "nslug": "L_個股體檢台新新光金2887臺新新光金288720年報"
 },
 {
  "vid": "Vd3pOcDFhFQ",
  "next": "J_VtZrDPZB8",
  "q": "合晶",
  "disc": "6182",
  "nslug": "L_個股體檢合晶6182你的合晶6182套牢18年還倒賠"
 }
];
  const START = 2, END = START + 2;        // 每批 2 支(MCP 呼叫 120s 硬超時,10 支跑不完)
  const results = [];
  const T = (ms) => page.waitForTimeout(ms);

  for (const t of targets.slice(START, END)) {
    try {
      // 導航前先掛 dialog 處理(未存變更會跳 beforeunload)
      page.once('dialog', d => d.accept().catch(() => {}));
      await page.goto('https://studio.youtube.com/video/' + t.vid + '/editor',
                      { waitUntil: 'domcontentloaded' });
      await T(2200);

      // 「開始使用」導覽浮層會吃掉點擊,先用最小元素法點掉(ytcp-button locator 抓不到)
      await page.evaluate(() => {
        const els = [...document.querySelectorAll('*')]
          .filter(e => e.offsetParent && (e.textContent || '').trim() === '開始使用'
                  && e.children.length <= 1);
        if (!els.length) return;
        let el = els[0];
        for (let i = 0; i < 5 && el; i++) {
          if (el.tagName === 'BUTTON' || el.tagName === 'YTCP-BUTTON'
              || el.getAttribute('role') === 'button') break;
          el = el.parentElement;
        }
        (el || els[0]).click();
      });
      await T(1800);

      // 🔴 正確入口是「片尾」列右側的 [+] YTCP-ICON-BUTTON,點文字沒有用
      //    (實測:點文字→面板不開;點列內 icon-button→套用範本選單出現)
      await page.evaluate(() => {
        const rows = [...document.querySelectorAll('*')]
          .filter(e => e.offsetParent && (e.textContent || '').trim() === '片尾'
                  && e.children.length <= 1);
        let row = rows.length ? rows[0] : null;
        for (let i = 0; i < 8 && row; i++) {
          const btn = row.querySelector
            && row.querySelector('button, ytcp-icon-button, [role="button"]');
          if (btn && btn.offsetParent
              && (btn.textContent || '').trim() !== '片尾') { btn.click(); return; }
          row = row.parentElement;
        }
      });
      await T(2200);

      const body = await page.evaluate(() => document.body.innerText);
      if (body.includes('影片: ')) {          // 已有影片元素 → 冪等跳過
        results.push([t.vid, 'already-has-element']);
        continue;
      }
      if (!/套用範本|新增元素/.test(body)) {
        results.push([t.vid, 'endscreen-panel-not-found']);
        continue;
      }

      // 點「影片」元素(TP-YT-PAPER-ITEM)
      await page.evaluate(() => {
        const els = [...document.querySelectorAll('tp-yt-paper-item')]
          .filter(e => (e.textContent || '').trim() === '影片' && e.offsetParent);
        if (els.length) els[0].click();
      });
      await T(1500);

      // 「選擇特定影片」
      const radio = page.locator('tp-yt-paper-radio-button', { hasText: '選擇特定影片' }).first();
      await radio.click({ timeout: 8000 });
      await T(1500);

      // 搜尋下一集(標題關鍵字;URL 搜不到,白老鼠實測)
      await page.locator('#search-yours').fill(t.q);
      await page.locator('#search-yours').press('Enter');
      await T(2200);

      // 選 aria-label 含判別碼的卡
      const cards = page.locator('ytcp-entity-card[role="option"]');
      const n = await cards.count();
      let picked = false;
      for (let i = 0; i < n; i++) {
        const al = (await cards.nth(i).getAttribute('aria-label')) || '';
        if (al.includes(t.disc)) { await cards.nth(i).click(); picked = true; break; }
      }
      if (!picked) {
        results.push([t.vid, 'card-not-found(n=' + n + ')']);
        await page.keyboard.press('Escape'); await T(800);
        // 捨棄未存的半成品,不留髒狀態
        try {
          await page.locator('ytcp-button', { hasText: '捨棄變更' }).first().click({ timeout: 3000 });
          await T(800);
          await page.locator('ytcp-button', { hasText: '捨棄' }).last().click({ timeout: 3000 });
        } catch (e) {}
        continue;
      }
      await T(1500);

      // 儲存
      await page.locator('ytcp-button', { hasText: '儲存' }).first().click({ timeout: 8000 });
      await T(2200);
      const after = await page.evaluate(() => document.body.innerText);
      results.push([t.vid, after.includes('捨棄變更') ? 'MAYBE-NOT-SAVED' : 'saved:' + t.q]);
    } catch (e) {
      results.push([t.vid, 'err:' + String(e).slice(0, 90)]);
      try { await page.keyboard.press('Escape'); } catch (_) {}
    }
  }
  return results;
}
