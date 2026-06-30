# 量化阿森 · 台股數據獵手 🎯

一支 **AI 自動掃台股市場強弱、推做多/做空警報** 的數據儀表板 + 背景機器人。
靈感來自 IG 那支「ELITE 數據獵手」，但做成 **真能跑、用真實 K 線計算** 的台股版。
你自己看盤用，畫面同時就是 IG/YT 引流素材。

## 它做什麼

每一輪掃描（盤中每 5 分、盤後每 30 分）：
1. 抓約 130 檔流動性好的台股（跨 18 產業）日線 —— 即時 yfinance 優先，失敗退 `twdata/cache` 快取
2. 每檔算 RSI / MA20 / MA60 / SuperTrend / MACD / 5日動能 → **個股強弱分 0–100**
3. 聚合成三塊看板資料：
   - **市場溫度 gauge**：平均 RSI + 站上 20MA 比例 + 漲跌家數 → 0–100 溫度（超強/偏多/中性/偏弱/超弱）
   - **產業板塊熱流**：18 產業強弱輪動排行（半導體/金融/航運/…）
   - **強弱榜**：最強 8 / 最弱 8
4. 偵測訊號：**做多**（SuperTrend 翻多 + RSI 健康）/ **做空**（跌破 20MA 或 SuperTrend 翻空）
5. 寫 `state.json` 給看板；對「**新出現**」的訊號推 **ntfy**（當日去重，不洗版）

## 怎麼用

| 想做的事 | 雙擊 / 指令 |
|---|---|
| 開即時看板（先掃一輪再開瀏覽器） | `開啟看板.bat` |
| 背景跑掃描迴圈（自動推 ntfy） | `背景掃描.bat` |
| 手動掃一次（即時 + 推播） | `python scan.py` |
| 手動掃一次（不推播，測試） | `python scan.py --no-push` |
| 只讀快取不連網（最快） | `python scan.py --cache` |

看板網址：<http://127.0.0.1:8899/>

## 重用了什麼（沒重造輪子）

- `../indicators.py` — RSI / MACD / SuperTrend / 布林 / MA
- `../tw_stock_data.py` + `../../twdata/cache/` — 台股抓價 + 2000+ 檔快取
- `../notify.py` — ntfy / LINE 推播（topic 從 `../.env` 的 `NTFY_TOPIC` 讀）
- `D:\ClawWork\.venv` — 已裝 yfinance / pandas / numpy

## 要擴充

- **加股票**：往 `universe.py` 的 `INDUSTRIES` 對應產業塞 `(代號, 名稱)`，掃描/熱流/看板自動跟上
- **調訊號**：`scan.py` 的 `analyse_one()` 改訊號條件、`build_state()` 改溫度權重
- **接盤中即時**：目前用日線（穩定可靠）；要真盤中分時可在 `load_universe_data` 加 `interval="15m"`

## 檔案

```
data_hunter/
├─ universe.py      宇宙 + 產業分類(約130檔/18產業)
├─ scan.py          掃描引擎(指標→聚合→state.json→推播)
├─ loop.py          背景迴圈(盤中5分/盤後30分)
├─ server.py        看板伺服器(純標準庫, 8899埠)
├─ dashboard.html   深色 HUD 看板(溫度gauge+熱流+強弱榜+訊號)
├─ 開啟看板.bat / 背景掃描.bat
└─ state.json       (自動產出, 不進版控)
```

> 本看板僅為技術數據呈現，非投資建議。
