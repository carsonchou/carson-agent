# D:\carson-agent 目錄結構（2026-06-13 整理）

整理原則：每個 session/專案盡量各放一個資料夾；垃圾刪除；大資料夾原地保留。
**注意：部分程式碼用「相對頂層目錄」的路徑耦合，硬搬會弄壞，故保留在頂層（見下方說明）。**

## 資料夾

| 資料夾 | 內容 | 備註 |
|--------|------|------|
| `pionex_crypto/` | 加密/Pionex 交易：`pionex_auto_trader.py`(自動下單)、`backtest_engine.py`、`final_backtest.py`、`multi_symbol_backtest.py`、`perp_calibrate.py`、`signal_check.py` + `bot_state.json`/`bot_log.txt` | 已抽出；純 API、state/log 隨腳本，import 驗證 OK |
| `trading_bot/` | 結構化多模組 Pionex bot（含 SMC 策略 `strategy/smc.py`） | 獨立專案，原本就是資料夾 |
| `ppt/` | 簡報製作：`make_ppt.py`、`make_ppt_v2.py`、`inspect_ppt.py` + `*.pptx` | 已抽出 |
| `screenshots/` | 181 張截圖（tv/freelancer/skills/pionex/metrics… 各類研究截圖） | 已歸檔 |
| `docs/` | 報告與說明：`ace_*.md`、`triple_supertrend_v4_*_說明.md`、`README_STOCK_API.md`、`SETUP_GUIDE.md` | 已歸檔 |
| `twdata/` | 台股 OHLCV 快取（667M） | **原地保留**（`tw_data.py` 用 `__file__` 綁定此路徑） |
| `youtube_channel/` | YouTube 變現專案（902M） | **原地保留**（獨立專案） |
| `node_modules/` `src/` `scripts/` `_vid_skills/` | 相依套件 / 雜項 | 保留 |

## 仍保留在頂層的程式碼（有路徑耦合、搬移會壞）

- **台股組**：`strategy.py`(Triple ST 多單移植)、`indicators.py`、`tw_data.py`、`tw_trendride.py`、`tw_adaptive.py` 與所有 `tw_*.py`、`verify_short.py`。
  → `tw_data.py` 以 `__file__` 定位頂層 `twdata/`，且 twdata 須原地，故整組留頂層。
- **Pine / TradingView 自動化**：30 個 `*.pine` + 20 個 `tv_*.mjs`、`arena_evolution.mjs` 等。
  → 多個 `tv_*.mjs` 用裸相對檔名讀寫 `.pine`（如 `out.pine`、`champion_r5.pine`），且 `.mjs` 用相對路徑引用登入 profile `.pw_tvprofile`（在頂層）。搬 `.pine` 或 `.mjs` 都會斷，故保留頂層。
- 冠軍檔：`triple_supertrend_v4_FINAL.pine`、`triple_supertrend_v4_champion.pine` 等。

## 本次清掉的垃圾

- 68 個 0-byte 檔（shell 重導向出錯把程式碼片段當檔名建出來的，如 `1e-9`、`notS1`、`RiskManager`）。
- `__pycache__/`。

頂層項目：371 → 106。
