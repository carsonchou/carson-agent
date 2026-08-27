#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""upload.py — 把 publish_meta.json 裡的集數上傳到副頻道 They Ran It Again。

繼承 music/calm/upload3.py 已驗過的教訓,不重新發明:
- **頻道白名單比對 channel ID**,不是比對 handle 字串。舊版 `if "carson" in
  customUrl` 是 fail-open:改名、customUrl 為 None、或第三個頻道都能過關。
- **selfDeclaredMadeForKids=False 必設**(不設 = 留言與營利腰斬)。
- **上傳完成 ≠ 處理完成**:輪詢到 processed 才算數;逾時要明講,不能默默當成功。
- **不信 insert 的回應,回讀確認**。
- 隱私參數**必填**:public 不可逆,不該有預設值。
- 不要設 `defaultAudioLanguage="zxx"`,API 會回 INVALID_REQUEST_METADATA。

## 每支片的配額
videos.insert = 1600 單位。ch2 用獨立的 GCP 專案(quiet-hour-yt),一天 10,000
→ **一天最多 5 支**(把輪詢 videos.list 也算進去之後)。所以預設一次只發
`--limit` 支,而且會先把估算印出來。

## 三道閘門
1. `publish_meta.py` 的溯源與 DOI fail-closed —— 進不了清單就進不了這裡
2. `semantic_gate()` —— 稿子講的話數字撐不撐得住(數字守門看不見這層)
3. 頻道 ID 白名單 + `--privacy` 必填

用法:
  python upload.py --list
  python upload.py --slug ego_depletion --privacy private
  python upload.py --limit 3 --privacy private
"""
import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube.force-ssl"]
# videos.insert 1600 / thumbnails.set 50 / videos.list 每次 1。
# 輪詢最多 40 次 + 回讀 1 次 + 每次執行 channels.list 1 次——舊版只算前兩項,
# 於是 --limit 6 算出 9,900 過關,但只要有一支處理得慢、輪詢吃滿就會超過,
# 而超額那一刻是在第 6 支的 insert 已經燒掉 1600 之後。
COST_INSERT, COST_THUMB, COST_POLL = 1600, 50, 41
DAILY_QUOTA = 10000


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def ledger():
    """🔴 fail-closed(2026-08-25 獨立驗證抓到)。

    舊版 `except Exception: return {}` 把兩件完全不同的事壓成同一個結果:
    檔案不存在(第一次跑,回空是對的)vs **檔案在但 JSON 壞了**(寫到一半
    斷電/磁碟滿)。第二種回空 = 把已經發過的整批再發一次。
    而 write_text 是非原子寫入,正好會製造第二種。
    """
    if not LEDGER.exists():
        return {}
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception as e:       # noqa: BLE001
        raise SystemExit(
            f"⛔ 帳本 {LEDGER} 存在但讀不了({e})。\n"
            f"   繼續跑會把已上傳的影片再傳一次。請先修好或改名再重試。")


# 稿子裡的「存在性斷言」——講這些話之前,數字必須撐得住
_CLAIMS_NONE = ("the effect is not there", "cannot be told apart from zero",
                "what you would expect from chance alone",
                "essentially, nothing")
_CLAIMS_REAL = ("the effect survived", "this one held up", "the effect is there",
                "so this one survives", "it is still there")


_NEG = ("cannot", "can not", "does not", "do not", "did not", "no longer",
        "never", "not ")


def _asserted(text, phrase):
    """稿子裡有這句話,而且**不是在否定它**。

    🔴 閘門一度只做子字串比對,於是 ego_depletion 的
    「cannot tell you the effect is there at all」被判成宣稱效應存在 ——
    那句話的意思正好相反。守門太笨會擋掉對的東西,而被誤擋的人下次就會
    習慣性加 --allow 繞過,那才是真正的損失。
    """
    i = text.find(phrase)
    while i >= 0:
        before = text[max(0, i - 42):i]
        if not any(n in before for n in _NEG):
            return True
        i = text.find(phrase, i + 1)
    return False


def semantic_gate(o):
    """發布前最後一道:稿子講的話,本集的數字撐得住嗎?

    🔴 為什麼要在**上傳端**再擋一次(2026-08-25 獨立驗證的建議):
    數字溯源的守門在 make_episode.audit() 和 publish_meta.check(),但那兩道
    **只掃數字 token**,對「數字對、話講反」結構上看不見。實測就抓到 ep005
    旁白說「效應不在那裡」而同一列 CSV 寫著 p < 0.001。

    產稿端已經改成看 p 值了,這一道是防「以後又有人改壞」——它是 fail-closed,
    看不懂就擋,不放行。回傳 None 表示通過,否則回傳擋下的理由。
    """
    d = ROOT / o["dir"]
    facts_p = d / "facts.json"
    if facts_p.exists():
        try:
            F = json.loads(facts_p.read_text(encoding="utf-8"))
            eo, er = float(F["orig"]["es"]), float(F["repl"]["es"])
            p_r = F.get("p_repl")
        except Exception as e:           # noqa: BLE001
            return f"讀不了 facts.json({str(e)[:40]})"
    else:
        # 🔴 名案線沒有 facts.json,舊版就直接 return None **全部放行**——
        #    而這道閘門正是為了「數字對、話講反」而建的,卻恰好不涵蓋
        #    編輯裁量最大、手工策展的那條線。改成讀 famous_episodes.json。
        fam = ROOT / "facts" / "famous_episodes.json"
        try:
            eps = json.loads(fam.read_text(encoding="utf-8"))["episodes"]
            E = next(e for e in eps if e["slug"] == o.get("slug"))
        except Exception as e:           # noqa: BLE001
            return f"名案事實庫讀不到 {o.get('slug')}({str(e)[:40]})"
        t = E["test"]
        ci = t.get("ci")
        text_all = " ".join(f.read_text(encoding="utf-8").lower()
                            for f in sorted(d.glob("narr_*.txt")))
        # 沒有信賴區間也沒有 p 值時,不准講存在性斷言(兩個方向都不准)
        if not ci and t.get("p") is None:
            for c in _CLAIMS_REAL + _CLAIMS_NONE:
                if _asserted(text_all, c):
                    return (f"名案沒有 CI 也沒有 p 值,卻講了存在性斷言"
                            f"「{c}」")
            return None
        if ci and ci[0] <= 0 <= ci[1]:
            for c in _CLAIMS_REAL:
                if _asserted(text_all, c):
                    return f"信賴區間跨零,卻講「{c}」"
        return None

    text = " ".join((d / f).read_text(encoding="utf-8").lower()
                    for f in sorted(x.name for x in d.glob("narr_*.txt")))
    sig = p_r is not None and float(p_r) < 0.05
    same_sign = (eo >= 0) == (er >= 0)
    shrink = abs(er) / max(abs(eo), 1e-9)

    if sig and any(_asserted(text, c) for c in _CLAIMS_NONE):
        return (f"稿子說效應不存在,但重測 p={p_r} < .05(測得到)"
                f" —— 這是把話講反")
    if any(_asserted(text, c) for c in _CLAIMS_REAL):
        if not same_sign:
            return f"稿子說效應站得住,但方向翻轉({eo:+.2f} → {er:+.2f})"
        if shrink <= 0.7 and not sig:
            return (f"稿子說效應站得住,但殘存比 {shrink:.2f} 且 "
                    f"p={p_r} 不顯著")
    return None


def key_of(o):
    return o.get("slug") or o["dir"]


def upload_one(yt, o, privacy, on_uploaded=lambda vid: None):
    from googleapiclient.http import MediaFileUpload
    video = ROOT / o["video"]
    print(f"\n[{key_of(o)}] {o['title']}")
    if not video.exists():
        print(f"    ⛔ 影片不存在:{video}")
        return None
    why = semantic_gate(o)
    if why:
        print(f"    ⛔ 語意閘門擋下:{why}")
        return None
    # 縮圖是這個頻道唯一的鉤子。沒有它 YouTube 會隨機抓一幀當封面,
    # 而舊批確實發生過影片產完之後 thumb.jpg 消失。上傳**前**就擋。
    thumb0 = ROOT / o["thumb"] if o.get("thumb") else None
    if not (thumb0 and thumb0.exists()) and privacy != "private":
        print("    ⛔ 缺縮圖,不上傳(縮圖是這個頻道的主要鉤子)")
        return None
    print(f"    {video.name} {video.stat().st_size / 1024 / 1024:.0f}MB  隱私 {privacy}")
    body = {
        "snippet": {"title": o["title"], "description": o["description"],
                    "tags": o["tags"], "categoryId": "27",   # Education
                    "defaultLanguage": "en"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "license": "youtube", "embeddable": True},
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, last = None, -1
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            p = int(status.progress() * 100)
            if p >= last + 25:
                print(f"    上傳 {p}%"); last = p
    vid = resp["id"]
    # 🔴 拿到 videoId 立刻寫帳本(2026-08-25)。
    #    舊版在 upload_one 全部跑完、回到外層迴圈才寫,而 insert **之後**還有
    #    輪詢、縮圖、回讀三個會拋例外的呼叫(配額 403、縮圖超過 2MB、
    #    items 空陣列 → IndexError)。任何一個炸掉 = 片子已經在頻道上、
    #    1600 單位已經燒掉,但帳本沒記 → 下次再傳一次 = 頻道上兩支一樣的片。
    on_uploaded(vid)
    print(f"    videoId={vid}  輪詢處理狀態…")
    processed = False
    for _ in range(40):                       # 這批片約 80 秒,10 分鐘綽綽有餘
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if not items:
            print(f"    ⛔ 影片查不到(通常=被拒)。videoId={vid}")
            return None
        st = items[0]["status"]
        if st.get("uploadStatus") == "rejected":
            print(f"    ⛔ 被拒:{st.get('rejectionReason')}")
            return None
        if st.get("uploadStatus") == "processed":
            print("    處理完成 ✓"); processed = True
            break
        time.sleep(15)
    if not processed:
        print("    ⚠️ 輪詢 10 分鐘仍未 processed,稍後自行到 Studio 確認")

    thumb = ROOT / o["thumb"] if o.get("thumb") else None
    if thumb and thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=str(thumb)).execute()
            print("    縮圖已設 ✓")
        except Exception as e:   # noqa: BLE001
            print(f"    ⚠️ 縮圖設定失敗({str(e)[:60]}),影片已上傳,稍後補設")
    else:
        print("    ⚠️ 找不到縮圖 —— 影片已上傳但沒有縮圖,請手動補")

    # 同一個檔案裡同一種呼叫,上面那處用 .get("items", []) 防了空陣列,
    # 這處直接 [0] —— 又是「一處防了一處沒防」。
    got_items = yt.videos().list(part="snippet,status", id=vid).execute().get("items", [])
    if got_items:
        st = got_items[0]["status"]
        ok_title = got_items[0]["snippet"]["title"] == o["title"]
        print(f"    回讀:隱私 {st['privacyStatus']}  "
              f"兒童 {st.get('selfDeclaredMadeForKids')}"
              f"  標題{'✓' if ok_title else ' ⚠️ 不符'}")
    else:
        print("    ⚠️ 回讀查無此片(已寫入帳本,請自行到 Studio 確認)")
    print(f"    https://youtu.be/{vid}")
    return vid


def flip(yt, vids, privacy):
    """把已上傳的片改隱私。

    🔴 `videos.update` 是**整包覆寫**:沒帶到的 status 欄位會被清空。
    主頻道踩過——只帶 privacyStatus 會把 selfDeclaredMadeForKids 洗掉,
    而那個欄位掉了等於留言與營利腰斬。所以一律先讀回現值、整包帶齊、
    再讀回驗證。
    """
    ok = 0
    for key, vid in vids:
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if not items:
            print(f"  {key:<24}⛔ 查無此片({vid})")
            continue
        st = items[0]["status"]
        if st["privacyStatus"] == privacy:
            print(f"  {key:<24}已經是 {privacy}")
            ok += 1
            continue
        yt.videos().update(part="status", body={
            "id": vid,
            "status": {"privacyStatus": privacy,
                       "selfDeclaredMadeForKids":
                           st.get("selfDeclaredMadeForKids", False),
                       "license": st.get("license", "youtube"),
                       "embeddable": st.get("embeddable", True),
                       "publicStatsViewable": st.get("publicStatsViewable", True)},
        }).execute()
        back = yt.videos().list(part="status", id=vid).execute()["items"][0]["status"]
        kids_ok = back.get("selfDeclaredMadeForKids") is False
        print(f"  {key:<24}{back['privacyStatus']}  兒童宣告 "
              f"{back.get('selfDeclaredMadeForKids')}"
              f"{' ✓' if back['privacyStatus'] == privacy and kids_ok else ' ⚠️'}")
        ok += back["privacyStatus"] == privacy and kids_ok
    print(f"\n{ok}/{len(vids)} 支已是 {privacy} 且兒童宣告完好")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"])
    ap.add_argument("--flip", choices=["private", "unlisted", "public"],
                    help="改已上傳影片的隱私(整包帶齊 status,不會洗掉兒童宣告)")
    # 🔴 2026-08-25:我把 `--limit 2 --privacy private` 當成乾跑拿來測閘門,
    #    結果它真的傳了兩支上去(已刪除、帳本已清)。**測閘門不該需要真的執行。**
    #    這個參數就是當時缺的那個東西:走完所有檢查、印出會發生什麼,然後停。
    ap.add_argument("--dry-run", action="store_true", dest="dry",
                    help="走完所有閘門並印出會上傳什麼,但不連網、不上傳")
    ap.add_argument("--allow-stale", action="store_true",
                    help="跳過陳舊檢查(只有你確定那些 mp4 是對的才用)")
    ap.add_argument("--list", action="store_true", dest="show")
    a = ap.parse_args()

    meta = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
    done = ledger()
    todo = [o for o in meta if key_of(o) not in done]
    if a.slug:
        todo = [o for o in todo if key_of(o) == a.slug or
                pathlib.Path(o["dir"]).name == a.slug]
    if a.show:
        for o in meta:
            mark = f"已上傳 {done[key_of(o)]}" if key_of(o) in done else "未上傳"
            exists = "✓" if (ROOT / o["video"]).exists() else "✗片子不在"
            print(f"  {key_of(o):<26}{o.get('tone','?'):<12}{exists:<10}{mark}")
        print(f"\n共 {len(meta)} 集,已上傳 {len(done)},待上傳 {len(meta) - len(done)}")
        return 0

    if a.flip:
        done_items = [(k, v) for k, v in done.items()]
        if a.slug:
            done_items = [(k, v) for k, v in done_items
                          if k == a.slug or pathlib.Path(k).name == a.slug]
        if not done_items:
            print("帳本裡沒有可改的影片"); return 1
        yt = svc()
        me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
        if me["id"] != EXPECT_CHANNEL:
            print(f"⛔ 頻道不符:{me['id']}"); return 1
        print(f"目標頻道:{me['snippet']['title']}")
        print(f"要把 {len(done_items)} 支改成 {a.flip}\n")
        return flip(yt, done_items, a.flip)

    if a.limit:
        todo = todo[:a.limit]
    if not todo:
        print("沒有待上傳的集數"); return 0

    est = len(todo) * (COST_INSERT + COST_THUMB + COST_POLL) + 1
    print(f"要上傳 {len(todo)} 集,估算配額 {est:,} / 每日 {DAILY_QUOTA:,}")
    if est > DAILY_QUOTA:
        print(f"⛔ 會超過當日配額(一天最多 "
              f"{DAILY_QUOTA // (COST_INSERT + COST_THUMB + COST_POLL)} 支)"
              f",請用 --limit")
        return 1
    if not a.privacy:
        print("⛔ --privacy 必填(public 不可逆,不設預設值)")
        return 1

    # 🔴 陳舊檢查在連網之前(2026-08-25 獨立驗證的建議)。
    #    這條線反覆出現「碼修好了、檔案也在,但 mp4 是舊碼的產物」——
    #    不報錯、不缺檔、清單看起來正常。而 facts.json 是渲染**之前**寫的、
    #    mp4 是**之後**才 mux 的,所以渲染死在中間時只比對 tone 會給假全綠。
    import preflight
    print("陳舊檢查:")
    stale = preflight.main_for(todo)
    if stale and not a.allow_stale:
        print("⛔ 有集數是舊碼或舊資料的產物,中止。"
              "重產後再試,或加 --allow-stale(不建議)。")
        return 1

    if a.dry:
        print("\n語意閘門:")
        blocked = 0
        for o in todo:
            why = semantic_gate(o)
            thumb = ROOT / o["thumb"] if o.get("thumb") else None
            miss_thumb = not (thumb and thumb.exists())
            key = key_of(o)
            if why:
                print(f"  ⛔ {key:<22}{why}"); blocked += 1
            elif miss_thumb and a.privacy != "private":
                print(f"  ⛔ {key:<22}缺縮圖"); blocked += 1
            else:
                print(f"  ✓  {key:<22}{o['title'][:58]}")
        print(f"\n--dry-run:未連網、未上傳。"
              f"實際會上傳 {len(todo) - blocked} 支,擋下 {blocked} 支。")
        return 0

    yt = svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    print(f"目標頻道:{me['snippet']['title']} ({me['snippet'].get('customUrl')})")
    if me["id"] != EXPECT_CHANNEL:          # 白名單比對 ID,不是 handle 字串
        print(f"⛔ 頻道不符:{me['id']} != {EXPECT_CHANNEL},中止。")
        return 1

    def record(key):
        def _w(vid):
            done[key] = vid
            tmp = LEDGER.with_suffix(".tmp")
            tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(LEDGER)          # 原子置換,不會留下半截 JSON
        return _w

    for o in todo:
        upload_one(yt, o, a.privacy, on_uploaded=record(key_of(o)))
    print(f"\n完成。帳本 {LEDGER.name} 共 {len(done)} 支。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
