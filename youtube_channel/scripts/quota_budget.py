#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quota_budget.py — YouTube Data API 每日配額預算表(事前預估,不是事後補救)。

為什麼要有這支(2026-08-25 建):
  配額上限 10,000 units/天,但**單價極不對稱**:videos.list 只要 1,
  captions.update 要 450,上傳一支影片 videos.insert 要 1600。
  排程表一路加 job、--max 一路調高,沒人算過總量 → 2026-08-24 查出固定排程
  估算 ~12,700 > 10,000 = **結構性超支,每天必爆**。
  爆掉的後果不是「少跑一支」,而是 gather_stats 分塊查詢部分失敗、
  回傳殘缺資料被當成真值寫進 metrics(見 memory yt-quota-partial-failure-silent-bad-data),
  害趨勢算出 -98.5% 假崩盤,再害 growth_agent 連續對假訊號出手灌題。

做法:解析 deploy/crontab.txt → 每行抓 script 與 --max → 掃該 script 原始碼
用到哪些 API → 對照單價表 × 每日執行次數,估出每日總量。
未來改排程/調 --max 會自動反映,不必手動維護清單。

用法:
  python scripts/quota_budget.py            # 印報表
  python scripts/quota_budget.py --notify   # 超標才推 ntfy(給排程用)
  python scripts/quota_budget.py --top 15   # 只看最貴的前 N 支

限制(誠實標示):這是**靜態估算**,不是實測值。
  - 只能看到「最多會用多少」:有些 script 實際處理數量會少於 --max(沒那麼多待辦)。
  - 抓不到迴圈內的動態呼叫次數,只用 --max 當上限;沒有 --max 的當 1 次。
  - 真實用量要靠 Google Cloud Console 的配額頁,或事後數 job_stderr.log 的 403。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CRONTAB = ROOT / "deploy" / "crontab.txt"

# 🔴 2026-08-31 10,000 → 19,645。10,000 是 Google 文件的預設值,**不是本專案的實際額度**。
# 實測:08-25 花 18,914 零被拒;08-31 發 8 支用 18,100、meter 回報剩 1,475(合計 19,575)。
# 舊常數的後果不是少花錢,是**每次跑都喊「超標 356%」**——一個永遠在響的警報等於沒有警報,
# 真的超標時沒人會注意到。上限仍未在 19,645 以上實測過,拿到新證據要往上修。
DAILY_LIMIT = 19645

# YouTube Data API v3 官方單價(units/次)
COST = {
    "videos.insert": 1600,
    "captions.update": 450,
    "captions.insert": 400,
    "captions.download": 200,
    "search.list": 100,
    "videos.update": 50,
    "videos.delete": 50,
    "videos.rate": 50,
    "thumbnails.set": 50,
    "playlists.insert": 50,
    "playlists.update": 50,
    "playlists.delete": 50,
    "playlistItems.insert": 50,
    "playlistItems.update": 50,
    "playlistItems.delete": 50,
    "comments.insert": 50,
    "comments.update": 50,
    "commentThreads.insert": 50,
    "captions.list": 50,
    "videos.list": 1,
    "playlists.list": 1,
    "playlistItems.list": 1,
    "comments.list": 1,
    "commentThreads.list": 1,
    "channels.list": 1,
    "channelSections.list": 1,
    "subscriptions.list": 1,
    "captions.list_": 50,
}

# 原始碼裡長這樣:yt.videos().list(...) / yt.captions().update(...)
API_RE = re.compile(r"\.(\w+)\(\)\s*\.\s*(list|insert|update|delete|set|rate|download)\b")


def parse_cron_field_count(expr: str) -> float:
    """把 cron 的「分 時 日 月 週」估成每日執行次數。"""
    parts = expr.split()
    if len(parts) < 5:
        return 1.0
    minute, hour, dom, mon, dow = parts[:5]

    def slots(field: str, total: int) -> int:
        if field == "*":
            return total
        n = 0
        for piece in field.split(","):
            if "/" in piece:
                base, step = piece.split("/", 1)
                try:
                    step_i = int(step)
                except ValueError:
                    step_i = 1
                span = total if base in ("*", "") else 1
                n += max(1, span // max(1, step_i))
            elif "-" in piece:
                try:
                    a, b = piece.split("-", 1)
                    n += max(1, int(b) - int(a) + 1)
                except ValueError:
                    n += 1
            else:
                n += 1
        return max(1, n)

    per_day = slots(minute, 60) * slots(hour, 24)

    # 週/日限制 → 折算成平均每日比例
    factor = 1.0
    if dow != "*":
        factor *= slots(dow, 7) / 7.0
    if dom != "*":
        factor *= slots(dom, 31) / 31.0
    if mon != "*":
        factor *= slots(mon, 12) / 12.0
    return per_day * factor


def apis_of(script_name: str):
    """掃 script 原始碼,回傳它用到的 API 端點集合。"""
    p = SCRIPTS / script_name
    if not p.exists():
        return set()
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return set()
    # 🔴 2026-08-25:這是純字串掃描,**連註解和 docstring 都會算進去**。
    # 實證:本檔自己有一行註解寫著「原始碼裡長這樣:yt.videos().list(...) /
    # yt.captions().update(...)」,被排進 crontab 之後,它就開始把**自己**估成
    # 451 units/日(450+1)——整份預算表因此虛報 451(37,930 實跑成 38,381)。
    # 用 tokenize 把註解與字串常數挖掉再掃;tokenize 失敗(語法錯)就退回原始碼,
    # 寧可高估也不要整支腳本從預算裡消失。
    try:
        import io
        import tokenize
        lines = src.splitlines(keepends=True)
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            (r1, c1), (r2, c2) = tok.start, tok.end
            for r in range(r1, r2 + 1):          # tokenize 的行號從 1 起算
                ln = lines[r - 1]
                a = c1 if r == r1 else 0
                b = c2 if r == r2 else len(ln.rstrip("\n"))
                lines[r - 1] = ln[:a] + " " * (b - a) + ln[b:]
        src = "".join(lines)
    except Exception:  # noqa: BLE001
        pass          # 語法錯就退回原始碼:寧可高估,也不要整支腳本從預算裡消失
    found = set()
    for res, verb in API_RE.findall(src):
        v = "set" if verb == "set" else verb
        key = "%s.%s" % (res, v)
        # thumbnails().set() → thumbnails.set
        if key in COST:
            found.add(key)
    return found


def parse_crontab():
    """回傳 [(script, args, per_day, raw_line)]"""
    if not CRONTAB.exists():
        return []
    out = []
    for raw in CRONTAB.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" in line.split()[0]:
            continue
        m = re.search(r"(scripts/([A-Za-z0-9_]+\.py))(.*?)(?:\s*>>|\s*2>|\s*$)", line)
        if not m:
            continue
        script = m.group(2)
        args = (m.group(3) or "").strip()
        cron_expr = " ".join(line.split()[:5])
        out.append((script, args, parse_cron_field_count(cron_expr), line))
    return out


# 🔴 2026-08-31 委派成本修正。apis_of 只掃**進入點那一個檔**,所以寫在 helper 裡的
# API 呼叫整個看不見:daily_publish 被估成 1,700/支,而帳本(by_op)實測是 2,150 ——
# 漏掉的 captions.insert(400)在 upload_youtube.py。這是整份表最大的一項,低估 21%,
# 而發布正是唯一沒有 RESERVE 保護、直接決定「今天發得出幾支」的那條。
#
# ⚠️ 試過「跟進一層本地 import」自動解決,**實測更糟**:總估算 33,500 → 67,371,
# 因為 produce_batch/ypp_meter/comment_watchdog 只是 import 了 daily_publish
# 就繼承它全部的 API —— 而 produce_batch 根本不吃 YouTube 配額(只走 LLM)。
# **import 一個模組不等於會呼叫它昂貴的函式。** 故改成這張定點表:
# 只列「已用帳本量過」的委派成本,沒量過的不猜。
_DELEGATED = {
    # script: (每次 --max 的額外 units, 來源)
    "daily_publish.py": (400, "captions.insert@upload_youtube;08-31 by_op 實測每支 2,150"),
}


def estimate(script, args, per_day):
    """估算單一 job 的每日 units。回傳 (units, 明細字串)。"""
    apis = apis_of(script)
    if not apis:
        return 0.0, ""
    m = re.search(r"--max\s+(\d+)", args)
    n = int(m.group(1)) if m else 1
    # 取該 script 用到的最貴的「寫入」API 當主成本(通常一支影片一次寫入),
    # 讀取類(1 unit)另計一次
    write = [a for a in apis if COST[a] >= 50]
    read = [a for a in apis if COST[a] < 50]
    units = 0.0
    detail = []
    for a in write:
        units += COST[a] * n
        detail.append("%s×%d" % (a, n))
    if script in _DELEGATED:
        _extra, _src = _DELEGATED[script]
        units += _extra * n
        detail.append("委派+%d×%d" % (_extra, n))
    for a in read:
        units += COST[a] * n
        detail.append("%s×%d" % (a, n))
    return units * per_day, ", ".join(detail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true", help="超標才推 ntfy")
    ap.add_argument("--top", type=int, default=20, help="列出最貴的前 N 支")
    args_ns = ap.parse_args()

    # 🔴 2026-08-31 把 YT_QUOTA_RESERVE 算進去。原本加總的是理論上限(每支 --max 全用滿),
    # 但帶 RESERVE 的工作合起來最多只花得到 `DAILY_LIMIT − RESERVE`。
    # 實測落差:08-31 估 37,236、實際 18,100 —— 差兩倍,而且**每次跑都 [ALERT]**。
    # 一個永遠在響的警報等於沒有警報:真的超標時沒人會注意到。
    # 封頂是**組層級**:五支都帶 19350 的工作是合起來分那 295,不是各自都能花 295
    # (逐支封頂會把估算灌水五倍,正是這次要修的病)。
    raw_rows, groups = [], {}
    for script, args, per_day, _raw in parse_crontab():
        units, detail = estimate(script, args, per_day)
        if units <= 0:
            continue
        m = re.search(r"YT_QUOTA_RESERVE=(\d+)", _raw)
        res = int(m.group(1)) if m else 0
        raw_rows.append([units, script, args, per_day, detail, res])
        groups.setdefault(res, []).append(raw_rows[-1])

    capped_note = []
    for res, members in groups.items():
        if res <= 0:
            continue                      # 沒 RESERVE 的(主線發布)本來就該優先吃配額
        room = max(0, DAILY_LIMIT - res)
        raw_sum = sum(m[0] for m in members)
        if raw_sum <= room:
            continue
        scale = room / raw_sum
        for m in members:
            m[0] *= scale                 # 按比例壓到組上限
        capped_note.append((res, raw_sum, room, len(members)))

    rows = [(m[0], m[1], m[2], m[3], m[4]) for m in raw_rows]
    rows.sort(reverse=True)

    total = sum(r[0] for r in rows)
    for res, raw_sum, room, n in sorted(capped_note):
        print(f"[封頂] RESERVE={res:,} 的 {n} 支工作:理論 {raw_sum:,.0f} → "
              f"實際最多 {room:,}(上限 {DAILY_LIMIT:,} 減掉預留額度)")
    print("=" * 74)
    print("YouTube API 每日配額預算(靜態估算)  上限 %s units" % f"{DAILY_LIMIT:,}")
    print("=" * 74)
    print("%-34s %9s %6s  %s" % ("script", "units/日", "次/日", "API"))
    print("-" * 74)
    for units, script, _a, per_day, detail in rows[:args_ns.top]:
        print("%-34s %9s %6.1f  %s"
              % (script[:34], f"{units:,.0f}", per_day, detail[:26]))
    if len(rows) > args_ns.top:
        print("... 另有 %d 支較小的未列出" % (len(rows) - args_ns.top))
    print("-" * 74)
    pct = total / DAILY_LIMIT * 100
    print("合計估算 %s units  =  上限的 %.0f%%" % (f"{total:,.0f}", pct))

    if total > DAILY_LIMIT:
        over = total - DAILY_LIMIT
        msg = ("配額預算超標:估算 %s > 上限 %s(超出 %s,%.0f%%)。"
               % (f"{total:,.0f}", f"{DAILY_LIMIT:,}", f"{over:,.0f}", pct))
        print("\n[ALERT] " + msg)
        print("        最貴的三支:" + "、".join(
            "%s(%s)" % (r[1], f"{r[0]:,.0f}") for r in rows[:3]))
        print("        超標的後果不是少跑一支,而是分塊查詢部分失敗→殘缺資料被當真值寫進 metrics。")
        if args_ns.notify:
            try:
                from notify import push
                push("量化阿森·配額預算超標", msg, tag="warning")
            except Exception as e:  # noqa: BLE001
                print("[warn] ntfy 失敗:%s" % e, file=sys.stderr)
        return 1
    print("\n[OK] 未超標,餘裕 %s units" % f"{DAILY_LIMIT - total:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
