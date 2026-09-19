# -*- coding: utf-8 -*-
"""會叫的檢查:段落大標題不得被畫出畫面外(左右裁切)。

用法: python check_標題不裁切.py <scripts目錄>
    exit 0 = 全過;exit 1 = 有標題會被裁

先寫失敗形態,再挑閘門(dispatch.md 第 6 節):

  形態① 標題像素寬 > 畫面寬 → 呼叫端一律 x=(width-w)//2 置中 → x 變負 → 左右兩端切掉
  形態② 折行函式回傳了「比 max_w 還寬的一行」→ 形態①的上游成因
  形態③ 英數被當成不可分割 token,而該 token 自己就比一行寬 → 形態②的具體觸發路徑
  形態④ 多位元組中文字寬估算錯誤(例外退回 len(s)*12)→ 量到的寬度比真的窄 → 形態①

閘門有兩層,因為只驗契約會漏掉「契約對了但呼叫端算錯 x」:
  L1 契約層:每一行的像素寬 ≤ max_w,且置中後 x ≥ 0
  L2 像素層:真的把卡片畫出來,掃畫面最左/最右 6 欄有沒有近白色的字身像素

L2 帶**陰性對照**:同一張卡片的中段必須掃得到近白像素。掃不到 = 這個偵測器對什麼都說
「沒有字」,那它在邊緣說「沒有字」也不算數(memory verification-that-cannot-fail 第零種)。
"""
from __future__ import annotations

import sys
from pathlib import Path

W, H = 1920, 1080
MD = min(W, H)
EDGE = 6          # 掃畫面左右各 6 欄
INK = 235         # 近白 = 字身(標題填色 248,250,255;K 線/金色柱的最小通道都遠低於此)

# 本片真實 heading(1560 中砂 / 2330 台積電 的個股體檢五段模板)+ 刻意的惡意輸入
CASES = [
    ("真實-基本面", "基本面體檢：營收、EPS、毛利率與股利資料"),
    ("真實-估值", "估值現況：本益比相對位置與產業排名"),
    ("真實-套牢", "持有真實體驗：最大回撤與長套牢的代價"),
    ("真實-對決", "對決：All-in、定期定額與 0050 的十年比較"),
    # 陽性對照①:不可分割英數 token,自己就比一行寬(形態③)
    ("陽性-英數長token", "EPSGROWTHANDVALUATIONBENCHMARKCOMPARISONFORTAIWANSEMICONDUCTOR2026Q3"),
    # 陽性對照②:刻意很長的中文標題(形態①的純中文版)
    ("陽性-超長中文", "估值現況與基本面體檢的交叉比對：本益比相對位置、產業排名、"
                      "營收與每股盈餘的十年趨勢以及最大回撤和長期套牢的真實代價全部攤開"),
    # 陽性對照③:中英混排,英數 token 卡在行尾
    ("陽性-中英混排", "十年實測：0050 vs 2330 vs TAIWANSEMICONDUCTORMANUFACTURINGCOMPANY 的總報酬對比"),
]


def main() -> int:
    sd = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(sd))
    import make_video as mv
    from PIL import Image, ImageDraw

    p = Path(mv.__file__).resolve()
    print(f"[受測] make_video <- {p}")
    assert str(p).lower().startswith(str(sd).lower()), f"載到別處: {p}"

    draw = ImageDraw.Draw(Image.new("RGB", (W, H)), "RGBA")
    # 與 render_concept_card 的頂部標題條逐字相同的兩個參數
    font = mv._load_font(int(MD * 0.058), bold=True)
    max_w = W - int(W * 0.10)
    assert font is not None, "字型載不到,這個檢查量不了寬度"
    print(f"[參數] 字級={int(MD * 0.058)} max_w={max_w} 畫面寬={W}")

    bad = []

    # ---------- L1 契約層 ----------
    for name, head in CASES:
        lines = mv._wrap_to_width(draw, head, font, max_w)
        ws = [draw.textlength(ln, font=font) for ln in lines]
        over = [(ln, w) for ln, w in zip(lines, ws) if w > max_w]
        xmin = min((W - w) / 2 for w in ws)
        ok = (not over) and xmin >= 0
        print(f"[L1] {'OK ' if ok else 'FAIL'} {name}: 行數={len(lines)} "
              f"最寬={max(ws):.0f} max_w={max_w} 置中x最小={xmin:.0f}")
        if over:
            bad.append(f"L1 {name}: {len(over)} 行超過 max_w(最寬 {max(w for _, w in over):.0f})")
        if xmin < 0:
            bad.append(f"L1 {name}: 置中後 x={xmin:.0f} < 0,標題左右兩端會被畫出畫面外")

    # ---------- L2 像素層(端到端畫一張真的卡) ----------
    out = Path(__file__).resolve().parent / "_check_frames"
    out.mkdir(exist_ok=True)
    for name, head in CASES:
        dest = out / f"{name}.png"
        mv.render_candle_card(W, H, big_text=head, watermark="量化阿森",
                              accent=(255, 210, 63), seed=f"chk_{name}", dest=dest)
        im = Image.open(dest).convert("RGB")
        px = im.load()

        def ink_in(x0, x1):
            return sum(1 for x in range(x0, x1) for y in range(H)
                       if min(px[x, y]) >= INK)

        left, right = ink_in(0, EDGE), ink_in(W - EDGE, W)
        middle = ink_in(W // 2 - 60, W // 2 + 60)          # 陰性對照:中段一定要有字
        ok = left == 0 and right == 0 and middle > 0
        print(f"[L2] {'OK ' if ok else 'FAIL'} {name}: 左{EDGE}欄字身像素={left} "
              f"右{EDGE}欄={right} 中段(陰性對照)={middle}")
        if left or right:
            bad.append(f"L2 {name}: 邊緣有字身像素(左{left} 右{right}) = 標題被裁掉")
        if middle == 0:
            bad.append(f"L2 {name}: 中段掃不到任何字身像素 —— 偵測器本身壞了,"
                       f"它在邊緣說「沒有字」不算數")

    print()
    if bad:
        print(f"[結論] FAIL,{len(bad)} 項:")
        for b in bad:
            print(f"  - {b}")
        return 1
    print(f"[結論] OK,{len(CASES)} 個標題 × 2 層全過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
