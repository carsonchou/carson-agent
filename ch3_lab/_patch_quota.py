# -*- coding: utf-8 -*-
"""把 quota.DAILY 從寫死的 10,000 改成有證據的值,並讓它自己發現真上限。

## 為什麼 10,000 是錯的
`DAILY = 10000` 是 Google 專案的**預設值**,不是這個專案的實際值,而且
程式裡沒有任何地方引用證據。兩條獨立實測都推翻它:

1. **ch3 自己**:配額日 2026-08-28(台北 08-28 16:00 → 08-29 16:00)
   實際發布 **1 長 + 12 短 = 20,935 單位**。那些片現在都還在線上。
2. memory `yt-quota-budget-2026-07`:2026-07-30 主頻道那條線實測
   「10k/5 支是天花板」被推翻,**實際 ≥18,000**。

也就是說我一直在跟 Carson 講的「一天最多 6 支」,是**我們自己設的預算**
造成的,不是 API 的限制。而這條線的瓶頸從來就不是配額
(memory 原話:「真瓶頸是可發庫存不是配額」)。

## 為什麼不直接設 20,935
那是**觀測到的下界**,不是上限 —— 真值可能更高,也可能那天剛好沒有別的
東西在花。設成觀測值等於把「至少這麼多」當成「就是這麼多」,而超額那一刻
是在最後一支的 1,600 已經燒掉之後。

所以:**上限用保守值,真上限讓它自己量。**
- `DAILY = 18000`:兩條證據的交集裡較小的那個。
- 真的吃到 `quotaExceeded` 時呼叫 `note_exhausted()`,把「今天花到 N 就
  被擋」記進帳本。那是**觀測**,下次就有真數字可用。

⚠️ 這不是把守門放寬 —— 記帳、逐支檢查、預留額度全部保留。改的只是那個
   從來沒有人驗證過的分母。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "quota.py"

OLD = "DAILY = 10000"
NEW = '''#: 每日配額上限。**這個數字是量出來的,不是預設值。**
#: 🔴 舊版寫死 10,000(Google 專案的預設值),而兩條獨立實測都推翻它:
#:    · ch3 自己:配額日 2026-08-28 實際發了 1 長 + 12 短 = **20,935 單位**
#:      (台北 08-28 16:25 ~ 08-29 03:05,那些片現在都還在線上)
#:    · memory yt-quota-budget-2026-07:2026-07-30 主頻道實測 **≥18,000**
#:    於是「一天最多 6 支」這個我一直拿來做決定的數字,其實是**我們自己
#:    設的預算**造成的,不是 API 的限制。而 memory 的原話是
#:    「真瓶頸是可發庫存不是配額」。
#: ⚠️ 不設成觀測到的 20,935 —— 那是**下界**不是上限,而且那天可能剛好
#:    沒有別的東西在花。取兩條證據裡較小的 18,000,保守方向。
#:    真上限讓 `note_exhausted()` 去量。
DAILY = 18000'''

TAIL = '''

def note_exhausted(label=""):
    """真的吃到 quotaExceeded 時記一筆。**這是唯一能量到真上限的方法。**

    寫死一個 DAILY 只能猜;被 API 擋下來的那一刻,今天到底花了多少是
    **觀測值**。記進帳本,下次就有真數字可以校準,而不是繼續猜。

    呼叫端:發布器 catch 到訊息含 "quota" 的例外時呼叫它,然後停。
    """
    st = _load()
    st["exhausted_at"] = st["spent"]
    st["exhausted_label"] = label
    st.setdefault("history", []).append(
        {"day": st["day"], "spent": st["spent"], "what": label})
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(STATE)
    print(f"  📏 配額在花掉 {st['spent']:,} 之後被擋 —— 已記進帳本。"
          f"目前 DAILY 設 {DAILY:,},下次可以照這個實測值校準。")
'''


def main():
    s = P.read_text(encoding="utf-8")
    if "note_exhausted" in s:
        print("已經打過了"); return 0
    assert OLD in s, "找不到 DAILY"
    s = s.replace(OLD, NEW, 1) + TAIL
    P.write_text(s, encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("quota.py 已改,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
