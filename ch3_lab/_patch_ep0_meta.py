# -*- coding: utf-8 -*-
"""把預告(ep0)接進 publish_meta。

一樣的原則:**同一本 publish_meta、同一支 make_thumbs、同一支 upload。**
它只是第三種 `kind`。

標題刻意把「8 個撐住」放進去,而不是只講「12 個消失」。
兩個理由,都不是文案偏好:
- 只講失敗是**拿一半的事實當全部**,而我自己的資料說 8 個活下來。
- 差異化在這裡。滿坑滿谷的「心理學都是假的」影片,而這支片說得出
  哪 8 個撐住了 —— memory `yt-belief-buster-franchise` 量過同一條。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "publish_meta.py"
ANCHOR = "    # 🔴 被刷掉的要彙總印出來"

BLOCK = '''
    # ── 頻道預告(ep0)──────────────────────────────────────────────
    ep0 = ROOT / "eps_lineup" / "ep0" / "facts.json"
    if ep0.exists():
        T = json.loads(ep0.read_text(encoding="utf-8"))
        nl = chr(10)
        lines = []
        for r in sorted(T["rows"], key=lambda r: (r["bucket"] != "held",
                                                  r["slug"])):
            mark = {"held": "held up", "mixed": "smaller, still there",
                    "fail": "gone"}[r["bucket"]]
            lines.append(f"  {r['slug']:<24} {r['es_r']:+.2f}  "
                         f"{r['n_r']:>7,} people   {mark}")
        desc = (
            f"{T['k']} claims people repeat as fact. We looked up the study "
            f"each one came from, then looked up what happened when somebody "
            f"ran it again.{nl}{nl}"
            f"{T['n_sum']:,} people took part in the replications.{nl}"
            f"{T['gone']} of the claims are gone - the retest could not tell "
            f"them apart from nothing.{nl}"
            f"{T['shrunk']} came back smaller but still measurable.{nl}"
            f"{T['flipped']} went the other way.{nl}"
            f"{T['survived']} held up, {T['stronger']} of them larger than "
            f"the original.{nl}{nl}"
            f"Every episode, with the replication effect size and sample:{nl}"
            + nl.join(lines) + footer_for(2))
        out.append({
            "kind": "trailer", "slug": "ep0", "dir": "eps_lineup/ep0",
            "video": "eps_lineup/ep0/ep0.mp4",
            "thumb": "eps_lineup/ep0/thumb.jpg",
            "tone": "held",
            "title": (f"{T['k']} famous psychology claims, retested on "
                      f"{T['n_sum']:,} people. {T['survived']} held up."),
            "description": desc, "tags": TAGS,
            # 縮圖走 lineup 那條佐證行(講次數與人數,不複述判決)。
            "facts": {"es_o": None, "es_r": None, "n_r": T["n_sum"],
                      "es_kind": "d", "is_replication": True,
                      "k": T["k"], "n_sig": T["survived"]},
        })
        print(f"  ✓ ep0:{out[-1]['title']}")

'''


def main():
    s = P.read_text(encoding="utf-8")
    if '"kind": "trailer"' in s:
        print("已經打過了"); return 0
    assert ANCHOR in s, "找不到錨點"
    P.write_text(s.replace(ANCHOR, BLOCK + ANCHOR, 1), encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("publish_meta 已支援 trailer,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
