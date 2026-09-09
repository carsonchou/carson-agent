# -*- coding: utf-8 -*-
"""突變測試 —— 量這支工具的**靈敏度**,而不是量它有多安靜。

🔴 為什麼需要這支:
手寫語料 12/12 全過,而同一時間真語料上 32 個 CONTRADICTED 有 31 個是誤指控。
那次的教訓是 memory `gate-verification-population`:驗閘門的母體必須是
**會經過它的全部片**,不是我自己想得到的那幾句。

但「誤指控降到 1」還有一個更難看的解釋:工具乾脆不叫了。
CONSISTENT 的條數證明它認得出對的,卻證不了它認得出**錯的**。
所以這裡把母體反過來用:拿真語料裡每一條判成 CONSISTENT 的宣稱,
**把金額改成錯的**,看它叫不叫。

  陽性對照:金額 ×2.73(刻意避開整數倍,免得撞上「翻N倍」的合法讀法)⇒ 應該叫
  陰性對照:金額換成同值的阿拉伯數字寫法 ⇒ 不該叫
           這一項在驗這支測試工具**自己**:證明翻掉的是金額,不是我的字串手術。

用法:python tests/mutation.py [語料根目錄]
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from numerus.check import BARE, CONSISTENT, CONTRADICTED, check_text

DEFAULT_ROOT = os.path.join("D:", os.sep, "carson-agent", "youtube_channel", "output")
FACTOR = 2.73


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


_NUMERAL = set(u"零一二三四五六七八九十百千萬億兩點0123456789")


def swap(seg, raw, text):
    """把 seg 裡的 raw 換成 text。找不到唯一位置就回 None。

    🔴 這個函式是被陰性對照抓出來的。原本用 seg.replace(raw, text, 1),
    而「七十八萬五千元」是「一百七十八萬五千元」的**子字串** ——
    替換打到了另一個數字上,於是「換寫法不換值」竟然翻出 3 個 CONTRADICTED。
    那 3 條不是工具誤判,是量尺自己刻歪了。
    陰性對照的用處就在這裡:它驗的是**測試工具本身**。
    """
    hits = [i for i in range(len(seg))
            if seg.startswith(raw, i) and (i == 0 or seg[i - 1] not in _NUMERAL)]
    if len(hits) != 1:
        return None
    i = hits[0]
    return seg[:i] + text + seg[i + len(raw):]


def verdict_of(seg, target):
    """在這一句裡找到金額≈target 的那條宣稱,回它的判決。"""
    for f in check_text(seg):
        if abs(f.claim.amount - target) <= 1.0:
            return f.verdict
    return "MISSING"      # 改寫後連這條宣稱都抽不出來了


def run(root):
    caught = 0
    ambiguous = 0
    missed = {}
    neg_ok = neg_false = 0
    samples = []

    for dirpath, _, files in os.walk(root):
        for fn in sorted(files):
            if not fn.endswith(".voice.txt"):
                continue
            for f in check_text(read(os.path.join(dirpath, fn))):
                if f.verdict != CONSISTENT:
                    continue
                seg, raw, amt = f.claim.segment, f.claim.raw, f.claim.amount
                if raw not in seg or amt <= 0:
                    continue

                wrong = round(amt * FACTOR)
                mseg = swap(seg, raw, "%d元" % wrong)
                if mseg is None:
                    ambiguous += 1
                    continue
                v = verdict_of(mseg, wrong)
                if v == CONTRADICTED:
                    caught += 1
                else:
                    missed[v] = missed.get(v, 0) + 1
                    if len(samples) < 10:
                        samples.append((v, raw, seg))

                same = round(amt)
                v2 = verdict_of(swap(seg, raw, "%d元" % same), same)
                if v2 == CONTRADICTED:
                    neg_false += 1
                else:
                    neg_ok += 1

    total = caught + sum(missed.values())
    print("=== 突變測試(母體 = 真語料判成 CONSISTENT 的宣稱)===")
    print("語料:%s" % root)
    print("陽性 注入 %d 條錯誤金額:抓到 %d → 靈敏度 %.1f%%"
          % (total, caught, 100.0 * caught / max(total, 1)))
    for v, n in sorted(missed.items(), key=lambda kv: -kv[1]):
        print("       漏掉 %-12s %d 條 (%.1f%%)" % (v, n, 100.0 * n / max(total, 1)))
    print("跳過(宣稱字串在句中不唯一,換不安全):%d 條" % ambiguous)
    print("陰性 換寫法不換值 %d 條:誤指控 %d → 誤報率 %.1f%%"
          % (neg_ok + neg_false, neg_false,
             100.0 * neg_false / max(neg_ok + neg_false, 1)))
    print("\n=== 漏掉的樣本(這些是已知的天花板,不是待修的 bug)===")
    for v, raw, seg in samples:
        print("  [%s] %s\n      %s" % (v, raw, seg[:90]))
    return caught, total, neg_false


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    if not os.path.isdir(root):
        print("語料目錄不存在:%s" % root)
        sys.exit(2)
    run(root)
