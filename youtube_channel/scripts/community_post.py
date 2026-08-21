#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""community_post.py — 把「今日體檢重點卡」發到 YouTube 社群貼文(Playwright)。

## 為什麼走 Playwright
YouTube Data API **沒有**社群貼文端點(communityPosts 不存在,2026-08 查證),
和片尾(end screen)一樣只能走 UI 自動化。登入態重用 MCP Chrome 的 profile
(D:/ms-playwright/mcp-chrome-0ce1802)——片尾自動化(_endscreen_driver.js)
已用同一個 profile 打過 Studio,登入是現成的。

## 安全設計
- profile 被 MCP 佔用(瀏覽器開著)時 launch 會失敗 → **優雅跳過**,下次 cron 再試。
  排在 07:40:MCP 通常只在互動 session 開著,清晨無人。
- 冪等:done 名單記日期,一天最多一篇;卡片不存在就先產。
- **發布前截圖**留證(STUDIO/community_cards/<date>_shot.png):UI 自動化的「已發布」
  判定天生脆弱(片尾那次的教訓:儲存判準要 reload 驗證),截圖讓事後可查。
- 貼文內容全部來自 community_card.py 產的 .txt(數字溯源自 fact 庫,不在這裡寫文案)。
- 選擇器策略同 _endscreen_driver:文字定位 + 往上找可點祖先,Studio 的 DOM 常變,
  任何一步找不到就截圖 + 報錯退出,**不亂點**。

## 用法
  python scripts/community_post.py --dry-run    # 只開頁面走到發布前一步,截圖不發
  python scripts/community_post.py --apply      # 真的發布
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
CARDS = STUDIO / "community_cards"
DONE = STUDIO / "community_post_done.json"
PROFILE = Path(r"D:\ms-playwright\mcp-chrome-0ce1802")
CHANNEL_ID = "UCqP5JQXlQR5ZDLtEiBt4kLA"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = date.today().isoformat()
    done = json.loads(DONE.read_text(encoding="utf-8")) if DONE.exists() else {}
    if done.get(today) and args.apply:
        print(f"今天已發過({done[today]}),跳過(一天一篇)")
        return 0

    # 卡片:今天的不存在就先產
    pngs = sorted(CARDS.glob(f"{today}_*.png"))
    if not pngs:
        import community_card
        p = community_card.build()
        if not p:
            print("產卡失敗,不發文")
            return 1
        pngs = [p]
    png = pngs[0]
    txt = png.with_suffix(".txt")
    if not txt.exists():
        print("貼文文字檔不存在,不發文")
        return 1
    body = txt.read_text(encoding="utf-8")

    if not PROFILE.exists():
        print(f"登入 profile 不存在:{PROFILE}")
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("本環境沒裝 playwright(pip install playwright)")
        return 1

    # 🔴 launch 前清掉佔用同 profile 的殭屍 Chrome(只殺命令列含本 profile 路徑的,
    # 不碰使用者一般 Chrome)。實測:前一輪失敗的殘留讓下一次 launch 直接
    # 「Target closed」——在 cron 情境等於殘留一次、之後天天失敗。
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
             "Where-Object { $_.CommandLine -like '*mcp-chrome-0ce1802*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, timeout=30)
        time.sleep(2)
    except Exception:  # noqa: BLE001
        pass

    shot = CARDS / f"{today}_shot.png"
    try:
        with sync_playwright() as pw:
            try:
                ctx = pw.chromium.launch_persistent_context(
                    str(PROFILE), headless=False, channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"])
            except Exception as e:
                if "ProcessSingleton" in str(e) or "already" in str(e).lower():
                    print("profile 被佔用(MCP 瀏覽器開著),本次跳過,下次 cron 再試")
                    return 0
                raise
            page = ctx.new_page()
            page.set_default_timeout(90000)
            # 🔴 社群貼文的作曲器**不在 Studio**:studio.youtube.com/channel/…/posts
            # 直接回「糟糕,系統發生錯誤」(實測截圖為證)。正確入口在 youtube.com 的
            # 頻道社群 tab(自己的頻道會有輸入框)。首載重,commit + 手動等。
            page.goto(f"https://www.youtube.com/channel/{CHANNEL_ID}/community",
                      wait_until="commit", timeout=90000)
            page.wait_for_timeout(9000)

            # 「建立」→「發布貼文」入口(Studio 版面多變,兩條路都試)
            def click_text(t, timeout=6000):
                loc = page.get_by_text(t, exact=True).first
                loc.click(timeout=timeout)

            opened = False
            # 社群頁的 composer 是頁面上方的假輸入框(點了才展開);先試點它
            try:
                ph = page.locator("#placeholder-area, ytd-comment-simplebox-renderer, #simplebox-placeholder").first
                ph.click(timeout=8000)
                page.wait_for_timeout(1500)
                opened = True
            except Exception:  # noqa: BLE001
                pass
            for path in ([] if opened else (["建立貼文"], ["建立", "發布貼文"], ["建立", "建立貼文"])):
                try:
                    for t in path:
                        click_text(t)
                        page.wait_for_timeout(1500)
                    opened = True
                    break
                except Exception:  # noqa: BLE001
                    continue
            if not opened:
                page.screenshot(path=str(shot))
                print(f"找不到貼文入口(截圖 {shot.name});Studio 版面可能又改了")
                ctx.close()
                return 1

            # 貼文文字
            box = page.locator("[contenteditable='true']").first
            box.click(timeout=8000)
            box.fill(body)
            page.wait_for_timeout(800)

            # 附圖:先試隱藏的 input[type=file] 直塞(最穩,不依賴按鈕文字),
            # 退而求其次才走 file chooser。實測「圖片」exact 文字點不到
            # (composer 的圖片鈕是 icon,aria-label 可能是「新增圖片」)。
            attached = False
            try:
                fi = page.locator("input[type='file']").first
                fi.set_input_files(str(png), timeout=5000)
                page.wait_for_timeout(2500)
                attached = True
            except Exception:  # noqa: BLE001
                for label in ("新增圖片", "圖片", "Add image"):
                    try:
                        with page.expect_file_chooser(timeout=4000) as fc:
                            page.get_by_label(label).first.click(timeout=3000)
                        fc.value.set_files(str(png))
                        page.wait_for_timeout(2500)
                        attached = True
                        break
                    except Exception:  # noqa: BLE001
                        continue
            if not attached:
                print("[warn] 附圖失敗,改純文字貼文(文字含影片連結,價值仍在)")

            # 截圖防禦:headed 視窗可能被外力關掉(實測 Target closed),
            # 截不到就記錄,不讓證據步驟炸掉主流程。
            try:
                page.screenshot(path=str(shot))
            except Exception:  # noqa: BLE001
                print("[warn] 發布前截圖失敗(頁面被關?),流程繼續")
            if not args.apply:
                print(f"[dry] 已走到發布前一步,截圖:{shot.name}(未發布)")
                ctx.close()
                return 0

            click_text("發布")
            page.wait_for_timeout(3500)
            page.screenshot(path=str(shot))
            done[today] = png.name
            DONE.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
            print(f"✅ 已發布社群貼文(證據截圖 {shot.name})")
            try:
                from ops import log_ops
                log_ops("社群貼文", f"今日體檢卡 {png.name}")
            except Exception:  # noqa: BLE001
                pass
            ctx.close()
            return 0
    except Exception as exc:  # noqa: BLE001
        # 🔴 任何失敗都要關 ctx:第一版 goto 超時後直接 return,殘留的 Chrome
        # 佔住 profile → 下一次跑(包括隔天 cron)全被「profile 被佔用」擋掉,
        # 一個超時變成永久停擺。實測踩到。
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
        print(f"[err] {str(exc)[:200]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
