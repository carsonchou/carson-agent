"""每個 claim 的 `value`,必須在它自己那句 `verbatim` 裡真的出現過。

🔴 為什麼需要這一格:第一輪的事實查證裡,有一條 `value = 1.5 (Cohen's d)`,
   而它自己附的原句是「(M = 0.67) over ... (M = 0.45) represented about a 50%
   improvement」—— **引文是真的、數字也是真的,但那個數字不是那句話說的**。
   這是 memory `paper-fact-extraction-traps` 講的「同一數字跨來源漂」:
   最難抓,因為每一個零件單獨看都對。

   `make_reel.audit()` 擋不住它 —— audit 問的是「稿子裡的數字有沒有在結構化
   欄位裡」,而這個數字**在**欄位裡。兩道閘門問的是不同的問題:
   audit 問「這個數字有沒有來源」,這一支問「這個來源真的說了這個數字嗎」。

用法:python _check_claim_values.py [檔案...]      預設掃 facts/*claims*.json
"""
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent


def variants(v):
    """同一個值的寫法變體。**只收格式變體,不收別的值。**

    `0.014` 與 `.014`、`50` 與 `50.0` 是同一個數字的兩種寫法;
    `1.5` 與 `1.50` 也是。這裡放寬的是排版,不是數值。
    """
    out = set()
    f = float(v)
    # 🔴 負號在論文原文裡常常是 en dash(`r = –.29`),而不是 ASCII 減號。
    #    只比對帶號的寫法會把一條**正確**的 claim 判成漂移(實測誤擋 1 條)。
    #    ⇒ 連絕對值的寫法一起收。這不放寬數值:0.29 和 -0.29 的差別是方向,
    #      而方向是由 label / what_it_means 講的,不是由這一格守的。
    for s in (f"{f:g}", f"{f:.1f}", f"{f:.2f}", f"{f:.3f}",
              f"{abs(f):g}", f"{abs(f):.1f}", f"{abs(f):.2f}", f"{abs(f):.3f}"):
        s = s.rstrip("0").rstrip(".") if "." in s else s
        out.add(s)
        if s.startswith("0."):
            out.add(s[1:])          # .014
        if float(s) == int(f) if f == int(f) else False:
            out.add(str(int(f)))
    if f == int(f):
        out.add(str(int(f)))
    out.add(f"{f:.2f}")
    out.add(f"{f:.1f}")
    return {x for x in out if x}


def walk(node, path=""):
    """把任何巢狀結構裡長得像 claim 的 dict 撈出來。"""
    if isinstance(node, dict):
        if "value" in node and isinstance(node.get("source"), dict):
            yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def main(argv):
    files = [pathlib.Path(a) for a in argv[1:]] or sorted(
        (ROOT / "facts").glob("*claims*.json"))
    bad, derived, total = [], [], 0
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:                       # noqa: BLE001
            bad.append((f.name, "(整個檔)", f"讀不起來:{e}")); continue
        for path, c in walk(d):
            total += 1
            src = c.get("source") or {}
            vb = (src.get("verbatim") or "")
            if not vb.strip():
                bad.append((f.name, path, "verbatim 是空的")); continue
            try:
                vs = variants(c["value"])
            except (TypeError, ValueError):
                bad.append((f.name, path,
                            f"value 不是數字:{c['value']!r}")); continue
            hits = [v for v in vs
                    if re.search(rf"(?<![0-9.]){re.escape(v)}(?![0-9])", vb)]
            if hits:
                continue
            # 逃生門一:論文把數字**寫成英文字**(「we found only one study」、
            # 「Ninety-four university students」)。那不是漂移,是排版。
            # 但不准用形容詞矇混 ⇒ 要**逐字指出**是哪一段字帶著這個值,
            # 而那段字必須真的在 verbatim 裡。
            as_words = (c.get("value_in_verbatim_as") or "").strip()
            if as_words:
                if as_words in vb:
                    continue
                bad.append((f.name, path,
                            f"value_in_verbatim_as「{as_words}」"
                            f"在 verbatim 裡逐字找不到"))
                continue
            # 逃生門二:這個值是**推導**出來的(例如「這篇一次都沒用過」= 0)。
            # 推導值可以存,但它沒有原句撐著 ⇒ 標記起來,而且**不可入稿**:
            # 旁白不准把它當成論文報出來的數字唸。
            if c.get("value_is_derived") and (c.get("derivation") or "").strip():
                derived.append((f.name, path, c.get("label", "")[:50]))
                continue
            bad.append((f.name, path,
                        f"value={c['value']} 在自己的 verbatim 裡找不到 "
                        f"| label={c.get('label', '')[:40]}"))
    print(f"掃了 {len(files)} 個檔、{total} 條 claim")
    for f, p_, lab in derived:
        print(f"  ⚠️ 推導值(可以存,**不可入稿**):{f} :: {p_} :: {lab}")
    for f, p, why in bad:
        print(f"  ⛔ {f} :: {p} :: {why}")
    if not bad:
        print("  ✓ 每一條的 value 都在自己的 verbatim 裡出現過")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
