# -*- coding: utf-8 -*-
"""
app.py — 台股數據獵手「桌面 app」一鍵啟動

雙擊桌面捷徑就會：
  1. 背景迴圈：每天自動刷一次快取(拉到昨日) → 盤中每2分用『證交所即時價』跟市場同步掃描、
     盤後每30分，偵測新訊號推 ntfy
  2. 開看板伺服器(8899) 並自動打開瀏覽器
關掉這個視窗就停止。不需要 Windows 工作排程。
"""
from __future__ import annotations

import sys
import time
import threading
import webbrowser
from datetime import datetime, date
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))   # indicators / notify / tw_stock_data
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import scan                              # noqa: E402
from server import Handler               # 重用看板 handler  # noqa: E402

PORT = 8899


def _market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 13 * 60 + 35


def worker():
    """背景掃描迴圈：每天刷快取 + 即時同步掃描 + 推播。"""
    rows = scan.all_codes()              # 精選宇宙(快、可即時同步)
    last_fresh: date | None = None
    print(f"[app] 背景掃描啟動（精選 {len(rows)} 檔，跟市場同步）")
    while True:
        mh = _market_hours()
        try:
            today = date.today()
            if last_fresh != today:      # 每天刷一次快取，讓當日漲跌幅正確
                print("[app] 每日刷新快取中…")
                n = scan.freshen_cache(rows)
                print(f"[app] 快取已更新 {n} 檔")
                last_fresh = today
            scan.run_once(push=True, realtime=True)   # 證交所即時價覆蓋最後一根
        except Exception as e:
            print(f"[app] 本輪錯誤（續跑）：{type(e).__name__}: {e}")
        wait = 2 if mh else 30
        print(f"[app] {datetime.now():%H:%M:%S} 本輪結束，{wait} 分後再掃（{'盤中即時' if mh else '盤後'}）")
        time.sleep(wait * 60)


def main():
    threading.Thread(target=worker, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    print("=" * 46)
    print("  量化阿森 · 台股數據獵手")
    print(f"  看板 → {url}")
    print("  關閉此視窗即停止")
    print("=" * 46)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[app] 已停止")
    except OSError as e:
        print(f"[app] 伺服器啟動失敗（埠 {PORT} 可能已被占用）：{e}")
        input("按 Enter 關閉…")


if __name__ == "__main__":
    main()
