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
    """背景掃描迴圈：每天刷快取 + 即時同步掃描 + 推播 + 每日全市場交易專區。"""
    rows = scan.load_full_universe()     # 全市場(~1900 檔上市櫃)
    last_fresh: date | None = None
    zones_day: date | None = None
    dt_pool_day: date | None = None
    dt_pool: list = []
    pre_day: date | None = None
    post_day: date | None = None
    print(f"[app] 背景掃描啟動（全市場 {len(rows)} 檔）")
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
            # 交易專區(當沖/短線/長線 全市場選股)：每日建一次(選股非 tick 敏感，~30s 不卡看板)
            if zones_day != today:
                try:
                    import zones
                    z = zones.build_zones(full=True, use_cache_only=True)
                    print(f"[app] 交易專區已產生（全市場 {z['universe_n']} 檔）")
                    zones_day = today
                except Exception as e:
                    print(f"[app] 交易專區產生略過：{type(e).__name__}: {e}")
            # 盤中即時當沖：每日開盤建一次池(＋可當沖清單)，盤中每輪掃描推播
            if mh:
                try:
                    import daytrade_live
                    if dt_pool_day != today or not dt_pool:
                        import daytrade_eligibility
                        daytrade_eligibility.refresh()
                        dt_pool = daytrade_live.build_universe(full=True, use_cache_only=True)
                        dt_pool_day = today
                        print(f"[app] 全市場基準已建（{len(dt_pool)} 檔）")
                    o = daytrade_live.scan_live(dt_pool, push=True)
                    print(f"[app] 當沖 regime={o['regime']['label']} 訊號{len(o['signals'])} 擋{len(o['filtered'])}")
                except Exception as e:
                    print(f"[app] 當沖掃描略過：{type(e).__name__}: {e}")
            # 盤前準備(08:40-08:55) / 盤後總結(13:31-13:50) 各每日一次
            hm_now = datetime.now().hour * 60 + datetime.now().minute
            if datetime.now().weekday() < 5:
                try:
                    import daytrade_live
                    if pre_day != today and 8 * 60 + 40 <= hm_now <= 8 * 60 + 55:
                        if not dt_pool:
                            import daytrade_eligibility
                            daytrade_eligibility.refresh()
                            dt_pool = daytrade_live.build_universe(full=True, use_cache_only=True)
                            dt_pool_day = today
                        daytrade_live.premarket_report(dt_pool)
                        pre_day = today
                        print("[app] 盤前當沖準備已推播")
                    if post_day != today and 13 * 60 + 31 <= hm_now <= 13 * 60 + 50:
                        daytrade_live.postmarket_report()
                        post_day = today
                        print("[app] 盤後當沖總結已推播")
                except Exception as e:
                    print(f"[app] 盤前/盤後報告略過：{type(e).__name__}: {e}")
        except Exception as e:
            print(f"[app] 本輪錯誤（續跑）：{type(e).__name__}: {e}")
        wait = 2 if mh else 30
        print(f"[app] {datetime.now():%H:%M:%S} 本輪結束，{wait} 分後再掃（{'盤中即時' if mh else '盤後'}）")
        time.sleep(wait * 60)


def main():
    threading.Thread(target=worker, daemon=True).start()
    # 埠占用 → 自動 +1 重試(最多 10 個埠)，綁定成功後再開實際埠的瀏覽器
    httpd = None
    port = PORT
    for p in range(PORT, PORT + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print(f"[app] 連續 10 個埠({PORT}-{PORT + 9})皆被占用，無法啟動。")
        input("按 Enter 關閉…")
        return
    url = f"http://127.0.0.1:{port}/"
    print("=" * 46)
    print("  量化阿森 · 台股數據獵手")
    print(f"  看板 → {url}" + (f"（埠 {PORT} 被占用改用 {port}）" if port != PORT else ""))
    print("  關閉此視窗即停止")
    print("=" * 46)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[app] 已停止")


if __name__ == "__main__":
    main()
