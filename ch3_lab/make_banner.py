#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_banner.py — 頻道橫幅。

## 為什麼要換
現在掛的是前身「One Quiet Hour」的晨霧湖景。頻道說明、關鍵字、影片、
縮圖全都已經是重複危機的內容,只有名稱(鎖到 09-03)和這張圖還停在
氛圍頻道。從 Short 點進來的人第一眼看到的就是這張 —— 那是整條漏斗上
最刺眼的不一致,而且它是現在就改得掉的少數幾件事之一。

## 版面
YouTube 橫幅在不同裝置裁切幅度差很多:電視看到全部 2560×1440,手機
只看得到正中央 **1546×423**。所以**所有字必須待在那塊安全區內**,
外圈只能放背景。這裡把安全區畫成常數 SAFE,不是憑感覺抓位置。

視覺語言跟縮圖同一套(見 make_thumbs):深底、判決字級的粗體、長條。

用法:
  python make_banner.py              # 產圖到 _banner_new.jpg
  python make_banner.py --apply      # 產圖並上傳(會改動正式頻道)
"""
import argparse
import pathlib
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
W, H = 2560, 1440
BG, FG, DIM = "#0E1116", "#F2F4F7", "#79808B"
ACCENT = "#FF6B4A"
#: 手機上唯一保證看得到的區域(1546×423,置中)。字只能放這裡面。
SAFE = ((W - 1546) / 2 / W, (W + 1546) / 2 / W,
        (H - 423) / 2 / H, (H + 423) / 2 / H)


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    return plt


def draw(plt, out_path, guides=False):
    x0, x1, y0, y1 = SAFE
    cx, cy = 0.5, (y0 + y1) / 2
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # 背景:安全區外的長條陣列。手機看不到,但電視與桌機會看到,
    # 而它用的正是縮圖那套「長條=效果量」的語彙,不是隨便的裝飾。
    rng = np.random.default_rng(7)
    for i in range(34):
        bx = 0.012 + i * 0.0295
        if x0 - 0.03 < bx < x1 + 0.01:
            continue
        h = 0.06 + rng.random() * 0.30
        ax.add_patch(plt.Rectangle((bx, 0.5 - h / 2), 0.017, h,
                                   color="#161C24", zorder=1))

    # 🔴 字級是由安全區寬度反推的,不是憑感覺挑的。第一版用 150/62/44,
    #    畫上安全區框線一看就穿幫:標題兩端在手機上會被切掉。安全區只有
    #    1,546px = 全寬的 60.4%,所有字都得塞進那 60.4% 裡。
    ax.text(cx, cy + 0.075, "THEY RAN IT AGAIN", ha="center", va="center",
            fontsize=104, color=FG, weight="bold", zorder=4)
    ax.plot([x0 + 0.10, x1 - 0.10], [cy + 0.005, cy + 0.005],
            color=ACCENT, lw=5, zorder=4)
    ax.text(cx, cy - 0.045, "Famous studies, tested again — with the numbers",
            ha="center", va="center", fontsize=46, color=DIM, zorder=4)
    ax.text(cx, cy - 0.105,
            "every number from the published replication record",
            ha="center", va="center", fontsize=34, color="#5C6470", zorder=4)

    if guides:                      # 只在檢查時畫,不進正式圖
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                                   edgecolor="#FF00AA", lw=3, zorder=9))
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    import imageio.v2 as iio
    iio.imwrite(out_path, buf, quality=94)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="上傳到正式頻道(會改動對外可見的頻道外觀)")
    ap.add_argument("--guides", action="store_true",
                    help="畫出手機安全區框線,只供檢查")
    a = ap.parse_args()
    plt = _plt()
    out = ROOT / "_thumb_ab" / "_banner_new.jpg"
    out.parent.mkdir(exist_ok=True)
    draw(plt, out, guides=a.guides)
    print(f"產出 {out}  {W}×{H}  {out.stat().st_size / 1024:.0f} KB")
    if not a.apply:
        print("(沒有 --apply,未上傳)")
        return 0

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    tok = CH2 / "token_manage.json"          # 寫入一律用 manage token
    cr = Credentials.from_authorized_user_file(
        str(tok), ["https://www.googleapis.com/auth/youtube.upload",
                   "https://www.googleapis.com/auth/youtube.force-ssl",
                   "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
    ch = yt.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
    if ch["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{ch['id']}")
        return 1
    old = ch["brandingSettings"].get("image", {}).get("bannerExternalUrl")
    print(f"舊 banner: {old}")

    res = yt.channelBanners().insert(
        media_body=MediaFileUpload(str(out), mimetype="image/jpeg",
                                   resumable=False)).execute()
    url = res["url"]
    # 🔴 channels.update 是**整段覆蓋**:brandingSettings 沒帶到的欄位會
    #    被清空。所以要把讀回來的整包帶上,只換 image.bannerExternalUrl。
    b = ch["brandingSettings"]
    b.setdefault("image", {})["bannerExternalUrl"] = url
    yt.channels().update(part="brandingSettings",
                         body={"id": EXPECT_CHANNEL,
                               "brandingSettings": b}).execute()
    back = yt.channels().list(part="brandingSettings",
                              mine=True).execute()["items"][0]
    bs = back.get("brandingSettings", {})
    now = bs.get("image", {}).get("bannerExternalUrl")
    # 🔴 `["channel"]` 直接索引:真的被清空時這行會 KeyError,而那正是
    #    我要印出來的那個訊息 —— 出事時反而看不到。改成 .get()。
    bb = bs.get("channel", {})
    swapped = now != old
    kept_desc = bool(bb.get("description"))
    kept_kw = bool(bb.get("keywords"))
    print(f"新 banner: {now}")
    print(f"回讀:換了沒={swapped} 說明還在={kept_desc} 關鍵字還在={kept_kw}")
    # 🔴 回讀要**擋門**,不能只是印出來。原本的回傳值只看 banner 有沒有換,
    #    所以「banner 換成功、但說明與關鍵字被清空」會印 False 之後照樣
    #    return 0 —— 有報告、沒有把關,等於白驗。
    if not (swapped and kept_desc and kept_kw):
        print("⛔ 回讀不通過。說明/關鍵字原文躺在 ch3_lab/rebrand.py 的常數裡,"
              "救得回來 —— 先確認頻道頁再做下一步。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
