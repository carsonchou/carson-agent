#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""attribution_guard.py — 問「**這句話宣稱的那個東西存不存在**」,不是問「值對不對」。

**為什麼要有這支(2026-09-08 存量稽核實案:力成 6239)**
旁白:「第三種則是『量化網格策略』…**回測顯示**這種做法能將最大回撤壓到百分之二十五以下,
但總報酬可能只剩百分之一百八十到兩百」——**我們沒有那個回測。**
事實庫對每檔股票只有三種買法(單筆 All in / 每月定期定額 / 買進持有 0050),
**沒有任何「網格策略回測」**。

🔴 **而現行判準結構上抓不到它:**
`fact_source_guard` 問的是「這個數字在事實庫查不查得到」,存量稽核判準問的是
「事實卡對**同一件事**給出**不同的值**」——**假掛名沒有可比對的條目**,所以兩者都只能放行/判「無法判定」。
**那不是這句話沒問題,那是判準的洞。**

📌 這個洞的形狀記過:memory `yt-integrity-methodology-claims-blindspot` ——
守門對「有算手續費」「這是第零集」這類**方法論宣稱**是盲的。
**「回測顯示…」而沒有那個回測,是同一個盲區的第三個實例。**

## 判準

一句話同時滿足:
  ① 帶**來源掛名詞**(沿用 `fact_source_guard._ATTRIBUTION`,**不另抄一份** —— 另抄一份正是
     合規哨漂掉的成因,見 `954e283c`)
  ② 句中**沒有**誠實揭露詞(沿用 `fact_source_guard.HEDGE`)—— 明講「假設」就不是宣稱實測
  ③ 句子在講**三種買法以外的策略**(網格/擇時/停利/抄底/槓桿…)
     ⇒ 事實庫對每檔只有 `checkup_three_way` 的三種買法,**那個回測結構上不存在**
  ④ 句中有績效數字
⇒ 標為 **`attrib_suspect`(假掛名嫌疑)**。

🔴 **第一版判準是「數字在池裡對不對得上」,那是錯的間接證據,實測當場打掉** ——
陽性對照沒抓到(力成的 25 在約 190 個數字的池裡撞到鄰居)、又誤標兩支。
**v2 直接問結構性的問題:那個回測存不存在**,與數字無關。

⚠️ **這一格不併進 A。** A 是「值錯」(舉證:指得出卡上的哪條、哪個值);
本格是「**來源不存在**」(舉證:該檔事實庫裡沒有那一類條目)。
**兩者的處置與舉證責任不同,合併會讓兩邊都講不清楚。**

⚠️ **能力邊界**:③ 是「數字對不上」的間接證據 —— 若那個回測**真的存在**且旁白引用正確,
數字就會對得上而不被標記。反過來,**旁白把真回測的數字講成概數**(「約三千」)也會被標記
⇒ 那是**誤標**,不是漏抓。反方向的量測見 `--audit30`。

用法:
  python scripts/attribution_guard.py --selftest   # 陽性對照=力成 6239 真案例
  python scripts/attribution_guard.py --slug <slug>
  python scripts/attribution_guard.py --audit30    # 在那 30 支上跑,兩個方向都報
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fact_source_guard as fsg  # noqa: E402

VERDICT = "attrib_suspect"

# 句界:同一句才算。跨句會把前一句的數字算進來(力成那支前一句就有「假設」,
# 而同句判定讓它不必依賴 HEDGE 是否跨句生效)。
_SEPS = "。！？!?；;" + chr(10)


def _sentences(text: str):
    buf, start = [], 0
    for i, ch in enumerate(text or ""):
        if ch in _SEPS:
            if i > start:
                buf.append((start, text[start:i]))
            start = i + 1
    if start < len(text or ""):
        buf.append((start, text[start:]))
    return buf


# 🔴 第一版判準是錯的,實測當場打掉(2026-09-09):
# v1 = 「掛名 + 句中績效數字在池裡一個都對不上」。結果:
#   ①**陽性對照沒抓到** —— 力成那句的 25(「壓到百分之二十五以下」)在該檔約 190 個數字的池裡
#     **剛好撞到鄰居**,於是整句被當成「有來源」跳過。**池子越大,這種巧合越常發生**,
#     而這正是本線一路在抓的同一個病(全域池 42,134 個數字時命中率 100%)。
#   ②**誤標兩支**:漢唐「歷史回測顯示近十年年化報酬超過百分之四十」(真值 43.7%,講「超過40」是對的)、
#     亞翔「0050 最大回撤約負百分之三十五」(真值 −33.8%,概括是對的)。
# ⇒ **用數字對不對得上去推「來源存不存在」,本來就是錯的間接證據。**
#
# v2 直接問那個結構性的問題:**事實庫對每檔股票只有三種買法**
# (單筆 All in / 每月定期定額 / 買進持有 0050),`checkup_three_way` 就是它們。
# ⇒ 掛名句若在講**三種買法以外的策略**,那個回測**結構上不存在**,與數字無關。
_KNOWN_METHODS = ("單筆", "All in", "ALL IN", "all in", "一次投入", "一次全押",
                  "定期定額", "每月", "買進持有", "長抱", "抱著", "0050", "元大台灣50")
_UNKNOWN_METHODS = ("網格", "擇時", "停利", "停損", "加碼", "抄底", "危機入市", "槓桿",
                    "當沖", "輪動", "均線", "KD", "RSI", "動能", "回檔買", "分批進場",
                    "再平衡", "機器人", "策略組合", "這種做法", "這個做法")


def check_text(text: str, pool) -> list[dict]:
    """回傳假掛名嫌疑句。pool = 該檔自己的事實池(fact_pool_for),不是全域池。"""
    out = []
    for _, sent in _sentences(text or ""):
        if not any(a in sent for a in fsg._ATTRIBUTION):
            continue
        # 誠實揭露豁免:句子自己講明是假設/示意 ⇒ 它沒有宣稱那是實測結果。
        # 沿用 fact_source_guard.HEDGE(**不另抄一份**)。
        # 實測必要性:亞翔 6139「…但若把資金拆成網格+定投組合,**假設**整體報酬略低一些…」
        # 句中引的 4952.5/48.0 是該檔 All-in 的**真值**,整句是明講的假設情境 ⇒ 不是假掛名。
        if any(h in sent for h in fsg.HEDGE):
            continue
        unknown = [m for m in _UNKNOWN_METHODS if m in sent]
        if not unknown:
            continue                       # 講的是三種買法之一 ⇒ 那個回測存在,不是假掛名
        claims = fsg.extract_claims(sent)
        if not claims:
            continue                       # 掛名但沒給數字 —— 本支不管(那是另一種問題)
        out.append({
            "unknown_method": unknown[:3],
            "verdict": VERDICT,
            "attrib": next(a for a in fsg._ATTRIBUTION if a in sent),
            "values": [c["value"] for c in claims][:5],
            "sentence": sent.strip()[:110],
            "why": "句子掛名『%s』並宣稱回測了『%s』,而事實庫對每檔只有三種買法"
                   "(單筆/定期定額/買進持有 0050),**沒有那個回測**"
                   % (next(a for a in fsg._ATTRIBUTION if a in sent), "、".join(unknown[:2])),
        })
    return out


def _pool_for(slug):
    try:
        return fsg.fact_pool_for(slug)
    except Exception:  # noqa: BLE001
        return None


def selftest() -> int:
    """🔴 陽性對照用**真案例**(力成 6239),不用合成 fixture
    —— memory `gate-blind-while-target-evolves`:合成 fixture 抓得到不代表真語料抓得到。"""
    bad = 0
    led = json.loads((fsg.STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    slugs = list(led.keys()) if isinstance(led, dict) else [x.get("slug") for x in led]
    pos = next((s for s in slugs if s and "力成6239" in s), None)
    if not pos:
        print("🔴 找不到陽性對照片 力成6239 —— 無法自檢", file=sys.stderr)
        return 2
    hits = check_text(fsg.slug_text(pos), _pool_for(pos))
    ok = any("網格" in h["sentence"] or 25.0 in h["values"] or 180.0 in h["values"] for h in hits)
    bad += (not ok)
    print(f"  {'✅' if ok else '🔴'} 陽性對照(力成 6239 真案例):抓到 {len(hits)} 句"
          + (f" → {hits[0]['sentence'][:60]}" if hits else " → **沒抓到**"))
    # 陰性:掛名而數字對得上的句子(拿真片的真句子,不合成)
    neg = next((s for s in slugs if s and "愛普6531" in s), None)
    if neg:
        h2 = check_text("回測顯示,愛普的最大回撤是負百分之七十六點一。", _pool_for(neg))
        ok2 = not h2
        bad += (not ok2)
        print(f"  {'✅' if ok2 else '🔴'} 陰性對照(掛名且值對得上 −76.1):"
              + ("放行" if ok2 else f"**誤標** {h2[0]['values']}"))
    print("[selftest] " + ("通過" if not bad else f"🔴 {bad} 項不符"))
    return 0 if not bad else 1


def audit30() -> int:
    """在存量稽核那 30 支上跑,**兩個方向都報**(督導要件③)。"""
    SC = (r"C:\Users\User\AppData\Local\Temp\claude\D--carson-agent"
          r"\8f69831e-1991-4a12-a3f0-998c9996e308\scratchpad")
    slugs = []
    for fn in ("audit_sample12.json", "audit_sample18.json"):
        try:
            slugs += [o["slug"] for o in json.loads(Path(SC, fn).read_text(encoding="utf-8"))]
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 讀不到 {fn}:{exc}", file=sys.stderr)
    print(f"[attrib] 在 {len(slugs)} 支上跑")
    n_hit = 0
    for s in slugs:
        p = _pool_for(s)
        if not p:
            continue
        hits = check_text(fsg.slug_text(s), p)
        if hits:
            n_hit += 1
            print(f"🔴 {s[:44]}")
            for h in hits[:2]:
                print(f"     掛名『{h['attrib']}』值 {h['values']}｜「{h['sentence'][:70]}」")
    print(f"[attrib] **{n_hit}/{len(slugs)} 支有假掛名嫌疑**")
    print("⚠️ 這個數字要配反方向一起看:上面每一句都要人工確認"
          "『那個來源真的不存在』,而不是『旁白把真數字講成概數』。")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--audit30" in sys.argv:
        return audit30()
    if "--slug" in sys.argv:
        slug = sys.argv[sys.argv.index("--slug") + 1]
        hits = check_text(fsg.slug_text(slug), _pool_for(slug))
        for h in hits:
            print(f"🔴 {h['why']}\n   「{h['sentence']}」")
        print(f"[attrib] {slug[:44]}:{len(hits)} 句假掛名嫌疑")
        return 1 if hits else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
