# -*- coding: utf-8 -*-
"""步驟 2 版面檢查:重皮加回來的 y 刻度有沒有撞到別的字。

為什麼需要這支:暗金重皮把 y 軸刻度加回每一張真資料圖(改版前 `set_yticks([])`,
等於整條軸沒有刻度也沒有格線)。刻度是**新增的文字**,而這張圖下緣本來就有年份刻度,
左下角是必然的碰撞點——實測 3714 回撤圖的「40」就壓在「2021」上。

判準(寫在跑之前,memory fallback-criterion-must-predate-the-result):
  [A] 任兩個文字的算繪框不得重疊(交集 > 3px × 3px 才算數,避開反鋸齒邊緣)
  [B] 每個文字都要落在 1920x1080 畫布內

memory layout-guard-blind-to-overlap:守門要驗**成對**,不是逐項——兩個字各自都在
畫布內(逐項全綠),疊在一起才是錯的。所以 [A] 是成對檢查,[B] 才是逐項。

用法:
  python check_step2_layout.py            # 跑母體
  python check_step2_layout.py --poscontrol   # 陽性對照:關掉刻度過濾,檢查必須要叫
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib.text import Text  # noqa: E402

YT = Path(r"D:\carson-agent\youtube_channel")
sys.path.insert(0, str(YT / "scripts"))
if len(sys.argv) > 1 and sys.argv[1] == "--cvis":
    sys.path.insert(0, sys.argv[2])
import concept_visuals as cvis  # noqa: E402

print("[check] concept_visuals <-", cvis.__file__)
cvis._FACTS_CACHE = YT / "STUDIO" / "tw_facts_cache"
cvis._CHECKUP_FACTS = (json.loads(
    (YT / "STUDIO" / "stock_checkup_facts.json").read_text(encoding="utf-8"))
    or {}).get("results") or {}
assert cvis._FACTS_CACHE.exists() and cvis._CHECKUP_FACTS, "真資料來源接不上"

POSCONTROL = "--poscontrol" in sys.argv
if POSCONTROL:
    # 把「砍掉下緣刻度」那段拿掉,其餘一模一樣 —— 還原成修之前的行為。
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    def _no_filter(ax, suffix=""):
        ax.yaxis.set_major_locator(MaxNLocator(nbins=4, prune="both"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}{suffix}"))
        ax.tick_params(axis="y", colors=cvis.MUTED, labelsize=15, length=0, pad=2)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color=(1, 1, 1, 0.05), lw=0.8)
    cvis._y_ticks = _no_filter
    print("[check] 陽性對照:已還原成「不過濾下緣刻度」的版本")

# 攔下 figure 好在 render 之後還摸得到它(render_concept_chart 內部會 close)。
_figs = []
_orig_figure = cvis.plt.figure
_orig_close = cvis.plt.close
cvis.plt.figure = lambda *a, **k: (_figs.append(_orig_figure(*a, **k)), _figs[-1])[1]
cvis.plt.close = lambda *a, **k: None   # 先擋下,量完再自己關

W, H = 1920, 1080
KINDS = ["drawdown", "candle", "dca", "history", "fundamentals", "valuation"]
TEXT_BY_KIND = {
    "drawdown": "期間最大回撤曾高達多少",
    "candle": "近一年的實際 K 線",
    "dca": "每月定期定額的實際平均成本",
    "history": "完整真實走勢",
    "fundamentals": "這幾年的營收與 EPS 走勢",
    "valuation": "目前本益比落在自身歷史什麼位置",
}


# 已知會踩到版面問題的個股,一律納入母體:3714 是我這次改出來的「40 壓在 2021」現場,
# 其餘是步驟 1 的 P0 受害者/陰性對照。
MUST = ["3714", "2485", "1536", "2610", "2330"]


def codes(n):
    """從事實庫挑有真價格 CSV 的代號,**跨整個代號區間等距取樣**。

    🔴 第一版寫「排序後取前 n 檔」,結果 25 檔全是 1101~1409 的水泥塑化股,
    而我這次改出來的碰撞現場 3714 根本不在母體裡——檢查全綠只代表它沒看過出問題的那張。
    (memory gate-verification-population:母體要是「會經過這個閘門的全部」,不是好取的那批。)"""
    elig = []
    for k in sorted(cvis._CHECKUP_FACTS):
        if "__" not in k:
            continue
        c = k.rsplit("__", 1)[1]
        if c not in elig and (cvis._FACTS_CACHE / f"{c}.csv").exists():
            elig.append(c)
    out = [c for c in MUST if c in elig]
    step = max(1, len(elig) // max(1, n - len(out)))
    for c in elig[::step]:
        if c not in out:
            out.append(c)
        if len(out) >= n:
            break
    return out


_orig_text_draw = Text.draw
_rec: list = []


def _rec_draw(self, renderer):
    """錄下**真的被畫出來**的文字。

    🔴 不可以用 fig.findobj(Text) 列舉:Axis 上每個 Tick 都掛著一個 Text 物件,
    視窗外的刻度**不會被畫**(Axis.draw 只取 view interval 內的),但那些 Text 物件
    還在、還帶著舊座標。第一版用 findobj 量到的 94 個「出界」全是這種幽靈刻度
    (對數軸的 0.01 / 1,000),而且**正常模式和陽性對照跑出一模一樣的結果**——
    量尺根本沒在量我改的東西(memory static-reading-vs-runtime-behaviour)。
    掛在 draw 上就只會收到實際進到畫面的那些。"""
    txt = (self.get_text() or "").strip()
    if txt:
        try:
            bb = self.get_window_extent(renderer=renderer)
            if bb.width > 0 and bb.height > 0:
                _rec.append((txt, bb))
        except Exception:  # noqa: BLE001
            pass
    return _orig_text_draw(self, renderer)


Text.draw = _rec_draw


def texts_of(fig):
    _rec.clear()
    fig.canvas.draw()
    return list(_rec)


def overlap(a, b, tol=3.0):
    dx = min(a.x1, b.x1) - max(a.x0, b.x0)
    dy = min(a.y1, b.y1) - max(a.y0, b.y0)
    return dx > tol and dy > tol


def main():
    n = 25
    cs = codes(n)
    # 🔴 漸進揭露每個 bucket 的資料窗口不同 → **ylim 不同 → 刻度落點不同**。
    # 只跑 reveal=1.0 會漏掉:我這次改出來的「40 壓在 2021」只在 r=0.625 出現,
    # r=1.0 的同一檔同一張圖是乾淨的。成片每個 bucket 都會播,母體就得含 bucket。
    REVEALS = [0.35, 0.625, 1.0]     # bucket 0 / 3 / 7
    total = len(cs) * len(KINDS) * len(REVEALS)
    print(f"[check] 母體:{len(cs)} 檔 × {len(KINDS)} 圖種 × {len(REVEALS)} 揭露階段 = {total} 張\n")
    drawn = 0
    bad_a, bad_b = [], []
    for code in cs:
        for kind in KINDS:
            for rv in REVEALS:
                _figs.clear()
                img = cvis.render_concept_chart(
                    W, H, TEXT_BY_KIND[kind], (255, 209, 102), seed=f"s_{code}_{kind}",
                    dest=None, force=kind, fallback_ticker=code, reveal=rv)
                if img is None or not _figs:
                    for f in _figs:
                        _orig_close(f)
                    continue
                drawn += 1
                fig = _figs[-1]
                tag = f"{kind} r{rv}"
                ts = texts_of(fig)
                for (ta, ba), (tb, bb) in combinations(ts, 2):
                    if overlap(ba, bb):
                        bad_a.append((code, tag, ta, tb))
                for txt, bb in ts:
                    if bb.x0 < -1 or bb.y0 < -1 or bb.x1 > W + 1 or bb.y1 > H + 1:
                        bad_b.append((code, tag, txt))
                _orig_close(fig)

    print(f"實際畫出來的張數:{drawn}")
    keys = sorted("|".join(r) for r in bad_a)
    if "--dump" in sys.argv:
        p = Path(sys.argv[sys.argv.index("--dump") + 1])
        p.write_text(json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已寫出重疊清單 ->", p)

    # 判準:重皮**不得新增**任何重疊。改版前就有的 42 組(絕大多數是 _fundamentals 的
    # EPS 標籤壓到年份)不是這一步造成的,也不在這一步的範圍內,但照實記下來不當作沒看到。
    base = []
    if "--base" in sys.argv:
        base = json.loads(Path(sys.argv[sys.argv.index("--base") + 1]).read_text(encoding="utf-8"))
    new = [k for k in keys if k not in set(base)]
    gone = [k for k in set(base) if k not in set(keys)]

    print(f"\n[A] 不新增文字重疊 : {'FAIL' if new else 'PASS'}"
          f"  (改版前 {len(base)} 組 → 現在 {len(keys)} 組;新增 {len(new)}、消失 {len(gone)})")
    for k in new[:12]:
        print("      + " + k.replace("|", "  "))
    if len(new) > 12:
        print(f"      ...另外 {len(new)-12} 組")
    print(f"[B] 文字不出血     : {'FAIL' if bad_b else 'PASS'}  ({len(bad_b)} 個出界)")
    for row in bad_b[:8]:
        print(f"      {row[0]} {row[1]}: 「{row[2]}」")

    if POSCONTROL:
        # 陽性對照的期望是**要叫**。全過反而代表這支檢查抓不到東西。
        print("\n陽性對照期望:[A] 要 FAIL。實際:",
              "FAIL ✓ 檢查抓得到" if new else "PASS ✗ 檢查抓不到,這支守門沒有用")
        return 0 if new else 1
    ok = not new and not bad_b
    print("\n全部通過" if ok else "\n有未通過項目")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
