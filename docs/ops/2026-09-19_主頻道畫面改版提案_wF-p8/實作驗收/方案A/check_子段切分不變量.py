# -*- coding: utf-8 -*-
"""方案 A 子段切分的不變量檢查(會叫的檢查,不是註解)。

被檢查的不變量:`_reveal_view_buckets(view, V, N)` 回的清單,必須包含所有
「自己算出來 view 就是這個 view」的 bucket。破了的話 render_ffmpeg._reveal_base
的 `.index(bucket)` 丟 ValueError → 被外層 except 吞掉 → 整片揭露圖靜默退回原卡。

用法: python check_子段切分不變量.py            # 檢查正式碼
      CVIS_DIR=<沙箱scripts> python ...         # 檢查沙箱副本

最後一格是**陽性對照**:故意餵一個壞掉的實作,檢查必須抓到它。
沒有陽性對照的話,「全過」也可能只是這支檢查對什麼都說 OK。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("CVIS_DIR") or r"D:\carson-agent\youtube_channel\scripts")
import render_ffmpeg as rf  # noqa: E402

print("[check] render_ffmpeg <-", rf.__file__)


def assert_invariant(fn, label):
    """對 V=1..5、N=1..16 的所有組合驗不變量。回 True=通過。"""
    for views in range(1, 6):
        for buckets in range(1, 17):
            seen = []
            for view in range(views):
                bs = fn(view, views, buckets)
                seen += bs
                for b in bs:
                    if b * views // buckets != view:
                        print(f"  ✗ {label}: V={views} N={buckets} bucket {b} 被放進 view {view}")
                        return False
            for b in range(buckets):
                if b not in seen:
                    print(f"  ✗ {label}: V={views} N={buckets} bucket {b} 沒有任何 view 收")
                    return False
                if seen.count(b) != 1:
                    print(f"  ✗ {label}: V={views} N={buckets} bucket {b} 被收 {seen.count(b)} 次")
                    return False
    print(f"  ✓ {label}")
    return True


def _broken(view, views, buckets):
    """陽性對照:等分切(把 bucket 平均分給每個 view),V=3 N=8 時 bucket 5 會錯位。"""
    per = buckets // views or 1
    return [b for b in range(view * per, min((view + 1) * per, buckets))]


ok = assert_invariant(rf._reveal_view_buckets, "正式實作")
print("  (以下是陽性對照,必須被抓到)")
caught = not assert_invariant(_broken, "故意寫壞的等分切")

print(f"\n實作通過={ok} 陽性對照有抓到={caught}")
print("V=3 N=8 實際切法:", [rf._reveal_view_buckets(v, 3, 8) for v in range(3)])
sys.exit(0 if (ok and caught) else 1)
