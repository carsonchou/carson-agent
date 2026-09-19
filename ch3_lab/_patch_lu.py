# -*- coding: utf-8 -*-
"""把 lineup 支援打進 publish_meta.py。

⚠️ **這支必須用 Write 工具建檔** —— 內容含 \\n 這種反斜線序列,
用 heredoc 餵的話 shell 會把 `\\\\n` 吃成 `\\n`,寫進去就是**真的換行**,
於是 Python 源碼變成 `items = "` 加換行 = 語法錯。
今天這是第五次踩同一個坑,memory 裡早就記著了(heredoc-backslash-escaping-trap)。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "publish_meta.py"
ANCHOR = "    # 🔴 被刷掉的要彙總印出來"
HEAD = "    # ── 效應家族(lineup)"

BLOCK = '''
    # ── 效應家族(lineup)────────────────────────────────────────────
    # 🔴 走**同一本 publish_meta**、同一支 make_thumbs、同一支 upload。
    #    新集型最容易做的事是配一套自己的 metadata/縮圖/發布 —— 那正是
    #    這條線今天修了一整天的病(同一件事多份實作,已經第九次)。
    #    所以它只是多一種 `kind`,不是多一條產線。
    lu_dir = ROOT / "eps_lineup"
    if lu_dir.exists():
        import plain as _plain
        from make_lineup import FAMILIES as _FAM
        for fam in _FAM:
            fj = lu_dir / fam / "facts.json"
            if not fj.exists():
                continue
            L = json.loads(fj.read_text(encoding="utf-8"))
            key = "eps_lineup/" + fam
            q = _plain.spoken(key)
            if not q:
                print(f"  ⛔ {fam}:缺手寫白話句,跳過")
                continue
            # 標題:白話問句 + 規模。**不放效果量** —— 小數對滑過去的人
            # 不構成訊息(今天已經在四個表面上證明過)。規模才是這集的賣點:
            # 不是「一個研究沒重現」,是「整條研究路線 k 個裡 0 個」。
            tail = (f" {L['k']} replications, {L['nr_sum']:,} people, "
                    f"{L['n_sig']} worked.")
            title = q + tail
            if len(title) > 100:
                title = f"{L['name']}: {L['k']} replications, {L['n_sig']} worked."
            rows = []
            for it in L["items"]:
                cite = ("  doi:" + it["doi_r"]) if it.get("doi_r") else ""
                rows.append(f"  {it['claim'][:96]}")
                rows.append(f"    {es_fmt(it['eo'])} on {n_fmt(it['no'])} -> "
                            f"{es_fmt(it['er'])} on {n_fmt(it['nr'])}{cite}")
            items = chr(10).join(rows)
            nl = chr(10)
            desc = (
                f"{q}{nl}{nl}"
                f"{L['name']}: {L['k']} replications drawn from "
                f"{L['papers_r']} replication papers, {L['nr_sum']:,} "
                f"participants in total against {L['no_sum']:,} in the "
                f"originals.{nl}"
                f"Original effect sizes ran {es_fmt(L['eo_lo'])} to "
                f"{es_fmt(L['eo_hi'])} (median {es_fmt(L['eo_med'])}); the "
                f"replications ran {es_fmt(L['er_lo'])} to "
                f"{es_fmt(L['er_hi'])} (median {es_fmt(L['er_med'])}).{nl}"
                f"{L['n_sig']} of the {L['n_p']} replications that report a "
                f"p-value reached p < 0.05.{nl}{nl}"
                f"Every row on screen:{nl}{items}{nl}{nl}"
                f"Source: {L['source']}") + footer_for(2)
            out.append({
                "kind": "lineup", "slug": fam, "dir": key,
                "video": f"{key}/{fam}.mp4",
                "thumb": f"{key}/thumb.jpg",
                "tone": "gone" if L["n_sig"] == 0 else "shrunk_real",
                "title": title, "description": desc, "tags": TAGS,
                "facts": {"es_o": L["eo_med"], "es_r": L["er_med"],
                          "n_o": L["no_sum"], "n_r": L["nr_sum"],
                          "es_kind": L["es_kind"], "is_replication": True,
                          "k": L["k"], "n_sig": L["n_sig"], "n_p": L["n_p"]},
            })
            print(f"  ✓ {fam}:{title}")

'''


def main():
    s = P.read_text(encoding="utf-8")
    # 先把上一版(被 heredoc 弄壞的)整段拿掉,再貼正確的。
    if HEAD in s:
        i = s.index(HEAD)
        j = s.index(ANCHOR, i)
        s = s[:i] + s[j:]
        print("已移除壞掉的舊區塊")
    if ANCHOR not in s:
        print("⛔ 找不到錨點,沒有改動")
        return 1
    s = s.replace(ANCHOR, BLOCK + ANCHOR, 1)
    P.write_text(s, encoding="utf-8")
    # 🔴 寫完自己驗一次語法。今天有三次「寫入成功」但檔案是壞的。
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("publish_meta.py 已支援 lineup,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
