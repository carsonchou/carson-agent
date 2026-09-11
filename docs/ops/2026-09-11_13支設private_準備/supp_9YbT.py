# -*- coding: utf-8 -*-
"""9YbTzPfXz6A 補讀 —— 🔴 read-only,本檔零 videos.update。

督導 09-11 轉來獨立驗證者的發現:9YbTzPfXz6A 旁白第三句在「追進零零五零或零零」中斷、直接接回聲 CTA,
兩把尺(尺A 有效主體、尺B 回聲餘)都不叫。派工:下一次 videos.list 帶上它、查 privacyStatus、
在 dry-run 另列「待 Carson 另判」,**不併進 13 支那批**。

呼叫:videos.list part=snippet,status,statistics,contentDetails,送 [9YbTzPfXz6A, ZZZZfake000],1 次 = 1 unit。
      假 id 是為了證明「沒回來」會被看見(videos.list 對讀不到的 id 靜默略過)。
產出:snapshot_9YbT.json(+ STUDIO/desc_backup 與 repo 外兩份副本)、snapshot_9YbT.md5、
      candidates.json 新增獨立鍵 pending_carson_separate(videos / count 不動)。
"""
import io, json, os, re, sys, hashlib, datetime, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
YC = os.path.normpath(os.path.join(HERE, "..", "..", "..", "youtube_channel"))
os.chdir(YC)
sys.path.insert(0, "scripts")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
import daily_publish as dp

VID = "9YbTzPfXz6A"
SLUG = "S_臺股狂漲3186點新手追高賠光嗎我回測揭露真實後果"
FAKE = "ZZZZfake000"
led = json.load(io.open("STUDIO/uploaded_ledger.json", encoding="utf-8"))
assert led.get(SLUG) == VID, "ledger slug↔id 對不上:%r" % led.get(SLUG)

# ---- 尺A / 尺B:627a3f4e §八 原文 ----
CTA = re.compile(r"訂閱|追蹤我|追蹤一下|回開頭|回頭重聽|重聽一次開頭|留言告訴我|私訊|Telegram|@Carson"
                 r"|按讚|分享給|不構成投資建議|把這句記起來|這就是「")
ECHO_CUE = re.compile(r"回開頭|回頭重聽|重聽一次開頭|從頭再聽一次|回到開頭")
QUOTED = re.compile(r"[「『\"]([^」』\"]{1,80})[」』\"]")
LEAD2 = re.compile(
    r"(?:(?:不確定的話|如果這個結果讓你意外|再看一次也可以)?[，,]?\s*"
    r"(?:回開頭再聽一次|回開頭對一次|回頭重聽一次開頭|回到開頭再聽一次)"
    r"|這就是|把這句記起來[：:]?)\s*$")
def split_s(t):
    return [s for s in re.split(r"(?<=[。!?！？\n])", t) if re.sub(r"\s", "", s)]
def effective_body(t):
    return "".join(re.sub(r"\s", "", s) for s in split_s(t) if not CTA.search(s))
def echo_leftover(t):
    best = None
    for s in split_s(t):
        if not ECHO_CUE.search(s): continue
        at = t.find(s)
        for m in QUOTED.finditer(s):
            pre = LEAD2.sub("", s[:m.start()])
            head = re.sub(r"\s", "", t[:at] + pre)
            q = re.sub(r"\s", "", m.group(1))
            if q and q == head[:len(q)]:
                v = len(head) - len(q)
                best = v if best is None else min(best, v)
        if best is None: best = 999
    return best

vt = io.open("output/%s.voice.txt" % SLUG, encoding="utf-8").read()
eb, el = len(effective_body(vt)), echo_leftover(vt)
print("[尺] %s  有效主體=%d(S_ 地板 28) 回聲餘=%s(門檻 2) ⇒ 尺A %s / 尺B %s"
      % (VID, eb, el, "叫" if eb <= 28 else "不叫", "叫" if el is not None and el <= 2 else "不叫"))

# ---- 1 unit ----
yt = dp.get_service()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
ids = [VID, FAKE]
resp = yt.videos().list(part="snippet,status,statistics,contentDetails", id=",".join(ids)).execute()
items = {it["id"]: it for it in resp.get("items", [])}
sent, back = set(ids), set(items)
print("[videos.list] 送出 %d / 回來 %d / 沒回來 %s" % (len(sent), len(back), sorted(sent - back)))
assert sent - back == {FAKE}, "完整性異常:沒回來的應該只有假 id,實際 %r" % sorted(sent - back)
it = items[VID]
st = it["status"]
print("[%s] privacyStatus=%s views=%s duration=%s publishedAt=%s"
      % (VID, st.get("privacyStatus"), it["statistics"].get("viewCount"),
         it["contentDetails"].get("duration"), it["snippet"].get("publishedAt")))
print("[%s] status 全欄位 %s" % (VID, json.dumps(st, sort_keys=True)))

# ---- 快照 + 三份副本 ----
snap = {"fetched_at": now,
        "request": {"part": "snippet,status,statistics,contentDetails",
                    "ids_sent": ids, "ids_returned": sorted(back)},
        "items": items}
sp = os.path.join(HERE, "snapshot_9YbT.json")
data = json.dumps(snap, ensure_ascii=False, indent=2) + "\n"
io.open(sp, "w", encoding="utf-8", newline="\n").write(data)
assert io.open(sp, encoding="utf-8", newline="").read() == data
copies = [os.path.join(YC, "STUDIO", "desc_backup", "private_prep_2026-09-11", "snapshot_9YbT.json"),
          r"D:\carson-agent-backups\private_prep_2026-09-11\snapshot_9YbT.json"]
for c in copies:
    os.makedirs(os.path.dirname(c), exist_ok=True)
    shutil.copy2(sp, c)
md5s = {p: hashlib.md5(io.open(p, "rb").read()).hexdigest() for p in [sp] + copies}
io.open(os.path.join(HERE, "snapshot_9YbT.md5"), "w", encoding="utf-8", newline="\n").write(
    "".join("%s  %s\n" % (m, p) for p, m in md5s.items()))
for p, m in md5s.items():
    print("md5", m, p)
print("三份 md5 一致:", len(set(md5s.values())) == 1)

# ---- candidates.json:獨立鍵,13 支那批一個字不動 ----
cp = os.path.join(HERE, "candidates.json")
cand = json.load(io.open(cp, encoding="utf-8"))
before_videos = json.dumps(cand["videos"], ensure_ascii=False, sort_keys=True)
cand["pending_carson_separate"] = [{
    "slug": SLUG, "videoId": VID,
    "privacyStatus_at_read": st.get("privacyStatus"),
    "viewCount_at_read": int(it["statistics"].get("viewCount", 0) or 0),
    "duration": it["contentDetails"].get("duration"),
    "publishedAt": it["snippet"].get("publishedAt"),
    "effective_body": eb, "echo_leftover": el,
    "rulers": "尺A 不叫(%d > 28)、尺B 不叫(%s > 2) —— 不是這兩把尺的命中" % (eb, el),
    "found_by": "獨立驗證者(督導 09-11 轉交):CTA 前無句末標點掃描,42 候選中唯一真斷尾",
    "own_reading": "本線開 voice.txt 全文複判:旁白第三句停在「就忍不住追進零零五零或零零」(半個代號),"
                   "無標點直接接「這就是「…結果假設」的答案,回開頭對一次…」—— 引文本身也斷在「結果假設」;"
                   "HOOK 承諾的「少賺五十八趴」回測內容一句都沒講。wordtimes.json 顯示 TTS 確實把斷句與回聲 CTA 當同一句念出(11.914s 起 11.551s)。",
    "status": "PENDING_CARSON_SEPARATE —— 不在 13 支批次內,未經 Carson 判定不得併入",
}]
out = json.dumps(cand, ensure_ascii=False, indent=2) + "\n"
tmp = cp + ".tmp"
io.open(tmp, "w", encoding="utf-8", newline="\n").write(out)
chk = json.load(io.open(tmp, encoding="utf-8"))
assert json.dumps(chk["videos"], ensure_ascii=False, sort_keys=True) == before_videos and chk["count"] == 13
os.replace(tmp, cp)
print("candidates.json:videos 13 支未動;新增 pending_carson_separate 1 筆")
print("API 用量:videos.list 1 次 = 1 unit(全程唯讀)")
