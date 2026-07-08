#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性:套用 3 支已獨立驗證的 A/B 標題(2026-07-04 因配額卡住的)。
配額重置後(台灣~15:00)自動跑;直接改 title、存舊標可還原;全套成功就自刪自己的 cron 行。"""
import sys, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import daily_publish as dp

TARGETS = {
    "kisa4xcy46o": "勝率87%照樣賠？一個公式揪出你的網格為什麼越跑越虧 #Shorts",
    "cSTlz7gg-AY": "新手先別急著設停利！我回測10年數據，8%和12%的結局讓你意外",
    "UbGetd1yvjk": "新手別被90%勝率騙了！網格機器人真實下場，破產機率一秒算給你看 #Shorts",
    # 誠信重整:2 支舊片假真錢标题 → 回測(去掉「真金白銀真錢」假稱)
    "zf2obEQaGsc": "我回測『丟十萬給網格機器人』跑30天，連手續費都算給你看——結果剩多少？ #Shorts",
    "ijCNjwEDRnc": "我不敢拿真錢賭機器人，所以我用回測把它往死裡測｜避雷企劃EP.0",
}
RESTORE = ROOT / "STUDIO" / "ab_title_manual_restore.json"


def main():
    restore = json.loads(RESTORE.read_text("utf-8")) if RESTORE.exists() else {}
    yt = dp.get_service()
    done = 0
    for vid, newt in TARGETS.items():
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            if not r.get("items"):
                print(f"[pending-title] 找不到 {vid}"); continue
            sn = r["items"][0]["snippet"]
            if sn.get("title") == newt:
                print(f"[pending-title] 已是新標題 {vid}"); done += 1; continue
            restore.setdefault(vid, sn.get("title", ""))  # 存舊標題,可還原
            sn["title"] = newt
            yt.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            print(f"[pending-title] ✅ 套用 {vid} → {newt[:30]}")
            done += 1
        except Exception as e:  # noqa: BLE001
            s = str(e)
            if "quota" in s.lower():
                print(f"[pending-title] 配額未回,{vid} 稍後再試")
            else:
                print(f"[pending-title] 錯誤 {vid}: {s[:120]}")
    RESTORE.write_text(json.dumps(restore, ensure_ascii=False, indent=2), "utf-8")
    if done == len(TARGETS):  # 全部到位→自刪 cron 行
        ct = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        new = "\n".join(l for l in ct.splitlines() if "_apply_pending_titles" not in l) + "\n"
        subprocess.run(["crontab", "-"], input=new, text=True)
        print("[pending-title] 全部套完,已自刪 cron。舊標題存於 ab_title_manual_restore.json 可還原。")


if __name__ == "__main__":
    main()
