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

## 🟢 架構級項目（本輪全數實作，附測試 test_review_fixes2~6.py）

| # | 項目 | 實作 | 測試 |
|---|------|------|------|
| 1 | 回撤上限納入未實現浮虧 | `daily_loss_limit_hit` 取「已實現%」與「權益回撤%」較大者；coordinator 改傳市值化權益(現金+持倉市值) | fixes2 |
| 2 | 風控當日狀態持久化 | `risk_manager` 原子持久化 today/realized/start_equity，盤中重啟沿用；main 接 `.state/{symbol}_risk.json` | fixes2 |
| 3 | 錯誤分類 + 不確定不當拒單 | `pionex_client` 細分 Network/RateLimit/Server/Client；executor 不確定→NEW+needs_reconcile、確定→REJECTED | fixes5 |
| 4 | 取整 + 退避 | `floor_to_step`/`round_to_tick`；idempotent(GET) 退避重試、POST 不重試 | fixes5 |
| 5 | 對帳 + 失敗退避告警 | coordinator 啟動+週期對帳本地 vs 交易所持倉(背離 CRITICAL)；連續失敗指數退避+告警；可注入 alert 出口 | fixes3 |
| 6 | Decimal 記帳 | `PositionTracker` 內部全 Decimal、消除累積漂移；對外仍 float、持久化字串保精度、相容舊格式 | fixes6 |
| 7 | K 棒 forming 語意明示 | `DataFeed.last_is_forming()`；coordinator 據此對齊策略 `drop_forming` | fixes4 |

### ⚠️ 仍需「實盤驗證 / 一行接線」才完整（已留 hook，非缺口）
- **#4 取整**：`size_step`/`price_tick` 預設 None＝不取整（維持原行為）。實盤前要從 Pionex 交易對規格填入**真實 stepSize/tickSize**，否則取整不生效。
- **#3 錯誤分類**：分類邏輯已就緒，但「timeout 後用 clientOrderId 查單對帳」需依 Pionex 實際 API 行為驗證（Pionex `get_order` 用 orderId 非 clientOrderId，對帳目前走 `get_position` 比對）。
- **#5 ntfy 告警**：✅ 已接上 `main.build_alert`，coordinator 對帳背離/連續失敗會推 ntfy。
  **啟用方式**：在 `config.yaml` 的 `notify.ntfy_topic` 填一個夠隨機的 topic（或設環境變數
  `TRADING_NTFY_TOPIC`），手機 ntfy app 訂閱同 topic 即可。留空＝告警僅記 log。
  等級對應 ntfy Priority：CRITICAL→urgent、ERROR→high、WARNING→default、INFO→low。
- **#1 回撤含浮虧**：現貨 `equity` 已改市值化；合約/槓桿商品的市值計算另需對應。

---

*產生方式：3 個平行 review agent → 人工對照原始碼核實（剔除過度告警）→ 安全項與架構項逐一修復+測試。全套測試 76/76 綠。*
