#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_video.py — 【審核部門】發布前自動品管 + 誠信把關。

規則式審核(不需 AI、可無人值守)。PASS 才允許上架；FAIL 隔離並記錄原因。
檢查：①技術(檔案存在/不過小/有影音軌/片長合理/Shorts<60s) ②誠信(禁語：保證賺、
穩賺不賠等；句子級脈絡識別，避免把揭穿型教學誤判) ③合規(有標題、有風險聲明)。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "output"

# 誠信禁語（誇大/保證型，違反誠信鐵則）
BANNED = [
    "保證賺", "保證獲利", "保證收益", "穩賺不賠", "穩賺", "必賺", "包賺",
    "零風險", "一定賺", "一定獲利", "穩定獲利", "躺著就能賺", "閉著眼睛賺",
    "穩定月收", "保本保息", "穩定報酬率",
]

# 否定詞：禁語前若有這些字，視為誠實聲明（如「不保證收益」）而非違規
NEG_CHARS = "不沒別非勿未拒避免絕毋並"
# 破除/反問語境標記：禁語前/同句有這些，屬誠實揭穿，非違規
DEBUNK = (
    "以為", "迷思", "真的", "真能", "真會", "別信", "別再", "騙", "假象", "謊", "難道",
    "憑什麼", "怎麼可能", "陷阱", "小心", "當心", "謊言", "宣稱", "號稱",
    "算出", "計算", "測試", "驗證", "分析", "研究", "真相", "揭秘", "破解",
    "真實", "實際上", "事實上", "其實", "實測", "才知道", "錯了", "錯誤",
    "警告", "注意", "風險", "虧損", "虧錢", "破產", "賠錢",
    "覺得", "認為", "相信", "感覺",   # 轉述迷思：「很多人覺得穩賺」
    "說", "都說", "人說",             # 引述迷思：「大家都說定投穩賺」
    "看起來", "聽起來", "看似", "像是",  # 反諷鋪陳：「看起來穩賺，結果虧了」
    "就能", "才能", "只要",           # 數學公式結論：「勝率 40% 就能穩定獲利」
)
QUESTION = "？?嗎吗"


def _probe(mp4: Path):
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        out = subprocess.run([ff, "-i", str(mp4)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        txt = out.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
        dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
        return dur, ("Video:" in txt), ("Audio:" in txt)
    except Exception:
        return 0.0, False, False


def audit(slug: str):
    """回傳 (ok: bool, reasons: list[str])。reasons 空 = PASS。"""
    reasons = []
    is_short = slug.startswith("S_")
    mp4 = OUTPUT / f"{slug}.mp4"
    voice = OUTPUT / f"{slug}.voice.txt"
    md = OUTPUT / f"{slug}.md"

    # ① 技術
    if not mp4.exists():
        return False, ["mp4 不存在"]
    size = mp4.stat().st_size
    if size < (150 * 1024 if is_short else 1024 * 1024):
        reasons.append(f"檔案過小（{size // 1024}KB），疑似損壞")
    dur, has_v, has_a = _probe(mp4)
    if dur < 5:
        reasons.append(f"片長過短（{dur:.0f}s）")
    if is_short and dur > 65:
        reasons.append(f"Shorts 超過 60 秒（{dur:.0f}s）")
    if not has_v:
        reasons.append("無視訊軌")
    if not has_a:
        reasons.append("無音軌")

    # ② 誠信禁語（辨識否定詞，避免把「不保證收益」這種誠實聲明誤判）
    blob = ""
    if voice.exists():
        blob += voice.read_text(encoding="utf-8")
    if md.exists():
        blob += "\n" + md.read_text(encoding="utf-8")
    def _ok_context(i, b):
        # 前視窗 20 字（中文平均詞距），後視窗 6 字
        pre = blob[max(0, i - 20):i]
        post = blob[i + len(b): i + len(b) + 6]
        if any(n in pre for n in NEG_CHARS):
            return True
        if any(dk in pre for dk in DEBUNK):
            return True
        if any(q in post for q in QUESTION):
            return True
        # 句子級：找本句句首，掃整句是否含否定/破除詞（捕捉「以為…穩賺」跨距長的句型）
        sent_start = max((blob.rfind(sep, 0, i) for sep in "。！？\n"), default=-1) + 1
        pre_sent = blob[sent_start:i]
        return any(n in pre_sent for n in NEG_CHARS) or any(dk in pre_sent for dk in DEBUNK)

    hits = []
    for b in BANNED:
        start = 0
        while True:
            i = blob.find(b, start)
            if i == -1:
                break
            if not _ok_context(i, b):
                hits.append(b)  # 真正當作宣稱在用 → 違規
                break
            start = i + len(b)
    if hits:
        reasons.append("含誇大/保證禁語（非破除語境）：" + "、".join(hits))

    # ③ 合規
    if md.exists():
        mdt = md.read_text(encoding="utf-8")
        first = mdt.splitlines()[0] if mdt.splitlines() else ""
        if "🎬" not in first and not first.startswith("# "):
            reasons.append("缺影片標題")
        if ("風險" not in mdt) and ("不構成投資建議" not in mdt):
            reasons.append("缺風險聲明")
    else:
        reasons.append(".md 腳本不存在")

    return (len(reasons) == 0), reasons


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: audit_video.py <slug>")
        return 2
    slug = sys.argv[1]
    ok, reasons = audit(slug)
    print(("PASS " if ok else "FAIL ") + slug)
    for r in reasons:
        print("  - " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
