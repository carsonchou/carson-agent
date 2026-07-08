#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tiktok_upload.py — 把 output/<slug>.mp4 上傳到 TikTok(跨平台加速成長)。

用 STUDIO/tiktok_state.json(Carson 瀏覽器登入後存的 session cookies)+ Playwright 自動上傳。
TikTok 網頁上傳吃「本地檔」(不像 IG 要公網 URL),所以不需 tunnel。
caption 取自 <slug>.md 的標題+hashtags(誠信同 YT,不喊單)。

⚠️ TikTok 有機器人偵測+上傳 UI 常改:預設 headed(TIKTOK_HEADLESS=1 才 headless);
selector 用多重 fallback;失敗優雅退出+清楚 log,不炸。session 過期→提示重登。

用法:
  python scripts/tiktok_upload.py --slug S_xxx           # 上傳單支
  python scripts/tiktok_upload.py --slug S_xxx --dry     # 只檢查(不真傳)
  python scripts/tiktok_upload.py --max 3                # 補傳最近未傳的 N 支(讀 ledger 去重)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
STATE = STUDIO / "tiktok_state.json"
LEDGER = STUDIO / "tiktok_ledger.json"
import studio_common as sc

UPLOAD_URLS = ["https://www.tiktok.com/tiktokstudio/upload", "https://www.tiktok.com/upload"]


def _caption(slug: str) -> str:
    """從 <slug>.md 取標題+hashtags 組 caption(TikTok 上限約 2200 字元、標籤吃 #)。"""
    md = OUT / f"{slug}.md"
    title, tags = slug.lstrip("SL_"), []
    if md.exists():
        txt = md.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"標題[:：]\s*(.+)", txt) or re.search(r"^#\s*(.+)", txt, re.M)
        if m:
            title = m.group(1).strip()
        h = re.search(r"[Hh]ashtags?[:：]\s*(.+)", txt)
        if h:
            tags = re.findall(r"#\S+", h.group(1))
    if not tags:
        tags = ["#量化交易", "#台股", "#投資理財", "#回測", "#股票"]
    return (title + "\n" + " ".join(tags[:8]))[:2100]


def _upload_one(slug: str, dry: bool = False) -> bool:
    mp4 = OUT / f"{slug}.mp4"
    if not mp4.exists():
        print(f"[tiktok] 找不到 {mp4.name}", file=sys.stderr)
        return False
    if not STATE.exists():
        print("[tiktok] 無 tiktok_state.json(尚未登入)。請開瀏覽器登入 TikTok 存 session。", file=sys.stderr)
        return False
    cap = _caption(slug)
    print(f"[tiktok] 準備上傳 {slug}｜caption: {cap[:40]}…")
    if dry:
        print("[tiktok][dry] 不實傳。")
        return True
    import os
    headless = os.environ.get("TIKTOK_HEADLESS") == "1"
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("[tiktok] 缺 playwright(pip install playwright)", file=sys.stderr)
        return False
    with sync_playwright() as p:
        br = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(storage_state=str(STATE),
                             user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"))
        page = ctx.new_page()
        ok = False
        try:
            for url in UPLOAD_URLS:
                try:
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)
                    if "login" in page.url:
                        print("[tiktok] session 過期→被導回登入。請重新開瀏覽器登入存 session。", file=sys.stderr)
                        break
                    # 檔案上傳:找 input[type=file](常在 iframe 內)
                    fi = page.query_selector("input[type=file]")
                    if not fi:
                        for fr in page.frames:
                            fi = fr.query_selector("input[type=file]")
                            if fi:
                                break
                    if not fi:
                        continue  # 換下一個 upload URL
                    fi.set_input_files(str(mp4))
                    print("[tiktok] 檔案已送入,等 TikTok 處理…")
                    page.wait_for_timeout(15000)  # 等上傳/轉檔
                    # caption:contenteditable
                    for sel in ["div[contenteditable=true]", "[data-text=true]", "div.public-DraftEditor-content"]:
                        el = page.query_selector(sel)
                        if el:
                            try:
                                el.click()
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Delete")
                                page.keyboard.type(cap[:150], delay=15)
                            except Exception:
                                pass
                            break
                    page.wait_for_timeout(3000)
                    # 發佈按鈕:①先等影片處理完(Post 鈕才 enable),輪詢最多 ~75s ②多重選擇器(data-e2e/role/文字)
                    posted = False

                    def _find_post_btn():
                        b = page.query_selector('[data-e2e="post_video_button"]')
                        if b:
                            return b
                        for name in ["發佈", "發布", "Post", "发布"]:
                            b = page.query_selector(f"button:has-text('{name}')")
                            if b:
                                return b
                        return None
                    for _ in range(15):  # 15×5s = 75s 等處理完+鈕可按
                        b = _find_post_btn()
                        if b:
                            try:
                                if b.is_enabled():
                                    b.scroll_into_view_if_needed(timeout=3000)
                                    b.click(timeout=8000)
                                    posted = True
                                    break
                            except Exception:  # noqa: BLE001
                                pass
                        page.wait_for_timeout(5000)
                    page.wait_for_timeout(6000)
                    ok = posted
                    if posted:
                        print(f"[tiktok] ✓ 已點發佈 {slug}(TikTok 端仍會審核)")
                    else:
                        print("[tiktok] 找不到發佈鈕(UI 可能改版),已上傳檔案+caption,請人工到 TikTok 按發佈", file=sys.stderr)
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"[tiktok] {url} 上傳流程出錯:{str(e)[:100]}", file=sys.stderr)
                    continue
        finally:
            ctx.close(); br.close()
        return ok


def _load_ledger():
    return sc.load_json_safe(LEDGER, {}) or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=None)
    ap.add_argument("--max", type=int, default=0, help="補傳最近未傳的 N 支")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    led = _load_ledger()

    if args.slug:
        ok = _upload_one(args.slug, dry=args.dry)
        if ok and not args.dry:
            led[args.slug] = int(time.time()); sc.save_json_atomic(LEDGER, led)
        return 0 if ok else 1

    if args.max:
        # 最近的短片 mp4、未傳過的,傳 N 支
        mp4s = sorted(OUT.glob("S_*.mp4"), key=lambda f: -f.stat().st_mtime)
        done = 0
        for f in mp4s:
            slug = f.stem
            if slug in led:
                continue
            if _upload_one(slug, dry=args.dry):
                if not args.dry:
                    led[slug] = int(time.time()); sc.save_json_atomic(LEDGER, led)
                done += 1
            if done >= args.max:
                break
            time.sleep(5)
        print(f"[tiktok] 補傳完成 {done} 支。")
        return 0
    print("用法:--slug S_xxx 或 --max N", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
