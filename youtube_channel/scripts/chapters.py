#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chapters.py — 從腳本 md + TTS 真實時間戳,機械產生 YouTube 章節時間戳。

## 為什麼(2026-08-17)
本頻道**搜尋是唯一還在成長的外部流量來源**(08-11→08-13 +42%:331→413→470),
而 Shorts feed 同期崩 -61%。搜尋詞 Top20 清一色是股票名——吃這個的正是個股體檢長片。
章節是還沒動過的搜尋槓桿,它一次給三件事:
  ① YouTube 會索引章節標題 → 多一批可被搜到的關鍵字(「最大回撤」「定期定額」等)
  ② 搜尋結果會顯示「影片中的關鍵時刻」,佔更大版位
  ③ 觀眾能跳到想看的段落 → 本來會關掉的人變成留下,直接打留存

## 為什麼不用 LLM
段落標題**腳本裡已經有**(`### 段落 N：標題`),時間軸 TTS 也已經產好(wordtimes)。
兩邊都是真的,對齊就好。用 LLM 反而引入編造風險,且每支多燒一次呼叫。

## 時間對齊
沿用 render_ffmpeg._narration_seg_starts 的同一套作法:拿每段旁白前 8 字去字幕句
裡找,找到就用那句的真實起點;對不到的用相鄰錨點線性插值。**必須加 INTRO_DURATION**
——旁白是在 3 秒片頭之後才開始的,漏掉這個位移,整組章節會系統性早 3 秒
(上傳的 CC 字幕就是這樣錯了很久,直到觀眾在留言區告訴我們才發現)。

## fail-open
YouTube 對章節有硬規:第一個必須 00:00、至少 3 個、每段至少 10 秒、時間遞增。
任何一條不滿足就**整組不輸出**(回空字串)——寧可沒有章節,也不要一組壞章節讓
YouTube 整個忽略、或把觀眾送到錯的位置。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUTPUT = ROOT / "output"

MIN_CHAPTERS = 3
MIN_SPAN = 10.0          # YouTube 硬規:每段至少 10 秒
MAX_TITLE = 26           # 章節標題字數上限(手機版約此長度後會被 YouTube 自己截掉)


def align_segment_starts(narrations, cues, total: float):
    """各段旁白在**音軌**上的起點(秒,不含片頭位移)。對不齊回 None。

    cues = [(start_sec, text), ...](已按時間排序);narrations = 各段旁白全文。

    ⚠️ **單調遞增搜尋**是這支的重點。2026-08-17 實測:個股體檢腳本裡連續兩段的旁白
    開頭常常一模一樣(「這意味著,如果你…」),各自獨立去全表找就會**對到同一句**,
    兩段起點相同 → 章節產不出來,渲染端則退回 per_seg 等分。等分的後果不是小事:
    勤誠那支真實邊界是 0/121.7/227.3/…,等分卻是 109 秒換一段——**畫面比旁白早 12 秒**,
    觀眾看到下一段的圖表時旁白還在講上一段。內部指標(完播、品質分)完全看不到這件事。
    只往上一個錨點之後找,撞句就自然對到下一次出現。

    這份是 render_ffmpeg._narration_seg_starts 與 chapters.build 的**共用實作**——
    同一套判準兩份程式碼是本專案踩過的坑(閘門修在沒人走的那份等於沒修)。
    """
    try:
        n = len(narrations)
        if n < 2 or not cues:
            return None
        starts = [0.0] + [None] * (n - 1)
        last = 0.0
        for i in range(1, n):
            probe = (narrations[i] or "").strip()[:8]
            if len(probe) < 6:
                continue
            for ct, ctext in cues:
                if ct <= last:          # 單調:只往前一個錨點之後找
                    continue
                if probe in (ctext or ""):
                    starts[i] = float(ct)
                    last = starts[i]
                    break
        idxs = [i for i, t in enumerate(starts) if t is not None]
        if len(idxs) < max(2, (n + 1) // 2):
            return None
        for i in range(n):
            if starts[i] is None:
                prev = max((j for j in idxs if j < i), default=None)
                nxt = min((j for j in idxs if j > i), default=None)
                if prev is None or nxt is None:
                    return None
                starts[i] = starts[prev] + (starts[nxt] - starts[prev]) * (i - prev) / (nxt - prev)
        for a, b in zip(starts, starts[1:]):
            if b <= a + 1.5:
                return None
        if total and starts[-1] >= float(total) - 1.5:
            return None
        return starts
    except Exception:  # noqa: BLE001
        return None


def _mmss(t: float) -> str:
    t = max(0, int(round(t)))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _clean_title(raw: str) -> str:
    """段落標題 → 章節標題。去掉「段落 N：」前綴與裝飾,保留關鍵字。"""
    t = re.sub(r"^\s*段落\s*\d+\s*[:：]\s*", "", raw or "").strip()
    t = re.sub(r"^[#\s*]+", "", t).strip()
    # 「主標：副標」型保留資訊量較高的一半:副標通常才含關鍵字(最大回撤/定期定額…)
    if len(t) > MAX_TITLE and ("：" in t or ":" in t):
        a, _, b = t.replace(":", "：").partition("：")
        t = b.strip() if len(b.strip()) >= 6 else a.strip()
    t = t.replace("、", " ")
    if len(t) > MAX_TITLE:
        # 不可切在數字/英文中間:「… vs 0050」被切成「… vs 00」不只難看,還把
        # 搜尋詞整個弄丟(0050 正是本頻道搜尋詞 Top20 之一)。往前退到 token 邊界。
        cut = MAX_TITLE
        while cut > 0 and re.match(r"[0-9A-Za-z]", t[cut - 1]) and \
                cut < len(t) and re.match(r"[0-9A-Za-z]", t[cut]):
            cut -= 1
        t = t[:cut] if cut >= 8 else t[:MAX_TITLE]
    return t.strip().rstrip("，,、 vsVS")


def build(slug: str) -> str:
    """回傳可直接貼進描述的章節區塊(含結尾換行);任一條件不滿足回空字串。"""
    try:
        md = OUTPUT / f"{slug}.md"
        wt = OUTPUT / f"{slug}.wordtimes.json"
        if not md.exists() or not wt.exists():
            return ""
        from make_video import parse_script_md, INTRO_DURATION
        _title, segments = parse_script_md(md)
        segs = [s for s in segments if (s.narration or "").strip()]
        if len(segs) < MIN_CHAPTERS:
            return ""
        cues = json.loads(wt.read_text(encoding="utf-8"))
        if not cues:
            return ""

        pairs = [(float(c.get("t", 0)), c.get("text") or "") for c in cues]
        total = max((t + float(c.get("d", 0))) for t, c in zip([p[0] for p in pairs], cues))
        starts = align_segment_starts([s.narration for s in segs], pairs, total)
        if starts is None:
            return ""

        # 片頭位移:旁白 t=0 對應成品的 INTRO_DURATION 秒。第一章固定 0:00(YouTube 硬規)。
        abs_starts = [0.0] + [float(s) + float(INTRO_DURATION) for s in starts[1:]]
        rows = []
        for i, (t, sg) in enumerate(zip(abs_starts, segs)):
            title = _clean_title(sg.heading or "")
            if not title:
                return ""
            rows.append((t, title))
        # 合規檢查:遞增且每段 ≥ MIN_SPAN
        for (a, _), (b, _) in zip(rows, rows[1:]):
            if b - a < MIN_SPAN:
                return ""
        if len(rows) < MIN_CHAPTERS or rows[0][0] != 0.0:
            return ""
        return "\n".join(f"{_mmss(t)} {ti}" for t, ti in rows) + "\n"
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    args = sys.argv[1:]
    if args:
        slugs = args
    else:
        led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
        slugs = sorted([p.stem for p in OUTPUT.glob("L_*.mp4") if p.stem not in led])[:8]
    ok = 0
    for s in slugs:
        blk = build(s)
        print(f"\n### {s[:44]}")
        if blk:
            ok += 1
            print(blk.rstrip())
        else:
            print("  (無法產生——條件不足,fail-open 跳過)")
    print(f"\n可產出章節:{ok}/{len(slugs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
