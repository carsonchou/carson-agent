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


CHANNEL_ID = "UCqP5JQXlQR5ZDLtEiBt4kLA"


def main() -> int:
    import daily_publish as dp
    yt = dp.get_service()
    r = yt.commentThreads().list(
        part="snippet,replies", allThreadsRelatedToChannelId=CHANNEL_ID,
        maxResults=100, order="time").execute()
    # 去重(2026-08-22 審核指出):無狀態檔會讓同批未回覆留言每天重複推播,
    # 疲勞轟炸的下場是通知被忽略。已推播過的 thread id 記檔,只推新出現的。
    import json as _json
    _sf = ROOT / "STUDIO" / "comment_watchdog_seen.json"
    _seen = set(_json.loads(_sf.read_text(encoding="utf-8"))) if _sf.exists() else set()
    pending = []
    _new_ids = []
    # 自家身分判定(2026-08-22 審核指出 displayName 太脆):顯示名稱隨時可改,
    # 改了就會把自己的回覆當成觀眾留言、或反過來把某個名字含「量化阿森」的觀眾
    # 誤判成自己而永遠不提醒。改用 channelId 這個不會變的識別;
    # displayName 只留作 fallback(萬一 API 沒回 authorChannelId)。
    def _is_self(sn):
        cid = ((sn.get("authorChannelId") or {}).get("value") or "")
        if cid:
            return cid == CHANNEL_ID
        au = sn.get("authorDisplayName", "")
        return "CarsonQuant" in au or "量化阿森" in au

    for it in r.get("items", []):
        top = it["snippet"]["topLevelComment"]["snippet"]
        au = top.get("authorDisplayName", "")
        if _is_self(top):
            continue
        if any(_is_self(x["snippet"])
               for x in (it.get("replies", {}).get("comments") or [])):
            continue
        _tid = it["snippet"]["topLevelComment"]["id"]
        if _tid not in _seen:
            _new_ids.append(_tid)
        pending.append((top.get("publishedAt", "")[:16], au,
                        (top.get("textDisplay") or "").replace("<br>", " ")[:60], _tid))
    if not pending:
        print("✅ 沒有未回覆的觀眾留言")
        return 0
    # 去重的語意要小心:單純「推過就不再推」會讓**一直沒人回的那則**從此消失——
    # 那正是 Carson 這次親自抓到的原況(擱置 23 小時、系統毫無知覺)。
    # 定案:**有新的才推播**(不疲勞轟炸),但推播內容列出**全部**未回覆的,
    # 舊的標「⏳」。這樣既不天天吵,積欠的也不會被靜音。
    print(f"🔴 未回覆觀眾留言 {len(pending)} 則(其中 {len(_new_ids)} 則是新的):")
    for t, au, tx, tid in pending:
        print(f"   {'🆕' if tid in _new_ids else '⏳'} {t}  {au[:14]}  {tx}")
    if _new_ids:
        try:
            import notify
            body = "\n".join(f"{'🆕' if tid in _new_ids else '⏳'}{au}: {tx}"
                             for _, au, tx, tid in pending[:6])
            notify.push(f"有 {len(pending)} 則觀眾留言沒回"
                        f"({len(_new_ids)} 新)", body, tag="speech_balloon")
        except Exception:  # noqa: BLE001
            pass
    else:
        print("   (沒有新的,不推播;上面的仍待回)")
    _seen.update(_new_ids)
    _sf.write_text(_json.dumps(sorted(_seen)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
