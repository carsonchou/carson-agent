# -*- coding: utf-8 -*-
"""把 `arc: outcomes` 接進 publish_meta 與 make_thumbs。

跨領域(domains)與多結果(outcomes)共用 `kind: "domains"`,因為它們的
發布形狀一樣(沒有 n_r、數字不是效果量對比)。差別只在 facts 裡是
`domains`(百分比)還是 `outcomes`(每個結果的 d 與 p)。

標題必須含 `power posing` —— 那個查詢詞在 effect_scan 拿到 9,484 分。
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent

PM_OLD = '''            by = {x["name"]: x for x in T["domains"]}
            nl = chr(10)
            best = max(T["domains"], key=lambda x: x["pct"])
            worst = min(T["domains"], key=lambda x: x["pct"])'''

PM_NEW = '''            nl = chr(10)
            if E.get("arc") == "outcomes":
                outs = T["outcomes"]
                kept = [x for x in outs if x["sig"]]
                title = (f"{E['popular_name'].capitalize()}: they measured "
                         f"{len(outs)} things on {t_n(T)} people. "
                         f"{len(kept)} came back.")
                rows = nl.join(
                    f"  {x['name']:<20} d = {x['d']:+.2f}   p = "
                    f"{x['p']:.3f}   "
                    f"{'significant' if x['sig'] else 'not significant'}"
                    for x in outs)
                desc = (
                    f"{_plain.spoken(key)}{nl}{nl}"
                    f"The original: {O['title']} ({O['year']}), "
                    f"n = {O['n']}, doi:{O['doi']}{nl}"
                    f"The replication: {T['title']} ({T['year']}), "
                    f"n = {T['n']}, doi:{T['doi']}{nl}{nl}"
                    f"What the replication found:{nl}{rows}{nl}{nl}"
                    f"Quoted from the replication:{nl}"
                    + nl.join('  "' + x["quote"] + '"' for x in outs) + nl
                    + f'  "{T["extra_quote"]}"{nl}{nl}'
                    f"The authors' own summary:{nl}"
                    f'"{T["verdict_quote"]}"{nl}{nl}'
                    f"On statistical power:{nl}"
                    f'"{T["power_quote"]}"') + footer_for(2)
                out.append({
                    "kind": "domains", "slug": d.name, "dir": key,
                    "video": f"{key}/{d.name}.mp4",
                    "thumb": f"{key}/thumb.jpg",
                    "tone": E.get("tone", "shrunk_real"),
                    "title": title, "description": desc, "tags": TAGS,
                    "facts": {"es_o": None, "es_r": None, "n_r": None,
                              "es_kind": "d", "is_replication": True,
                              "k": len(outs), "k_word": "outcomes",
                              "n_kept": len(kept), "arc": "outcomes"},
                })
                print(f"  ✓ {d.name}:{title}")
                continue
            by = {x["name"]: x for x in T["domains"]}
            best = max(T["domains"], key=lambda x: x["pct"])
            worst = min(T["domains"], key=lambda x: x["pct"])'''

HELPER = '''
def t_n(T):
    """重測人數。**沒有就回報沒有,不要填 0。**"""
    n = T.get("n")
    if n is None:
        raise SystemExit("⛔ outcomes 集缺 test.n —— 標題會講一個假數字")
    return f"{int(n):,}"


'''

TH_OLD = '''def _dom_rows(o):
    """跨領域集的每個領域。從 facts.json 讀,不從說明欄回推。"""
    import json as _j
    p = ROOT / o["dir"] / "facts.json"
    return _j.loads(p.read_text(encoding="utf-8"))["test"]["domains"]'''

TH_NEW = '''def _dom_rows(o):
    """跨領域集的每一列。從 facts.json 讀,不從說明欄回推。

    兩種形狀:`domains`(百分比)與 `outcomes`(每個結果的 d 與 p)。
    回傳 (是不是 outcomes, 列)。
    """
    import json as _j
    E = _j.loads((ROOT / o["dir"] / "facts.json").read_text(encoding="utf-8"))
    T = E["test"]
    if E.get("arc") == "outcomes":
        return True, T["outcomes"]
    return False, T["domains"]'''

TH_WORD_OLD = '''        word = f"<{f['pct_worst']}% AT WORK"'''
TH_WORD_NEW = '''        if f.get("arc") == "outcomes":
            # 判決字講**哪一個活下來**,不是「全部沒重現」——四個裡有一個
            # 顯著,講成全滅是過度宣稱,而且跟說明欄引的原文矛盾。
            word = f"{f['n_kept']} OF {f['k']} HELD"
        else:
            word = f"<{f['pct_worst']}% AT WORK"'''

TH_SUB_OLD = '''        # 寫法從 make_domains 匯入 —— 一個規則一份實作。
        from make_domains import fmt_pct
        sub = " · ".join(f"{x['name']} {fmt_pct(x)}" for x in _dom_rows(o))'''
TH_SUB_NEW = '''        # 寫法從 make_domains 匯入 —— 一個規則一份實作。
        is_out, rows = _dom_rows(o)
        if is_out:
            sub = " · ".join(
                f"{x['name']} {'held' if x['sig'] else 'no'}" for x in rows)
        else:
            from make_domains import fmt_pct
            sub = " · ".join(f"{x['name']} {fmt_pct(x)}" for x in rows)'''


def main():
    pm = HERE / "publish_meta.py"
    s = pm.read_text(encoding="utf-8")
    if "arc\") == \"outcomes\"" not in s:
        assert PM_OLD in s, "找不到 domains 的標題段"
        s = s.replace(PM_OLD, PM_NEW, 1)
        s = s.replace("\ndef footer_for(", HELPER + "\ndef footer_for(", 1)
        pm.write_text(s, encoding="utf-8")
        print("publish_meta 已支援 outcomes")

    mt = HERE / "make_thumbs.py"
    t = mt.read_text(encoding="utf-8")
    if "is_out, rows" not in t:
        for old, new, what in ((TH_OLD, TH_NEW, "_dom_rows"),
                               (TH_WORD_OLD, TH_WORD_NEW, "判決字"),
                               (TH_SUB_OLD, TH_SUB_NEW, "佐證行")):
            assert old in t, f"找不到:{what}"
            t = t.replace(old, new, 1)
        mt.write_text(t, encoding="utf-8")
        print("make_thumbs 已支援 outcomes")

    p = HERE / "facts" / "plain_claims.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["eps_domain/power_posing"] = {
        "lines": ["STAND LIKE THIS", "AND BECOME MORE POWERFUL"],
        "spoken": "Does standing in a powerful pose make you more powerful?",
    }
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    import py_compile
    py_compile.compile(str(pm), doraise=True)
    py_compile.compile(str(mt), doraise=True)
    print("語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
