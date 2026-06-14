'use strict';

/**
 * 台灣證交所 (TWSE) 即時報價用戶端
 *
 * 資料來源：MIS 即時行情 API
 *   https://mis.twse.com.tw/stock/api/getStockInfo.jsp
 *
 * 注意：此為證交所提供的公開行情 API，盤中資料約有 15~20 秒延遲，
 * 僅供參考，非即時交易報價。
 */

const TWSE_ENDPOINT = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp';
const REQUEST_TIMEOUT_MS = 8000;

/**
 * 把證交所回傳的字串數字轉成 number；遇到 '-' 或空值回傳 null。
 */
function toNumber(value) {
  if (value === undefined || value === null || value === '' || value === '-') {
    return null;
  }
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

/**
 * 解析證交所的五檔委買/委賣字串（以 '_' 分隔），回傳 number 陣列。
 */
function parseLevels(value) {
  if (!value) return [];
  return value
    .split('_')
    .filter((s) => s !== '')
    .map((s) => toNumber(s))
    .filter((n) => n !== null);
}

/**
 * 向證交所查詢單一股票的即時報價。
 *
 * @param {string} symbol 股票代號，例如 '2330'
 * @returns {Promise<object>} 正規化後的報價物件
 * @throws {Error} 查無資料時拋出 code='NOT_FOUND'；上游錯誤時 code='UPSTREAM_ERROR'
 */
async function fetchQuote(symbol) {
  // 上市 (tse) 與上櫃 (otc) 都查，讓呼叫端不必先知道股票屬於哪個市場
  const channels = [`tse_${symbol}.tw`, `otc_${symbol}.tw`].join('|');
  const url =
    `${TWSE_ENDPOINT}?ex_ch=${encodeURIComponent(channels)}&json=1&delay=0`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let payload;
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        // 證交所 API 會擋掉沒有來源資訊的請求
        'User-Agent': 'Mozilla/5.0 (carson-agent stock-quote-api)',
        Referer: 'https://mis.twse.com.tw/stock/index.jsp',
      },
    });

    if (!res.ok) {
      const err = new Error(`TWSE 上游回應狀態碼 ${res.status}`);
      err.code = 'UPSTREAM_ERROR';
      throw err;
    }
    payload = await res.json();
  } catch (e) {
    if (e.code) throw e;
    const err = new Error(
      e.name === 'AbortError' ? 'TWSE 上游請求逾時' : `TWSE 上游請求失敗：${e.message}`
    );
    err.code = 'UPSTREAM_ERROR';
    throw err;
  } finally {
    clearTimeout(timer);
  }

  const row = payload && Array.isArray(payload.msgArray) ? payload.msgArray[0] : null;
  if (!row) {
    const err = new Error(`查無股票代號 ${symbol} 的報價`);
    err.code = 'NOT_FOUND';
    throw err;
  }

  return normalize(row);
}

/**
 * 把證交所原始欄位轉成易讀的報價物件。
 * 證交所欄位對照：
 *   c=代號 n=名稱 z=成交價 o=開盤 h=最高 l=最低 y=昨收
 *   v=累計成交量(張) tv=當盤成交量 b=委買五檔 a=委賣五檔 tlong=時間(ms)
 */
function normalize(row) {
  const price = toNumber(row.z);
  const prevClose = toNumber(row.y);

  let change = null;
  let changePercent = null;
  if (price !== null && prevClose !== null && prevClose !== 0) {
    change = Number((price - prevClose).toFixed(2));
    changePercent = Number(((change / prevClose) * 100).toFixed(2));
  }

  return {
    symbol: row.c,
    name: row.n,
    price,
    previousClose: prevClose,
    open: toNumber(row.o),
    high: toNumber(row.h),
    low: toNumber(row.l),
    change,
    changePercent,
    volume: toNumber(row.v), // 累計成交量（張）
    bidPrices: parseLevels(row.b),
    askPrices: parseLevels(row.a),
    market: row.ex === 'tse' ? '上市' : row.ex === 'otc' ? '上櫃' : row.ex,
    time: row.tlong ? new Date(Number(row.tlong)).toISOString() : null,
    source: 'TWSE MIS',
  };
}

module.exports = { fetchQuote };
