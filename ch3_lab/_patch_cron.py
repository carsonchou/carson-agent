# -*- coding: utf-8 -*-
"""把 ch3 的發布節奏改成 6 個時段 × (1 長 + 1 短)。

## Carson 2026-08-30 拍板的三件事
1. 一天 6 長 + 6 短(「不要管配額」)
2. **一次只發 2 支**,分多個時段
3. 掃完剩下的候選(已做:33/44 通過)

## 為什麼一次 2 支
實測(n=19 支 Short、6 個批次),每支每 24 小時觀看的中位數:

    一批 2 支 →  9.7
    一批 3 支 →  5.6
    一批 4 支 →  2.7
    一批 5 支 →  0.0

四個層級單調遞減。⚠️ **批次大小跟時段完全糾纏** —— 那批 5 支發在凌晨
03:03,同時是最大批和最爛時段,所以不能說是批次造成的。但這是目前最強
的訊號,而固定成「每批 2 支、時段固定」之後,下一週的資料就能把兩者分開。

## 為什麼每個時段是 1 長 + 1 短
長片實測 12/14 零觀看、每 24h 中位 0.00;Shorts 中位 3.15。Carson 選擇
兩者都發 6 支,所以配成對:每個時段送一支長一支短,兩種格式拿到完全
一樣的時段分布 —— 這樣「長片沒人看」到底是格式問題還是時段問題,
下週分得出來。上一版兩者的時段分布不同,那個比較本來就不乾淨。

## 配額
每個時段 1,663 + 1,606 = 3,269,六個時段 = **19,614**。
`quota.DAILY` 現在是 20,800(觀測下界),預留 300 → 可用 20,500。
今天實測單一配額日花掉 19,802 沒有被擋,所以 19,614 在已證實的範圍內。
真的撞到上限時 `note_exhausted()` 會記下來並乾淨停住。

## 時段
每 3 小時一次:08:25 / 11:25 / 14:25 / 17:25 / 20:25 / 23:25(台北)。
配額日在台北 15:00~16:00 換,所以 17:25 之後那三個時段屬於新的配額日、
前三個屬於舊的 —— 六個時段剛好落在同一個配額日的兩端,每個配額日
仍然是 6 個時段。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CRON = pathlib.Path(r"D:\carson-agent\youtube_channel\deploy\crontab.txt")

OLD = """25 16 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 2 >> /root/yt/logs/cron.log 2>&1
25 22 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 0 --shorts 3 >> /root/yt/logs/cron.log 2>&1"""

NEW = """# 2026-08-30 改:一天 12 支(6 長 + 6 短),**一次只發 2 支**,分六個時段。
# 依據(實測 n=19 支 Short、6 個批次,每支每 24 小時觀看中位數):
#     一批 2 支 →  9.7      一批 4 支 →  2.7
#     一批 3 支 →  5.6      一批 5 支 →  0.0
# 四個層級單調遞減。⚠️ 批次大小跟時段**完全糾纏**(那批 5 支發在凌晨
# 03:03,同時是最大批和最爛時段),所以不能斷言是批次造成的 —— 但固定成
# 「每批 2 支、時段固定」之後,下週的資料就能把兩者分開。
# 每個時段刻意是 **1 長 + 1 短**:長片實測 12/14 零觀看、每 24h 中位 0.00,
# 而 Shorts 是 3.15。兩者配成對送出 → 拿到完全一樣的時段分布,下週才分得出
# 「長片沒人看」是格式問題還是時段問題。上一版兩者時段不同,比較不乾淨。
# 配額:每時段 1,663 + 1,606 = 3,269,六次 = 19,614;可用 20,500
#       (quota.DAILY 20,800 − 預留 300)。08-30 實測單日花 19,802 未被擋。
25 8 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> /root/yt/logs/cron.log 2>&1
25 11 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> /root/yt/logs/cron.log 2>&1
25 14 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> /root/yt/logs/cron.log 2>&1
25 17 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> /root/yt/logs/cron.log 2>&1
25 20 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> /root/yt/logs/cron.log 2>&1
25 23 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> /root/yt/logs/cron.log 2>&1"""


def main():
    s = CRON.read_text(encoding="utf-8")
    if "--limit 1 --shorts 1" in s:
        print("已經改過了"); return 0
    if OLD not in s:
        print("⛔ 找不到舊的兩行 ch3 排程,沒有改動"); return 1
    CRON.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
    n = sum(1 for ln in CRON.read_text(encoding="utf-8").splitlines()
            if "ch3_publish.py" in ln and not ln.strip().startswith("#"))
    print(f"crontab 已改:ch3 發布時段 {n} 個(每個 1 長 + 1 短)")
    return 0 if n == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
