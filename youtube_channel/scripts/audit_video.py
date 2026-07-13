#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_video.py — 【審核部門】發布前自動品管 + 誠信把關。

規則式審核(不需 AI、可無人值守)。PASS 才允許上架；FAIL 隔離並記錄原因。
檢查：①技術(檔案存在/不過小/有影音軌/片長合理/Shorts<60s) ②誠信(禁語：保證賺、
穩賺不賠等) ③合規(有標題、有風險聲明)。
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
NEG_CHARS = "不沒別非勿未拒避免絕毋"
# 破除/反問語境標記：同一句內出現這些詞(如「打臉穩賺神話」「你以為網格穩賺?」)或緊接問號，
# 屬誠實破除，非違規。2026-07 修：舊版只看禁語前 8 字/後 2 字的窄窗，「打臉穩賺神話」這種
# 破除詞在禁語*前*超出窗口、或神話/騙局這類破除詞接在禁語*後*都會漏判，誤擋「拆穿穩賺神話」
# 這類避雷片標題——改成掃整句(標點斷句)才不漏。
DEBUNK = ("以為", "迷思", "真的", "真能", "真會", "別信", "別再", "騙", "假象", "謊",
          "難道", "憑什麼", "怎麼可能", "拆穿", "打臉", "揭穿", "神話", "騙局")
QUESTION = "？?嗎吗"
_SENT_SPLIT_RE = re.compile(r"[。！？!?\n]")


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
    mp3 = OUTPUT / f"{slug}.mp3"
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

    # ①b 旁白截斷檢查(P0 止血 2026-07-13)：發布前最後一道關卡，不論上游哪條渲染路徑/是否
    # 雲端 code drift 都在這裡兜底攔下——04_0056 事故(旁白218.9s/成品僅61.7s)當時完全沒有
    # 任何一道 gate 比對過 mp4 與旁白 mp3 的長度，結果直接發布到 YouTube。
    # ratio < 0.9 = 疑似截斷(旁白沒剪完就發布)；fail-closed，不放行。
    if mp3.exists() and dur > 0:
        adur, _, _ = _probe(mp3)
        if adur > 0:
            ratio = dur / adur
            if ratio < 0.9:
                reasons.append(f"旁白疑似截斷（成品{dur:.1f}s / 旁白{adur:.1f}s，比值{ratio:.2f}<0.9）")

    # ② 誠信禁語（辨識否定詞，避免把「不保證收益」這種誠實聲明誤判）
    blob = ""
    if voice.exists():
        blob += voice.read_text(encoding="utf-8")
    if md.exists():
        blob += "\n" + md.read_text(encoding="utf-8")
    def _ok_context(i, b):
        pre = blob[max(0, i - 8):i]
        post = blob[i + len(b): i + len(b) + 2]
        if any(n in pre for n in NEG_CHARS):       # 不/沒保證…
            return True
        if any(q in post for q in QUESTION):       # 穩賺？ 反問
            return True
        # 破除詞不侷限窄窗，掃「同句」(標點斷句)——「打臉穩賺神話」的「打臉」「神話」
        # 才抓得到；同句沒有真宣稱在用才擋（「跟著我穩賺」這種仍會擋）
        left = 0
        for m in _SENT_SPLIT_RE.finditer(blob[:i]):
            left = m.end()
        right_m = _SENT_SPLIT_RE.search(blob, i + len(b))
        right = right_m.start() if right_m else len(blob)
        sentence = blob[left:right]
        if any(dk in sentence for dk in DEBUNK):   # 打臉/拆穿/揭穿/神話/騙局/你以為/迷思…
            return True
        return False

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
