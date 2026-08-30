# -*- coding: utf-8 -*-
"""所有送進 YouTube metadata 的文字都要過一次清洗 + fail-closed 斷言。

## 為什麼(2026-08-30 實測,只有真的打 API 才會現形)
`videos.insert` 對標題與說明裡的 `<` 與 `>` 回 **HTTP 400**。實測一次送 5 支
Shorts,兩支被擋:

    10000_hour_rule   說明裡有 `professions: <1%`
    social_priming    說明裡有 `p < 0.05` 與 `0.80 on 30 -> 0.02 on 6,340`
    power_posing      兩個都沒有 → 成功

而且掃過去發現**還有一支沒發的長片 `eps/ep007` 也會炸**,原因更棘手:
它引用的論文 DOI **本身就含角括號** ——

    10.1002/(sici)1099-0771(200001/03)13:1<1::aid-bdm333>3.0.co;2-s

那是 Wiley 的 SICI 格式,不能改寫語意。只能百分比編碼(`%3C` / `%3E`),
而 doi.org 照樣解析得到。

## 三種來源三種處理
1. **DOI 裡的**:百分比編碼。改寫成文字會讓那個 DOI 查不到。
2. **數學比較**:`p < 0.05` → `p less than 0.05`,`<1%` → `under 1%`。
3. **箭頭**:`->` → `to`。

## 最後一定要斷言
清洗完再掃一次,還有角括號就**中止**。這條線的模式是「修在一條路上,
而實際走的是另一條」—— 清洗函式可以漏掉新的來源,斷言不會。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent

FN = '''
_DOI_ANGLE = re.compile(r"(doi:\\S*?)([<>])")


def api_safe(text, where=""):
    """把文字清成 YouTube metadata 收得下的樣子。**fail-closed。**

    🔴 `videos.insert` 對標題/說明裡的 `<` `>` 回 HTTP 400(2026-08-30 實測,
    一次送 5 支被擋 2 支)。而角括號有三種來源,處理方式不一樣:

    - **DOI 裡的**(Wiley SICI 格式,例如
      `10.1002/(sici)1099-0771(200001/03)13:1<1::aid-bdm333>3.0.co;2-s`)
      → 百分比編碼。改寫成文字會讓那個 DOI 查不到,而 DOI 是這條線
      唯一叫觀眾去驗證的東西。
    - **數學比較**(`p < 0.05`、`<1%`)→ 改成文字,意思一樣而且更好唸。
    - **箭頭**(`->`)→ `to`。

    清完再斷言一次:還有角括號就中止。清洗函式會漏掉新的來源,斷言不會。
    """
    s = text
    # 1) DOI 內的角括號:百分比編碼(反覆做到沒有為止,一個 DOI 可能兩個)
    for _ in range(8):
        new = _DOI_ANGLE.sub(
            lambda m: m.group(1) + ("%3C" if m.group(2) == "<" else "%3E"), s)
        if new == s:
            break
        s = new
    # 2) 箭頭與比較
    s = s.replace(" -> ", " to ").replace("->", " to ")
    s = s.replace("< ", "less than ").replace(" <", " less than ")
    s = s.replace("> ", "more than ").replace(" >", " more than ")
    s = s.replace("<", "under ").replace(">", "over ")
    # 3) 斷言
    if "<" in s or ">" in s:
        raise SystemExit(
            f"⛔ {where} 的 metadata 清洗後仍有角括號 —— YouTube 會回 400。"
            f"不出片。原文片段:{text[:80]}")
    return s

'''


def main():
    pm = HERE / "publish_meta.py"
    s = pm.read_text(encoding="utf-8")
    if "def api_safe(" not in s:
        anchor = "\ndef footer_for(n_papers):"
        assert anchor in s
        s = s.replace(anchor, FN + anchor, 1)
        # 出口統一清洗:所有 out.append 的 title/description
        old = "    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),"
        assert old in s, "找不到寫檔處"
        s = s.replace(old,
                      "    # 🔴 **出口統一清洗。** 逐個生成點去修會漏 ——\n"
                      "    #    今天就漏了三個不同來源(百分比上界、箭頭、"
                      "DOI 裡的角括號)。\n"
                      "    for _o in out:\n"
                      "        _o[\"title\"] = api_safe(_o[\"title\"], "
                      "_o.get(\"slug\") or _o[\"dir\"])\n"
                      "        _o[\"description\"] = api_safe(\n"
                      "            _o[\"description\"], _o.get(\"slug\") or "
                      "_o[\"dir\"])\n" + old, 1)
        pm.write_text(s, encoding="utf-8")
        print("publish_meta 已加 api_safe 與出口清洗")

    ps = HERE / "publish_shorts.py"
    t = ps.read_text(encoding="utf-8")
    if "api_safe" not in t:
        old = "    return {\"key\": d.name, \"video\": str(mp4.relative_to(ROOT)),"
        assert old in t, "找不到 famous_meta 的回傳"
        t = t.replace(old,
                      "    from publish_meta import api_safe\n"
                      "    title, desc = api_safe(title, d.name), "
                      "api_safe(desc, d.name)\n" + old, 1)
        t = t.replace('"title": title, "description": desc, "tags": TAGS,\n'
                      '            "tone": "famous"}',
                      '"title": title, "description": desc, "tags": TAGS,\n'
                      '            "tone": "famous"}')
        ps.write_text(t, encoding="utf-8")
        print("publish_shorts 的名案路徑已清洗")

    import py_compile
    for f in (pm, ps):
        py_compile.compile(str(f), doraise=True)
    print("語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
