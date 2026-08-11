#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_backlog_hooks.py — 把 08-05 兩項已驗證/待驗證的開場修復回填到未發布庫存。

## 為什麼(2026-08-11)
08-05 產線修了兩件事:①碎句開場(留存殺手)②35% 片中訂閱鉤。但修的是**生成端**,
當時已產好的庫存不受惠。實測 72 支近期長片:非碎句開場的每千觀看訂閱 7.9 vs 碎句 3.9
(2 倍)、完播 24.6% vs 17.1%。庫存 38 支裡有 5 支碎句、23 支無片中鉤——片的曝光窗
只有 4 天(快照 diff 實測),帶著已知缺陷發布等於浪費唯一一次曝光。

## 做法(每支)
1. 碎句開場 → 確定性合併:把開頭 <12 中文字的斷句的「。」改成「，」直到前兩句完整。
   **不走 LLM 改寫**——LLM 可能動到數字,確定性合併零編造風險(誠信鐵律)。
2. 無片中鉤 → 直接重用產線的 produce_batch._insert_mid_sub_hook(同一份程式,不重刻)。
3. 文字有變 → 備份原 voice.txt(.prehook.bak) → 重配音(_run_tts) → 驗 mp3 真的更新
   → 舊 mp4 搬進 output/_prehook_bak/(不是刪:可還原)。
4. mp4 消失後,local_cron 的 hybrid_render --cloud(每 15 分)自動重渲;發布閘門看不到
   mp4 會跳過該支,不會發出半成品——fail-safe 靠既有機制,不另造。

TTS 失敗 → 還原備份、保留舊 mp4,該支維持原樣(寧可帶舊缺陷發布,不可斷炊)。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
BAK = OUT / "_prehook_bak"
CJK = re.compile(r"[一-鿿]")
_SEAM_CHECK = re.compile(r"上一段|前一段|上一節|接續上|承上|如前所述|前面我們看到|前面提到")


def _fragmented(voice: str) -> bool:
    """與 produce_batch._long_fragmented_hook 的判定基準一致:前兩句 <12 中文字=碎。"""
    parts = [p for p in voice.replace("\n", " ").split("。") if p.strip()]
    return any(len(CJK.findall(p)) < 12 for p in parts[:2]) if parts else False


def _defrag_opening(text: str, rounds: int = 6) -> str:
    """確定性合併開場碎句——只動標點、不動任何字,數字/事實零編造風險。

    方向很重要(乾跑實測):碎句要**往前併**(把上一句句尾的「。」改「，」),
    「你有沒有想過。那些配息。可能吃掉本金。」→「你有沒有想過，那些配息，可能吃掉本金。」
    往後併會跨段落撞進下一段開頭,變成「…定期定額，上一段我們看到…」這種連珠炮。
    只有第一句(沒有上一句可併)才往後併;兩個方向都**不跨段落**(遇 \\n 收手)。"""
    for _ in range(rounds):
        head = text[:400]
        segs, prev = [], 0
        for m in re.finditer("。", head):
            if head[prev:m.start()].strip():
                segs.append((prev, m.start()))
            prev = m.start() + 1
            if len(segs) >= 3:
                break
        bad = None
        for j, (a, b) in enumerate(segs[:2]):
            if len(CJK.findall(text[a:b])) < 12:
                bad = (j, a, b)
                break
        if bad is None:
            return text
        j, a, b = bad
        seg_text = text[a:b]
        lead_ws = len(seg_text) - len(seg_text.lstrip())
        if j > 0 and "\n" not in text[segs[j - 1][1]: a + lead_ws]:
            p = segs[j - 1][1]          # 往前併:上一句句尾的「。」→「，」
            text = text[:p] + "，" + text[p + 1:]
        elif j == 0 and text[b] == "。" and "\n" not in text[b + 1: b + 3]:
            text = text[:b] + "，" + text[b + 1:]   # 首句往後併(同段落內)
        else:
            return text                  # 段落邊界,不硬併
    return text


def main() -> int:
    import produce_batch as pb
    from audit_video import find_banned_hits

    led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    slugs = sorted({p.name[:-4] for p in OUT.glob("L_*.mp4")} - set(led))
    BAK.mkdir(exist_ok=True)
    changed = skipped = failed = 0
    for slug in slugs:
        vt = OUT / f"{slug}.voice.txt"
        if not vt.exists():
            continue
        voice = vt.read_text(encoding="utf-8")
        new = voice
        acts = []
        # 接縫語清洗(2026-08-11 二輪):「上一段我們看到/接續上段」這類講稿疤痕,
        # 未發布 38 支裡 9 支中招;直接重用產線 _clean_narration(規則已擴充),不重刻。
        # ⚠️ 只在真的含接縫語時才過清洗器:它的空白/符號正規化會讓「乾淨檔」也產生
        # 無意義 diff → 全庫存被誤判有變 → 白白重配音+重渲幾小時。
        if _SEAM_CHECK.search(new):
            cleaned = pb._clean_narration(new)
            if cleaned != new:
                new = cleaned
                acts.append("洗接縫")
        if _fragmented(new):
            new = _defrag_opening(new)
            acts.append("併碎句")
        with_hook = pb._insert_mid_sub_hook(new, slug)
        if with_hook != new:
            new = with_hook
            acts.append("補片中鉤")
        if new == voice:
            # 冪等盲點修補(2026-08-11 實測):上一輪在 TTS 中途被砍,「文字沒變」不代表
            # mp3 完好——實測留下 302s 殘骸配 425s 的稿(7.9字/秒,正常 4~5.5),而 audit
            # 只比 mp4 vs mp3 長度,若用殘骸重渲兩者一致照樣放行。兩個訊號判殘骸:
            # ①mp3 比 voice.txt 舊(改稿後沒配完) ②語速 >6.5 字/秒(截斷)。
            mp3c = OUT / f"{slug}.mp3"
            bak = OUT / f"{slug}.voice.txt.prehook.bak"
            broken = ""
            if bak.exists():   # 只檢查本腳本動過的(有備份=改過稿),別誤傷正常產線件
                if not mp3c.exists() or mp3c.stat().st_mtime + 1 < vt.stat().st_mtime:
                    broken = "mp3比稿舊"
                else:
                    try:
                        from audit_video import _probe
                        adur, _, _ = _probe(mp3c)
                        ncjk = len(CJK.findall(new))
                        if adur > 0 and ncjk / adur > 6.5:
                            broken = f"語速{ncjk / adur:.1f}字/秒"
                    except Exception:  # noqa: BLE001
                        pass
            if not broken:
                skipped += 1
                continue
            print(f"🔧 {slug[:40]} 文字已回填但配音是殘骸({broken}),重配音")
            acts = ["修殘骸"]
        if _fragmented(new):
            print(f"⚠️ {slug[:40]} 併句後仍碎,跳過不動")
            skipped += 1
            continue
        bad = find_banned_hits(new)
        if bad:
            print(f"⚠️ {slug[:40]} 改後含禁語{bad},跳過不動")
            skipped += 1
            continue
        bak = OUT / f"{slug}.voice.txt.prehook.bak"
        if not bak.exists():
            bak.write_text(voice, encoding="utf-8")
        vt.write_text(new, encoding="utf-8")
        mp3 = OUT / f"{slug}.mp3"
        t0 = time.time()
        pb._run_tts(slug)
        ok = mp3.exists() and mp3.stat().st_size > 10 * 1024 and mp3.stat().st_mtime >= t0
        if not ok:
            vt.write_text(voice, encoding="utf-8")  # 還原,保留舊 mp4 照常發布
            print(f"❌ {slug[:40]} 重配音失敗,已還原原稿")
            failed += 1
            continue
        mp4 = OUT / f"{slug}.mp4"
        if mp4.exists():
            shutil.move(str(mp4), str(BAK / mp4.name))
        changed += 1
        print(f"✅ {slug[:40]} {'+'.join(acts)} → 已重配音,待自動重渲")
    print(f"\n完成:改 {changed} / 略過 {skipped} / 失敗 {failed}(共 {len(slugs)} 支未發布長片)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
