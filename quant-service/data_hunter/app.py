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

import os
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
        except Exception as e:
            print(f"[app] 本輪錯誤（續跑）：{type(e).__name__}: {e}")
        wait = 2 if mh else 30
        print(f"[app] {datetime.now():%H:%M:%S} 本輪結束，{wait} 分後再掃（{'盤中即時' if mh else '盤後'}）")
        time.sleep(wait * 60)


def daytrade_worker():
    """盤中即時當沖：獨立 daemon thread，與看板 run_once 解耦——即使當沖抓價卡住，
    看板 state.json 仍每 2 分穩定更新（不再凍結）。含盤中掃描＋盤前盤後報告＋到價警示監控。"""
    dt_pool_day: date | None = None
    dt_pool: list = []
    elig_day: date | None = None          # 當沖適格清單的**獨立**日次守衛(見下方註解)
    pre_day: date | None = None
    post_day: date | None = None
    while True:
        mh = _market_hours()
        try:
            import daytrade_live
            today = date.today()
            # 🔴 當沖適格清單改成「每日一次、不限盤中」(2026-07-17,Carson 拍板):
            #   舊版把 refresh() 塞在 `if mh` 裡 → **只有 app 剛好開著且是盤中**才會刷,
            #   實測因此停在 07-13(Carson 都收盤後才開 app)。但它只是 2 個 TWSE OpenAPI GET +
            #   寫一個日期為 key 的快取,跟盤中盤後無關;而且抓的是「當日公告」,
            #   **收盤後抓到的才是當天完整名單**。這份清單同時是 M1 免費磁鐵的資料源。
            # ⚠️ 守衛必須獨立:`dt_pool_day` 是設在 `if mh` 區塊**裡面**的,若沿用它,
            #   盤後永遠不會被設 → 每輪(30 分)都打一次 TWSE。故另開 elig_day。
            if elig_day != today:
                try:
                    import daytrade_eligibility
                    r = daytrade_eligibility.refresh()
                    if daytrade_eligibility.is_trusted(r):
                        elig_day = today          # 只有抓成功才記「今天做過了」→ 失敗會在下一輪重試
                        print(f"[dt] 當沖適格清單已更新:處置 {len(r.get('disposition', []))} 檔、"
                              f"注意 {len(r.get('attention', []))} 檔")
                    else:
                        # 不設 elig_day → 下一輪(盤中 2 分/盤後 30 分)自動重試
                        print(f"[dt] ⚠️ 當沖適格清單抓取失敗({r.get('reason')}),下一輪重試;"
                              f"在抓到之前,下游一律以「無法確認」呈現,不會顯示 0 檔。")
                except Exception as e:  # noqa: BLE001
                    # 留痕:舊版是 `except: pass`,吞掉的正是 ImportError / API 形狀改變
                    # 這種「**真的壞了**」的錯(網路錯 _fetch_json 自己已經吞了)→ 靜默 = 永遠不會有人發現。
                    print(f"[dt] ⚠️ 當沖適格清單更新略過:{type(e).__name__}: {e}")
            if mh:
                if dt_pool_day != today or not dt_pool:
                    dt_pool = daytrade_live.build_universe(full=True, use_cache_only=True)
                    dt_pool_day = today
                    print(f"[dt] 全市場基準已建（{len(dt_pool)} 檔）")
                o = daytrade_live.scan_live(dt_pool, push=True)
                print(f"[dt] regime={o['regime']['label']} 訊號{len(o['signals'])} 擋{len(o['filtered'])} 掃{o.get('swept')}")
                try:
                    import alerts_monitor
                    alerts_monitor.check_and_push()      # 到價警示 → ntfy(鎖屏也收)
                except Exception as e:
                    print(f"[dt] 警示監控略過：{type(e).__name__}: {e}")
            # 盤前(08:40-08:55) / 盤後(13:31-13:50) 各每日一次
            hm_now = datetime.now().hour * 60 + datetime.now().minute
            if datetime.now().weekday() < 5:
                if pre_day != today and 8 * 60 + 40 <= hm_now <= 8 * 60 + 55:
                    if not dt_pool:
                        dt_pool = daytrade_live.build_universe(full=True, use_cache_only=True)
                        dt_pool_day = today
                    daytrade_live.premarket_report(dt_pool)
                    pre_day = today
                    print("[dt] 盤前準備已推播")
                if post_day != today and 13 * 60 + 31 <= hm_now <= 13 * 60 + 50:
                    daytrade_live.postmarket_report()
                    post_day = today
                    print("[dt] 盤後總結已推播")
        except Exception as e:
            print(f"[dt] 本輪略過（續跑）：{type(e).__name__}: {e}")
        time.sleep((2 if mh else 30) * 60)


def research_worker():
    """每日持股研究摘要：獨立 daemon thread，盤前(08:30-08:45)跑一次 ai_agents.research_agent()，
    成功後推播白話摘要。用「今天是否已推過」的日期旗標防重複推（純記憶體變數，重開程式會忘記
    今天推過與否，重開後最壞情況多推一次，不會漏推——比寫檔案旗標更簡單且無需清理）。"""
    pushed_day: date | None = None
    while True:
        try:
            now = datetime.now()
            today = date.today()
            hm_now = now.hour * 60 + now.minute
            if now.weekday() < 5 and pushed_day != today and 8 * 60 + 30 <= hm_now <= 8 * 60 + 45:
                import ai_agents
                res = ai_agents.research_agent()
                pushed_day = today   # 不管有無持股都算今天處理過，避免無持股時每輪重跑
                if not res.get("error") and res.get("holdings"):
                    try:
                        import notify
                        mkt = res.get("market", {}) or {}
                        lines = [f"{mkt.get('tone', '中性')}｜{mkt.get('one_line', '')}"]
                        for h in res.get("holdings", []):
                            chg = h.get("chg_pct")
                            chg_s = f"{chg:+.1f}%" if isinstance(chg, (int, float)) else "—"
                            lines.append(f"• {h.get('name')} {chg_s} [{h.get('grade') or '—'}] {h.get('impact') or ''}")
                        note = res.get("actions_note") or ""
                        if note:
                            lines.append(f"\n注意：{note}")
                        body = "\n".join(lines)
                        notify.broadcast(body, title=f"📊 今日持股研究 {res.get('date', '')}", priority="default")
                        print(f"[research] 已推播（{len(res.get('holdings', []))} 檔）")
                    except Exception as e:
                        print(f"[research] 推播失敗（略過）：{type(e).__name__}: {e}")
                else:
                    print(f"[research] 本輪無持股或無結果，略過推播：{res.get('error', '')}")
        except Exception as e:
            print(f"[research] 本輪錯誤（續跑）：{type(e).__name__}: {e}")
        time.sleep(5 * 60)   # 5 分鐘檢查一次是否進盤前窗口


def _lan_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=daytrade_worker, daemon=True).start()   # 當沖獨立 thread，不卡看板
    threading.Thread(target=research_worker, daemon=True).start()   # 盤前每日持股研究摘要，獨立 thread
    # 綁定位址：預設 0.0.0.0(手機同區網可連)；env DH_BIND=127.0.0.1 鎖回純本機
    bind = os.getenv("DH_BIND", "0.0.0.0")
    httpd = None
    port = PORT
    for p in range(PORT, PORT + 10):
        try:
            httpd = ThreadingHTTPServer((bind, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print(f"[app] 連續 10 個埠({PORT}-{PORT + 9})皆被占用，無法啟動。")
        input("按 Enter 關閉…")
        return
    url = f"http://127.0.0.1:{port}/"
    lan = f"http://{_lan_ip()}:{port}/"
    print("=" * 46)
    print("  量化阿森 · 台股數據獵手")
    print(f"  本機 → {url}" + (f"（埠 {PORT} 被占用改用 {port}）" if port != PORT else ""))
    if bind == "0.0.0.0":
        print(f"  手機(同wifi) → {lan}")
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
