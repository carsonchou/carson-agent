# -*- coding: utf-8 -*-
"""步驟 1 的陽性對照 —— 證明 check_step1 的兩格斷言「會叫」,不是對什麼都說 PASS。

作法:讀正式碼原始碼 → 字串替換造出兩個**刻意壞掉**的版本 → exec 進獨立 namespace
(__file__ 仍指向正式碼路徑,所以事實庫還是讀得到;全程唯讀,不碰正式碼檔案)
→ 拿同一組斷言跑它們,要求各自 FAIL。

  對照 A:把 xlim 改回舊公式 lo=min(p25,cur)*0.85 / hi=max(p75,cur)*1.12 → [A] 必須 FAIL
  對照 B:把標籤的 ha 換邊改回固定 ha="center"                          → [B] 必須 FAIL
  陰性對照:正式碼本身必須 PASS(否則上面兩個 FAIL 可能只是環境壞了)

用法: <venv>/python.exe poscontrol_step1.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(r"D:\carson-agent\youtube_channel\scripts\concept_visuals.py")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SRC.parent))

import check_step1_valuation as chk  # noqa: E402

BREAKS = {
    "A": ("""    _box = max(p75 - p25, 1.0)
    pad = _box * 0.35
    lo, hi = max(p25 - pad, 0.0), p75 + pad""",
          """    pad = 1.0
    lo, hi = min(p25, cur) * 0.85, max(p75, cur) * 1.12"""),
    "B": ("""        _ha = "center" if not off_scale else ("right" if cur > hi else "left")
        _dx = 0 if _ha == "center" else (-14 if _ha == "right" else 14)""",
          """        _ha = "center"
        _dx = 0"""),
}


def load_broken(tag):
    src = SRC.read_text(encoding="utf-8")
    old, new = BREAKS[tag]
    assert src.count(old) == 1, f"對照 {tag} 的目標字串在正式碼出現 {src.count(old)} 次(應為 1),程式碼已漂移"
    mod = types.ModuleType(f"cvis_broken_{tag}")
    mod.__file__ = str(SRC)          # 事實庫是相對 __file__ 定位的,保持指向正式路徑(唯讀)
    exec(compile(src.replace(old, new), str(SRC), "exec"), mod.__dict__)
    return mod


def run(tag, fn):
    mod, real = load_broken(tag), chk.cvis
    chk.cvis = mod
    try:
        fn()
    except AssertionError as e:
        print(f"[對照{tag}] PASS — 壞版本如預期被擋下:{str(e)[:120]}")
        return True
    finally:
        chk.cvis = real
    print(f"[對照{tag}] FAIL — 壞版本竟然通過了斷言,這格檢查是空砲")
    return False


if __name__ == "__main__":
    ok = run("A", chk.check_a_population)
    ok = run("B", chk.check_b_no_text_clipped) and ok
    chk.check_a_population()
    chk.check_b_no_text_clipped()
    print("陰性對照 PASS — 正式碼本身通過同一組斷言")
    print("步驟 1 陽性對照" + ("全部通過" if ok else "有失敗"))
    sys.exit(0 if ok else 1)
