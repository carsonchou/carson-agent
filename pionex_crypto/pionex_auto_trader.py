# -*- coding: utf-8 -*-
"""
Multi v1 -> 派網 自動對接程式
每次執行:抓 BTC 永續日線 -> 算 Multi v1 訊號 -> 若持倉狀態變化則發 webhook 到派網
訊號邏輯已通過一致性驗證(同期間 13 筆與 TradingView 完全吻合)

安全設計:
- DRY_RUN=True 時只印出判斷,不真發 webhook(預設)
- 用狀態檔記錄持倉,只在「狀態改變」時發訊號(冪等,漏跑可補)
- 用「已收盤」的日K訊號,避免未收盤K線造成誤判
"""
import json, time, os, sys
import requests
from datetime import datetime, timezone
from backtest_engine import fetch_klines, supertrend_signals, ema

# ============== 設定 ==============
DRY_RUN      = True   # ★ True=只模擬不發送;確認無誤後改 False 才會真的下單
WEBHOOK_URL  = "https://www.pionex.com/signal/api/v1/signal_listener/trading_view?token=9d59758b-400b-4b98-bcf4-696427f62b7c"
SIGNAL_TYPE  = "e3a00071-9ccb-487b-ba8a-d5a33743edc5"
SYMBOL       = "BTCUSDT.P"
STATE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")
LOG_FILE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_log.txt")
# Multi v1 參數
ATR_LEN, MULT, EMA_LEN, RSI_LEN = 10, 3.0, 200, 14

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def compute_position():
    """重算從頭到『最後一根已收盤日K』的應有持倉,回傳 (pos, 最後收盤日, 收盤價)"""
    df = fetch_klines("BTCUSDT", "1d", total=3000, market="perp")
    d = supertrend_signals(df, mult=MULT, atr_period=ATR_LEN)
    d["ema"] = ema(d["close"], EMA_LEN)
    delta = d["close"].diff()
    ag = delta.clip(lower=0).ewm(alpha=1/RSI_LEN, adjust=False).mean()
    al = (-delta.clip(upper=0)).ewm(alpha=1/RSI_LEN, adjust=False).mean()
    d["rsi"] = 100 - 100/(1 + ag/al)
    d["goLong"]   = d["st_long"] & (d["close"] > d["ema"]) & (d["rsi"] > 50) & (d["rsi"] < 75)
    d["exitLong"] = (d["st_dir"] == -1) | (d["close"] < d["ema"])
    # 只用已收盤的K(排除當前進行中的UTC日)→ 用倒數第二根
    last_closed = len(d) - 2
    pos = 0
    for i in range(last_closed + 1):
        if pos == 0 and d["goLong"].iloc[i]:   pos = 1
        elif pos == 1 and d["exitLong"].iloc[i]: pos = 0
    return pos, str(d["date"].iloc[last_closed])[:10], float(d["close"].iloc[last_closed])

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f: return json.load(f)
    return {"pos": 0, "last_action": None, "last_date": None}

def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=2)

def send_webhook(action, price):
    payload = {
        "data": {"action": action, "contracts": "1",
                 "position_size": "1" if action == "buy" else "0"},
        "price": str(price), "signal_param": "{}",
        "signal_type": SIGNAL_TYPE, "symbol": SYMBOL,
        "time": str(int(time.time() * 1000)),
    }
    if DRY_RUN:
        log(f"[DRY_RUN] 會發送 webhook: {json.dumps(payload, ensure_ascii=False)}")
        return True
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        log(f"已發送 webhook action={action} 狀態碼={r.status_code} 回應={r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        log(f"webhook 發送失敗: {e}")
        return False

def main():
    log(f"===== 執行檢查 (DRY_RUN={DRY_RUN}) =====")
    target_pos, last_date, price = compute_position()
    state = load_state()
    cur_pos = state.get("pos", 0)
    log(f"最後收盤日 {last_date} 收盤 ${price:,.0f} | 策略應有持倉={target_pos} 目前記錄持倉={cur_pos}")

    if target_pos == cur_pos:
        log("持倉狀態未變,無需發送訊號。")
        return
    # 狀態改變 → 發對應訊號
    if cur_pos == 0 and target_pos == 1:
        action = "buy";  log("偵測到【進場做多】訊號")
    else:
        action = "sell"; log("偵測到【出場平倉】訊號")
    if send_webhook(action, price):
        state.update({"pos": target_pos, "last_action": action, "last_date": last_date})
        save_state(state)
        log(f"狀態已更新為 pos={target_pos}")
    else:
        log("發送未成功,狀態不更新(下次重試)")

if __name__ == "__main__":
    main()
