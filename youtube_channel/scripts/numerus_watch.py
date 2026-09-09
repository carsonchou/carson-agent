#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""numerus_watch.py — 同段可驗算檢查(只報告不阻斷)。

掃 output/ 的旁白稿,找「稿子自己寫的金額」和「用同一段自己給的數字算出來的金額」
對不起來的地方,寫成旗標檔。**不擋任何東西、不搬任何檔、永遠 exit 0。**

## 為什麼是只報告不阻斷(2026-09-09 裁示)
三個母體量完:
  ① 新增被擋 = 0/817(拿同一批輸入跑「有閘門/無閘門」兩次做差,不是跑一次數擋幾支)
  ② 定義域 = 922 支,其中 BARE 897 —— BARE 當閘門等於停產
  ③ 突變測試靈敏度 86.0%,陰性對照 0 誤報
①=0 ⇒ 接上去安全。但全母體唯一那支 CONTRADICTED 已經不在出貨路徑上
⇒ **「安全」證明了,「有用」還沒有。** 在它抓到一支真的會出貨的之前,不給它擋產出的權力。
升級成阻斷的判準寫在 solo_saas/GATE_UPGRADE_CRITERIA.md,**在抓到之前就寫好了**。

## 這支為什麼存在(而不是直接在 crontab 寫 solo_saas/watch.py)
🔴 `scripts/local_cron.py:275` 的解析器是 `r"(scripts/[A-Za-z0-9_]+\.py)"` ——
   只認 `scripts/X.py`。寫成別的路徑,排程器會**靜默略過**,而不會報錯。

輸出:STUDIO/numerus_flags.json(照 fact_guard.py 的形狀:覆寫單檔、原子寫入)
      solo_saas/ledger.json(累積帳本,升級判準讀這本)
"""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SOLO = ROOT.parent / "solo_saas"
FLAGS = ROOT / "STUDIO" / "numerus_flags.json"


def save_atomic(path, data):
    """🔴 tmp → 讀回 → os.replace。memory write-truncates-before-it-fails:
    open(p,"w") 先截斷後寫入,中途拋例外原檔剩 0 bytes,而空旗標檔對下游是
    合法的「零筆」= 零訊號。"""
    tmp = str(path) + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    json.load(io.open(tmp, encoding="utf-8"))
    os.replace(tmp, str(path))


def main():
    if not SOLO.exists():
        print("[warn] 找不到 %s,跳過(不視為錯誤)" % SOLO)
        return 0
    sys.path.insert(0, str(SOLO))
    try:
        from numerus.check import CONTRADICTED, check_text   # noqa
        import watch
    except Exception as e:
        print("[warn] numerus 載入失敗,跳過:%r" % (e,))
        return 0   # 🔴 只報告的東西壞掉不可以害到產線

    # 🔴 整段都包在 try 裡。獨立驗證抓到的:原本 flagged 迴圈和 save_atomic 在
    # try 外面,於是有兩個確定會 exit 1 的輸入 ——(A)帳本裡有一條缺 closest
    # 或 gate_context 的舊紀錄 → KeyError;(B)STUDIO/ 不存在 → FileNotFoundError。
    # 「永遠 exit 0」寫在 docstring 和 crontab 註解裡,那句話當時是錯的。
    try:
        watch.CORPUS = str(ROOT / "output")
        watch.do_scan()
        d, _exists = watch.load()

        flagged = {}
        for f in d["findings"].values():
            # 給人看的那頁只列**第一次看到時**就在出貨路徑上的。用 first_context
            # 不用當下位置,理由見 solo_saas/watch.py do_scan()。
            if f.get("first_context", f.get("gate_context")) != "PASSING":
                continue
            flagged[f.get("slug", "?")] = {
                "claim": f.get("claim"), "script_says": f.get("script_says"),
                "same_paragraph_computes_to": f.get("closest"),
                "human_verdict": f.get("human_verdict"),
                "current_context": f.get("current_context"),
            }
        # 🔴 正向輸出,不是「有事才響」。空的 flagged 有兩種讀法:掃過了沒事、
        # 或這支根本沒跑/壞了。所以一定要有 scanned —— 它是 0 的時候才是壞了。
        scanned = sum(1 for _r, _d, fs in os.walk(str(ROOT / "output"))
                      for fn in fs if fn.endswith(".voice.txt"))
        FLAGS.parent.mkdir(parents=True, exist_ok=True)
        save_atomic(FLAGS, {
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scanned": scanned,
            "contradicted_total": len(d["findings"]),
            "flagged": flagged,
            "note": "只報告不阻斷。升級成阻斷的判準見 solo_saas/GATE_UPGRADE_CRITERIA.md,"
                    "現況用 python solo_saas/watch.py --status 查。",
        })
    except Exception as e:
        print("[warn] numerus 掃描/寫檔失敗,跳過:%r" % (e,))
        return 0

    print("[ok] numerus:出貨路徑上的 CONTRADICTED %d 支 → %s"
          % (len(flagged), FLAGS.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
