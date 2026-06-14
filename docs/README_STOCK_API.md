# 台股報價 REST API

串接台灣證交所（TWSE）MIS 公開行情 API，提供台股即時報價查詢。

> ⚠️ 資料來源為證交所公開行情，盤中約有 15~20 秒延遲，僅供參考，非交易等級即時報價。

## 啟動

```powershell
npm install      # 安裝相依套件（express）
npm start        # 啟動伺服器，預設埠號 3000
```

啟動後可用環境變數 `PORT` 改埠號：`$env:PORT=8080; npm start`

## 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/health` | 健康檢查 |
| GET | `/quote/:symbol` | 查詢單一股票，例如 `/quote/2330` |
| GET | `/quotes?symbols=2330,2317,0050` | 一次查多檔（逗號分隔，上限 10 檔）|

## 範例

```powershell
curl http://localhost:3000/quote/2330
```

```json
{
  "symbol": "2330",
  "name": "台積電",
  "price": 2305,
  "previousClose": 2295,
  "open": 2305,
  "high": 2320,
  "low": 2295,
  "change": 10,
  "changePercent": 0.44,
  "volume": 33117,
  "bidPrices": [2305, 2300, 2295, 2290, 2285],
  "askPrices": [2310, 2315, 2320, 2325, 2330],
  "market": "上市",
  "time": "2026-06-09T06:30:00.000Z",
  "source": "TWSE MIS",
  "cached": false
}
```

## 行為說明

- **上市/上櫃自動判斷**：同時查 `tse_` 與 `otc_` 頻道，呼叫端不必事先知道市場別。
- **快取**：同一代號 5 秒內重複查詢直接回傳快取（`cached: true`），降低對證交所的請求量。
- **錯誤處理**：
  - 代號格式錯誤 → `400`
  - 查無此股票 → `404`
  - 證交所上游錯誤/逾時 → `502`

## 檔案結構

```
src/
  server.js       Express 伺服器與路由
  twseClient.js   證交所 API 呼叫與資料正規化
```
