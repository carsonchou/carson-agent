# -*- coding: utf-8 -*-
"""把 domains 集型接進 publish_meta + make_thumbs。

第四種 `kind`,一樣不另開一本 metadata、不另寫一支縮圖工具。

標題必須含 `10000 hour rule` —— 這一集之所以被做出來,就是因為那個
查詢詞在 effect_scan 拿到 24,311 分(22 個候選第一名,第二名的 2.3 倍)。
標題不含它 = 需求測試白做。今晚 social_priming 已經犯過一次。
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
ANCHOR = "    # 🔴 被刷掉的要彙總印出來"

BLOCK = '''
    # ── 跨領域(domains)────────────────────────────────────────────
    dom_dir = ROOT / "eps_domain"
    if dom_dir.exists():
        import plain as _plain
        for d in sorted(dom_dir.glob("*")):
            fj = d / "facts.json"
            if not (fj.exists() and (d / f"{d.name}.mp4").exists()):
                continue
            E = json.loads(fj.read_text(encoding="utf-8"))
            T, O = E["test"], E["original"]
            key = f"eps_domain/{d.name}"
            if not _plain.spoken(key):
                print(f"  ⛔ {d.name}:缺手寫白話句,跳過"); continue
            by = {x["name"]: x for x in T["domains"]}
            nl = chr(10)
            best = max(T["domains"], key=lambda x: x["pct"])
            worst = min(T["domains"], key=lambda x: x["pct"])
            title = (f"The {E['popular_name'].replace('the ', '')}: practice "
                     f"explained {best['pct']}% in {best['name']}, "
                     f"{by['education']['pct']}% in education, "
                     f"under {worst['pct']}% in {worst['name']}.")
            rows = nl.join(
                f"  {x['name']:<12} "
                f"{('<' if x.get('pct_is_upper_bound') else '')}{x['pct']}%"
                for x in T["domains"])
            desc = (
                f"{_plain.spoken(key)}{nl}{nl}"
                f"{T['year']} meta-analysis, {T['title']}{nl}"
                f"doi:{T['doi']}{nl}{nl}"
                f"Percent of the variance in performance explained by "
                f"deliberate practice:{nl}{rows}{nl}{nl}"
                f"Quoted from the abstract:{nl}\\"{T['quote']}\\"{nl}{nl}"
                f"The authors' own conclusion:{nl}\\"{T['verdict_quote']}\\"{nl}{nl}"
                f"The claim being tested comes from {O['title']} "
                f"({O['year']}), doi:{O['doi']}, cited {O['cited_by']:,} "
                f"times (OpenAlex).{nl}"
                f"Note: this meta-analysis reports variance explained, not "
                f"an effect size in d or r, so no d or r is shown anywhere "
                f"in this video." + footer_for(2))
            out.append({
                "kind": "domains", "slug": d.name, "dir": key,
                "video": f"{key}/{d.name}.mp4",
                "thumb": f"{key}/thumb.jpg",
                "tone": E.get("tone", "shrunk_real"),
                "title": title, "description": desc, "tags": TAGS,
                "facts": {"es_o": None, "es_r": None,
                          "n_r": None, "es_kind": "pct",
                          "is_replication": False,
                          "k": len(T["domains"]), "k_word": "domains",
                          "pct_best": best["pct"], "pct_worst": worst["pct"],
                          "best": best["name"], "worst": worst["name"]},
            })
            print(f"  ✓ {d.name}:{title}")

'''

THUMB_OLD = '''    if o.get("kind") == "trailer":'''
THUMB_NEW = '''    if o.get("kind") == "domains":
        # 跨領域集沒有效果量,也沒有「重測了幾個人」——它的證據是
        # **同一個宣稱在不同領域解釋掉多少**。硬套 SCALE 會印出
        # 「Retested on None people」。
        word = f"<{f['pct_worst']}% AT WORK"
        sub = " · ".join(f"{x['name']} {x['pct']}%"
                         for x in _dom_rows(o))
    elif o.get("kind") == "trailer":'''

HELPER = '''
def _dom_rows(o):
    """跨領域集的每個領域。從 facts.json 讀,不從說明欄回推。"""
    import json as _j
    p = ROOT / o["dir"] / "facts.json"
    return _j.loads(p.read_text(encoding="utf-8"))["test"]["domains"]


'''


def main():
    pm = HERE / "publish_meta.py"
    s = pm.read_text(encoding="utf-8")
    if '"kind": "domains"' not in s:
        assert ANCHOR in s
        pm.write_text(s.replace(ANCHOR, BLOCK + ANCHOR, 1), encoding="utf-8")
        print("publish_meta 已支援 domains")

    mt = HERE / "make_thumbs.py"
    t = mt.read_text(encoding="utf-8")
    if '"kind") == "domains"' not in t:
        assert THUMB_OLD in t, "找不到 trailer 分支"
        t = t.replace(THUMB_OLD, THUMB_NEW, 1)
        t = t.replace("def draw(plt, o, out_path):",
                      HELPER.lstrip("\n") + "def draw(plt, o, out_path):", 1)
        mt.write_text(t, encoding="utf-8")
        print("make_thumbs 已支援 domains")

    # 白話主張(不能有數字)
    p = HERE / "facts" / "plain_claims.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["eps_domain/10000_hour_rule"] = {
        "lines": ["PRACTICE IS WHAT", "SEPARATES THE BEST"],
        "spoken": "Is how much you practise what separates the best?",
    }
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    import py_compile
    py_compile.compile(str(pm), doraise=True)
    py_compile.compile(str(mt), doraise=True)
    print("語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
