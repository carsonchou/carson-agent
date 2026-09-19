#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thumb_ab.py — 縮圖 A/B:把「在搜尋結果尺寸下讀不到的元素」拿掉,空間讓給讀得到的。

## 為什麼
Carson 從 Studio 讀到**曝光點閱率 2% 以下**(多數頻道 2~10%)——破口在點擊。
標題已經在跑 A/B(`title_ab.py`,另外 40 支)。點擊決策的另一半是縮圖。

把已發布縮圖縮到**搜尋結果的實際尺寸(246×138)**看,量到的不是美感問題是物理問題:
  · 左上「量化阿森 | Carson Quant」pill 是 32px 字級 → 顯示時約 6px,**讀不到**
  · 底部說明條同理
  · 吉祥物佔右側,而且把主文可用寬度從 1040 壓到 **760(少 27%)**
唯一在那個尺寸讀得到的是**大數字**,而它被壓在剩下的空間裡。

所以 B 版不是重新設計,是**把讀不到的拿掉、把空間還給讀得到的**:
拿掉 pill 與吉祥物 → 主文寬度 760 → 1040(+37%)→ 字級跟著變大。

## 誠實邊界
- 這仍是**一個假設**。我在這個 session 已經三次憑感覺改內容然後被數據推翻,
  所以照樣做對照組,不直接全套上去。
- `thumbnails.set` 只換圖,**保留 videoId 與搜尋排名**(同 memory yt-video-lifespan-4days),
  所以可以直接在存量上做,而且失敗可還原(舊圖先備份)。
- n=20/20 只看得出大的差異;±15% 內要說「看不出差異」。
- ⚠️ 2026-08-24 起 YouTube 改成「播放即計為一次觀看」,跨那天的觀看數不可直接比。
  本實驗有對照組,差異中的差異可抵銷,但單看某一組的絕對變化沒有意義。

用法:
  python scripts/thumb_ab.py --preview    # 產 A/B 對照圖(246px 實際尺寸),先看再說
  python scripts/thumb_ab.py              # dry-run:列出會換哪些
  python scripts/thumb_ab.py --apply
  python scripts/thumb_ab.py --report
  python scripts/thumb_ab.py --restore
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
STATE = STUDIO / "thumb_ab.json"
BACKUP = ROOT / "assets" / "thumbnails" / "_pre_ab"
N_PER_ARM = 20
SEED = 20260828
SEARCH_W, SEARCH_H = 246, 138          # YouTube 搜尋結果縮圖的實際顯示尺寸


def _title_of(slug):
    p = ROOT / "output" / f"{slug}.md"
    if not p.exists():
        return None
    try:
        first = p.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except Exception:  # noqa: BLE001
        return None
    return re.sub(r"^#\s*🎬?\s*", "", first).strip() or None


def make_variant_b(slug, title):
    """產 B 版縮圖:抑制 pill 與吉祥物,主文吃滿寬度。回 PIL Image。

    做法是**暫時 monkeypatch** make_thumbnails 的兩個繪製點,而不是複製一份排版邏輯
    —— 本專案有「同一件事兩份實作、產線走沒閘門那份」的事故,縮圖排版尤其不能再分岔。"""
    import make_thumbnails as mt
    orig_mascot = mt._paste_mascot
    orig_text = mt.ImageDraw.ImageDraw.text

    def _no_mascot(*a, **k):
        return None                     # 不貼吉祥物 → show_mascot 分支回 None → max_w 用 1040

    def _skip_pill(self, xy, text, *a, **k):
        # 頻道標:246px 下約 6px,讀不到;整個略過(連底板都不畫時版面會空,只略過文字最保險)
        if text == mt.CHANNEL:
            return None
        return orig_text(self, xy, text, *a, **k)

    mt._paste_mascot = _no_mascot
    mt.ImageDraw.ImageDraw.text = _skip_pill
    try:
        cfg = mt.derive_cfg(slug, title)
        if not cfg.get("debunk") and not cfg.get("card"):
            rc = mt._real_card(slug, title)
            if rc:
                cfg["card"] = rc
        cfg.pop("card", None)           # 回測卡也佔右側,B 版一併讓出
        out = mt.make_one(cfg)
        from PIL import Image
        return Image.open(out).convert("RGB")
    finally:
        mt._paste_mascot = orig_mascot
        mt.ImageDraw.ImageDraw.text = orig_text


def _preview(slugs):
    """把 A(現行)/B(變體)並排縮到搜尋結果實際尺寸,存成一張對照圖。"""
    from PIL import Image, ImageDraw
    import make_thumbnails as mt
    rows = []
    for s in slugs:
        t = _title_of(s)
        if not t:
            continue
        a_path = ROOT / "assets" / "thumbnails" / f"{s}.jpg"
        if not a_path.exists():
            continue
        a = Image.open(a_path).convert("RGB").resize((SEARCH_W, SEARCH_H), Image.LANCZOS)
        try:
            b = make_variant_b(s, t).resize((SEARCH_W, SEARCH_H), Image.LANCZOS)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {s[:30]} B 版失敗:{str(e)[:70]}")
            continue
        rows.append((a, b))
        if len(rows) >= 5:
            break
    if not rows:
        print("沒有可預覽的。")
        return None
    W = SEARCH_W * 2 + 30
    H = len(rows) * (SEARCH_H + 12) + 30
    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    # 用英文標籤:PIL 預設點陣字型是 latin-1,畫中文會 UnicodeEncodeError。
    # 這裡只是預覽用的說明條,不值得為它去載中文字型。
    d.text((10, 6), "A = current            B = stripped (no pill / no mascot)",
           fill=(200, 200, 210))
    for i, (a, b) in enumerate(rows):
        y = 24 + i * (SEARCH_H + 12)
        sheet.paste(a, (10, y))
        sheet.paste(b, (SEARCH_W + 20, y))
    out = ROOT / "STUDIO" / "thumb_ab_preview.png"
    sheet.save(out)
    print(f"對照圖已存:{out}")
    return out


def _candidates():
    """可用樣本:已發布體檢長片,**排除標題實驗佔用的 40 支**(免得兩個實驗互相污染)。"""
    import yt_analytics as ya
    from datetime import date, timedelta
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    v2s = {v: k for k, v in led.items() if isinstance(v, str) and len(v) == 11}
    used = set()
    tp = STUDIO / "title_ab.json"
    if tp.exists():
        ts = json.loads(tp.read_text(encoding="utf-8"))
        used = {r["vid"] for r in ts.get("treat", [])} | {r["vid"] for r in ts.get("ctrl", [])}
    s = ya._service()
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=27)
    rows = s.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end),
        metrics="views", dimensions="video", sort="-views",
        maxResults=200).execute().get("rows", [])
    out = []
    for vid, views in rows:
        slug = v2s.get(vid)
        if not slug or vid in used or not slug.startswith("L_") or "體檢" not in slug:
            continue
        if not (ROOT / "assets" / "thumbnails" / f"{slug}.jpg").exists():
            continue
        out.append({"slug": slug, "vid": vid, "views": views})
    return out, (start.isoformat(), end.isoformat())


def _assign(c):
    """依觀看數配對分派(同 title_ab:個股搜尋量差異是這裡最強的混淆變數)。"""
    import random
    rnd = random.Random(SEED)
    ranked = sorted(c, key=lambda x: -x["views"])[:N_PER_ARM * 2]
    t, ct = [], []
    for i in range(0, len(ranked) - 1, 2):
        a, b = ranked[i], ranked[i + 1]
        if rnd.random() < 0.5:
            a, b = b, a
        t.append(a)
        ct.append(b)
    return t, ct


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    if args.preview:
        c, _ = _candidates()
        t, _ct = _assign(c)
        return 0 if _preview([r["slug"] for r in t]) else 1

    if args.report or args.restore:
        if not STATE.exists():
            print("還沒有實驗紀錄。")
            return 0
        st = json.loads(STATE.read_text(encoding="utf-8"))

    if args.restore:
        import daily_publish as dp
        from googleapiclient.http import MediaFileUpload
        yt = dp.get_service()
        n = 0
        for r in st["treat"]:
            bak = BACKUP / f"{r['slug']}.jpg"
            if not bak.exists():
                print(f"[skip] {r['slug'][:30]} 無備份")
                continue
            try:
                yt.thumbnails().set(videoId=r["vid"],
                                    media_body=MediaFileUpload(str(bak), mimetype="image/jpeg")).execute()
                n += 1
                print(f"↩ 還原 {r['vid']}")
            except Exception as e:  # noqa: BLE001
                print(f"[err] {r['vid']} {str(e)[:70]}")
                if "quota" in str(e).lower():
                    break
        print(f"\n已還原 {n} 支。")
        return 0

    if args.report:
        import statistics as stx
        import yt_analytics as ya
        from datetime import date, timedelta
        s = ya._service()
        end = date.today() - timedelta(days=2)
        start = end - timedelta(days=27)
        rows = s.reports().query(
            ids="channel==MINE", startDate=str(start), endDate=str(end),
            metrics="views", dimensions="video", sort="-views",
            maxResults=200).execute().get("rows", [])
        now = {r[0]: r[1] for r in rows}
        print(f"換圖於 {st['applied_at']};現在期間 {start} ~ {end}\n")
        res = {}
        for arm, lbl in (("treat", "實驗(換圖)"), ("ctrl", "對照(不動)")):
            g = [(r, now.get(r["vid"], 0)) for r in st[arm]]
            b = stx.median(r["views"] for r, _ in g)
            a = stx.median(n for _, n in g)
            res[arm] = (b, a)
            print(f"{lbl:<10}{len(g):>4} 支  基準中位 {b:>6.0f} → 現在中位 {a:>6.0f}"
                  f"  {(a-b)/max(b,1)*100:>+6.0f}%")
        tb, ta = res["treat"]
        cb, ca = res["ctrl"]
        print(f"\n差異中的差異(扣掉大盤趨勢):"
              f"{((ta/max(tb,1))/max(ca/max(cb,1),0.01)-1)*100:+.0f}%")
        print("⚠️ n=20/20 只看得出大的差異;±15% 內是「看不出差異」。")
        print("⚠️ 2026-08-24 起 YouTube 改成播放即計觀看 —— 單組的絕對變化不可信,只能看兩組的差。")
        return 0

    c, (b0, b1) = _candidates()
    print(f"可用樣本(已排除標題實驗的 40 支):{len(c)} 支;基準期間 {b0} ~ {b1}")
    t, ct = _assign(c)
    import statistics as stx
    print(f"配對分派:實驗 {len(t)} / 對照 {len(ct)}")
    print(f"  基準中位觀看  實驗 {stx.median(r['views'] for r in t):.0f}"
          f" / 對照 {stx.median(r['views'] for r in ct):.0f}")
    if not args.apply:
        print(f"\n[dry-run] 未改動。先跑 --preview 看 A/B 長什麼樣;"
              f"要換圖:--apply(每支 50 units,共 {len(t)*50})")
        return 0

    import daily_publish as dp
    from googleapiclient.http import MediaFileUpload
    yt = dp.get_service()
    BACKUP.mkdir(parents=True, exist_ok=True)
    done = []

    def _flush():
        STATE.write_text(json.dumps(
            {"applied_at": time.strftime("%F %T"), "baseline_period": [b0, b1],
             "treat": done, "ctrl": ct, "seed": SEED}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    for r in t:
        try:
            src = ROOT / "assets" / "thumbnails" / f"{r['slug']}.jpg"
            import shutil
            shutil.copy2(src, BACKUP / f"{r['slug']}.jpg")     # 先備份舊圖才動
            img = make_variant_b(r["slug"], _title_of(r["slug"]))
            tmp = ROOT / "assets" / "thumbnails" / f"{r['slug']}__abB.jpg"
            img.save(tmp, quality=92)
            yt.thumbnails().set(videoId=r["vid"],
                                media_body=MediaFileUpload(str(tmp), mimetype="image/jpeg")).execute()
            done.append(r)
            _flush()
            print(f"✅ {r['vid']} {r['slug'][6:36]}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {r['vid']} {str(e)[:90]}")
            if "quota" in str(e).lower():
                print("配額停止(已換的都已落地)")
            else:
                print("非配額錯誤,停止本輪(避免記錯帳)")
            break
    if not done:
        print("一支都沒換成,**不寫 state**。")
        return 1
    _flush()
    print(f"\n換了 {len(done)} 支;對照 {len(ct)} 支不動。兩週後 --report。")
    try:
        from ops import log_ops
        log_ops("縮圖實驗", f"B 版換圖 {len(done)} 支(對照 {len(ct)} 支不動)")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
