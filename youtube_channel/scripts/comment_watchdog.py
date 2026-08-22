#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comment_watchdog.py — 未回覆留言偵測:有真觀眾留言沒人回就推播提醒。

## 為什麼(2026-08-22)
Carson 親自發現「留言沒有回」——兩則好問題(大空頭/新唐)分別擱置 23 小時與 8 分鐘,
而系統毫無知覺。comment_dept 的設計是「只草擬不自動回」(誠信考量,對),
但草擬完沒人看就等於沒有;真問題型留言需要帶數據的真回答,模板回不了。
本支只做偵測與告警:未回覆的真觀眾留言 >0 → ntfy 推播(給 Carson 或下個 session 處理)。
不自動回——亂承諾的風險大於晚回的成本。

## 判定
commentThreads(order=time, 近 100 則)裡:非自己帳號發的頂層留言,
且 replies 裡沒有自己帳號 = 未回覆。配額:1~2 units,幾乎免費。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def main() -> int:
    import daily_publish as dp
    yt = dp.get_service()
    r = yt.commentThreads().list(
        part="snippet,replies", allThreadsRelatedToChannelId="UCqP5JQXlQR5ZDLtEiBt4kLA",
        maxResults=100, order="time").execute()
    # 去重(2026-08-22 審核指出):無狀態檔會讓同批未回覆留言每天重複推播,
    # 疲勞轟炸的下場是通知被忽略。已推播過的 thread id 記檔,只推新出現的。
    import json as _json
    _sf = ROOT / "STUDIO" / "comment_watchdog_seen.json"
    _seen = set(_json.loads(_sf.read_text(encoding="utf-8"))) if _sf.exists() else set()
    pending = []
    _new_ids = []
    for it in r.get("items", []):
        top = it["snippet"]["topLevelComment"]["snippet"]
        au = top.get("authorDisplayName", "")
        if "CarsonQuant" in au or "量化阿森" in au:
            continue
        reps = [x["snippet"].get("authorDisplayName", "")
                for x in (it.get("replies", {}).get("comments") or [])]
        if any("CarsonQuant" in a or "量化阿森" in a for a in reps):
            continue
        _tid = it["snippet"]["topLevelComment"]["id"]
        if _tid in _seen:
            continue
        _new_ids.append(_tid)
        pending.append((top.get("publishedAt", "")[:16], au,
                        (top.get("textDisplay") or "").replace("<br>", " ")[:60]))
    if not pending:
        print("✅ 沒有(新的)未回覆觀眾留言")
        return 0
    print(f"🔴 未回覆觀眾留言 {len(pending)} 則:")
    for t, au, tx in pending:
        print(f"   {t}  {au[:14]}  {tx}")
    try:
        import notify
        body = "\n".join(f"{au}: {tx}" for _, au, tx in pending[:5])
        notify.push(f"有 {len(pending)} 則觀眾留言沒回", body, tag="speech_balloon")
    except Exception:  # noqa: BLE001
        pass
    _seen.update(_new_ids)
    _sf.write_text(_json.dumps(sorted(_seen)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
