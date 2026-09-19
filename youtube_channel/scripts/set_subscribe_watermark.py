#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_subscribe_watermark.py — 在 YouTube Studio 設定「影片浮水印」(訂閱鈕)。

## 為什麼(2026-08-24)
浮水印是**唯一一個對「所有既有影片、每一次觀看」同時生效**的訂閱轉化元件:
它出現在播放器右下角,點下去就是訂閱。本頻道靠搜尋長尾吃流量(近28天 32,577 觀看),
而訂閱轉化只有 0.46~0.50% —— 這種「一次設定、全站生效」的元件沒設等於白放。

Data API 的 `watermarks.set` 端點在配額用罄時無法呼叫,而且它的 timing 參數常和
Studio UI 的設定互相覆蓋;Studio 介面是官方主路徑,故走 Playwright。

## 安全
- 登入態重用 MCP Chrome profile(community_post.py 同一套)。
- launch 前清殭屍 chrome;任何錯誤路徑都 ctx.close()(不關會鎖住 profile,下次全掛)。
- **設定後 reload 重新確認**(UI 自動化的「已儲存」判定天生脆弱,片尾那次的教訓)。
- 每一步截圖存證到 STUDIO/watermark_*.png。

用法:
  python scripts/set_subscribe_watermark.py --dry-run   # 走到上傳前一步,截圖不送出
  python scripts/set_subscribe_watermark.py --apply
"""
from __future__ import annotations

import argparse
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
PROFILE = Path(r"D:\ms-playwright\mcp-chrome-0ce1802")
CHANNEL_ID = "UCqP5JQXlQR5ZDLtEiBt4kLA"
WM = ROOT / "assets" / "brand" / "watermark_subscribe.png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not WM.exists():
        print(f"浮水印圖不存在:{WM}")
        return 1
    if not PROFILE.exists():
        print(f"登入 profile 不存在:{PROFILE}")
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("本環境沒裝 playwright")
        return 1

    # 清殭屍(只殺佔用本 profile 的)
    try:
        import subprocess
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*mcp-chrome-0ce1802*' } | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                       capture_output=True, timeout=30)
        time.sleep(2)
    except Exception:  # noqa: BLE001
        pass

    ctx = None
    try:
        with sync_playwright() as pw:
            try:
                ctx = pw.chromium.launch_persistent_context(
                    str(PROFILE), headless=False, channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"])
            except Exception as e:  # noqa: BLE001
                if "ProcessSingleton" in str(e) or "already" in str(e).lower():
                    print("profile 被佔用(瀏覽器開著),本次跳過")
                    return 0
                raise
            page = ctx.new_page()
            page.set_default_timeout(90000)
            url = f"https://studio.youtube.com/channel/{CHANNEL_ID}/editing/images"
            page.goto(url, wait_until="commit", timeout=90000)
            page.wait_for_timeout(9000)
            page.screenshot(path=str(STUDIO / "watermark_1_page.png"))

            # 找「影片浮水印」區塊的上傳按鈕。Studio 版面多變 → 先試直接塞 file input。
            done = False
            try:
                fis = page.locator("input[type='file']")
                n = fis.count()
                print(f"頁面上的 file input:{n} 個")
                # 品牌頁通常有三個:大頭貼 / 橫幅 / 浮水印 —— 浮水印是最後一個
                if n >= 1:
                    if args.dry_run:
                        print("[dry] 已定位到上傳欄位,未送出")
                        page.screenshot(path=str(STUDIO / "watermark_2_dry.png"))
                        ctx.close()
                        return 0
                    fis.nth(n - 1).set_input_files(str(WM))
                    page.wait_for_timeout(4000)
                    page.screenshot(path=str(STUDIO / "watermark_2_uploaded.png"))
                    done = True
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] 直塞 file input 失敗:{str(exc)[:120]}")

            if not done:
                page.screenshot(path=str(STUDIO / "watermark_err.png"))
                print("找不到上傳欄位(截圖 watermark_err.png)")
                ctx.close()
                return 1

            # 🔴 送出是**兩段**,少一段就白做:上傳後先跳「自訂影片浮水印」裁切對話框
            #    (取消/完成),點「完成」只關掉對話框;頁面右上角還有一個**頁面層級的「發布」**
            #    在那之前是 disabled,完成之後才變成可按。第一版只點了「完成」就收工,
            #    reload 回來欄位仍是「上傳」= 根本沒存進去(實測踩到,所以驗收一定要 reload)。
            clicked = page.evaluate("""() => {
                const words = ['完成','Done'];
                const els = [...document.querySelectorAll('*')].filter(e =>
                    e.offsetParent && e.children.length <= 1 &&
                    words.includes((e.textContent||'').trim()));
                for (let el of els) {
                    let n = el;
                    for (let i = 0; i < 6 && n; i++) {
                        if (n.tagName === 'BUTTON' || n.tagName === 'YTCP-BUTTON'
                            || n.getAttribute('role') === 'button') {
                            if (n.hasAttribute('disabled')) break;
                            n.click(); return (el.textContent||'').trim();
                        }
                        n = n.parentElement;
                    }
                }
                return null;
            }""")
            print(f"對話框送出:{clicked or '(沒找到)'}")
            page.wait_for_timeout(4000)
            # 🔴 顯示時間預設是「影片結尾」——而本頻道**只有 7% 的觀眾看得到片尾**
            #    (實測留存:片長 95% 處只剩 7%)。不改的話這個元件等於白設。
            #    改成「整部影片」= 曝光從 7% 變 100%,同一個元件差 14 倍。
            try:
                page.get_by_text("影片浮水印", exact=False).first.scroll_into_view_if_needed(timeout=15000)
                page.wait_for_timeout(1200)
                page.get_by_text("整部影片", exact=True).first.click(timeout=15000)
                page.wait_for_timeout(2500)
                print("顯示時間已選『整部影片』")
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] 顯示時間沒改到({str(exc)[:80]})——請手動確認,"
                      f"預設『影片結尾』只有 7% 觀眾看得到")
            # 第二段:頁面層級「發布」(等它從 disabled 變成可按)
            def _pub():
                return page.evaluate("""() => {
                    const els=[...document.querySelectorAll('*')].filter(e=>e.offsetParent
                        && e.children.length<=1 && (e.textContent||'').trim()==='發布');
                    for(let el of els){ let n=el;
                      for(let i=0;i<6&&n;i++){
                        if(n.tagName==='BUTTON'||n.tagName==='YTCP-BUTTON'||n.getAttribute('role')==='button'){
                          if(n.hasAttribute('disabled')||n.getAttribute('aria-disabled')==='true') break;
                          n.click(); return true;} n=n.parentElement;} }
                    return false; }""")
            pub = False
            for _ in range(4):
                pub = _pub()
                if pub:
                    break
                page.wait_for_timeout(2500)
            print(f"頁面『發布』:{pub}")
            page.wait_for_timeout(8000)
            page.screenshot(path=str(STUDIO / "watermark_3_after.png"))

            # 🔴 reload 重新確認(不 reload 的「已儲存」判定不算數)
            page.goto(url, wait_until="commit", timeout=90000)
            page.wait_for_timeout(9000)
            page.screenshot(path=str(STUDIO / "watermark_4_verify.png"))
            # 驗收判準:浮水印那個 file input(頁面上最後一個)附近的文字。
            # 未設定顯示「上傳」,已設定顯示「變更/移除」——這是唯一可靠的判準。
            for _ in range(6):
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(600)
            info = page.evaluate("""() => [...document.querySelectorAll("input[type='file']")].map((el,i)=>{
                let n=el,label=''; for(let k=0;k<8&&n;k++){
                  if((n.innerText||'').trim()){label=(n.innerText||'').trim().slice(0,20); break;} n=n.parentElement;}
                return {i,label};})""")
            wm = info[-1]["label"] if info else ""
            ok = ("變更" in wm or "移除" in wm)
            print(f"重載驗收:浮水印欄位={wm!r} → {'✅ 已設定' if ok else '❌ 仍未設定'}")
            if not ok:
                ctx.close()
                return 1
            ctx.close()
            return 0
    except Exception as exc:  # noqa: BLE001
        try:
            if ctx:
                ctx.close()
        except Exception:  # noqa: BLE001
            pass
        print(f"[err] {str(exc)[:200]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
