#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rescue_redo.py — 把 _redo 裡「剝掉 prompt 洩漏就合格」的稿救回產線(零 LLM 成本)。

## 為什麼
2026-08-28 退回 15 支帶 prompt 洩漏的成品(唸出 21~87 秒的指令原文,最嚴重那支從第 13 秒
就開始唸),可發庫存因此從 26 掉到 5 支。而重產一支要 ~13 分鐘 + LLM 費用。

但那些稿的缺陷是**規則修得掉的**:洩漏的是整句純指令,刪掉不損失任何內容。
實測 `_redo` 47 支裡有 **18 支剝完六道閘門全過**,保留 81~98% 內容。
→ 不必重產,只要**重配音 + 重渲**:零 LLM 呼叫,而且題目、事實、結構都已經驗過。

## 做法
1. 剝除 → 六道閘門全過 + 保留 >=70% 內容,才救(否則留在 _redo 走重產)
2. 把剝乾淨的 voice.txt / md 放回 output/
3. **刪掉舊的 mp3 / wordtimes / srt / mp4** —— 那些是用**帶洩漏的旁白**產的,
   不刪的話渲染會直接沿用,等於什麼都沒修(這是最容易出錯的一步)
4. 渲染迴圈(hybrid_render --loop)會自己撿起來重建

## 安全
- 原檔留在 `_redo/`(不刪),救回失敗可回溯。
- dry-run 預設;`--apply` 才動。

用法:
  python scripts/rescue_redo.py            # 列出可救的
  python scripts/rescue_redo.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

OUT = ROOT / "output"
REDO = OUT / "_redo"
# 用**帶洩漏的旁白**產出來的衍生檔,救回時一定要刪掉重建,否則等於沒修
STALE = (".mp3", ".mp4", ".wordtimes.json", ".srt", ".ab.txt")


def _gate(pb, v, title=""):
    for fn, name in ((lambda: pb._long_mixed_period(v, title), "期間偷換"),
                     (lambda: "【" in v, "【】洩漏"),
                     (lambda: pb._long_prompt_leak(v), "prompt洩漏"),
                     (lambda: pb._long_stage_direction(v), "分鏡指示"),
                     (lambda: pb._long_underlength(v), "長度不足"),
                     (lambda: pb._long_content_padding(v), "資訊密度")):
        r = fn()
        if r:
            return name
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    import produce_batch as pb

    good, bad = [], []
    for p in sorted(REDO.glob("L_*.voice.txt")):
        slug = p.name[:-len(".voice.txt")]
        raw = p.read_text(encoding="utf-8", errors="replace")
        clean = pb._strip_prompt_leak(raw)
        keep = pb._long_chinese_chars(clean) / max(pb._long_chinese_chars(raw), 1)
        why = _gate(pb, clean)
        if why is None and keep >= 0.7:
            good.append((slug, clean, keep))
        else:
            bad.append((slug, why or f"剝過頭(只剩{keep:.0%})"))

    print(f"_redo 共 {len(good)+len(bad)} 支")
    print(f"  剝除後六道閘門全過、可直接重渲:**{len(good)} 支**(零 LLM 成本)")
    print(f"  仍不合格、留在 _redo 走重產:{len(bad)} 支")
    for slug, _c, k in good[:20]:
        print(f"    救 保留{k:.0%}  {slug[6:46]}")
    if not args.apply:
        print("\n[dry-run] 未改動。要真的救回:--apply")
        return 0

    n = 0
    for slug, clean, _k in good:
        try:
            # 1) 剝乾淨的稿放回 output
            (OUT / f"{slug}.voice.txt").write_text(clean, encoding="utf-8")
            src_md = REDO / f"{slug}.md"
            if src_md.exists():
                md = src_md.read_text(encoding="utf-8", errors="replace")
                # md 裡的旁白區也要同步剝,否則 make_video 會用到舊文字
                (OUT / f"{slug}.md").write_text(pb._strip_prompt_leak(md), encoding="utf-8")
            # 2) 刪掉用舊旁白產的衍生檔(關鍵:不刪就等於沒修)
            for ext in STALE:
                for d in (OUT, REDO):
                    f = d / f"{slug}{ext}"
                    if f.exists():
                        f.unlink()
            n += 1
            print(f"✅ 救回 {slug[6:44]}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {slug[:30]} {str(e)[:70]}")
    print(f"\n救回 {n} 支;渲染迴圈會自己撿起來重建(每支約 18~23 分鐘)。")
    print("原檔仍留在 _redo/,可回溯。")
    try:
        from ops import log_ops
        log_ops("救回重渲", f"{n} 支剝除洩漏後合格的稿救回產線(零 LLM)")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
