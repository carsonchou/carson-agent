#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_alpha_cron.py — 排程轉接器：驅動 BRAIN alpha 挖礦。

## 為什麼需要這支
`local_cron.py` 的解析器只認 `scripts/X.py` 格式，所以排程進得來的腳本必須放在
`youtube_channel/scripts/` 底下。但量化程式不該搬進影片產線目錄 —— 這支只做轉接，
真正的邏輯在 `quant-service/brain_alpha/`。

## 2026-08-27：改成兩段式，而且會自己接續
原本只呼叫 `brain_auto.py --run 15`（手寫模板）。問題是：
  · 手寫模板只用了 4,367 個可用欄位裡的 15 個 —— **覆蓋率 0.34%**
  · 一批跑完就停，沒有東西讓它繼續

改成：
  **第一階段** `field_miner.py` —— 一個實測模板（Sharpe 2.25 那個）套遍全欄位，
     依「最沒人挖的優先」排序。目的是找出**哪些欄位本身有訊號**。
  **第二階段** `brain_auto.py` —— 全欄位掃完後，才對有訊號的欄位做參數／運算子變化。

每 2 小時跑一批，跑完自動接續，不需要人。

## 已知硬限（實測，別再試）
· 併發上限 **2**（第 3 條回 429）—— 多重模擬是顧問專屬功能
· region 只有 **USA** 可用（EUR/ASI/CHN/GLB/JPN/KOR/TWN/HKG/AMR 全回 400）
· 每日積分上限 **2,000**（官方 Challenge 規則）
→ 吞吐天花板約 600~950 條/天，這是平台端的限制不是程式的。
"""
from __future__ import annotations

import io
import json
import runpy
import sys
from pathlib import Path

BRAIN = (Path(__file__).resolve().parent.parent.parent
         / "quant-service" / "brain_alpha")


def unscanned_fields() -> int:
    """還有幾個欄位沒被一階掃過。決定這一輪要跑哪個階段。

    ⚠️ 例外時回 **1 而不是 -1**（2026-08-29 修）。
    舊版回 -1 → `left > 0` 不成立 → **靜默掉回二階**，也就是雙胞胎工廠，
    而那正是 08-28 self-correlation 0.9653 被擋的元凶。
    這是 fail-open：一個無關的小錯（例如我改了 load_fields 的回傳欄位數）
    就能把整條產線導回已知的死路，而且不會有任何訊號。
    → 改成 fail-closed：判斷不出來就**留在一階**（一階最壞情況只是重複掃，
      會被帳本 dedup 擋掉；二階最壞情況是產出一批交不出去的廢稿）。
    """
    try:
        sys.path.insert(0, str(BRAIN))
        import brain_auto as B
        import field_miner as FM
        led = B.load_ledger()
        n = 0
        for row in FM.load_fields(led):
            f, ftype = row[1], row[4]
            for pat in FM.forms_for(ftype).values():
                if B._key(FM.TEMPLATE.format(X=pat.format(F=f)), FM.SETTINGS) not in led:
                    n += 1
        return n
    except Exception as e:  # noqa: BLE001
        print(f"[cron] 判斷階段失敗（fail-closed → 留在一階）：{e}", file=sys.stderr)
        return 1


def unscanned_second_order() -> int:
    """二階還有幾條沒跑。命中率遠高於一階,所以排在前面。"""
    try:
        sys.path.insert(0, str(BRAIN))
        import brain_auto as B
        import second_order as S2
        led = B.load_ledger()
        return sum(1 for _l, e, st in S2.build() if B._key(e, st) not in led)
    except Exception as e:  # noqa: BLE001
        print(f"[cron] 判斷二階失敗：{e}", file=sys.stderr)
        return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    args = sys.argv[1:]
    n = "60"
    if "--run" in args:
        i = args.index("--run")
        if len(args) > i + 1:
            n = args[i + 1]

    # 🔴 2026-08-28 優先序整個翻轉。
    # 事故：`QP7vPrEr` 提交被擋 —— **self-correlation 0.9653 > 0.7**。
    # 原因是它跟同日已交的 `wpjQpqJ6` 只差一個外層變換
    #   （ts_rank vs ts_quantile，同樣是 operating_income/cap）。
    # 進一步盤點：**61 條「候選」拆開只有 7 個獨立 base**，其中 43 條全是
    #   est_eps/close 的變體 —— 二階的「組合爆炸」在**大量生產雙胞胎**。
    #
    # 社群研究兩天前就寫過而我沒應用：
    #   「换窗口、换权重、换 neutralization **不能创造真正的低相关**」
    #   （同簇日收益相關實測 0.74~0.84）
    #
    # → 命中率高（15%）不代表有用：同 base 的第二條交不出去。
    #   真正稀缺的是**獨立的 base**，那只能靠一階掃新欄位。
    # 所以：**一階優先**，二階降為補充（每個 base 只需要一條能交）。
    left = unscanned_fields()
    if left > 0:
        target, phase = BRAIN / "field_miner.py", f"一階全欄位掃描（剩 {left} 個欄位，找獨立 base）"
    else:
        left2 = unscanned_second_order()
        if left2 > 0:
            target, phase = BRAIN / "second_order.py", f"二階補充（剩 {left2} 條）"
        else:
            target, phase = BRAIN / "brain_auto.py", "手寫模板批（前兩階都掃完了）"

    if not target.exists():
        print(f"[cron] 找不到 {target}", file=sys.stderr)
        return 1
    print(f"[cron] {phase} → {target.name} --run {n}")
    sys.argv = [str(target), "--run", n]
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
