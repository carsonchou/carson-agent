# -*- coding: utf-8 -*-
"""第二儀器 T0 預檢 —— 🔴 read-only,零寫入。

prep.py 裡的 playlistItems.list(videoId=...) 在 22 支裡只回了 1 支 ⇒ 那個過濾寫法不能當儀器。
改用:把 uploads 播放清單整份翻完(part=status,contentDetails,每頁 1 unit),
從裡面挑出我們關心的 22 支,看 status.privacyStatus 能不能跟 videos.list 對上。

要回答的三件事:
  1. 陽性對照(已知 private / unlisted)在這支儀器上讀得出非 public 嗎?(讀不出=它恆報 public,不能用)
  2. 22 支裡有幾支根本沒被翻到(memory yt-playlistitems-pagination-bug:909 列只有 874 唯一)
  3. 整份清單 列數 vs 唯一 id 數
產出:instrument2_preflight.json
"""
import io, json, os, sys, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
YC = os.path.normpath(os.path.join(HERE, "..", "..", "..", "youtube_channel"))
os.chdir(YC)
sys.path.insert(0, "scripts")
import daily_publish as dp

snap = json.load(io.open(os.path.join(HERE, "snapshot.json"), encoding="utf-8"))
cand = json.load(io.open(os.path.join(HERE, "candidates.json"), encoding="utf-8"))
uploads = snap["instrument2_T0"]["uploads_playlist"]
groups = collections.OrderedDict([
    ("13", [r["videoId"] for r in cand["videos"]]),
    ("ctrl", [c["videoId"] for c in cand["negative_controls_public"]]),
    ("unl", [c["videoId"] for c in cand["negative_controls_unlisted"]]),
    ("pos", [c["videoId"] for c in cand["instrument2_positive_controls"]]),
])
want = [v for g in groups.values() for v in g]

yt = dp.get_service()
rows, pages, tok = [], 0, None
while True:
    r = yt.playlistItems().list(part="status,contentDetails", playlistId=uploads,
                                maxResults=50, pageToken=tok).execute()
    pages += 1
    for it in r.get("items", []):
        rows.append((it.get("contentDetails", {}).get("videoId"),
                     it.get("status", {}).get("privacyStatus")))
    tok = r.get("nextPageToken")
    if not tok or pages >= 60:
        break

seen = collections.defaultdict(set)
for v, p in rows:
    seen[v].add(p)
dist = collections.Counter(p for _, p in rows)
print("uploads=%s 翻了 %d 頁(%d units)| 列 %d / 唯一 id %d | privacyStatus 分佈 %s"
      % (uploads, pages, pages, len(rows), len(seen), dict(dist)))
print("pageInfo.totalResults(最後一頁):", r.get("pageInfo", {}).get("totalResults"))

out = {}
print("\n  %-12s %-6s %-9s %-12s %s" % ("videoId", "組", "儀器1", "儀器2", "判定"))
for g, vs in groups.items():
    for v in vs:
        a = snap["items"].get(v, {}).get("status", {}).get("privacyStatus")
        b = sorted(seen[v]) if v in seen else None
        verdict = "未翻到" if b is None else ("一致" if b == [a] else "不一致")
        out[v] = {"group": g, "inst1": a, "inst2": b, "verdict": verdict}
        print("  %-12s %-6s %-9s %-12s %s" % (v, g, a, b, verdict))

c = collections.Counter(x["verdict"] for x in out.values())
pos_ok = [v for v in groups["pos"] + groups["unl"] if out[v]["verdict"] == "一致"]
print("\n判定分佈:", dict(c))
print("陽性對照讀得出非 public 的:%d/%d %s" % (len(pos_ok), len(groups["pos"]) + len(groups["unl"]), pos_ok))

json.dump({"fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "uploads_playlist": uploads, "pages": pages, "rows": len(rows), "unique_ids": len(seen),
           "privacy_distribution": dict(dist), "per_video": out},
          io.open(os.path.join(HERE, "instrument2_preflight.json"), "w", encoding="utf-8", newline="\n"),
          ensure_ascii=False, indent=2)
