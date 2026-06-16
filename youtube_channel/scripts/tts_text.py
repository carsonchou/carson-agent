# -*- coding: utf-8 -*-
"""tts_text.py — 配音前把旁白正規化成「TTS 念得順、念得對」的文字。

修三類常見壞點：
  1) 數字/百分比/小數：8.3% → 百分之八點三、1.2%到1.8% → 百分之一點二到百分之一點八、
     0.1% → 百分之零點一、6.5萬 → 六點五萬（避免 TTS 念錯小數與 % 符號）
  2) 符號：$ → 美元、~ → 約、× → 乘、＋/+ 在數字前 → 正、英文逗號→中文逗號
  3) 斷點：—— … ： 等轉成自然停頓；超長句（>40字無句號）補逗號，避免一口氣念到斷。
tts_minimax / tts_edge 配音前都會先套 normalize()。
"""
from __future__ import annotations
import re

_DIG = "零一二三四五六七八九"


def _int_zh(n: int) -> str:
    if n == 0:
        return "零"
    units = ["", "十", "百", "千"]
    big = ["", "萬", "億"]
    s = str(n)
    # 分成每 4 位一組
    groups = []
    while s:
        groups.append(s[-4:]); s = s[:-4]
    out = ""
    for gi in range(len(groups) - 1, -1, -1):
        g = int(groups[gi])
        if g == 0:
            continue
        gs = ""
        gstr = str(g).zfill(4)
        started = False
        for i, ch in enumerate(gstr):
            d = int(ch)
            pos = 3 - i
            if d == 0:
                if started and not gs.endswith("零"):
                    gs += "零"
            else:
                gs += _DIG[d] + units[pos]
                started = True
        gs = gs.rstrip("零")
        out += gs + big[gi]
    out = out.strip("零") or "零"
    # 「一十」開頭口語化成「十」（十二 而非 一十二）
    out = re.sub(r"^一十", "十", out)
    return out


def _num_zh(tok: str) -> str:
    """把 '8.3' / '20' / '1000' 轉中文念法（小數逐位、整數正常）。"""
    if "." in tok:
        a, b = tok.split(".", 1)
        ai = _int_zh(int(a)) if a not in ("", "0") else "零"
        bz = "".join(_DIG[int(c)] for c in b if c.isdigit())
        return f"{ai}點{bz}"
    try:
        return _int_zh(int(tok))
    except Exception:
        return tok


def normalize(text: str) -> str:
    t = text.strip()
    # 範圍百分比：A%到B% / A%~B%
    t = re.sub(r"(\d+(?:\.\d+)?)%\s*([到~至])\s*(\d+(?:\.\d+)?)%",
               lambda m: f"百分之{_num_zh(m.group(1))}{m.group(2).replace('~','到')}百分之{_num_zh(m.group(3))}", t)
    # 單一百分比
    t = re.sub(r"(\d+(?:\.\d+)?)%", lambda m: f"百分之{_num_zh(m.group(1))}", t)
    # 金額 $1000 / US$24
    t = re.sub(r"(?:US)?\$\s*(\d+(?:\.\d+)?)", lambda m: f"{_num_zh(m.group(1))}美元", t)
    # 帶單位的小數（含萬/倍/年/天/支/筆…）→ 念中文，避免小數點被吃
    t = re.sub(r"(\d+\.\d+)(?=[萬億倍年天月週支筆檔次%元])?", lambda m: _num_zh(m.group(1)), t)
    # 正負號在數字前
    t = re.sub(r"[+＋](?=\d|百分之)", "正", t)
    t = re.sub(r"(?<![\d.])[-－](?=\d|百分之)", "負", t)
    # 符號
    t = t.replace("~", "約").replace("×", "乘").replace("&", "和")
    # 斷點：破折號/冒號/刪節號 → 自然停頓
    t = t.replace("——", "，").replace("—", "，").replace("…", "。").replace("⋯", "。")
    t = re.sub(r"[：:]", "，", t)
    t = t.replace("（", "，").replace("）", "，").replace("(", "，").replace(")", "，")
    t = t.replace(",", "，")
    # 清掉多餘逗號/句號
    t = re.sub(r"，{2,}", "，", t)
    t = re.sub(r"，(。)", r"\1", t)
    t = re.sub(r"。{2,}", "。", t)
    # 超長句補停頓：連續 >38 字沒有句末標點，找最後一個逗號斷不到就硬插
    out, run = [], 0
    for ch in t:
        out.append(ch)
        if ch in "。！？!?":
            run = 0
        elif ch == "，":
            run = 0
        else:
            run += 1
            if run >= 42:
                out.append("，"); run = 0
    return "".join(out).strip("，")
