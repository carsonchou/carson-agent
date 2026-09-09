# -*- coding: utf-8 -*-
"""母體① —— 「新增被擋」是**差集**,不是定義域。

🔴 這支工具存在的理由(memory `gate-verification-population`):
   跑一次有閘門的、數它擋幾支 —— 那量到的是**定義域**(母體②),不是差集。
   要的是「接上這道閘門之後,和**現在**相比多擋了誰」,所以要拿**同一批輸入**
   跑「無閘門/有閘門」兩次做差。

口徑:
   無閘門 = 產線現在的決定。判準 = 稿子落在 output/ 根目錄
            (底線開頭的子目錄 = 已經被現有閘門隔離/退稿的)
   有閘門 = 現在的決定 AND numerus 不判 CONTRADICTED
   ①      = 無閘門放行 ∖ 有閘門放行

用法:python tests/measure_delta.py [語料根目錄]
"""
import io, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from numerus.check import CONTRADICTED, check_text

DEFAULT_ROOT = r"D:\carson-agent\youtube_channel\output"
EXT = ".voice.txt"


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def split_by_existing_gates(root):
    """回傳 (現有閘門放行的, 現有閘門已擋掉的)。"""
    passing, blocked = [], []
    for dirpath, _, filenames in os.walk(root):
        # 根目錄 = 通過了現有全部閘門;底線子目錄 = 已被隔離
        bucket = passing if os.path.relpath(dirpath, root) == "." else blocked
        for fn in sorted(filenames):
            if fn.endswith(EXT):
                bucket.append(os.path.join(dirpath, fn))
    return passing, blocked


def numerus_blocks(paths):
    return [p for p in paths
            if any(f.verdict == CONTRADICTED for f in check_text(read(p)))]


def main(argv):
    root = argv[1] if len(argv) > 1 else DEFAULT_ROOT
    passing, blocked = split_by_existing_gates(root)
    delta = numerus_blocks(passing)
    also = numerus_blocks(blocked)

    print("語料:%s" % root)
    print("  現有閘門放行(output/ 根目錄)  :%d 支" % len(passing))
    print("  現有閘門已擋(底線子目錄)      :%d 支" % len(blocked))
    print()
    print("① 新增被擋(差集)= %d 支  (%.2f%% of %d)"
          % (len(delta), 100.0 * len(delta) / max(len(passing), 1), len(passing)))
    for p in delta:
        print("     " + os.path.basename(p))
    print()
    print("(參考,不算進①)numerus 在**已經被擋掉那批**裡另外找到 %d 支 ——" % len(also))
    print("   它們已經因為別的理由被隔離了,接上這道閘門不會改變它們的命運:")
    for p in also:
        print("     %s\n       目錄:%s"
              % (os.path.basename(p), os.path.relpath(os.path.dirname(p), root)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
