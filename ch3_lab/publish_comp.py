#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_comp.py — 合輯的 metadata、縮圖與上傳。

## 為什麼合輯要單獨一支
它的價值主張跟單集不同:單集回答一個問題,合輯給的是「一次看完六個」。
所以標題、縮圖、說明都不一樣 ——
- **標題**帶數量(「6 psychology findings that…」),那是合輯型內容最有效的形態
- **說明要有時間戳章節**,那既是觀眾要的,也讓 YouTube 知道這支片有結構
- **縮圖**放數量與最大的那個落差,不是單一數字對比

## 誠信
章節標題與說明裡的每個數字都來自各集已通過審核的事實庫,不重算。
合輯自己**不下任何新結論** —— 它只是把六集依序播出來。

用法:
  python publish_comp.py --list
  python publish_comp.py --bucket fail --dry-run
  python publish_comp.py --bucket fail
"""
import argparse
import json
import math
import pathlib
import subprocess
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded_comp.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
sys.path.insert(0, str(ROOT))

TITLES = {
    "fail": "{n} psychology findings that did not survive a bigger test",
    "mixed": "{n} findings that are real — and far smaller than you were told",
    "held": "{n} psychology findings that actually held up",
}
LEAD = {
    "fail": "Every one of these was published, cited, and repeated. Then a "
            "much larger team ran the same study again.",
    "mixed": "Not debunked — corrected. This is the outcome that gets covered "
             "worst, because it has no villain.",
    "held": "You have heard a lot about the findings that broke. These did not.",
}
TAGS = ["replication crisis", "psychology", "effect size", "science",
        "research", "statistics", "meta-analysis", "replication study",
        "open science", "social psychology"]


def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def chapter_times(man):
    """章節時間戳。**唯一來源** —— `verify_comp` 也從這裡拿。

    🔴 這個函式存在是因為它一度有兩份實作:`publish_comp` 和 `verify_comp`
    各算各的,我只修了前者,於是驗收工具印出來的時間戳跟實際會寫進說明欄
    的**不一樣** —— 而驗收工具的整個用途就是「確認說明欄會寫對」。
    這條線的同型錯誤(同一件事兩個地方、只修一份)這是第八次。

    指**串場卡的開頭**不是本體的開頭:跳到第 3 章的人應該聽到
    「Number 3. Does scarcity-induced focus…」那段介紹,而不是直接掉進
    本體開場、沒有脈絡。而且**往上進位** —— 截斷會落在前一段的尾巴
    (抽幀實測第 252 秒看到的是前一集的紀錄畫面,不是卡片)。
    """
    out = []
    for c in man["clips"]:
        if c.get("kind") != "card":
            continue
        t = math.ceil(c["start"])
        out.append((t, c["row"]))
    return out


def build(bucket):
    """組出標題、章節時間戳、說明。

    ## 章節只能從 manifest.json 算
    第一版是重跑 `make_compilation.pick()` 去推「這支片裡有哪幾集」。那是
    錯的:`pick()` 只挑**當下 mp4 存在**的集數,所以只要剪接之後有任何
    一集被重產或刪掉(這批 14 集正好在重產),推出來的就是另一支片的
    章節 —— 而時間戳看起來完全正常,沒有任何東西會報錯。

    manifest 是剪接當下落的檔,記著實際進到成片裡的每一段與長度。這條線
    已經因為「同一件事兩份實作」出過七次錯,不再多一次。
    """
    import json as _json
    from make_episode import CARD_TEXT, build_facts
    import pandas as _pd
    d = ROOT / "compilations" / bucket
    mp4 = d / f"{bucket}_compilation.mp4"
    man_p = d / "manifest.json"
    if not mp4.exists():
        return None
    if not man_p.exists():
        print(f"  ⛔ {bucket}:沒有 manifest.json —— 這支是舊版剪接的產物,"
              f"章節無從查證。重跑 make_compilation.py --bucket {bucket}。")
        return None
    # 🔴 **合輯要有人看過才准發**。單集是同一個模板產了 20 幾支、每一支的
    #    每一幕都被看過;合輯是**新格式**(各段裁掉結語、串場卡帶問題、
    #    片尾放整份清單),而它有 10 分鐘以上。排程會在無人看管的時候把它
    #    送出去 —— 那等於發一支從來沒人看過的長片。
    #    這道閘門刻意**不能由產生器自己滿足**:`make_compilation` 不會寫
    #    這個檔,只有實際看過的人/agent 才會寫。
    ver_p = d / "verified.json"
    if not ver_p.exists():
        print(f"  ⛔ {bucket}:還沒有人看過(缺 verified.json)。"
              f"合輯是新格式且超過 10 分鐘,不在無人看管下送出。\n"
              f"     驗過之後寫入:{ver_p}")
        return None
    try:
        v = json.loads(ver_p.read_text(encoding="utf-8"))
        if not isinstance(v, dict):
            raise ValueError(f"內容是 {type(v).__name__} 不是物件")
    except Exception as e:                                   # noqa: BLE001
        print(f"  ⛔ {bucket}:verified.json 讀不了({str(e)[:60]})")
        return None
    # 🔴 **缺欄位要擋,不能跳過。** 第一版寫成
    #    `if v.get("mp4_md5") is not None and ...`,於是手寫一份
    #    `{"by": "carson"}`(人最自然會寫的東西)就**永久通行、重剪幾次
    #    都不失效**。「欄位不存在 = 通過」是今天第四次遇到的同一個 species。
    #
    #    版本識別用 **mp4 的雜湊**,不是片長。最可能發生的重剪是「**同樣
    #    那六集,重渲之後再剪一次**」—— 結構一樣、長度只差零點幾秒,拿
    #    秒數當識別碼在**最該擋的那個情境**下正好分辨不出來,而那一版的
    #    每一集旁白和畫面都變了。
    #    雜湊 mp4 也天生對「只改說明文案」免疫:說明欄不在 mp4 裡,
    #    它是發布當下從事實庫現組的。
    import hashlib
    got = hashlib.md5(mp4.read_bytes()).hexdigest()
    if "mp4_md5" not in v:
        print(f"  ⛔ {bucket}:verified.json 缺 `mp4_md5`,不知道你驗的是"
              f"哪一版。用 `verify_comp.py --bucket {bucket} --ok` 產生,"
              f"不要手寫。")
        return None
    if v["mp4_md5"] != got:
        print(f"  ⛔ {bucket}:verified.json 驗的是**另一個檔案**"
              f"(它記 {v['mp4_md5'][:12]}…,現在的是 {got[:12]}…)。"
              f"重剪過就要重看。")
        return None
    man = _json.loads(man_p.read_text(encoding="utf-8"))
    if abs(man["total"] - dur(mp4)) > 1.5:
        print(f"  ⛔ {bucket}:manifest 記 {man['total']:.1f}s,實際成片 "
              f"{dur(mp4):.1f}s —— 對不上,表示 mp4 是之後另外重編的。")
        return None

    q = _pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
    n = man["n"]
    title = TITLES[bucket].format(n=n)
    chapters, lines, items, k = ["0:00 Intro"], [], [], 0
    for t, row in chapter_times(man):       # 唯一來源,verify_comp 共用
        k += 1
        m, s = divmod(t, 60)
        F = build_facts(q.iloc[row])
        items.append(F)
        claim = F["claim"].rstrip(".")
        # 來源的主張有些是小寫開頭(「individuals who reflected…」),
        # 章節標題那樣讀起來像半句話。只動第一個字母,不改內容。
        ch = claim[:1].upper() + claim[1:]
        chapters.append(f"{m}:{s:02d} {ch[:70]}")
        lines.append(
            f"{k}. {claim}\n"
            f"   {F['orig']['n']:,} people → {F['orig']['es']:+.2f}   |   "
            f"{F['repl']['n']:,} people → {F['repl']['es']:+.2f}   "
            f"({CARD_TEXT[F['tone']]})\n"
            f"   doi:{F['orig']['doi']}\n"
            f"   doi:{F['repl']['doi']}")

    desc = (LEAD[bucket] + "\n\n"
            + "\n".join(chapters) + "\n\n"
            + "─────────\n\n"
            + "\n\n".join(lines) + "\n\n"
            + "Every number here comes from the published replication record. "
              "Nothing is estimated or rounded for effect — the narration is "
              "generated from the same data fields you see on screen. Not "
              "every finding fails: replications that held up get their own "
              "videos too.\n\n"
              "Replication data: FORRT Replication Database (FReD), "
              "osf.io/2tbvd")
    return {"bucket": bucket, "video": str(mp4.relative_to(ROOT)),
            "title": title, "description": desc, "tags": TAGS,
            "n": n, "minutes": dur(mp4) / 60, "items": items}


def thumb(rec):
    """縮圖:數量 + 最大的那個落差。合輯賣的是「一次看完六個」。

    版面語言跟單集縮圖同一套(見 make_thumbs 的說明):頂端橫幅一個判決
    詞、下面用長條給形狀。差別只在橫幅寫的是「6 FINDINGS」—— 那才是
    合輯的賣點,單集賣的是單一落差。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    import imageio.v2 as iio
    BG, FG, DIM = "#0E1116", "#F2F4F7", "#79808B"
    col = {"fail": "#FF6B4A", "mixed": "#7FA8FF", "held": "#3DD68C"}[rec["bucket"]]
    F = rec["items"][0]
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(plt.Rectangle((0, 0.715), 1, 0.285, color="#151A21", zorder=1))
    ax.add_patch(plt.Rectangle((0, 0.715), 1, 0.008, color=col, zorder=2))
    ax.text(0.5, 0.895, f"{rec['n']} FINDINGS", ha="center", va="center",
            fontsize=104, color=col, weight="bold", zorder=4)
    word = {"fail": "THAT DIDN'T SURVIVE", "mixed": "SMALLER THAN YOU HEARD",
            "held": "THAT HELD UP"}[rec["bucket"]]
    ax.text(0.5, 0.785, word, ha="center", va="center", fontsize=52, color=FG,
            weight="bold", zorder=4)
    # 🔴 符號不能被 abs() 吃掉,理由與版面數字同 make_thumbs.py 的說明:
    #    翻轉的那一集若把兩根都畫成朝上,圖等於在說「縮小」而不是「翻轉」。
    base, cap = 0.46, 0.155
    top = max(abs(F["orig"]["es"]), abs(F["repl"]["es"]), 0.1)
    for x, v, c, lc, n in ((0.30, F["orig"]["es"], "#49515D", "#7A828E",
                            F["orig"]["n"]),
                           (0.70, F["repl"]["es"], col, col, F["repl"]["n"])):
        h = max(cap * abs(v) / top, 0.014)
        y = base if v >= 0 else base - h
        ax.add_patch(plt.Rectangle((x - 0.125, y), 0.25, h, color=c, zorder=3))
        ly = (base + h + 0.075) if v >= 0 else (base - h - 0.075)
        ax.text(x, ly, f"{v:+.2f}".replace("+", ""), ha="center", va="center",
                fontsize=72, color=lc, weight="bold", zorder=4)
        ax.text(x, 0.07, f"{n:,} people", ha="center", va="center",
                fontsize=46, color=FG, weight="bold", zorder=4)
    ax.plot([0.10, 0.90], [base, base], color="#3A424E", lw=3, zorder=2)
    ax.text(0.985, 0.752, "THEY RAN IT AGAIN", ha="right", va="bottom",
            fontsize=22, color="#39414D", weight="bold", zorder=9)
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    p = ROOT / "compilations" / rec["bucket"] / "thumb.jpg"
    iio.imwrite(p, buf, quality=92)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", choices=["fail", "mixed", "held"])
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    ap.add_argument("--list", action="store_true", dest="show")
    # 一天最多一支 —— 合輯每支吃 1,691 配額,而排程還要留額度給
    # Shorts(見 scripts/ch3_publish.py 的配比說明)。
    ap.add_argument("--limit", type=int, default=1)
    a = ap.parse_args()

    led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    buckets = [a.bucket] if a.bucket else ["fail", "mixed", "held"]
    recs = [r for r in (build(b) for b in buckets) if r]
    if a.show:
        for r in recs:
            print(f"  {r['bucket']:<8}{r['minutes']:>5.1f} 分  {r['n']} 集  "
                  f"{led.get(r['bucket'], '未上傳'):<14}{r['title'][:52]}")
        return 0

    todo = [r for r in recs if r["bucket"] not in led][:a.limit]
    if not todo:
        # ⚠️ 「沒得發」有兩種原因,講清楚是哪一種。舊版一律印「都發過了」,
        #    但 build() 被閘門擋下時 recs 是空的 —— 那會把「三支全被擋」
        #    報成「三支全發完」,而那正是讓靜默失敗活下來的那種話。
        blocked = len(buckets) - len(recs)
        if blocked:
            print(f"沒有可發的合輯:{blocked} 支被閘門擋下(理由見上),"
                  f"{len(recs)} 支已發過。")
        else:
            print(f"合輯都發過了({len(led)} 支)")
        return 0
    for r in todo:
        p = thumb(r)
        print(f"[{r['bucket']}] {r['title']}")
        print(f"  {r['minutes']:.1f} 分,{r['n']} 集,縮圖 {p.name}")
        print(f"  章節:{r['n'] + 1} 個(含 Intro)")
    if a.dry:
        print("\n--dry-run:未連網、未上傳。")
        print("\n說明前 12 行:")
        for ln in todo[0]["description"].split("\n")[:12]:
            print("   " + ln[:78])
        return 0

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build as gbuild
    from googleapiclient.http import MediaFileUpload
    tok = CH2 / "token_manage.json"
    cr = Credentials.from_authorized_user_file(
        str(tok), ["https://www.googleapis.com/auth/youtube.upload",
                   "https://www.googleapis.com/auth/youtube.force-ssl",
                   "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    yt = gbuild("youtube", "v3", credentials=cr, cache_discovery=False)
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1

    for r in todo:
        print(f"\n[{r['bucket']}] 上傳中…")
        req = yt.videos().insert(part="snippet,status", body={
            "snippet": {"title": r["title"], "description": r["description"],
                        "tags": r["tags"], "categoryId": "27",
                        "defaultLanguage": "en"},
            "status": {"privacyStatus": "public",
                       "selfDeclaredMadeForKids": False,
                       "license": "youtube", "embeddable": True},
        }, media_body=MediaFileUpload(str(ROOT / r["video"]),
                                      chunksize=8 * 1024 * 1024,
                                      resumable=True, mimetype="video/mp4"))
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        vid = resp["id"]
        # 配額在 insert 回來的當下就花掉了,所以這裡就記(理由同帳本)。
        try:
            import quota as _quota
            _quota.spend(_quota.COMP, f"comp/{r['bucket']}")
        except Exception as e:                               # noqa: BLE001
            print(f"  (配額帳沒記到:{str(e)[:50]})")
        led[r["bucket"]] = vid
        tmp = LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(led, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(LEDGER)
        print(f"  videoId={vid}  https://youtu.be/{vid}")
        for _ in range(40):
            got = yt.videos().list(part="status", id=vid).execute().get("items", [])
            if got and got[0]["status"].get("uploadStatus") == "processed":
                print("  處理完成 ✓")
                break
            time.sleep(15)
        tp = ROOT / "compilations" / r["bucket"] / "thumb.jpg"
        if tp.exists():
            yt.thumbnails().set(videoId=vid, media_body=str(tp)).execute()
            print("  縮圖已設 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
