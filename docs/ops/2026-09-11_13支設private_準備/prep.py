# -*- coding: utf-8 -*-
"""13 支 public Shorts 設 private 的準備工作 —— 🔴 read-only,本檔零 videos.update。

呼叫(全部唯讀):
  videos.list  part=snippet,status,statistics,contentDetails   1 次(≤50 id)   1 unit
  channels.list part=contentDetails mine=True                  1 次            1 unit
  playlistItems.list part=status,contentDetails videoId=<id>    每支 1 次       ~24 units
產出(本資料夾):
  candidates.json   機器可讀清單(13 支 + 對照組)
  snapshot.json     完整 status+snippet 快照 + 第二儀器 T0 基線
  snapshot.md5      三份副本(本資料夾 / STUDIO/desc_backup / repo 外)的 md5
"""
import io, json, os, sys, hashlib, datetime, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
YC = os.path.normpath(os.path.join(HERE, "..", "..", "..", "youtube_channel"))
os.chdir(YC)
sys.path.insert(0, "scripts")
import daily_publish as dp

HITS = [  # slug / videoId / 觀看(掃描時) / 有效主體 / 回聲餘   ← 627a3f4e §二
    ("S_台積電暴跌35元你恐慌殺出會少賺多少0050回測嚇壞", "MuXiM5IqVQQ", 702,  0, 0),
    ("S_CPI破254你該追高我用回測資料打臉這句通膨追高網",   "TDbm4XR5pYk", 183,  0, 0),
    ("S_CPI連破3個月你的投資組合正在被通膨怪獸悄悄吃掉多", "cObU5NcFT-I",  91,  0, 0),
    ("S_非農資料利空臺股恐慌殺出0050定投竟多賺23倍",       "I8F83sPFKWg", 741,  0, 0),
    ("S_Fed恐慌殺你的資產會少幾成這招資金配置避開大虧",     "_Cc49y7ZAeM", 220,  5, 9),
    ("S_台積電飆破800元你的網格機器人是賺翻還是慘賠",       "tN56crKxwJE", 718, 13, 0),
    ("S_市場狂熱你的網格機器人是賺翻還是清零",               "mvDrUnxEjWs", 204,  0, 0),
    ("S_CPI爆表0050定投vs恐慌殺出十年報酬竟差一倍",        "vwEaoo3Txjw", 290,  0, 0),
    ("S_0050定期定額臺股回檔竟比一次全押少賺一半",           "UTuMMyvdQ5U", 898,  0, 0),
    ("S_臺股暴漲5000點你的0050網格反而少賺一臺賓士",        "DhX2uNzjZ-o", 866,  0, 0),
    ("S_市場巨變你的自動交易設定會讓你多賠一輛車",           "OyprNxjrIBQ",  89, 28, 2),
    ("S_CPI資料一公佈你的網格機器人會不會被套到歸零",       "nHwP_cyy_hc", 328,  0, 0),
    ("S_升息499你的投資組合會被這盲點多咬掉多少",           "xjQPW3sTY28", 186, 19, 7),
]
# 陰性對照 A:627a3f4e 判得動且 A/B 皆否的 public Shorts,且不出現在任何 09-1x docs/ops 報告、
# _private_batch_ids、STUDIO/*private*/*zombie* 清單裡(=其他線不太可能去動它)。取前 3 支 public。
CTRL_CANDIDATES = ["kk893Wva6c4", "fYTywq3Ah1c", "s4jROPETmlE", "Xmc_qtMqPhk", "PEi1jvjhD68"]
# 陰性對照 B:3 支 unlisted 壞片 —— 派工明定不在這批、維持不動(627a3f4e 建議 B)
UNLISTED = ["nrIYmQgjHFs", "h4vTXYtlQ7I", "rgeDJ3vxlxI"]
# 第二儀器的陽性對照:已知曾被設 private 的片(STUDIO/_private_batch_ids.json)。只讀,不寫那個檔。
POS_CTRL = json.load(io.open("STUDIO/_private_batch_ids.json", encoding="utf-8"))

hit_ids = [h[1] for h in HITS]
ids = hit_ids + CTRL_CANDIDATES + UNLISTED + POS_CTRL
assert len(set(ids)) == len(ids) <= 50, "id 重複或超過 50"

yt = dp.get_service()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()

# ---- 儀器 1:videos.list(寫入時也會用它) ----
resp = yt.videos().list(part="snippet,status,statistics,contentDetails",
                        id=",".join(ids)).execute()
items = {it["id"]: it for it in resp.get("items", [])}
sent, back = set(ids), set(items)
print("[儀器1 videos.list] 送出 %d / 回來 %d / 沒回來 %s"
      % (len(sent), len(back), sorted(sent - back) or "無"))

def priv(v):
    return items.get(v, {}).get("status", {}).get("privacyStatus")

controls = [v for v in CTRL_CANDIDATES if priv(v) == "public"][:3]
assert len(controls) == 3, "public 陰性對照湊不到 3 支:%r" % {v: priv(v) for v in CTRL_CANDIDATES}

keys = set()
for it in items.values():
    keys |= set(it.get("status", {}))
print("[儀器1] status 回傳欄位:", sorted(keys))

# ---- 儀器 2:playlistItems.list(uploads 播放清單,videoId 過濾,一支一問,不走分頁) ----
ch = yt.channels().list(part="contentDetails", mine=True).execute()
uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
inst2 = {}
for v in hit_ids + controls + UNLISTED + POS_CTRL:
    try:
        r = yt.playlistItems().list(part="status,contentDetails", playlistId=uploads,
                                    videoId=v, maxResults=5).execute()
        its = r.get("items", [])
        got = [i.get("contentDetails", {}).get("videoId") for i in its]
        inst2[v] = {
            "n_items": len(its),
            "videoIds_returned": got,
            # 過濾有沒有真的套用:回來的每一筆都必須是我問的那支(memory filter-accepted-is-not-filter-applied)
            "filter_applied": bool(its) and all(g == v for g in got),
            "privacyStatus": its[0].get("status", {}).get("privacyStatus") if its else None,
        }
    except Exception as e:  # noqa: BLE001
        inst2[v] = {"error": repr(e)[:200]}

print("\n[儀器2 playlistItems.list videoId=] 對照儀器1:")
print("  %-12s %-9s %-9s %-6s %s" % ("videoId", "儀器1", "儀器2", "一致", "過濾套用"))
agree = {}
for v in hit_ids + controls + UNLISTED + POS_CTRL:
    a, b = priv(v), inst2[v].get("privacyStatus")
    agree[v] = (a == b)
    grp = "13" if v in hit_ids else "ctrl" if v in controls else "unl" if v in UNLISTED else "pos"
    print("  %-12s %-9s %-9s %-6s %s  [%s]%s" % (v, a, b, a == b, inst2[v].get("filter_applied"), grp,
          ("  ERR " + inst2[v]["error"]) if "error" in inst2[v] else ""))
cats = sorted(set(priv(v) for v in POS_CTRL + UNLISTED if priv(v)))
print("  陽性/陰性對照涵蓋的非 public 值:", cats)

# ---- 清單 ----
rows = []
for slug, vid, views_at_scan, eff, echo in HITS:
    it = items.get(vid, {})
    why = "尺A 零主體(有效主體 %d ≤ 28)" % eff
    if echo <= 2:
        why += " + 尺B 自我循環(回聲餘 %d ≤ 2)" % echo
    rows.append({
        "slug": slug, "videoId": vid,
        "privacyStatus_at_prep": priv(vid),
        "viewCount_at_prep": int(it.get("statistics", {}).get("viewCount", 0) or 0),
        "viewCount_at_scan": views_at_scan,
        "duration": it.get("contentDetails", {}).get("duration"),
        "publishedAt": it.get("snippet", {}).get("publishedAt"),
        "effective_body": eff, "echo_leftover": echo,
        "reason": why,
        "proposed_privacyStatus": "private",
    })

def _ctrl(v, must):
    it = items.get(v, {})
    return {"videoId": v, "title": it.get("snippet", {}).get("title"),
            "privacyStatus_at_prep": priv(v), "must_remain": must}

doc = {
    "generated_at": now,
    "source_report": "docs/ops/2026-09-11_已發布壞片_空旁白與自我循環_母體掃描.md (627a3f4e)",
    "status": "PROPOSAL_ONLY_NOT_EXECUTED",
    "note": "🔴 尚未執行。設 private 屬對外+寫正式機:需 Carson 拍板 + 督導放行 + 獨立驗證。"
            "🔴 不要把這些 id 放進 STUDIO/_private_batch_ids.json —— zombie_sweep.py 會自動執行、"
            "set_private_by_ids.py 的寫法會重設 status 其他欄位。",
    "count": len(rows),
    "videos": rows,
    "negative_controls_public": [_ctrl(v, "public") for v in controls],
    "negative_controls_unlisted": [_ctrl(v, "unlisted") for v in UNLISTED],
    "instrument2_positive_controls": [_ctrl(v, priv(v)) for v in POS_CTRL],
}
io.open(os.path.join(HERE, "candidates.json"), "w", encoding="utf-8", newline="\n").write(
    json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

# ---- 快照 + 三份副本 ----
snap = {"fetched_at": now,
        "request": {"part": "snippet,status,statistics,contentDetails",
                    "ids_sent": ids, "ids_returned": sorted(back)},
        "items": items,
        "instrument2_T0": {"uploads_playlist": uploads, "results": inst2}}
sp = os.path.join(HERE, "snapshot.json")
io.open(sp, "w", encoding="utf-8", newline="\n").write(json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
copies = [os.path.join(YC, "STUDIO", "desc_backup", "private_prep_2026-09-11", "snapshot.json"),
          r"D:\carson-agent-backups\private_prep_2026-09-11\snapshot.json"]
for c in copies:
    os.makedirs(os.path.dirname(c), exist_ok=True)
    shutil.copy2(sp, c)
md5s = {p: hashlib.md5(io.open(p, "rb").read()).hexdigest() for p in [sp] + copies}
io.open(os.path.join(HERE, "snapshot.md5"), "w", encoding="utf-8", newline="\n").write(
    "".join("%s  %s\n" % (m, p) for p, m in md5s.items()))
for p, m in md5s.items():
    print("md5", m, p)
print("三份 md5 一致:", len(set(md5s.values())) == 1)
print("清單 %d 支;現況 privacyStatus:%s" % (len(rows), sorted(set(r["privacyStatus_at_prep"] for r in rows))))
print("陰性對照 public:", controls, "| unlisted:", [(v, priv(v)) for v in UNLISTED])
