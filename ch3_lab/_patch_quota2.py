# -*- coding: utf-8 -*-
"""把配額上限改成**唯一直接量到的那個數**,並且真的把量測接起來。

## 獨立驗證推翻的
我原本給了兩條證據,驗證把它們拆開了:

- **證據 2 是錯的專案。** memory `yt-quota-budget-2026-07` 的「實測
  ≥18,000」量的是 `524513894332`(主頻道)。ch3 跑在 `881902283633`
  (quiet-hour-yt),08-20 才切過去,而卡在 Carson 手上的提額稽核表
  寫的 Project Number 是 524513894332 —— **quiet-hour-yt 從來沒有送過
  提額申請**。這條證據不能用,而且它的反面有具體理由。
- **證據 1 推翻不了。** 驗證用四條路線攻(分箱邊界 15:00 vs 16:00、
  publishedAt 是不是排程發布、當天有沒有換專案、有沒有第四支腳本),
  全部失敗。配額日 2026-08-28 確實有 **13 次 videos.insert**
  (組成是 1 長 + 1 合輯 + 11 短,不是我說的 1 長 + 12 短)。

## 所以 18,000 是最差的選擇
13 × 1600 = **20,800 > 18,000**。18,000 大到會授權超過真上限的花費
(如果 10,000 才是對的),又小到**重現不了它自己引用的那個觀測**
(RESERVE 之後只夠 11 支,而那天做了 13 支)。

改成 **20,800** —— 那是這個專案**唯一一個直接量到的數字**,而且明確是
下界不是上限。若真上限其實更低,下一次 403 會免費地、大聲地告訴我們,
而 `note_exhausted()` 會把它記下來。

## 這次才真的把量測接起來
上一版加了 `note_exhausted()` 卻**一個呼叫端都沒有**,而三支發布器對
`videos.insert` 完全沒有 try/except —— 403 直接往上炸,那個「唯一能量到
真上限的方法」永遠不會執行。同一輪裡我自己犯了「寫了檢查沒接上」。

另外:`_load()` 跨日回傳全新 dict,`history` 每天被清空。量到的東西
活不過換日 = 等於沒量。改成跨日保留 `history`。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent

Q_OLD = "DAILY = 18000"
Q_NEW = "DAILY = 20800"

Q_DOC_OLD = """#: ⚠️ 不設成觀測到的 20,935 —— 那是**下界**不是上限,而且那天可能剛好
#:    沒有別的東西在花。取兩條證據裡較小的 18,000,保守方向。
#:    真上限讓 `note_exhausted()` 去量。"""
Q_DOC_NEW = """#: ⚠️ 獨立驗證推翻了上面第二條:memory 那個 ≥18,000 量的是**主頻道的
#:    專案**(524513894332),而 ch3 跑在 881902283633,08-20 才切過去、
#:    從來沒送過提額申請。所以只剩證據 1。
#: 🔴 而 18,000 是三個選項裡最差的:13×1600 = 20,800 > 18,000,
#:    它**重現不了它自己引用的那個觀測**。改成 20,800 ——
#:    這是這個專案唯一直接量到的數字,而且明確是**下界**。
#:    真上限如果更低,下一次 403 會免費地、大聲地告訴我們。"""

ROLL_OLD = '''    if st.get("day") != _day():
        return {"day": _day(), "spent": 0, "items": []}
    return st'''
ROLL_NEW = '''    if st.get("day") != _day():
        # 🔴 **`history` 要跨日保留。** 舊版換日回傳全新 dict,於是
        #    `note_exhausted()` 辛苦記下來的觀測值下一次 `spend()` 就被
        #    寫掉了 —— 量到的東西活不過換日,等於沒量。
        return {"day": _day(), "spent": 0, "items": [],
                "history": st.get("history", [])}
    return st'''

#: 三支發布器的 insert 都要包起來。**現在一支都沒接。**
INS_SHORTS_OLD = '''        vid = insert_one(yt, o, p)'''
INS_SHORTS_NEW = '''        # 🔴 insert 外面**必須有 try/except**。舊版 403 直接往上炸:
        #    後面的片不會試、`note_exhausted()` 不會執行、
        #    「發了幾支、為什麼停」完全沒有紀錄。
        #    而配額被擋是這條線的常態,不是理論風險。
        try:
            vid = insert_one(yt, o, p)
        except Exception as e:                                # noqa: BLE001
            if "quota" in str(e).lower():
                quota.note_exhausted(f"shorts insert {o['key']}")
                print(f"  ⛔ 配額被 API 擋下,停在 {o['key']}")
                break
            print(f"  ⛔ {o['key']} 上傳失敗:{str(e)[:80]}")
            continue'''


def main():
    q = HERE / "quota.py"
    s = q.read_text(encoding="utf-8")
    if Q_OLD in s:
        s = s.replace(Q_OLD, Q_NEW, 1)
        s = s.replace(Q_DOC_OLD, Q_DOC_NEW, 1)
        print("DAILY 18000 → 20800")
    if ROLL_OLD in s:
        s = s.replace(ROLL_OLD, ROLL_NEW, 1)
        print("history 已改成跨日保留")
    q.write_text(s, encoding="utf-8")

    p = HERE / "publish_shorts.py"
    t = p.read_text(encoding="utf-8")
    if "note_exhausted" not in t:
        assert INS_SHORTS_OLD in t, "找不到 publish_shorts 的 insert"
        t = t.replace(INS_SHORTS_OLD, INS_SHORTS_NEW, 1)
        p.write_text(t, encoding="utf-8")
        print("publish_shorts 已接上 note_exhausted")

    import py_compile
    for f in (q, p):
        py_compile.compile(str(f), doraise=True)
    print("語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
