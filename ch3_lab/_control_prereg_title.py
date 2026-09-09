"""事前登記標題閘門的陰性/陽性對照。可重跑。

🔴 為什麼這道閘門存在:標題就是這個實驗**唯一被操縱的變數**
   (`that actually work` vs 純裁決)。事前登記檔把 6 個標題逐字寫死,
   而產線原本把它存進 `prereg_title` —— **全 repo 零個讀取者**,
   真正送出去的是 `popular_name: story_type_short` 組出來的另一個字串。
   規則只寫在文件層 = 期望不是規則,而且失效**完全靜默**:
   片子照發、標題照有,只是換了一個,然後我們拿它去讀「措辭」那題的答案。

判準(memory `verification-that-cannot-fail`):
   把被測的機制弄壞,這個對照會不會跟著失敗?答案必須是「會」。
"""
import sys

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import publish_shorts as ps  # noqa: E402

REG = list(ps.prereg_titles())


def run(batch, tag):
    out = ps.prereg_title_gate(batch)
    print(f"  {tag}: {'擋下' if out else '通過'}")
    return bool(out)


def main():
    print(f"登記檔解析到 {len(REG)} 個逐字標題")
    print("陰性對照(六支全用登記的逐字標題,閘門必須安靜):")
    neg = run([{"key": f"reel_{i}", "title": t, "is_prereg": True}
               for i, t in enumerate(REG)], "六支齊全")

    print("陽性對照(每一種都必須被擋下):")
    pos = [
        run([{"key": "reel_x", "title": REG[0] + " ", "is_prereg": True}],
            "尾巴多一個空格(逐字就是逐字)"),
        run([{"key": "reel_x", "title": "Study Techniques That Actually Work",
              "is_prereg": True}], "少了 The Only"),
        run([{"key": "reel_x", "title": "Study Tips Backed By Science",
              "is_prereg": True}], "換成實測 0 勝出的那個措辭"),
        run([{"key": "reel_x",
              "title": "hot hand fallacy: the arithmetic was wrong",
              "is_prereg": True}], "舊產線 popular_name 組出來的那種標題"),
        run([{"key": "a", "title": REG[0], "is_prereg": True},
             {"key": "b", "title": REG[0], "is_prereg": True}],
            "兩支搶同一個登記標題"),
    ]
    ok = (not neg) and all(pos)
    print()
    print("結論:", "✓ 這道閘門會叫,而且不對正確的批次誤叫" if ok
          else "🔴 對照失敗 —— 這道閘門不算數")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
