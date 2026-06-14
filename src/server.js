'use strict';

/**
 * 台股報價 REST API
 *
 * 端點：
 *   GET /health           健康檢查
 *   GET /quote/:symbol    查詢單一股票即時報價，例如 /quote/2330
 *   GET /quotes?symbols=2330,2317,0050   一次查多檔（以逗號分隔，上限 10 檔）
 */

const express = require('express');
const { fetchQuote } = require('./twseClient');

const app = express();
const PORT = process.env.PORT || 3000;

// 簡單的記憶體快取，避免短時間內重複打證交所 API
const CACHE_TTL_MS = 5000;
const cache = new Map(); // symbol -> { data, expires }

async function getQuoteCached(symbol) {
  const hit = cache.get(symbol);
  const now = Date.now();
  if (hit && hit.expires > now) {
    return { ...hit.data, cached: true };
  }
  const data = await fetchQuote(symbol);
  cache.set(symbol, { data, expires: now + CACHE_TTL_MS });
  return { ...data, cached: false };
}

// 驗證股票代號格式：4~6 碼英數（涵蓋一般股票與部分 ETF/權證）
function isValidSymbol(symbol) {
  return typeof symbol === 'string' && /^[0-9A-Za-z]{4,6}$/.test(symbol);
}

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'tw-stock-quote-api', time: new Date().toISOString() });
});

app.get('/quote/:symbol', async (req, res) => {
  const symbol = req.params.symbol;
  if (!isValidSymbol(symbol)) {
    return res.status(400).json({ error: '股票代號格式錯誤', symbol });
  }
  try {
    const quote = await getQuoteCached(symbol);
    res.json(quote);
  } catch (e) {
    handleError(res, e, symbol);
  }
});

app.get('/quotes', async (req, res) => {
  const raw = (req.query.symbols || '').toString();
  const symbols = raw.split(',').map((s) => s.trim()).filter(Boolean);

  if (symbols.length === 0) {
    return res.status(400).json({ error: '請提供 symbols 參數，例如 /quotes?symbols=2330,2317' });
  }
  if (symbols.length > 10) {
    return res.status(400).json({ error: '一次最多查詢 10 檔', count: symbols.length });
  }
  const invalid = symbols.filter((s) => !isValidSymbol(s));
  if (invalid.length > 0) {
    return res.status(400).json({ error: '部分股票代號格式錯誤', invalid });
  }

  const results = await Promise.all(
    symbols.map(async (symbol) => {
      try {
        return await getQuoteCached(symbol);
      } catch (e) {
        return { symbol, error: e.message, code: e.code || 'ERROR' };
      }
    })
  );
  res.json({ count: results.length, quotes: results });
});

function handleError(res, e, symbol) {
  if (e.code === 'NOT_FOUND') {
    return res.status(404).json({ error: e.message, symbol });
  }
  if (e.code === 'UPSTREAM_ERROR') {
    return res.status(502).json({ error: e.message, symbol });
  }
  return res.status(500).json({ error: '伺服器內部錯誤', detail: e.message, symbol });
}

// 404 fallback
app.use((req, res) => {
  res.status(404).json({ error: '找不到此端點', path: req.path });
});

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`台股報價 API 已啟動：http://localhost:${PORT}`);
    console.log(`  健康檢查：  GET /health`);
    console.log(`  單檔報價：  GET /quote/2330`);
    console.log(`  多檔報價：  GET /quotes?symbols=2330,2317,0050`);
  });
}

module.exports = app;
