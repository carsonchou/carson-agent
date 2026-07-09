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


def _reachable(host: str = "www.tiktok.com", port: int = 443, timeout: float = 6.0):
    """TikTok 只有 IPv4(無 AAAA/IPv6)。本機 IPv4 出口若斷,goto 會空等到 timeout。
    先做一次快速 IPv4 連線探測,回 (ok, msg),讓失敗即時給出明確診斷而非乾等。"""
    import socket
    try:
        ip = socket.gethostbyname(host)  # IPv4
    except Exception as e:  # noqa: BLE001
        return False, f"DNS 解析失敗:{e}"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True, f"IPv4 可達 {ip}"
    except Exception as e:  # noqa: BLE001
        return False, (f"IPv4 連不上 TikTok({ip}:{port}, {type(e).__name__})。"
                       "TikTok 是 IPv4-only(無 IPv6),本機 IPv4 出口疑似中斷。"
                       "確認網路/開 VPN 後重試。")
    finally:
        s.close()


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
    yt = "▶️ 完整版+每日更新在 YouTube 搜尋「量化阿森」訂閱 🔔"
    return (title + "\n" + yt + "\n" + " ".join(tags[:8]))[:2100]


def _upload_one(slug: str, dry: bool = False) -> bool:
    if not (OUT / f"{slug}.mp4").exists():
        print(f"[tiktok] 找不到 {slug}.mp4", file=sys.stderr)
        return False
    if not STATE.exists():
        print("[tiktok] 無 tiktok_state.json(尚未登入)。請開瀏覽器登入 TikTok 存 session。", file=sys.stderr)
        return False
    # 片尾接「訂閱量化阿森 YouTube」CTA(只加在 TikTok 版,YT 原片不動);失敗自動退回原片
    try:
        import append_yt_cta
        mp4 = append_yt_cta.append_cta(slug)
    except Exception:  # noqa: BLE001
        mp4 = OUT / f"{slug}.mp4"
    cap = _caption(slug)
    print(f"[tiktok] 準備上傳 {slug}｜caption: {cap[:40]}…")
    if dry:
        print("[tiktok][dry] 不實傳。")
        return True
    # 網路預檢:TikTok 無 IPv6,IPv4 出口斷時直接明確報錯(避免兩輪 45s 空等)
    okr, msg = _reachable()
    if not okr:
        print(f"[tiktok] 網路預檢失敗:{msg}", file=sys.stderr)
        return False
    print(f"[tiktok] 網路預檢:{msg}")
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
                    # 導頁:commit 即可(SPA 之後自己載),對 IPv4 抖動較耐;失敗重試一次
                    nav_ok = False
                    for attempt in range(2):
                        try:
                            page.goto(url, timeout=60000, wait_until="commit")
                            nav_ok = True
                            break
                        except Exception as ne:  # noqa: BLE001
                            print(f"[tiktok] 導頁重試 {attempt+1}/2 失敗:{str(ne)[:80]}", file=sys.stderr)
                            page.wait_for_timeout(3000)
                    if not nav_ok:
                        continue
                    if "login" in page.url:
                        print("[tiktok] session 過期→被導回登入。請重新開瀏覽器登入存 session。", file=sys.stderr)
                        break
                    # 檔案上傳:等 input[type=file] 出現(SPA 需時間;常在 iframe 內)最多 ~40s
                    fi = None
                    for _ in range(20):
                        fi = page.query_selector("input[type=file]")
                        if not fi:
                            for fr in page.frames:
                                fi = fr.query_selector("input[type=file]")
                                if fi:
                                    break
                        if fi:
                            break
                        if "login" in page.url:
                            print("[tiktok] session 過期→被導回登入。", file=sys.stderr)
                            break
                        page.wait_for_timeout(2000)
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
                    # 發佈:核心方法=JS 原生 element.click() 繞過版權彈窗 overlay 攔截(實證有效·2026-07-09)。
                    # Playwright 的 .click() 會被 TUXModal-overlay 攔;JS click 直接觸發 handler、擋不住。
                    posted = False
                    # 設隱私=所有人(公開),否則預設可能「僅自己」沒觸及
                    try:
                        page.evaluate("() => { const c=document.querySelector('[data-e2e=\"video_visibility_container\"]');"
                                      " if(c){const b=c.querySelector('button,[role=button]'); if(b)b.click();} }")
                        page.wait_for_timeout(1200)
                        for t in ["所有人", "公開", "Everyone", "Public"]:
                            el = page.query_selector(f"[role=option]:has-text('{t}'), li:has-text('{t}')")
                            if el:
                                try:
                                    el.click(timeout=2000)
                                except Exception:  # noqa: BLE001
                                    pass
                                break
                    except Exception:  # noqa: BLE001
                        pass
                    # 輪詢等發佈鈕就緒(影片處理完才 enable)→ JS click
                    for _ in range(24):  # 24×5s = 120s
                        st = page.evaluate("() => { const b=document.querySelector('[data-e2e=\"post_video_button\"]');"
                                           " return b?{found:true,disabled:b.disabled||b.getAttribute('aria-disabled')==='true'}:{found:false}; }")
                        if st.get("found") and not st.get("disabled"):
                            page.evaluate("() => { const b=document.querySelector('[data-e2e=\"post_video_button\"]');"
                                          " if(b){b.scrollIntoView();b.click();} }")  # JS 原生 click 繞 overlay
                            page.wait_for_timeout(8000)
                            body = (page.inner_text("body") or "")[:800]
                            if ("upload" not in page.url) or any(k in body for k in ("內容審查中", "發佈成功", "已發佈", "管理你的貼文")):
                                posted = True
                                break
                        page.wait_for_timeout(5000)
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
        # 最近的短片 mp4、未傳過的,傳 N 支。排除衍生 _ytcta 檔+洗版骨架片(別把垃圾/重複跨發出去)
        mp4s = sorted(OUT.glob("S_*.mp4"), key=lambda f: -f.stat().st_mtime)
        done = 0
        for f in mp4s:
            slug = f.stem
            if slug.endswith("_ytcta"):
                continue  # 衍生片尾卡檔,非原片
            if slug in led:
                continue
            if sc.is_banned_skeleton(slug):
                continue  # 洗版骨架舊片(爆倉還活著等),不跨發
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
