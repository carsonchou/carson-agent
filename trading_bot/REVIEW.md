# trading_bot Code Review（2026-06-25）

多 agent 平行 code review（風控 / 執行 / 協調+策略 三條線），聚焦「會虧錢或讓系統卡死」的正確性問題。
**誠實前提**：每個 review agent 只讀自己那塊，看不到 `coordinator` 的接線，因此**過度告警**了好幾項其實已處理的東西。下方分三類標注。

審查範圍：`risk/`、`execution/`、`orchestrator/coordinator.py`、`strategy/`。僅審查 + 安全修復，未改動金鑰或網路行為。

---

## ✅ 本輪已修（有測試，見 `tests/test_review_fixes.py`）

| 項 | 檔案:行 | 問題 | 修法 |
|----|---------|------|------|
| A | `risk/risk_manager.py:198` | `float(signal.confidence)` 遇 `confidence=None` 拋 TypeError → 整個 `evaluate` 崩潰，連停損都評估不到（fail-open） | None 視為 1.0 再 clamp |
| B | `risk/position_tracker.py:_save` | `write_text` 非原子寫入，寫到一半當機留半損毀 state（重啟部位變孤兒、停損消失） | temp 檔 + `os.replace` 原子置換 |
| C | `risk/position_tracker.py:_save / load` | `except: pass` 靜默吞掉持久化失敗/損毀 | 改記 `logger.error`（不再無聲） |
| D | `risk/position_tracker.py:record_fill` | 多 agent 並發對 `positions`/`realized` 做 read-modify-write 無鎖 → 部位漂移、損益重複或漏計 | 加 `threading.RLock` 序列化（測試：並發 200 筆無漏更新） |
| E | `risk/position_tracker.py:record_fill` | 非法成交（qty/price<=0）靜默 return，可能與交易所持倉分歧 | 改記 `logger.warning` |

回歸：原有 `test_risk_fixes.py` 16/16、`test_smoke.py` 8/8 全綠。

---

## 🟡 先前已處理（agent 過度告警，經核對程式碼確認無需再修）

- **「訂單冪等用隨機 id 會重複下單」** → `coordinator._prep_order`（L492-501）已產生決定性 `client_order_id = {sym}-{ts}-{action}`，executor 的 `uuid` 只是 fallback。同根同動作 → 同 id，交易所端可去重。
- **「已實現損益沒接回風控」** → `coordinator._account_fill`（L519-523）已 call `register_realized_pnl`。
- **「未確認成交照記帳」** → `_account_fill`（L508-516）已擋掉非 FILLED/PARTIALLY_FILLED 且 filled<=0 的情況並告警。
- **「實盤停損 entry_price=0 永不觸發」** → 已由 `PositionTracker` 提供真實 entry_price（見 `test_risk_fixes.py #2`）。
- **「市價單裸送無滑價保護」** → `LiveExecutor` 已把市價單轉保護限價（見 `test_risk_fixes.py #4`）。

---

## 🟠 真實但屬「架構級／會動到實盤行為」，建議你拍板再做（本輪刻意不自動改，避免動到live風控）

1. **當日回撤上限只看「已實現損益」，不含未實現浮虧**（`risk_manager.daily_loss_limit_hit`）。
   重倉抱大浮虧時回撤閘門不會關。安全修需先讓 `equity` = 現金 + 持倉市值（現貨目前 `equity` 只取 quote 餘額），否則直接用 equity 跌幅判斷會對「持倉中」誤判。**影響大、需設計。**
2. **風控當日狀態未持久化**（`_daily_realized_pnl` / `_daily_start_equity`）。盤中重啟 → 當日虧損歸零，同一天可二度虧到上限。建議併入 `PositionTracker` 持久化。
3. **錯誤分類過粗**：`pionex_client` 把網路 timeout / HTTP 5xx / result=false 全包成同一種 `PionexAPIError`，executor 一律標 REJECTED。timeout 後「其實已成交」會被當沒成交。建議區分「確定拒單 vs 需查證」，timeout 時先用 `client_order_id` 查單再決定重送。
4. **缺 tick/lot size 取整、429/時鐘偏移退避**（`pionex_client`）。精度不符或限流會被拒單造成空窗。
5. **缺「本地 tracker vs 交易所實際持倉」對帳 + 資料源長掛只靜默空轉無告警**。**你出國無人看管時這條最危險**，建議加連續失敗計數 + 退避 + ntfy 告警（topic 見 memory）。
6. **金額/數量用 float 記帳**：長跑會有累積誤差漂移 entry_price/停損基準。建議改 `Decimal`（較大重構）。
7. **K 棒邊界語意依賴 feed 履約 `get_latest`「已收盤」契約**：`coordinator` 已假設收盤，但若某 feed 回 forming K 棒會有前視/同根重複進場。建議由 DataFeed 明示 `last_is_forming` 旗標而非靠約定。

---

*產生方式：3 個平行 review agent → 人工對照原始碼核實 → 安全項修復+測試，風險項記錄待決。*
