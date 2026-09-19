#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status.py — 一個指令看完整條 ch3 產線的狀態。

## 為什麼需要這支
今天(2026-08-28)為了搞清楚「現在到底能不能發」,我散開來查了七八件事:
頻道實況、本地庫存、三條發布線各自的帳本、四道閘門會不會擋、配額夠不夠。
每一件都是臨時拼的指令,下次還要再拼一次 —— 而其中兩件(已發布影片的
真實觀看數、閘門會擋掉誰)正是最容易憑印象猜錯的。

所以收成一支。**全部唯讀**,不會改動任何東西,可以隨時跑。

用法:
  python status.py            # 完整
  python status.py --local    # 只看本地,不連網(不花配額)
"""
import argparse
import json
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"


def rule(t):
    print(f"\n\033[1m── {t} ──\033[0m" if sys.stdout.isatty() else f"\n── {t} ──")


_BAD_DUR = []


def dur(p):
    """讀不到長度就記下來 —— 靜默回 0.0 會讓「合計 X 分」少報而不報錯。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        _BAD_DUR.append(p.name)
        return 0.0


def render_state():
    """從 render log 判斷「還在跑」還是「跑完但失敗」。

    🔴 `V4-x-DONE` 這種標記只代表**腳本跑完**,不代表**渲成功** —— 實測
    render_v4_1.log 的最後一列是 rc=1,DONE 照樣印。拿它當放行條件會在
    一個大部分失敗的狀態上放行。任何完成訊號都要配成敗證明。
    """
    # 🔴 **只看最新那一輪**。`render_v*.log` 會撈到 v2、v3、v4、v5 全部 ——
    #    而 v4 有十列失敗,它的 log 不會消失,於是就算 v5 十支全成功,
    #    報告也會**永遠**說「跑完但有失敗」,還引用一個早就修好的錯誤。
    #    永遠紅燈比永遠綠燈更難處理:它會訓練人忽略那一行,然後真的失敗時
    #    長得跟殘留噪音一模一樣。
    #    這跟我前一個 bug(拿上一輪的結果講話)是同一個病的另一半。
    import re as _re
    vs = [(int(m.group(1)), p) for p in ROOT.glob("render_v*_*.log")
          if (m := _re.match(r"render_v(\d+)_\d+\.log$", p.name))]
    latest = max((v for v, _p in vs), default=None)
    # ⚠️ 「最新那一輪」不能只看版號。**補渲輪會跟前一輪的尾巴並行** ——
    #    今天 v6(補我誤殺的兩支)啟動時,v5 還在渲最後一集,只取版號最大
    #    的會把那支正在跑的 worker 濾掉,報告就變成部分真相。
    #    所以:版號最大的那一輪 **加上任何還沒收工的**(沒有 DONE 標記)。
    logs = [p for v, p in vs
            if v == latest
            or "-DONE ===" not in p.read_text(encoding="utf-8", errors="replace")]
    out = []
    for lg in sorted(logs):
        t = lg.read_text(encoding="utf-8", errors="replace")
        # ⚠️ 不能用「有沒有 rc 行」當納入條件。剛啟動的那一輪還沒跑完第一集,
        #    一行 rc 都還沒有 —— 於是它被濾掉,報告就會拿**上一輪**的結果
        #    說「重產已經跑完」,而其實新的一輪正在跑。實際踩過。
        if t.strip():
            out.append((lg.name,
                        t.count("rc=0 ---"),
                        sum(t.count(f"rc={i} ---") for i in range(1, 10)),
                        "-DONE ===" in t))
    return out


def led(name):
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def local():
    rule("本地庫存")
    eps = sorted((ROOT / "eps").glob("ep*/ep*.mp4"))
    fam = sorted((ROOT / "eps_famous").glob("*/*.mp4"))
    sh = sorted((ROOT / "shorts").glob("*/*_short.mp4"))
    comps = [(b, ROOT / "compilations" / b / f"{b}_compilation.mp4")
             for b in ("fail", "mixed", "held")]
    # ⚠️ 「幾支成片」要算**讀得到的**。渲染中的 mp4 檔案已經存在但 ffprobe
    #    讀不了 —— 把它算進去就會多報,而這個數字的用途正是判斷庫存。
    dd = [(p, dur(p)) for p in eps]
    good = [(p, d) for p, d in dd if d > 0]
    tot = sum(d for _p, d in good)
    print(f"  長片(FReD)  {len(good):>2} 支可用,合計 {tot / 60:5.1f} 分"
          + (f"(另 {len(dd) - len(good)} 個檔在寫入中)" if len(good) != len(dd) else ""))
    eps = [p for p, _d in good]
    print(f"  長片(名案)  {len(fam):>2} 支")
    print(f"  Shorts       {len(sh):>2} 支")
    for b, p in comps:
        if p.exists():
            man = p.parent / "manifest.json"
            m = ("有" if man.exists() else "**缺**")
            print(f"  合輯 {b:<6}{dur(p) / 60:5.1f} 分   manifest {m}")
        else:
            print(f"  合輯 {b:<6}(未產出)")
    # 渲染中的跡象:目錄存在但 mp4 不在 = 正在重建
    if _BAD_DUR:
        print(f"  ⚠️ 有 {len(_BAD_DUR)} 個檔讀不到長度(上面的分鐘數少報了):"
              f"{', '.join(_BAD_DUR[:5])}")
    half = [d.name for d in sorted((ROOT / "eps").iterdir())
            if d.is_dir() and not (d / f"{d.name}.mp4").exists()]
    q = ROOT / "facts" / "episode_queue.csv"
    if not q.exists():
        return
    import pandas as pd
    n_rows = len(pd.read_csv(q, low_memory=False))
    if n_rows == len(eps) and not half:
        return
    print(f"  ⚠️ 佇列有 {n_rows} 列但只有 {len(eps)} 支成片"
          f"{'、且 ' + ','.join(half) + ' 正在重建' if half else ''}")
    # 🔴 處置建議要分得出「還在跑」和「跑完但失敗」。原本一律寫
    #    「等重產跑完」—— 而重產跑完卻有十列被溯源守門擋下時,那句話
    #    指向一個永遠不會發生的結果。status.py 自己不讀 log 就分不出來。
    st = render_state()
    running = [n for n, _o, _f, d in st if not d]
    failed = [(n, f) for n, _o, f, _d in st if f]
    if running:
        print(f"     → 還在跑({', '.join(running)}),等它收工")
    elif failed:
        # 🔴 **失敗訊號跟完成訊號一樣需要配上原因,只有計數不夠。**
        #    「DONE 不代表成功」和「rc=1 不代表內容有問題」是同一個教訓的
        #    兩個方向 —— 今天兩邊都親自撞過:先是 DONE 掩蓋了十列真失敗,
        #    然後是我自己 TaskStop 殺掉兩支渲染、rc=1 看起來像內容被擋。
        #    ⚠️ 分類的風險是**把新東西塞進舊桶子**,所以留一個
        #    「不屬於任何一類」的出口 —— 出現第三種失敗時它不會被消音。
        kinds = {"被中斷(有人殺掉或當機)": "3221225794",
                 "溯源守門擋下(稿中有查無來源的數字)": "查無來源的數字"}
        tally, unknown_n = {}, 0
        for lg, f in failed:
            t = (ROOT / lg).read_text(encoding="utf-8", errors="replace")
            hit = [k for k, sig in kinds.items() if sig in t]
            if hit:
                for k in hit:
                    tally[k] = tally.get(k, 0) + 1
            else:
                unknown_n += 1
        n_fail = sum(f for _n, f in failed)
        print(f"     → **重產已經跑完,但有 {n_fail} 列失敗**")
        print("        (`-DONE` 只代表腳本跑完,不代表渲成功)")
        for k, c in tally.items():
            print(f"        · {k}(出現在 {c} 份 log)")
        if unknown_n:
            print(f"        · ‼️ 有 {unknown_n} 份 log 的失敗**不屬於已知類別**"
                  f" —— 要人看,不要當成上面那些")
        for lg, _f in failed[:1]:
            t = (ROOT / lg).read_text(encoding="utf-8", errors="replace")
            for ln in t.splitlines():
                if "⛔" in ln or "Error" in ln:
                    print(f"        首個錯誤:{ln.strip()[:88]}")
                    break
    else:
        print("     → 現在不要發布或重剪合輯,等重產跑完")


def queues(offline=False):
    rule("三條發布線")
    meta = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
    long_led, sh_led, comp_led = (led("uploaded.json"), led("uploaded_shorts.json"),
                                  led("uploaded_comp.json"))
    k = lambda o: o.get("slug") or o["dir"]
    left = [o for o in meta if k(o) not in long_led]
    # 🔴 「待發」要扣掉**檔案不在的**。只比對清單與帳本會高估三倍
    #    (實測 14 vs 真正發得出去的 5)—— 而這個數字的用途正是判斷
    #    「庫存夠不夠」,高估等於在空的倉庫上做計畫。
    ready = [o for o in left if (ROOT / o["video"]).exists()
             and (not o.get("thumb") or (ROOT / o["thumb"]).exists())]
    gap = len(left) - len(ready)
    print(f"  長片   清單 {len(meta):>2}、已發 {len(long_led):>2}、"
          f"待發 {len(left):>2},其中**現在真的發得出去** {len(ready):>2}"
          + (f"(另 {gap} 支缺 mp4 或縮圖)" if gap else ""))
    # 「下一支」等一下才印 —— 長片名額是**合輯優先**(見 ch3_publish.py),
    # 所以要先知道有沒有合輯可發,不能直接印單集的第一支。
    # 這跟 Shorts 排序是同一類錯:報告的順序必須等於發布器的順序。
    # 🔴 順序要跟發布器一致,不能自己排一份。發布器把**名案排在前面**
    #    (那是唯一有搜尋量的題材),純字母排序會把 ep000/ep001 排到第三、
    #    第四 —— 於是這裡印出來的「下四支」跟實際會發的不是同一批。
    #    一份會誤導的狀態報告比沒有報告更糟。
    shorts = sorted((d.name for d in (ROOT / "shorts").iterdir() if d.is_dir()),
                    key=lambda n: (n.startswith("ep"), n))
    sl = [s for s in shorts if s not in sh_led]
    print(f"  Shorts 產好 {len(shorts):>2}、已發 {len(sh_led):>2}、待發 {len(sl):>2}"
          f"   下四支:{', '.join(sl[:4]) if sl else '—'}")
    print("         (實際會發哪四支要看閘門 —— 被擋下的會由候補遞補;"
          + ("--local 不查閘門,所以這裡只是候選順序)" if offline
             else "見下面「閘門」那段)"))
    # 🔴 合輯要把「有沒有 manifest」跟「發不發得出去」**連起來講**。
    #    publish_comp 沒有 manifest 就 return None,所以缺 manifest =
    #    那支現在一支都發不出去 —— 而原本這兩件事印成兩行不相干的事實。
    comp_ok = [b for b in ("fail", "mixed", "held")
               if (ROOT / "compilations" / b / f"{b}_compilation.mp4").exists()
               and (ROOT / "compilations" / b / "manifest.json").exists()
               and b not in comp_led]
    print(f"  合輯   已發 {len(comp_led)} / 3、**現在發得出去** {len(comp_ok)} 支"
          f"   {', '.join(comp_ok) if comp_ok else '(缺 manifest → publish_comp 會全部擋下)'}")
    nxt = (f"合輯 {comp_ok[0]}(合輯優先)" if comp_ok
           else (ready[0]["title"][:52] if ready else "— 沒有可發的"))
    print(f"\n  長片名額下一支:{nxt}")

    n_long = 1 if (ready or comp_ok) else 0
    n_short = min(4, len(sl))
    print(f"\n  下次排程(每天 16:25)實際會送出:長片 {n_long} 支 + Shorts "
          f"{n_short} 支(閘門可能再減),配額約 "
          f"{n_long * 1691 + n_short * 1641:,} / 10,000")


def live():
    rule("頻道實況")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(
        str(CH2 / "token.json"),
        ["https://www.googleapis.com/auth/youtube.readonly"])
    yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
    ch = yt.channels().list(part="snippet,statistics,contentDetails",
                            mine=True).execute()["items"][0]
    if ch["id"] != EXPECT_CHANNEL:
        print(f"  ⛔ 頻道不符:{ch['id']}")
        return
    s, st = ch["snippet"], ch["statistics"]
    print(f"  {s['title']}  {s.get('customUrl', '')}")
    print(f"  訂閱 {st.get('subscriberCount')}  影片 {st.get('videoCount')}"
          f"  總觀看 {st.get('viewCount')}")

    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=up,
                                    maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    rows = []
    for i in range(0, len(ids), 50):
        rows += yt.videos().list(part="snippet,status,statistics,contentDetails",
                                 id=",".join(ids[i:i + 50])).execute()["items"]
    rows.sort(key=lambda v: -int(v["statistics"].get("viewCount", 0)))
    n_pub = sum(1 for v in rows if v["status"]["privacyStatus"] == "public")
    views = sum(int(v["statistics"].get("viewCount", 0)) for v in rows)
    shorts = sum(1 for v in rows
                 if v["contentDetails"]["duration"].startswith("PT")
                 and "M" not in v["contentDetails"]["duration"])
    print(f"  上線 {len(rows)} 支(public {n_pub})、總觀看 {views}")
    # ⚠️ 只用長度判定,**不等於**「有幾支被 YouTube 判為 Short」——
    #    16:9 的片就算 58 秒也不會是 Short(要直式)。擺在「上線 N 支」
    #    旁邊很容易被讀成「我們有 N 支 Shorts」。
    print(f"  其中 60 秒內 {shorts} 支(**這不是 Shorts 數** —— 還要直式才算)")
    print(f"\n  {'觀看':>4}  {'狀態':<9}{'長度':<9}{'發布':<11}標題")
    for v in rows[:12]:
        print(f"  {v['statistics'].get('viewCount', '0'):>4}  "
              f"{v['status']['privacyStatus']:<9}"
              f"{v['contentDetails']['duration']:<9}"
              f"{v['snippet']['publishedAt'][:10]:<11}"
              f"{v['snippet']['title'][:52]}")
    if not any(v["status"]["privacyStatus"] != "public" for v in rows):
        return
    print("\n  非 public 的:")
    for v in rows:
        if v["status"]["privacyStatus"] != "public":
            print(f"    {v['id']}  {v['status']['privacyStatus']:<9}"
                  f"{v['snippet']['title'][:50]}")


def gates():
    # ⚠️ 標題不能寫「不連網」:`cta_gate` 吃的長片公開狀態是
    #    `public_only()` 用 videos.list 查來的,它**要連網**。
    rule("閘門會擋下誰(需要連網:要查長片目前公不公開)")
    sys.path.insert(0, str(ROOT))
    try:
        import publish_shorts as ps
        items = ps.build_meta()
        done = ps.ledger(ps.LEDGER)
        todo = [o for o in items if o["key"] not in done][:4]
        blocked = ps.cta_gate(todo, ps._LONGS_PUB, ps._LONGS_ALL)
        bad, _src = ps.stale(todo)
        print(f"  Shorts 陳舊檢查:{'全部是最新產物 ✓' if not bad else ''}")
        for b in bad:
            print(f"     ⛔ {b}")
        print(f"  Shorts 宣稱閘門:{'沒有擋下任何一支 ✓' if not blocked else ''}")
        for k_, why in blocked:
            print(f"     ⛔ {k_}  {why}")
    except Exception as e:                                    # noqa: BLE001
        print(f"  (Shorts 閘門查不了:{str(e)[:80]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="不連網")
    a = ap.parse_args()
    local()
    queues(offline=a.local)
    if a.local:
        return 0
    # 🔴 兩段各自包 try/except。共用一個的話,`live()` 中途丟例外(配額、
    #    網路)就會讓 `gates()` 整段不執行,而畫面上只有一句「連網部分
    #    失敗」—— **沒有 ⛔ 會被讀成「沒有東西被擋」**,那是最危險的誤讀。
    for fn, label in ((live, "頻道實況"), (gates, "閘門")):
        try:
            fn()
        except Exception as e:                                # noqa: BLE001
            print(f"\n  ⚠️ 「{label}」查不到({str(e)[:90]})")
            print("     —— 這不等於沒問題,只是**沒查到**。別把它讀成綠燈。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
