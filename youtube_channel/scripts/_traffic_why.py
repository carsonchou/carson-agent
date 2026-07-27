# -*- coding: utf-8 -*-
"""_traffic_why.py — 診斷「觀看數為何變動」：流量來源 + 每日趨勢 + 近期爆量片 + 週對週。

🔴 2026-07-28 修正一個會產生假警報的 bug(它害我對 Carson 報了一個錯誤的 -54%):
   舊版把所有視窗都錨在 `date.today()`,但 **YouTube Analytics 有 2~4 天資料延遲**。
   於是「近7天」(today-7 ~ today) 實際只涵蓋 3~4 天有資料的日子,卻拿去比「前7天」
   (today-14 ~ today-7) 這個**完整 7 天**區間 → 系統性低報最近一週,實測算出 -54%,
   而用等長完整區間重算真實只有 -14%。**不等長的區間對比是假訊號製造機。**
   修法:先抓每日序列,取「最後一個真的有資料的日子」當錨點,所有視窗一律以它為基準,
   並印出延遲天數與各區間實際天數,讓讀的人一眼看得出有沒有被截斷。
"""
import sys, json
sys.path.insert(0, "scripts")
from pathlib import Path
from datetime import date, timedelta
import yt_analytics as ya

svc = ya._service()
if svc is None:
    print("NO_TOKEN"); sys.exit(0)


def q(**kw):
    try:
        return svc.reports().query(ids="channel==MINE", **kw).execute().get("rows", [])
    except Exception as e:
        return [("ERR", str(e))]


# ── 先抓夠長的每日序列,用來決定「資料真正到哪一天」 ──
_probe = q(startDate=(date.today() - timedelta(days=35)).isoformat(),
           endDate=date.today().isoformat(),
           dimensions="day", metrics="views,estimatedMinutesWatched,subscribersGained", sort="day")
_days = [r for r in _probe if isinstance(r, (list, tuple)) and len(r) >= 2 and str(r[0])[:2] == "20"]
if not _days:
    print("NO_DATA"); sys.exit(0)

END = date.fromisoformat(_days[-1][0])          # 錨點 = 最後一個有資料的日子
LAG = (date.today() - END).days
print(f"※ 資料截至 {END}(今天 {date.today()},Analytics 延遲 {LAG} 天)。"
      f"所有區間以「資料最後一天」為錨點,確保兩邊等長。")

# 1) 每日趨勢(近14天)
print("\n=== 每日觀看(近14天) ===")
for r in _days[-14:]:
    print(r)

W = 7
cur_s, cur_e = (END - timedelta(days=W - 1)).isoformat(), END.isoformat()
prev_s, prev_e = (END - timedelta(days=2 * W - 1)).isoformat(), (END - timedelta(days=W)).isoformat()

# 2) 流量來源
print(f"\n=== 流量來源({cur_s}~{cur_e}) views / 觀看分鐘 / 平均觀看% ===")
for r in q(startDate=cur_s, endDate=cur_e,
           dimensions="insightTrafficSourceType",
           metrics="views,estimatedMinutesWatched,averageViewPercentage", sort="-views"):
    print(r)

# 3) top 影片
print(f"\n=== top 影片({cur_s}~{cur_e}) ===")
vids = q(startDate=cur_s, endDate=cur_e, dimensions="video",
         metrics="views,averageViewPercentage,subscribersGained", sort="-views", maxResults=8)
titles = {}
p = Path("STUDIO/channel_videos.json")
if p.exists():
    try:
        cv = json.loads(p.read_text(encoding="utf-8"))
        items = cv if isinstance(cv, list) else cv.get("videos", cv.get("items", []))
        for it in items:
            vid = it.get("video_id") or it.get("id") or it.get("videoId")
            t = it.get("title") or it.get("name")
            if vid and t:
                titles[vid] = t
    except Exception:
        pass
# 補:uploaded_ledger 的 slug 也能當標題用(channel_videos.json 常不存在)
if not titles:
    lp = Path("STUDIO/uploaded_ledger.json")
    if lp.exists():
        try:
            def _walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, str) and len(v) == 11:
                            titles[v] = k
                        _walk(v)
                elif isinstance(o, list):
                    for v in o:
                        _walk(v)
            _walk(json.loads(lp.read_text(encoding="utf-8")))
        except Exception:
            pass
for r in vids:
    print(r, "|", titles.get(r[0], "?")[:40])

# 4) 週對週(等長,且明示天數)
print("\n=== 週對週(等長區間) ===")


def _sum(a, b, metric):
    s = [r for r in _days if a <= r[0] <= b]
    idx = {"views": 1, "minutes": 2, "subs": 3}[metric]
    return sum(r[idx] for r in s if len(r) > idx), len(s)


for label, metric in (("觀看", "views"), ("觀看分鐘", "minutes"), ("訂閱", "subs")):
    c, cn = _sum(cur_s, cur_e, metric)
    p_, pn = _sum(prev_s, prev_e, metric)
    delta = f"{(c - p_) / p_ * 100:+.0f}%" if p_ else "n/a"
    warn = "  ⚠️ 區間天數不等,勿直接比較" if cn != pn else ""
    print(f"  {label:<5} 近{cn}天({cur_s}~{cur_e}) {c:>7}  vs  前{pn}天({prev_s}~{prev_e}) {p_:>7}   {delta}{warn}")

print("\n※ 觀看數下降但『觀看分鐘』上升 = 格式從 Shorts 轉長片的預期結果,不是流量出事;"
      "\n   兩者要一起看,只看觀看數會做出錯誤決策。")
