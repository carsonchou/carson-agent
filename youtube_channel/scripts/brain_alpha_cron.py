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
    """還有幾個欄位沒被一階掃過。決定這一輪要跑哪個階段。"""
    try:
        sys.path.insert(0, str(BRAIN))
        import brain_auto as B
        import field_miner as FM
        led = B.load_ledger()
        n = 0
        for _ds, f, _cov, _ac in FM.load_fields():
            if B._key(FM.TEMPLATE.format(F=f), FM.SETTINGS) not in led:
                n += 1
        return n
    except Exception as e:  # noqa: BLE001
        print(f"[cron] 判斷階段失敗：{e}", file=sys.stderr)
        return -1


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

    # 三段式,依「期望產出」排序而不是依階段編號：
    #   二階（已知有礦的欄位做全面變化）命中率約 15%，
    #   一階（盲掃新欄位）約 1% —— 所以二階優先，掃完才回頭補一階。
    left2 = unscanned_second_order()
    if left2 > 0:
        target, phase = BRAIN / "second_order.py", f"二階組合爆炸（剩 {left2} 條，命中率高）"
    else:
        left = unscanned_fields()
        if left > 0:
            target, phase = BRAIN / "field_miner.py", f"一階全欄位掃描（剩 {left} 個欄位）"
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
