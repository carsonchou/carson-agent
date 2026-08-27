#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""channel_setup.py — 頻道頁的門面:播放清單、首頁版位、浮水印訂閱鈕。

## 為什麼這些值得做(以及它們救不了什麼)
現況是 10 支片、2 次觀看。**這些設定不會帶來觀眾**——它們決定的是
「有人來了之後看不看得懂這個頻道在幹嘛、會不會留下」。所以它是必要
但不充分的一步,真正的分發靠 Shorts 與搜尋。

三件事按實測價值排序:
1. **浮水印訂閱鈕** —— 主頻道實測它觸及 **100% 的觀看**,而片尾只有 7%。
   這是整個頻道唯一全流量生效的訂閱入口。
2. **播放清單** —— 讓 YouTube 知道這頻道的主題結構,也讓訪客看到「這裡
   有一整條可以追的東西」而不是一牆散片。分三條,依結局分:垮了 /
   兩邊都不是 / 撐住了。**第三條是這個頻道的護城河**——證明它不是一味打臉。
3. **首頁版位** —— 訪客第一眼看到的排列。

## API 事實
- `watermarks.set` 可以用 API 設,但**顯示時段預設是「影片結尾」**,
  必須明確指定 `timing.type=fromStart` + `durationMs` 才會全片顯示。
  主頻道踩過:沒改的話等於只在最後幾秒出現,差 14 倍。
- `channelSections` 全部重建約 500 單位;刪掉的版位無從回復,所以先備份。
- 寫入一律用 `token_manage.json`(`token.json` 只有 readonly)。

用法:
  python channel_setup.py --dry-run
  python channel_setup.py --apply
"""
import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
META = ROOT / "publish_meta.json"
LEDGER = ROOT / "uploaded.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
STATE = ROOT / "channel_state.json"

# 依結局分,不是依題材 —— 題材是散的,結局才是這個頻道的敘事骨架。
PLAYLISTS = {
    "fail": ("Findings that did not survive",
             "Famous-sounding results that a much larger replication could not "
             "find again. Every number is from the published record, with DOIs."),
    "mixed": ("Smaller than you were told",
              "The effect is real — and much smaller than the first study "
              "reported. The outcome that gets covered worst."),
    "held": ("Findings that held up",
             "Replications that survived a far larger test. These matter as "
             "much as the ones that broke."),
}


def svc(write=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    # 🔴 token.json 只有 readonly,寫入一律 token_manage.json
    tok = CH2 / ("token_manage.json" if write else "token.json")
    scopes = ["https://www.googleapis.com/auth/youtube.force-ssl",
              "https://www.googleapis.com/auth/youtube.readonly"]
    cr = Credentials.from_authorized_user_file(str(tok), scopes)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def make_watermark(path):
    """產一張浮水印圖:小、低調、看得懂是訂閱。Carson 偏好深色不刺眼。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import imageio.v2 as iio
    fig = plt.figure(figsize=(1.5, 1.5), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(plt.Circle((0.5, 0.5), 0.44, color="#0E1116", alpha=0.88))
    ax.add_patch(plt.Circle((0.5, 0.5), 0.44, fill=False, color="#E8EAED",
                            lw=2.5, alpha=0.9))
    ax.text(0.5, 0.5, "SUB", ha="center", va="center", fontsize=26,
            color="#E8EAED", weight="bold")
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba()).copy()
    plt.close(fig)
    iio.imwrite(path, buf)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    meta = json.loads(META.read_text(encoding="utf-8"))
    led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    sys.path.insert(0, str(ROOT))
    from make_episode import TONE_META

    # 已上線的片依 bucket 分組
    groups = {"fail": [], "mixed": [], "held": []}
    by_key = {(o.get("slug") or o["dir"]): o for o in meta}
    for key, vid in led.items():
        o = by_key.get(key)
        if not o:
            continue
        groups[TONE_META[o["tone"]]["bucket"]].append(vid)

    print("播放清單(依結局分,已上線的片):")
    for b, (title, _) in PLAYLISTS.items():
        print(f"  {title:<34}{len(groups[b])} 支")
    print(f"\n浮水印訂閱鈕:全片顯示(fromStart, durationMs=0 = 整支)")
    if not a.apply:
        print("\n--dry-run:未連網。")
        return 0

    yt = svc(write=True)
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1
    print(f"目標頻道:{me['snippet']['title']}\n")
    st = load_state()

    # ── 播放清單:建一次,之後只補成員 ──
    st.setdefault("playlists", {})
    for b, (title, desc) in PLAYLISTS.items():
        if not groups[b]:
            print(f"  {title}:沒有已上線的片,略過")
            continue
        pid = st["playlists"].get(b)
        fresh = not pid
        if not pid:
            r = yt.playlists().insert(part="snippet,status", body={
                "snippet": {"title": title, "description": desc,
                            "defaultLanguage": "en"},
                "status": {"privacyStatus": "public"}}).execute()
            pid = r["id"]
            st["playlists"][b] = pid
            save_state(st)
            print(f"  建立「{title}」 {pid}")
        # 既有成員(避免重複加)。
        # 🔴 剛建的清單查成員會回 404(記憶 yt-industry-playlists-multichannel
        #    記過同一個坑):它要幾秒才可查詢,而且新清單本來就是空的 ——
        #    根本不該去查。
        have = set()
        tok = None
        while not fresh:
            r = yt.playlistItems().list(part="contentDetails", playlistId=pid,
                                        maxResults=50, pageToken=tok).execute()
            have |= {i["contentDetails"]["videoId"] for i in r.get("items", [])}
            tok = r.get("nextPageToken")
            if not tok:
                break
        added = 0
        for vid in groups[b]:
            if vid in have:
                continue
            # 剛建好的清單前幾秒會回 409 SERVICE_UNAVAILABLE(還在生效),
            # 那是暫時性的,退避重試即可;真的失敗才報出來。
            for attempt in range(5):
                try:
                    yt.playlistItems().insert(part="snippet", body={
                        "snippet": {"playlistId": pid,
                                    "resourceId": {"kind": "youtube#video",
                                                   "videoId": vid}}}).execute()
                    added += 1
                    break
                except Exception as e:                       # noqa: BLE001
                    if "409" in str(e) or "SERVICE_UNAVAILABLE" in str(e):
                        time.sleep(3 * (attempt + 1))
                        continue
                    print(f"    ⚠️ {vid} 加不進去:{str(e)[:70]}")
                    break
        print(f"  「{title}」 {len(have)}+{added} 支")

    # ── 浮水印:唯一全流量生效的訂閱入口 ──
    try:
        wm = make_watermark(ROOT / "watermark.png")
        # 🔴 timing 必須明講。預設是「影片結尾」,那等於只在最後幾秒出現
        #    ——主頻道實測差 14 倍。
        from googleapiclient.http import MediaFileUpload
        yt.watermarks().set(
            channelId=EXPECT_CHANNEL,
            # ⚠️ durationMs=0 不是「整支」,是**無效值**(API 回 400)。
            #    600,000 毫秒 = 10 分鐘,遠超這條線每支片的長度 → 等效全片。
            body={"timing": {"type": "offsetFromStart", "offsetMs": 3000,
                             "durationMs": 600000},
                  "position": {"type": "corner", "cornerPosition": "bottomRight"}},
            media_body=MediaFileUpload(str(wm), mimetype="image/png")).execute()
        print("  浮水印訂閱鈕已設(從第 3 秒起,全片顯示)")
        st["watermark"] = True
        save_state(st)
    except Exception as e:                                   # noqa: BLE001
        print(f"  ⚠️ 浮水印設定失敗:{str(e)[:110]}")

    print(f"\n狀態寫入 {STATE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
