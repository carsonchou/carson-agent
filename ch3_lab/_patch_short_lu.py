# -*- coding: utf-8 -*-
"""make_short 加第三條取材路徑:效應家族(lineup)。

現有兩條是 `--row`(FReD 單列)和 `--slug`(名案)。家族集兩條都不是:
它的事實在 `eps_lineup/<家族>/facts.json`,而且它的賣點是**次數**
(6 種做法、12 次重測),不是某一篇的效果量。

## 不新增第四支檔案
Short 的畫面、TTS、安全區斷言全部在 make_short 裡,家族集要的畫面
跟名案完全一樣(主張 → 判決卡 → 數字)。差別只在數字從哪裡讀。
所以這裡只加一個分支,不是再抄一份 make_short。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "make_short.py"

OLD = """    eps = json.loads((ROOT / "facts" / "famous_episodes.json")
                     .read_text(encoding="utf-8"))["episodes"]
    E = next(e for e in eps if e["slug"] == slug)"""

NEW = '''    lu = ROOT / "eps_lineup" / str(slug) / "facts.json"
    if lu.exists():
        from make_episode import CARD_TEXT, TONE_META, say_num as lsay
        L = json.loads(lu.read_text(encoding="utf-8"))
        pc = _plain(f"eps_lineup/{slug}")
        # 家族集的定調是**數出來的**,不是判出來的:有幾個重測達到
        # p<0.05。0 個就是 gone,不需要再過一次 tone_of —— 那支是為
        # 「單一效應」寫的,拿家族的中位數餵它是把兩件事混在一起。
        tone = "gone" if L["n_sig"] == 0 else "shrunk_real"
        return {
            "key": slug,
            "question": pc["spoken"],
            "claim_lines": pc["lines"],
            "has_original": True,
            "es_o": L["eo_med"], "es_r": L["er_med"],
            "n_o": L["no_sum"], "n_r": L["nr_sum"],
            "say_o": lsay(L["eo_med"]), "say_r": lsay(L["er_med"]),
            "k": L["k"], "k_word": "replications",
            "k_distinct": L["k_distinct"], "n_sig": L["n_sig"],
            "card": CARD_TEXT[tone], "tone": tone,
            "color": BUCKET_COLOR[TONE_META[tone]["bucket"]],
            "has_full": _has_full(f"eps_lineup/{slug}"),
            "source": L["source"],
        }

    eps = json.loads((ROOT / "facts" / "famous_episodes.json")
                     .read_text(encoding="utf-8"))["episodes"]
    E = next(e for e in eps if e["slug"] == slug)'''


def main():
    s = P.read_text(encoding="utf-8")
    if "eps_lineup" in s:
        print("已經打過了"); return 0
    assert OLD in s, "找不到名案分支"
    P.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("make_short 已支援 lineup,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
