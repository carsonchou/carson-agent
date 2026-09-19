# -*- coding: utf-8 -*-
"""步驟 3 陽性對照 —— 三個硬性失敗形態各餵一個**會觸發它**的輸入,要求閘門真的擋下
並改走 CTA 分支;外加陰性對照(合法輸入必須放行)與全片母體通過率。

「規則要嘛是檢查要嘛是期望」:這裡每一格都會印出實際的 Decision,不是註解層的期望。

用法: <venv>/python.exe poscontrol_step3.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

YT = Path(r"D:\carson-agent\youtube_channel")
sys.path.insert(0, str(YT / "scripts"))

import narration_number_gate as gate  # noqa: E402

CODE = "3714"
SLUG = "L_個股體檢富采3714長抱富採56年報酬竟是-281這"


def facts_for(code):
    raw = json.loads((YT / "STUDIO" / "stock_checkup_facts.json").read_text(encoding="utf-8"))["results"]
    return {k: (v or {}).get("data") for k, v in raw.items()
            if k.endswith(f"__{code}") and (v or {}).get("data")}


def _show(tag, d):
    print(f"  {tag}: ok={d.ok} number={d.number} reason={d.reason}")


def positive_controls(facts):
    """三個硬性失敗形態,各一格。每格都要 ok=False,且 reason 落在對應編號。"""
    ok = True

    # ① 旁白引用全歷史 -69.8%,但這一幀圖說是漸進揭露重算的 -59.9%
    d = gate.decide("期間最大回撤曾高達負的百分之六十九點八。", facts,
                    caption="3714 實際最大回撤 -59.9%(2021-01-06 → 2024-08-05)")
    _show("①視窗不一致", d)
    ok &= (not d.ok) and d.reason.startswith("①")

    # ② 數字與單位都解析得出(2 年),但事實庫沒有這個值 → 不准印
    d = gate.decide("如果你在兩年前的高點單筆 All in 買入富採。", facts)
    _show("②無對應欄位", d)
    ok &= (not d.ok) and d.reason.startswith("②")

    # ②的另一形:連單位都不認得(CTA 進度數字) → 連解析都不給過
    d = gate.decide("這個系列會把全台股1925檔一檔一檔體檢完，目前完成223檔。", facts)
    _show("②無單位可辨識", d)
    ok &= (not d.ok) and d.reason.startswith("④")

    # 指標詞未被點名:實測本片抓到的兩個假陽性,修完必須被擋
    for t in ("這意味著如果你在這一年持有富採。", "即使你抱了五年多，不僅沒賺。"):
        d = gate.decide(t, facts)
        _show(f"假陽性回歸「{t[:8]}…」", d)
        ok &= not d.ok

    # ③ 同一句兩個數字(總報酬 vs 年化),無法確定在唸哪個
    d = gate.decide("你的總報酬會是負的百分之二十八點一，年化報酬率為負的百分之五點七。", facts)
    _show("③同句兩個數字", d)
    ok &= (not d.ok) and d.reason.startswith("③")

    # 陰性對照:單一數字 + 事實庫對得上 + 圖說一致 → 必須放行(否則上面三格可能只是全擋)
    d = gate.decide("期間最大回撤曾高達負的百分之六十九點八。", facts,
                    caption="3714 實際最大回撤 -69.8%(2022-02-09 → 2022-11-04)")
    _show("陰性對照(應放行)", d)
    ok &= d.ok and d.number == "-69.8%" and "max_drawdown" in (d.fact_path or "")
    return ok


def population(facts):
    """母體=這支片全部字幕 cue。報通過率,避免「全部擋掉」被當成閘門有效(形態⑦)。"""
    import make_video as mv
    voice = (YT / "output" / f"{SLUG}.voice.txt").read_text(encoding="utf-8")
    # 🔴 必須跟正式渲染用**同一組 cue**。render_ffmpeg.py:1057 先試 load_word_cues
    # (TTS 真實時戳,本片 233 句),拿不到才退 build_subtitle_cues(估算,216 句)。
    # 用估算版量出來的通過率量的是另一台儀器 → 這裡直接斷言拿到真值版。
    out = YT / "output"
    sp = mv.SlugPaths(slug=SLUG, output_dir=out, audio=out / f"{SLUG}.mp3",
                      script_md=out / f"{SLUG}.md", voice_txt=out / f"{SLUG}.voice.txt",
                      out_mp4=out / f"{SLUG}.mp4")
    cues = mv.load_word_cues(sp, voice, 628.632)
    assert cues, "load_word_cues 回 None:量到的會是估算時間軸,不是成片用的那組"
    passed, blocked = [], {}
    for c in cues:
        d = gate.decide(c.text, facts)
        if d.ok:
            passed.append((c.text[:18], d.number, d.fact_path))
        else:
            blocked[d.reason[0]] = blocked.get(d.reason[0], 0) + 1
    print(f"  母體 cue 數 = {len(cues)};放行 {len(passed)};擋下 {dict(sorted(blocked.items()))}")
    for t, n, p in passed[:12]:
        print(f"    放行: 「{t}…」 → {n}  ({p})")
    assert len(cues) > 100, f"母體太小,抓錯東西:{len(cues)}"
    assert passed, "閘門把整支片都擋光了 = 功能等於沒上線(形態⑦)"
    return len(cues), len(passed)


if __name__ == "__main__":
    f = facts_for(CODE)
    print(f"事實庫 3714 有 {len(f)} 組事實")
    print("[陽性對照]")
    ok = positive_controls(f)
    print("[母體通過率]")
    n, p = population(f)
    print("步驟 3 陽性對照" + ("全部通過" if ok else "有失敗") + f";全片 {p}/{n} cue 放行")
    sys.exit(0 if ok else 1)
