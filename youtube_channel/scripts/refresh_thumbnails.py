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

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(同 quality_score.py/make_thumbnails.py 作法)——
    否則直跑 --render 讀不到 OPENROUTER key，llm.complete 全供應商都失敗。"""
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

ACCENT = {"yellow": (255, 209, 102), "green": (88, 224, 140), "red": (255, 96, 96), "blue": (90, 184, 255)}
# yellow=#FFD166，B5：與 design_system.json / make_thumbnails.py / assets/brand 全線統一同一個金


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
    """items: [(vid,title)]。LLM 只配文案角度(l1/l2/tag/accent)，回 {vid: cfg}。
    誠信鐵則(同 make_thumbnails._real_card)：數據卡的數字絕不讓 LLM 現場編——
    一律由 do_render() 呼叫 make_thumbnails._real_card() 依標題領域(台股/加密)比對
    真實資料檔(backtest_cards.json / tw_stock_facts.json)取得，領域對不上或無真資料
    就不掛卡，不會出現「台股題配加密卡」或「查無憑據的示意數字」。
    2026-07 根因修復：舊版直打 api.anthropic.com(工作室已改 OpenRouter，key 早失效)——
    改走共用 llm.py 路由，同 make_thumbnails.derive_cfg()。"""
    import llm  # sys.path 已在模組頂插入 scripts/（見 ROOT/"scripts"）
    listing = "\n".join(f"{i}. {t}" for i, (_, t) in enumerate(items))
    prompt = f"""你是量化阿森頻道（量化/網格/派網Pionex/回測/風控，繁中 faceless）的封面設計師。
為下面每支影片設計縮圖文案（不含任何數據卡數字——數據卡由程式另外依真實回測資料配對，
你不用也不可以編造 pct/mdd/回撤/報酬等數字）：
- l1/l2：兩行大字鉤子，每行 ≤5 字，從標題濃縮（左側顯示，要短）。
- tag：底部一行（≤16 字）。accent 從 yellow/green/red/blue 擇一（警示紅、方法綠、工具藍、一般黃，
  純視覺配色，與是否掛得到數據卡無關）。

影片清單：
{listing}

只輸出 JSON 陣列（i 對應編號，不要其他字、不要 markdown 圍欄）：
[{{"i":0,"l1":"丟1萬","l2":"跑30天","tag":"自動交易實測｜結果公開","accent":"green"}}]"""
    # 注意：輸出是 JSON 陣列(非物件)，不能開 json_mode(OpenAI 相容端點的 response_format=json_object
    # 只接受頂層物件)——沿用原本的正則抓 [...] 解析法。
    txt = llm.complete(prompt, max_tokens=8000, temperature=0.6)
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
    no_card = 0
    for vid, title in items:
        c = cfgs.get(vid)
        if not c:
            print(f"[skip] {vid} 無設定"); continue
        accent = ACCENT.get((c.get("accent") or "yellow").lower(), ACCENT["yellow"])
        # 誠信防線：數據卡一律走 make_thumbnails._real_card()（先判定台股/加密領域，
        # 領域對不上或無真實資料就回 None）——絕不讓 LLM 現場臆造 pct/mdd/回撤數字，
        # 也絕不會出現台股題掛加密卡、或反之的跨領域誤配。
        real_card = mt._real_card(vid, title)
        if real_card is None:
            no_card += 1
        cfg = {"slug": vid, "l1": c.get("l1", "")[:8], "l2": c.get("l2", "")[:8],
               "tag": c.get("tag", "")[:18], "accent": accent, "mark": "$",
               "card": real_card}
        # 借 make_thumbnails 的繪圖（改輸出到 refresh 目錄）
        img = mt.gradient_bg((14, 22, 46), (28, 44, 86))
        d = ImageDraw.Draw(img, "RGBA")
        _draw_full(mt, d, img, cfg)
        out = REFRESH_DIR / f"{vid}.jpg"
        img.save(out, "JPEG", quality=90)
        manifest[vid] = {"title": title, "file": f"assets/thumbnails/refresh/{vid}.jpg",
                          "has_card": bool(real_card)}
        note = "" if real_card else "（無真數據可對應，乾淨版·不掛卡）"
        print(f"[ok] {vid}  {title[:24]} {note}")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== 完成：渲染 {len(manifest)} 張（{no_card} 支無真數據·乾淨版無卡）→ {REFRESH_DIR} ==")
    return 0


def _draw_full(mt, d, img, cfg):
    """重現 make_thumbnails.make_one 的繪圖（不另存檔，畫到傳入的 d/img）。"""
    accent = cfg["accent"]
    if cfg.get("card"):
        mt.draw_backtest_card(d, cfg["card"], accent)
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
        if not any(os.environ.get(_k,"").strip() for _k in ("OPENROUTER_API_KEY","ANTHROPIC_API_KEY","DEEPSEEK_API_KEY","GEMINI_API_KEY","GROQ_API_KEY")):
            print("[FATAL] 無 LLM key(OPENROUTER_API_KEY 等皆未設)", file=sys.stderr); return 2
        return do_render(args.render)
    if args.apply:
        return do_apply()
    print(__doc__); return 1


if __name__ == "__main__":
    raise SystemExit(main())
