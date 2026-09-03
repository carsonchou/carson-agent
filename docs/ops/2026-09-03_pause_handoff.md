# 基建線(non.)停機交接 — 2026-09-03(Carson 裁決:暫停,非收線)

> **狀態更新:已於同日恢復(督導驅動)。本檔保留作為暫停時點的狀態快照,勿刪。**
> 恢復時督導盤點出本檔「會自己動的東西」漏了兩項:①premises.md 第 1 條(多發×單支觀看,main ch. 09-15 出結果)——別條線在跑、不需人推動就會發生,且落在 verified 配額申請書上;②ntfy 通道從未被真事件端到端驗證過(只走過 [DRILL]),若它是死的,無聲失效面就有兩個。②的答案見沙箱測試 V4(結果回填於此:____)。

> 給零脈絡後手:重點是**不要重做什麼**。細節都在被指到的檔案裡,別重推導。

## 停在哪

- **配額申請包** `youtube_channel/docs/yt_quota_increase_2026-09.md`:**verified 可交 Carson**(v3 三輪+09-03 對帳後 v4 兩輪全 PASS)。送出日**零證據=未送出**,證據門檻三選一寫在 `2026-09-02_handoff.md`。**不要重驗、不要改數字**——每個數字都指得回 ops_log 行號。
- **RAM 決策包** `docs/ram-upgrade-decision-2026-09.md`:**verified**(09-03 因果更正後 inv-audit 確認)。
- **行動單** `docs/carson-two-actions-2026-09-02.md`:三件(送表單/買 RAM/重授權 google_token),督導已送 Carson 手機,三件皆零回音。
- **節流建議** `docs/inventory-throttle-brief-2026-09-03.md`:已交 w9,w9 同意方向;**是否已改排程未知**,生效觀測第一天(09-03 15:20)還沒到。
- 做到一半:僅一個 session 內監視(等今日 15:20 守望行,session 亡則消失,無實害——守望本身照跑)。其餘**無**。

## 暫停期間會自己動的東西(逐項:沒人看著它時會怎樣)

1. **`carson-quota-ceiling-watch`(Windows Task Scheduler,每日 15:20)**:照跑,每天寫一行到 `docs/ops/quota-ceiling-watch.log`(天花板+長片渲染數+庫存)。提額核准時印 🎉 並**推 ntfy 到 Carson 手機**(讀 STUDIO/design_system.json 的 topic,不依賴任何 session)。⚠️ 兩個已知假警報面(帳本遺失/牆日被標 unreliable)行內自帶判別文字。**唯一無聲失效面:log 出現日期空洞=守望自己死了,沒有任何東西會通知**——後手接線第一件事就是看日期連續性。
2. **09-05 premises.md 刪條**(ch3 已結案條;09-15 另有範例條):**這不是排程,是寫在條目裡的人工動作**,沒有 session 執行就不會發生。條目自己寫著誰、哪天、做什麼,任何線讀到可代執行;不執行的後果=登記處囤兩條死條目,無實害。
3. **w9 側的三件**(節流採用、7 支 prompt 洩漏片處置、發布端日期戳):全在 w9 線上,非本線資產,別越界碰。
4. 本線**沒有**掛任何東西進 local_cron / crontab.txt / 產線。
5. (09-03 恢復後補)**「重開機後 local_cron 會自動起來」至今未驗**——watchdog 的 LogonTrigger 面沙箱測不到;下次重開機(RAM 安裝必然發生)是計畫中的觀測窗口,見 premises.md 該條。裝完 RAM 重開後**先查這個再做別的**。

## 重啟時第一件該做的事

讀 `docs/ops/quota-ceiling-watch.log` 最新一行與日期連續性(核准了沒+守望活著沒),再確認 Carson 行動單三件的狀態——**等待條件不會自己通知你它已滿足**(premises.md 守則 4)。
