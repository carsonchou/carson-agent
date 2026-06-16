#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_thumbnails.py — 【完整更新片庫·現有片縮圖】換成新『派網回測卡』封面。

跨機流程（縮圖渲染要 Windows 字型＝本機；上傳要 token＝雲端）：
  1) 雲端 --dump out.json     讀 ledger+API，倒出 {videoId: title}
  2) 本機 --render            讀 dump，Claude 依每支『角度』配卡（獲利片綠正報酬／警示片紅負數），
                              用 make_thumbnails 渲染到 assets/thumbnails/refresh/{vid}.jpg，寫 manifest
  3) 雲端 --apply             讀 manifest+圖，先備份現有縮圖網址，再 thumbnails().set 逐支上線
誠實鐵則：卡片數字一律示意、含回撤、明標非保證；警示片用負數/對比不造假獲利。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"
REFRESH_DIR = ROOT / "assets" / "thumbnails" / "refresh"
MANIFEST = REFRESH_DIR / "_manifest.json"
TW = timezone(timedelta(hours=8))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

ACCENT = {"yellow": (255, 210, 63), "green": (88, 224, 140), "red": (255, 96, 96), "blue": (90, 184, 255)}


def tw_ts():
    return datetime.now(TW).strftime("%Y%m%d_%H%M")


# ───────── 1) 雲端 dump ─────────
def do_dump(path):
    from daily_publish import get_service
    yt = get_service()
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    vids = list(ledger.values())
    out = {}
    for i in range(0, len(vids), 50):
        rr = yt.videos().list(part="snippet", id=",".join(vids[i:i+50])).execute()
        for it in rr.get("items", []):
            out[it["id"]] = it["snippet"].get("title", "")
    Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[dump] {len(out)} 支 → {path}")
    return 0


# ───────── 2) 本機 render ─────────
def gen_configs(items):
    """items: [(vid,title)]。Claude 依角度配封面卡，回 {vid: cfg}。"""
    import requests
    listing = "\n".join(f"{i}. {t}" for i, (_, t) in enumerate(items))
    prompt = f"""你是量化阿森頻道（量化/網格/派網Pionex/回測/風控，繁中 faceless）的封面設計師。
為下面每支影片設計一張縮圖文案＋一張『派網回測卡』。鐵則：
- 卡片數字一律「示意、含回撤、不保證」；**獲利/方法類**片用綠色正報酬(pct_color=green、pct 如 +82.4%)，
  **警示/虧損/過擬合類**片用紅色負數或對比(pct_color=red、pct 如 -40%，metric 寫『實盤(示意)』)，**不可在警示片造假獲利**。
- l1/l2：兩行大字鉤子，每行 ≤5 字，從標題濃縮（左側顯示，要短）。
- tag：底部一行（≤16 字）。accent 從 yellow/green/red/blue 擇一（警示紅、方法綠、工具藍、一般黃）。
- mdd/range：兩列副資料（如『最大回撤 -15.3%』『實盤 -40%』『區間 1774-2028』擇合適兩條）。

影片清單：
{listing}

只輸出 JSON 陣列（i 對應編號，不要其他字、不要 markdown 圍欄）：
[{{"i":0,"l1":"丟1萬","l2":"跑30天","tag":"自動交易實測｜結果公開","accent":"green","metric":"回測年化(示意)","pct":"+82.4%","pct_color":"green","mdd":"最大回撤 -15.3%","range":"區間 1774-2028","note":"※示意回測，非真實獲利保證"}}]"""
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 8000,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=240)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    m = re.search(r"\[.*\]", txt, re.S)
    arr = []
    if m:
        try:
            arr = json.loads(m.group(0))
        except Exception:
            for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
                try:
                    arr.append(json.loads(om.group(0)))
                except Exception:
                    continue
    out = {}
    for o in arr:
        try:
            i = int(o["i"])
            if 0 <= i < len(items):
                out[items[i][0]] = o
        except Exception:
            continue
    return out


def do_render(dump_path):
    import make_thumbnails as mt
    from PIL import ImageDraw
    data = json.loads(Path(dump_path).read_text(encoding="utf-8"))
    items = list(data.items())
    print(f"== 為 {len(items)} 支配卡＋渲染 ==")
    cfgs = gen_configs(items)
    REFRESH_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for vid, title in items:
        c = cfgs.get(vid)
        if not c:
            print(f"[skip] {vid} 無設定"); continue
        accent = ACCENT.get((c.get("accent") or "yellow").lower(), ACCENT["yellow"])
        cfg = {"slug": vid, "l1": c.get("l1", "")[:8], "l2": c.get("l2", "")[:8],
               "tag": c.get("tag", "")[:18], "accent": accent, "mark": "$",
               "card": {"strat": "網格·示意", "metric": c.get("metric", "回測年化(示意)"),
                        "pct": c.get("pct", "+82.4%"), "pct_color": c.get("pct_color", "green"),
                        "mdd": c.get("mdd", "最大回撤 -15.3%"), "range": c.get("range", "區間 1774-2028"),
                        "note": c.get("note", "※示意回測，非真實獲利保證")}}
        # 借 make_thumbnails 的繪圖（改輸出到 refresh 目錄）
        img = mt.gradient_bg((14, 22, 46), (28, 44, 86))
        d = ImageDraw.Draw(img, "RGBA")
        _draw_full(mt, d, img, cfg)
        out = REFRESH_DIR / f"{vid}.jpg"
        img.save(out, "JPEG", quality=90)
        manifest[vid] = {"title": title, "file": f"assets/thumbnails/refresh/{vid}.jpg"}
        print(f"[ok] {vid}  {title[:24]}")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== 完成：渲染 {len(manifest)} 張 → {REFRESH_DIR} ==")
    return 0


def _draw_full(mt, d, img, cfg):
    """重現 make_thumbnails.make_one 的繪圖（不另存檔，畫到傳入的 d/img）。"""
    accent = cfg["accent"]
    if cfg.get("card"):
        mt.draw_backtest_card(d, cfg["card"])
    mt.draw_text_stroke  # noqa
    d.rectangle([0, 0, 18, mt.H], fill=accent)
    tagf = mt.font(38, bold=True)
    ct = mt.CHANNEL
    tb = d.textbbox((0, 0), ct, font=tagf); pad = 18
    d.rounded_rectangle([60, 48, 60 + (tb[2]-tb[0]) + pad*2, 48 + (tb[3]-tb[1]) + pad*2], radius=14, fill=(255, 255, 255, 28))
    d.text((60 + pad, 48 + pad - tb[1]), ct, font=tagf, fill=(220, 230, 245))
    # 自動縮放字級，讓兩行都塞進卡片左邊空間（有卡時可用寬≈600，無卡≈1000），不硬切字
    has_card = bool(cfg.get("card"))
    avail = 600 if has_card else 1000

    def _fit(text, start):
        sz = start
        while sz > 80:
            fb = d.textbbox((66, 0), text or "·", font=mt.font(sz, bold=True), stroke_width=7)
            if fb[2] - 66 <= avail:
                return sz
            sz -= 6
        return 80
    fsz = min(_fit(cfg["l1"], 150), _fit(cfg["l2"], 150))
    f1 = mt.font(fsz, bold=True); y = 210 if has_card else 200
    mt.draw_text_stroke(d, (66, y), cfg["l1"], f1, fill=accent, sw=7)
    b1 = d.textbbox((66, y), cfg["l1"], font=f1, stroke_width=7)
    d.rectangle([70, b1[3]+6, 70 + min(avail - 40, b1[2]-66), b1[3]+18], fill=accent)
    y2 = b1[3] + 34
    mt.draw_text_stroke(d, (66, y2), cfg["l2"], mt.font(fsz, bold=True), fill=(245, 248, 255), sw=7)
    tf = mt.font(54, bold=True); bar_h = 96
    d.rectangle([0, mt.H - bar_h, mt.W, mt.H], fill=(*accent, 235))
    tbb = d.textbbox((0, 0), cfg["tag"], font=tf)
    d.text((66, mt.H - bar_h//2 - (tbb[3]-tbb[1])//2 - tbb[1]), cfg["tag"], font=tf, fill=(12, 18, 38))


# ───────── 3) 雲端 apply ─────────
def do_apply():
    from daily_publish import get_service
    from googleapiclient.http import MediaFileUpload
    yt = get_service()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    if not manifest:
        print("[FATAL] 無 manifest（先在本機 --render）", file=sys.stderr); return 2
    # 備份現有縮圖網址
    vids = list(manifest.keys())
    backup = {}
    for i in range(0, len(vids), 50):
        rr = yt.videos().list(part="snippet", id=",".join(vids[i:i+50])).execute()
        for it in rr.get("items", []):
            th = it["snippet"].get("thumbnails", {})
            best = th.get("maxres") or th.get("high") or th.get("medium") or {}
            backup[it["id"]] = best.get("url", "")
    ts = tw_ts()
    bpath = STUDIO / f"thumb_backup_{ts}.json"
    bpath.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    # 真備份：把舊縮圖圖檔抓下來存檔（之後可 thumbnails().set 還原）
    bdir = STUDIO / f"thumb_backup_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    import urllib.request as _u
    saved = 0
    for vid, url in backup.items():
        if not url:
            continue
        try:
            data = _u.urlopen(url, timeout=20).read()
            (bdir / f"{vid}.jpg").write_bytes(data)
            saved += 1
        except Exception:
            pass
    print(f"[backup] 舊縮圖：網址→{bpath.name}、圖檔 {saved} 張→{bdir.name}/")
    ok = 0
    for vid, m in manifest.items():
        fp = ROOT / m["file"]
        if not fp.exists():
            print(f"[skip] {vid} 無圖檔"); continue
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(fp), mimetype="image/jpeg")).execute()
            ok += 1
            print(f"[ok] {vid}  {m['title'][:24]}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {vid}: {e}", file=sys.stderr)
    log_ops("片庫更新", f"現有片縮圖換回測卡 {ok}/{len(manifest)} 支（備份 {bpath.name}）")
    print(f"\n== 完成：上線 {ok}/{len(manifest)} 張新縮圖（備份 {bpath.name}）==")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=None, help="(雲端) 倒出 {videoId:title} 到此路徑")
    ap.add_argument("--render", default=None, help="(本機) 讀 dump json 產圖")
    ap.add_argument("--apply", action="store_true", help="(雲端) 上線 manifest 的縮圖")
    args = ap.parse_args()
    if args.dump:
        return do_dump(args.dump)
    if args.render:
        if not API_KEY:
            print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr); return 2
        return do_render(args.render)
    if args.apply:
        return do_apply()
    print(__doc__); return 1


if __name__ == "__main__":
    raise SystemExit(main())
