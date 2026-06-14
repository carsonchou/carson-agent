// 離線驗證解析器：讀已存的 _panel.txt，套用同一套行解析邏輯，印出結果。
import fs from 'fs';
const bodyText = fs.readFileSync(process.argv[2] || 'metrics_A_panel.txt', 'utf8');
const m = {};
const lines = bodyText.split('\n').map(s => s.trim()).filter(Boolean);
const PCT = /-?[0-9][0-9,]*\.?[0-9]*\s*%/;
const NUM = /-?[0-9][0-9,]*\.?[0-9]+/;
const idxOf = (re) => lines.findIndex(l => re.test(l));
const nextMatch = (i, re) => { if (i < 0) return null; for (let j = i + 1; j < Math.min(i + 6, lines.length); j++) { const mm = lines[j].match(re); if (mm) return mm[0].replace(/\s/g, ''); } return null; };
m.netProfit = nextMatch(idxOf(/^Total PnL$/), PCT);
m.maxDrawdown = nextMatch(idxOf(/^Max drawdown$/), PCT);
m.percentProfitable = nextMatch(idxOf(/^Profitable trades$/), PCT);
m.profitFactor = nextMatch(idxOf(/^Profit factor$/), NUM);
m.sharpe = nextMatch(idxOf(/^Sharpe ratio$/), NUM);
m.sortino = nextMatch(idxOf(/^Sortino ratio$/), NUM);
m.returnOverMaxDD = nextMatch(idxOf(/^Return of max drawdown$/), NUM);
const wl = lines.find(l => /^\d+\/\d+$/.test(l));
if (wl) { const [w, t] = wl.split('/'); m.winningTrades = w; m.totalTrades = t; }
console.log(JSON.stringify(m, null, 2));
