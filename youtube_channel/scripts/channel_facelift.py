#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""channel_facelift.py — 頻道門面改造(一次性,冪等,排在配額重置後自動執行)。

## 背景(2026-08-21,Carson 指令:讓人看到就想訂閱、影片一部一部接著看)
盤點發現三個門面問題,全部可用 API 修,但當下配額已耗盡(重置 = 台北 15:00),
所以寫成這支冪等腳本排 15:05 自動開火。做三件事:

① **發布 checkup EP0 並設為非訂閱者 trailer**
   EP0/系列說明片是實測轉化最高的格式(5.81%/8.33%,一般片 0.67%),
   而個股體檢是旗艦系列(EP1~87、搜尋流量主力),它的最新 EP0(377檔版)已渲好未發布。
   現任 trailer 是 tw_lab EP0(實測 1.79%)——換成主力系列的說明片。
   非訂閱者進頻道首頁自動播 trailer,這是「看到就想訂閱」最直接的一支槓桿。

② **首頁貨架重排**:把個股體檢連載清單排到熱門影片正下方(位置 1)。
   追劇的入口要在第一屏,不是埋在第四排。

③ **追劇鏈續跑**由 binge_chain.py 的每日排程負責(不在這裡重複)。

## 安全
- 冪等:EP0 已發布就跳過上傳、trailer 已是目標就跳過、貨架已在位置 1 就跳過。
- 發布走產線同一條 upload_one(含 audit fail-closed、EP 系列處理、縮圖、字幕),
  並照規矩更新 uploaded_ledger 與 publish_daily_count(每日硬上限的計數器要誠實)。
- trailer 舊值備份到 STUDIO/facelift_backup.json,可還原。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
EP0_SLUG = "L_個股體檢系列已體檢377檔台股其中190檔資料有缺口"
BK = STUDIO / "facelift_backup.json"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import daily_publish as dp
    from studio_common import save_json_atomic
    yt = dp.get_service()
    led = dp.load_ledger()

    # ── ① EP0 發布 ──────────────────────────────────────────────
    vid = led.get(EP0_SLUG)
    if vid:
        print(f"① EP0 已發布({vid}),跳過上傳")
    elif not (OUT / f"{EP0_SLUG}.mp4").exists():
        print("① EP0 成品不存在,跳過(檢查渲染)")
    elif not args.apply:
        print("① [dry] 將發布 EP0 並記帳")
    else:
        import audit_video
        ok, reasons = audit_video.audit(EP0_SLUG)
        if not ok:
            print(f"① EP0 未過 audit,不發布:{reasons}")
        else:
            # 🔴 upload_one 現在會因捏造閘門丟例外,而本呼叫原本**沒包 try** ——
            # 一次被擋就整支 script 崩,步驟②③④(trailer/貨架/橫幅)全不執行。
            # 本檔 :88 註解記載過他們修過一次同款 bug。crontab 16:05 每天跑。
            try:
                vid = dp.upload_one(yt, EP0_SLUG, "public")
            except Exception as _e:  # noqa: BLE001
                print(f"① EP0 未發布({type(_e).__name__}):{str(_e)[:160]}")
                vid = None
            if not vid:
                # ⚠️ 沒發成就**什麼都不要記**:計數器與「已發布」那行原本在這條路上照跑,
                # 會謊報一次發布、還吃掉 daily_publish 每日硬上限的一格額度。
                print("① EP0 這輪未發布,不記帳、不計數(後面步驟照跑)")
            else:
                led[EP0_SLUG] = vid
                dp.save_ledger(led)
                # 每日硬上限計數器要誠實(daily_publish 的護欄靠它)
                try:
                    from datetime import datetime
                    cf = STUDIO / "publish_daily_count.json"
                    c = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {}
                    k = datetime.now().strftime("%Y-%m-%d")
                    c[k] = int(c.get(k, 0)) + 1
                    save_json_atomic(cf, c)
                except Exception:  # noqa: BLE001
                    pass
                print(f"① EP0 已發布:https://youtu.be/{vid}")

    # 🔴 2026-08-22 獨立審核:本步原本沒有 try——08-21 15:05 cron 在 channels.list
    # 撞 403 quotaExceeded,main 直接炸,③貨架④橫幅**從未執行**(banner done_mark
    # 至今不存在)。每一步都必須自己扛錯,一步炸不准拖累後面的步。
    try:
        # ── ② trailer 換成 EP0 ──────────────────────────────────────
        if vid:
            ch = yt.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
            bs = ch["brandingSettings"]
            cur = (bs.get("channel") or {}).get("unsubscribedTrailer")
            if cur == vid:
                print(f"② trailer 已是 EP0({vid}),跳過")
            elif not args.apply:
                print(f"② [dry] trailer {cur} → {vid}")
            else:
                BK.write_text(json.dumps({"old_trailer": cur}, ensure_ascii=False), encoding="utf-8")
                bs.setdefault("channel", {})["unsubscribedTrailer"] = vid
                yt.channels().update(part="brandingSettings",
                                     body={"id": ch["id"], "brandingSettings": bs}).execute()
                print(f"② trailer 已換:{cur} → {vid}(舊值備份 {BK.name})")
        else:
            print("② EP0 尚無 videoId,trailer 下次跑再換(冪等)")

    except Exception as exc:  # noqa: BLE001
        print(f"② [warn] trailer 處理失敗:{str(exc)[:120]}", file=sys.stderr)

    # ── ③ 首頁貨架:個股體檢連載排到位置 1 ─────────────────────────
    try:
        secs = yt.channelSections().list(part="snippet,contentDetails", mine=True).execute()
        items = secs.get("items", [])
        pls = [p for it in items for p in (it.get("contentDetails", {}).get("playlists") or [])]
        names = {}
        if pls:
            r = yt.playlists().list(part="snippet", id=",".join(pls)).execute()
            names = {x["id"]: x["snippet"]["title"] for x in r.get("items", [])}
        target_sec = None
        for it in items:
            for p in (it.get("contentDetails", {}).get("playlists") or []):
                if "個股體檢" in names.get(p, ""):
                    target_sec = it
        if target_sec is None:
            print("③ 貨架裡沒有個股體檢清單,跳過(先確認清單存在)")
        elif target_sec["snippet"].get("position") == 1:
            print("③ 個股體檢貨架已在位置 1,跳過")
        elif not args.apply:
            print(f"③ [dry] 個股體檢貨架 位置{target_sec['snippet'].get('position')} → 1")
        else:
            sn = target_sec["snippet"]
            sn["position"] = 1
            yt.channelSections().update(part="snippet,contentDetails", body={
                "id": target_sec["id"], "snippet": sn,
                "contentDetails": target_sec.get("contentDetails", {}),
            }).execute()
            print("③ 個股體檢貨架已移到位置 1(熱門影片正下方)")
    except Exception as exc:  # noqa: BLE001
        print(f"③ [warn] 貨架處理失敗:{str(exc)[:120]}", file=sys.stderr)

    # ── ④ 頻道橫幅(2026-08-21):訪客第一眼看到的東西 ─────────────────────
    # 設計沿用縮圖產線的深色語言(BASE_BG 近黑 + K 線剪影 + 克制 bloom),
    # 已送 Carson 過目。舊橫幅 URL 先備份進 facelift_backup.json,可還原:
    #   把 backup 裡的 old_banner_url 塞回 brandingSettings.image.bannerExternalUrl 即可。
    # 冪等:banner_done 標記存在就跳過(橫幅上傳每次都會生新 URL,不能用 URL 比對)。
    banner = STUDIO / "channel_banner_v2.png"
    done_mark = STUDIO / "facelift_banner_done.json"
    if done_mark.exists():
        print("④ 橫幅已換過,跳過")
    elif not banner.exists():
        print("④ 橫幅檔不存在,跳過")
    elif not args.apply:
        print("④ [dry] 將上傳橫幅並備份舊 URL")
    else:
        try:
            from googleapiclient.http import MediaFileUpload
            ch = yt.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
            bs = ch["brandingSettings"]
            old_url = (bs.get("image") or {}).get("bannerExternalUrl")
            bk = json.loads(BK.read_text(encoding="utf-8")) if BK.exists() else {}
            bk["old_banner_url"] = old_url
            BK.write_text(json.dumps(bk, ensure_ascii=False), encoding="utf-8")
            ins = yt.channelBanners().insert(
                media_body=MediaFileUpload(str(banner), mimetype="image/png")).execute()
            url = ins.get("url")
            bs.setdefault("image", {})["bannerExternalUrl"] = url
            yt.channels().update(part="brandingSettings",
                                 body={"id": ch["id"], "brandingSettings": bs}).execute()
            done_mark.write_text(json.dumps({"url": url}), encoding="utf-8")
            print(f"④ 橫幅已換(舊 URL 已備份:{str(old_url)[:50]}…)")
        except Exception as exc:  # noqa: BLE001
            print(f"④ [warn] 橫幅上傳失敗:{str(exc)[:120]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
