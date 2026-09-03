# -*- coding: utf-8 -*-
"""暴發日 vs 非暴發日:當日發布片的「累積至今總量」對比(每日總量口徑,非每支中位)。
督導質疑削峰建議的承重:每支中位低(3 vs 37)但暴發日貢獻 52% 流量——若每日總量
暴發日較高,削峰=削掉主要流量來源,建議要撤回。兩口徑(觀看次數/觀看時數)都算。"""
import sys, json, pathlib, datetime, collections, statistics
ROOT = pathlib.Path(r"D:/carson-agent/youtube_channel")
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
try:
    import quota_meter as _qm; _qm.install()
except Exception:
    pass

creds = Credentials.from_authorized_user_file(str(ROOT / "token_manage.json"))
yt = build("youtube", "v3", credentials=creds)
creds_a = Credentials.from_authorized_user_file(str(ROOT / "token_analytics.json"))  # 含 yt-analytics.readonly
ya = build("youtubeAnalytics", "v2", credentials=creds_a)

led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text("utf-8"))
ids = sorted({v for v in led.values() if isinstance(v, str) and len(v) == 11})
print(f"ledger video ids: {len(ids)}", file=sys.stderr)

# ── Data API:發布日+現在的累積觀看+片長(1 unit/50 支) ──
meta = {}
for i in range(0, len(ids), 50):
    batch = ids[i:i+50]
    r = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(batch), maxResults=50).execute()
    for it in r.get("items", []):
        pub = it["snippet"]["publishedAt"]                       # UTC
        d = (datetime.datetime.fromisoformat(pub.replace("Z", "+00:00"))
             + datetime.timedelta(hours=8)).date().isoformat()   # 台北日
        dur = it["contentDetails"]["duration"]                   # PT#M#S
        secs, num = 0, ""
        for ch in dur:
            if ch.isdigit(): num += ch
            elif ch in "HMS" and num:
                secs += int(num) * {"H": 3600, "M": 60, "S": 1}[ch]; num = ""
        meta[it["id"]] = {"day": d, "views": int(it["statistics"].get("viewCount", 0)),
                          "secs": secs, "short": secs <= 90}
print(f"videos.list got {len(meta)} (calls={len(range(0,len(ids),50))})", file=sys.stderr)

# ── Analytics:每支終身觀看時數(filters=video== 分批,繞 Top-200 截斷) ──
end = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
minutes = {}
poison = []

def q(batch, depth=0):
    import time as _t
    for attempt in range(3):
        try:
            r = ya.reports().query(ids="channel==MINE", startDate="2026-01-01", endDate=end,
                                   metrics="estimatedMinutesWatched,views", dimensions="video",
                                   filters="video==" + ",".join(batch), maxResults=200).execute()
            for row in r.get("rows", []) or []:
                minutes[row[0]] = {"min": row[1], "aviews": row[2]}
            return
        except Exception as e:
            if attempt < 2:
                _t.sleep(3 * (attempt + 1)); continue
            if len(batch) == 1:
                poison.append(batch[0]); print(f"poison id skipped: {batch[0]} ({e})", file=sys.stderr); return
            mid = len(batch) // 2
            q(batch[:mid], depth+1); q(batch[mid:], depth+1); return

live = [v for v in meta]
for i in range(0, len(live), 50):
    q(live[i:i+50])
print(f"analytics rows: {len(minutes)}, poison skipped: {len(poison)}", file=sys.stderr)

# ── 按發布日彙總 ──
day = collections.defaultdict(lambda: {"n": 0, "views": 0, "min": 0.0, "n_long": 0, "min_long": 0.0})
for vid, m in meta.items():
    d = day[m["day"]]
    d["n"] += 1
    d["views"] += m["views"]
    mn = minutes.get(vid, {}).get("min", 0.0)
    d["min"] += mn
    if not m["short"]:
        d["n_long"] += 1
        d["min_long"] += mn

BURST = 21
def agg(days):
    if not days: return None
    tv = [day[d]["views"] for d in days]; tm = [day[d]["min"] for d in days]
    tl = [day[d]["min_long"] for d in days]
    return {"days": len(days), "vids": sum(day[d]["n"] for d in days),
            "views_total": sum(tv), "views/day_med": statistics.median(tv), "views/day_mean": round(sum(tv)/len(days)),
            "hours_total": round(sum(tm)/60), "hours/day_med": round(statistics.median(tm)/60, 1),
            "hours/day_mean": round(sum(tm)/60/len(days), 1),
            "longform_hours_total": round(sum(tl)/60)}

all_days = sorted(day)
burst = [d for d in all_days if day[d]["n"] >= BURST]
normal = [d for d in all_days if day[d]["n"] < BURST]
print("\n== 全期 ==")
print("暴發日(≥21):", burst)
print("burst :", json.dumps(agg(burst), ensure_ascii=False))
print("normal:", json.dumps(agg(normal), ensure_ascii=False))

# 同時代窗口(排除頻道八月起飛的混淆):06-15 ~ 07-15
era = [d for d in all_days if "2026-06-15" <= d <= "2026-07-15"]
eb = [d for d in era if day[d]["n"] >= BURST]; en = [d for d in era if day[d]["n"] < BURST]
print("\n== 同時代窗口 06-15~07-15 ==")
print("burst :", json.dumps(agg(eb), ensure_ascii=False))
print("normal:", json.dumps(agg(en), ensure_ascii=False))

out = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
       "burst_days": burst, "per_day": {d: day[d] for d in all_days}}
p = pathlib.Path(r"C:/Users/User/AppData/Local/Temp/claude/D--carson-agent/00a16ee8-8ed7-4e89-9595-01ed040ff2b6/scratchpad/burst_day_totals.json")
p.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
print("\nevidence saved:", p, file=sys.stderr)
