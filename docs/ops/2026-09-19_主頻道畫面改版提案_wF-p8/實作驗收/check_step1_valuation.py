# -*- coding: utf-8 -*-
"""步驟 1 檢查:_valuation 的 x 軸不再被離群值撐爆,且標籤不會被畫布切掉。

兩格斷言都是**會產生輸出的檢查**(不是註解層的期望):
  A. 母體全掃 —— stock_checkup_facts.json 全部 693 檔有估值資料的個股,
     逐檔實際呼叫 _valuation 取 ax.get_xlim(),算 P25~P75 佔畫布比例,要求每一檔 >= 45%。
     (改動前:142 檔 < 30%,最慘 0.44%。)
  B. 版面 —— 實際 render 之後量每個 Text 物件的**渲染後像素框**,
     要求全部落在畫布內。這格在我加 ha 換邊之前會 FAIL(「目前 992 倍（超出區間）」
     以 ha="center" 釘在右緣,右半被切掉),所以它是陽性對照過的,不是空砲。

用法: <venv>/python.exe check_step1_valuation.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

YT = Path(r"D:\carson-agent\youtube_channel")
sys.path.insert(0, str(YT / "scripts"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import concept_visuals as cvis  # noqa: E402

W, H = 1920, 1080
MIN_BOX_FRAC = 0.45       # 箱型區間至少要佔畫布寬 45%
FRAMES = ["3714", "1536", "2485", "2610", "2330"]   # 3 離群 + 2 陰性對照(本來就正常)


class _FakeCtx:
    """只餵 _valuation 需要的欄位:ctx.real[0] 當代號、reveal 控制揭露。"""
    def __init__(self, code, reveal=1.0):
        self.real = (code, None, None)
        self.reveal = reveal
        self.rng = None
        self.direction = 0
        self.text = ""


def _axis(code, reveal=1.0):
    # 一定要先 setup 字型:否則中文全部 fallback 成豆腐框,[B] 量到的字寬不是成片的字寬
    # (量錯對象 → 檢查看起來會過但量的不是同一個東西,見 dispatch.md「看的是哪一本帳」)。
    cvis._font_setup()
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(cvis.BG)
    ax = fig.add_axes([0.06, 0.46, 0.88, 0.40])
    ax.set_facecolor(cvis.BG)
    out = cvis._valuation(ax, _FakeCtx(code, reveal))
    return fig, ax, out


def check_a_population():
    facts = json.loads((YT / "STUDIO" / "stock_checkup_facts.json").read_text(encoding="utf-8"))["results"]
    codes = sorted(k.split("__")[1] for k in facts if k.startswith("checkup_valuation_position__"))
    worst, drawn, bad = (1.0, None), 0, []
    for code in codes:
        d = facts[f"checkup_valuation_position__{code}"]["data"]
        fig, ax, out = _axis(code)
        if out is None:                      # 欄位不全 → 本來就不畫,不算
            plt.close(fig)
            continue
        lo, hi = ax.get_xlim()
        plt.close(fig)
        drawn += 1
        frac = (d["p75"] - d["p25"]) / (hi - lo)
        if frac < worst[0]:
            worst = (frac, code)
        if frac < MIN_BOX_FRAC:
            bad.append((code, round(frac * 100, 2)))
    print(f"[A] 實際畫出的估值圖 {drawn} 檔;箱型佔畫布最小 {worst[0]*100:.2f}%(個股 {worst[1]})")
    assert drawn >= 600, f"畫出的檔數太少,母體不對:{drawn}"
    assert not bad, f"仍有 {len(bad)} 檔箱型 < {MIN_BOX_FRAC*100:.0f}% 畫布:{bad[:10]}"
    print(f"[A] PASS — {drawn}/{drawn} 檔的箱型都 >= {MIN_BOX_FRAC*100:.0f}% 畫布寬")


def check_b_no_text_clipped():
    bad = []
    for code in FRAMES:
        fig, ax, out = _axis(code)
        assert out is not None, code
        fig.canvas.draw()
        for t in ax.texts + ax.get_xticklabels() + ax.get_yticklabels():
            if not (t.get_text() or "").strip():
                continue
            bb = t.get_window_extent(renderer=fig.canvas.get_renderer())
            if bb.x0 < 0 or bb.x1 > W or bb.y0 < 0 or bb.y1 > H:
                bad.append((code, t.get_text(),
                            round(bb.x0), round(bb.x1), round(bb.y0), round(bb.y1)))
        plt.close(fig)
    print(f"[B] 量了 {len(FRAMES)} 檔的所有文字渲染框")
    assert not bad, f"有文字被畫布切掉:{bad}"
    print("[B] PASS — 沒有任何文字超出 1920x1080 畫布")


if __name__ == "__main__":
    check_a_population()
    check_b_no_text_clipped()
    print("步驟 1 檢查全部通過")
