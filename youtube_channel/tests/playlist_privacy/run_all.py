#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_playlists privacyStatus 閘門的回歸套件 —— 再動那段 insert 迴圈之前先跑這支。

用法(任何目錄下都可以跑,cwd 由本支自己設):
    youtube_channel/.venv/Scripts/python.exe youtube_channel/tests/playlist_privacy/run_all.py

驗收三條(派工單原文):突變一條翻紅、陰性對照一條、離線重模擬 09-17 那一輪 5 支不在名單。
全部走 sim.py,跑的是 scripts/build_playlists.py 的**真程式碼**,不是抄本。

🔴 這支自己會不會叫:第 0 條先核突變錨點在原始碼裡恰好出現 1 次。錨點不見了(被改寫、
被搬走)就直接 FAIL —— 不然突變列會變成「改了個不存在的東西,原碼照跑,測試照綠」
(memory `verification-that-cannot-fail`)。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BASE / "scripts"))

from sim import SRC, simulate  # noqa: E402

# 09-17 22:00 那一輪(crontab.txt:423 `0 22 * * 4 ... --max 10`)當天會變 private 的 5 支。
TARGETS = ["I8F83sPFKWg", "tN56crKxwJE", "vwEaoo3Txjw", "UTuMMyvdQ5U", "DhX2uNzjZ-o"]
PRIVATE_5 = {v: "private" for v in TARGETS}

# 突變:把閘門條件改成恆真 = 「把 privacyStatus 檢查拿掉」。
ANCHOR = 'if privacy.get(vid) != "public":   # PRIVACY-GATE'
MUTANT = 'if False:   # PRIVACY-GATE(已突變)'

_p = _f = 0


def check(cond, msg, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"PASS  {msg}")
    else:
        _f += 1
        print(f"FAIL  {msg}" + (f"\n        {detail}" if detail else ""))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src = SRC.read_text(encoding="utf-8")

    # ---- ⓪ 儀器自檢:突變錨點存在且唯一 ----
    check(src.count(ANCHOR) == 1,
          "⓪ 突變錨點在 build_playlists.py 恰好 1 次",
          f"實際出現 {src.count(ANCHOR)} 次;錨點被改掉就等於突變列失效,先修這裡再談其他條")
    if src.count(ANCHOR) != 1:
        print("\n錨點不在,後面每一條都證明不了東西,直接停。")
        return 1

    # ---- ① 離線重模擬 09-17 22:00 那一輪:5 支不在 insert 名單 ----
    r = simulate(privacy=PRIVATE_5, max_add=10)
    ins = r["inserted"]
    hit = [v for v in TARGETS if v in ins]
    check(r["rc"] == 0, "① 重模擬跑完 rc == 0", f"rc={r['rc']}  stderr尾={r['stderr'][-300:]}")
    check(not hit, "① 09-17 那一輪 insert 名單不含那 5 支",
          f"仍被插進去:{hit}\n        本輪 insert 名單:{ins}")
    check(all(f"[skip]" in r["stderr"] and v in r["stderr"] for v in TARGETS),
          "① 5 支各有一行 [skip] 記錄", r["stderr"][:600])

    # ---- ② 陰性對照:public 的片照常加入 ----
    check(len(ins) == 10, "② 陰性對照:額度仍用滿 10 支(跳過的不佔額度)",
          f"實際插了 {len(ins)} 支:{ins}")
    check(all(v not in TARGETS for v in ins) and len(set(ins)) == len(ins),
          "② 陰性對照:插進去的都是 public 且不重複", str(ins))
    r_allpub = simulate(privacy={}, max_add=10)
    check(set(TARGETS).issubset(set(r_allpub["inserted"])),
          "② 陰性對照(相反那一邊):5 支若仍是 public,閘門不會擋它們",
          f"全 public 時的名單:{r_allpub['inserted']}")

    # ---- ③ 突變:拿掉 privacyStatus 檢查 → ① 必須翻紅 ----
    r_mut = simulate(privacy=PRIVATE_5, max_add=10,
                     mutate=lambda s: s.replace(ANCHOR, MUTANT, 1))
    mut_hit = [v for v in TARGETS if v in r_mut["inserted"]]
    check(len(mut_hit) == 5,
          "③ 突變列:閘門條件改成恆真後,5 支全部被插回去(測試翻紅)",
          f"突變後只插回 {len(mut_hit)} 支:{mut_hit}\n        "
          f"沒有全翻紅 = 這條判準沒在看那段程式碼,閘門的因果宣稱不成立")

    # ---- ④ fail-closed:查不到狀態的 id 也要跳過 ----
    r_miss = simulate(privacy={v: None for v in TARGETS}, max_add=10)
    check(not [v for v in TARGETS if v in r_miss["inserted"]],
          "④ videos.list 沒回來的 id 當成「不是 public」跳過(失敗方向 = 不加入)",
          str(r_miss["inserted"]))

    # ---- ⑤ videos.list 用法:part=status、每批 ≤ 50 ----
    check(all(0 < len(c) <= 50 for c in r["videos_list_calls"]) and r["videos_list_calls"],
          "⑤ videos.list 每批 ≤ 50 個 id(1 unit/批)",
          str([len(c) for c in r["videos_list_calls"]]))
    check('part="status"' in src and "yt.videos().list(" in src,
          "⑤ 查的是 videos.list part=status")

    print(f"\n合計 PASS={_p} FAIL={_f}")
    return 0 if _f == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
