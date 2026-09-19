#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ch3_publish.py — 副頻道 They Ran It Again 的每日自動發布。

## 這是什麼
`ch3_lab/upload.py` 的排程包裝器。`local_cron` 只認 `youtube_channel/scripts/`
底下的腳本,所以放這裡;真正的閘門與上傳邏輯都在 ch3_lab 那支裡。

## 為什麼可以自動跑(這是對外發布,不能隨便自動化)
片子與文案是**先產好、先驗過**才進 `publish_meta.json` 的。這支只負責把
已通過的東西按配額分天送出,它自己不生成任何內容。而 upload.py 裡有三道
fail-closed 的閘門會在每次上傳前重跑:
1. **陳舊檢查**(preflight):mp4 必須比程式碼與資料新,否則中止
2. **語意閘門**:稿子講「效應存在/不存在」時 p 值必須撐得住
3. 頻道 ID 白名單 + 缺縮圖硬中止

任何一道擋下來,那一集就不會發,而且會印出理由。

## 配額
videos.insert 1600 + 縮圖 50 + 輪詢約 41 = 每支約 1,691。ch2 是獨立的 GCP
專案,一天 10,000 → **上限 5 支**。台北時間 15:00~16:00 重置,所以排 16:25。

用法(排程用):
  python scripts/ch3_publish.py            # 發 5 支
  python scripts/ch3_publish.py --dry-run  # 走完閘門但不上傳
"""
import argparse
import json
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent   # D:\carson-agent
CH3 = ROOT / "ch3_lab"
PY = ROOT / "youtube_channel" / ".venv" / "Scripts" / "python.exe"
# 🔴 配額要分流(2026-08-28)。Shorts 與長片**共用**同一個每日 10,000,
#    每支都是 1,600。舊版長片吃滿 5 支就沒額度給 Shorts 了。
#    現在:長片 3 支 + Shorts 2 支 ≈ 8,455 單位,留 1,500 給改標題與讀取。
#    分流的理由不是公平,是**兩條線做的事不一樣**:長片累積觀看時數
#    (YPP 只認長片),Shorts 負責把人帶進來。停掉任一條都會斷。
DAILY_LONG = 3
DAILY_SHORT = 2
DAILY = DAILY_LONG


def notify(msg):
    """發到 ntfy。沒設 topic 就是靜默 no-op —— 那個坑記憶裡有記,
    所以這裡明講:通知失敗不影響發布結果,只是我不會知道。"""
    try:
        sys.path.insert(0, str(ROOT / "youtube_channel" / "scripts"))
        import notify as n
        n.push("ch3 發布", msg)
    except Exception as e:                                   # noqa: BLE001
        print(f"  (通知沒送出:{str(e)[:50]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=DAILY)
    a = ap.parse_args()

    meta_p = CH3 / "publish_meta.json"
    led_p = CH3 / "uploaded.json"
    if not meta_p.exists():
        print("⛔ 沒有 publish_meta.json,先跑 ch3_lab/publish_meta.py")
        return 1
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    done = json.loads(led_p.read_text(encoding="utf-8")) if led_p.exists() else {}
    left = len(meta) - len(done)
    print(f"清單 {len(meta)} 集,已發 {len(done)},待發 {left}")
    if left <= 0:
        print("沒有待發的集數 —— 這條線發完了。")
        notify(f"ch3 已全部發完({len(done)} 支)")
        return 0

    cmd = [str(PY), str(CH3 / "upload.py"), "--limit", str(a.limit),
           "--privacy", "public"]
    if a.dry_run:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print(r.stdout[-4000:])
    if r.stderr.strip():
        print("--- stderr ---")
        print(r.stderr[-1500:])

    # Shorts:用剩下的額度。它跟長片是不同的產品,不是同一批的一部分。
    sp = CH3 / "publish_shorts.py"
    if sp.exists():
        print("\n── Shorts ──")
        scmd = [str(PY), str(sp), "--limit", str(DAILY_SHORT)]
        if a.dry_run:
            scmd.append("--dry-run")
        rs = subprocess.run(scmd, cwd=str(ROOT), capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        print(rs.stdout[-2500:])
        if rs.stderr.strip():
            print(rs.stderr[-800:])

    after = json.loads(led_p.read_text(encoding="utf-8")) if led_p.exists() else {}
    sent = len(after) - len(done)
    still = len(meta) - len(after)
    print(f"\n本次送出 {sent} 支,還剩 {still} 支")
    if not a.dry_run:
        notify(f"送出 {sent} 支,剩 {still} 支" if sent
               else f"⚠️ 一支都沒送出(閘門擋下或出錯),待發 {still} 支")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
