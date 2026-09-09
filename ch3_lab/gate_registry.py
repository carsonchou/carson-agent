#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_registry.py — 閘門與它的對照腳本綁在一起,**而規則的定義就是那份案例清單**。

## 為什麼有這支

2026-09-09 一晚三輪獨立驗證,嚴重度收斂得很陡:
R1「一支都發不出去、登記標題永遠不會出現且完全靜默」→ R2「比較結構無效」→
R3「不影響任何數字,只誤導下一個讀的人」。

🔴 **但同一個形狀三輪三次:規則寫在一個不會產生輸出的位置。**
- **R1** `prereg_title` 存進事實庫,而**全 repo 零個讀取者** —— 送出去的是別的字串
- **R2** 「並附 `display_only_why` —— 靠沉默不算」只寫在**錯誤訊息**裡,程式沒檢查
- **R3** `window_readout` 的 **docstring 描述一個被放棄的設計**(「唯一可靠的判準是數列數」),
  而實作用的是資料視界;執行訊息還宣稱了一個**不存在的檢查**(「列數檢查通過」)

**類型零收斂。** 嚴重度掉得快,是因為每輪都留下一支帶真案例的對照腳本,而對照會累積 ——
收斂的是「同一個錯下次會被自家對照抓到」的覆蓋率,**不是「不再犯這個錯」**。

## 規則

**任何描述閘門行為的文字(docstring / 錯誤訊息 / 判準檔)必須指名它的對照腳本,
而對照腳本的案例清單就是那個規則的唯一定義。**

兩層:
1. 每道閘門宣告真的常數 `CONTROL`(不是註解),meta 檢查驗它存在、跑得動、
   案例清單至少各有一個陰性與一個陽性。
2. **人類可讀的描述由案例清單產生**,寫回 docstring 的標記區塊之間。
   不要人手寫一份、程式跑另一份 —— **產生勝過驗證**,那才讓 R3 結構上不可能發生。

## ⚠️ 這支治不了的

**對照腳本自己的案例清單會過期**(memory `gate-blind-while-target-evolves`)。
這道規則靠對照腳本定義,而**對照腳本需要定期用真案例證明它還抓得到**。
這件事沒有完結,不要讀成完結。

用法:
  python gate_registry.py            # meta 檢查
  python gate_registry.py --sync     # 把產生的描述寫回各 docstring 的標記區塊
<!--GATE-CASES:meta.gate_registry-->
這道閘門(meta.gate_registry)的定義 = 它的對照腳本 _control_gate_registry.py 的案例清單。
實作在 gate_registry.meta_check()。
**它會叫**(陽性,3 種):
  · R1 真形狀:CONTROL 宣告了但沒有任何地方讀它(= prereg_title 零讀取者)
  · R2 真形狀:訊息點名 display_only_why 而程式從來沒讀過它(= 規則只寫在錯誤訊息裡)
  · R3 真形狀:docstring 的產生區塊被換成一個被放棄的設計(= window_readout 的「唯一可靠的判準是數列數」)
**它不該叫**(陰性,1 種):
  · 現況的三道閘門:R1/R2/R3 都不該叫
⚠️ 這份清單會過期。它需要定期用真案例證明它還抓得到。
<!--/GATE-CASES:meta.gate_registry-->
"""
import argparse
import ast
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
#: 🔴 標記帶 gate_id。一個模組可以住兩道閘門(make_reel 就是),
#:    共用一組標記的話,第二道的描述會**覆蓋掉第一道的**,
#:    而覆蓋後 R3 偵測器只會抱怨「對不上」,不會告訴你是被蓋掉的。
def _marks(gate_id):
    return (f"<!--GATE-CASES:{gate_id}-->", f"<!--/GATE-CASES:{gate_id}-->")

#: gate_id → 這道閘門住在哪、它的對照腳本是誰。
#: 🔴 `control` 是**這份註冊表**的一部分,不是註解 —— 它會被程式讀。
GATES = {
    "reel.display_vs_facts": {
        "module": "make_reel", "func": "audit",
        "control": "_control_display_vs_facts.py"},
    "reel.orphan_value": {
        "module": "make_reel", "func": "audit",
        "control": "_control_orphan.py"},
    "publish.prereg_title": {
        "module": "publish_shorts", "func": "prereg_title_gate",
        "control": "_control_prereg_title.py"},
    # 🔴 這支自己也要進註冊表。一道「要求別人有對照」的檢查如果自己沒有對照,
    #    它就是它自己在抓的那個形狀。
    "meta.gate_registry": {
        "module": "gate_registry", "func": "meta_check",
        "control": "_control_gate_registry.py"},
}

#: 🔴 這道閘門「檢查什麼」的定義,在對照腳本的 CASES 清單裡。
CONTROL = "_control_gate_registry.py"


def _load_cases(control):
    """對照腳本必須宣告 `CASES`。**沒有 CASES 的對照腳本不算註冊。**

    🔴 用 **AST 靜態讀**,不 import。對照腳本是拿來**跑**的東西:
       import 它就等於在 meta 檢查裡把整套對照跑一遍,
       而其中一支結尾有 `sys.exit()` —— 那會讓 meta 檢查**靜靜地提早結束**,
       輸出看起來像「跑完了」。**檢查不可以靠執行被測物來讀它的宣告。**
    """
    src = (ROOT / control).read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CASES"
                for t in node.targets):
            cases = ast.literal_eval(node.value)
            if not cases:
                break
            return list(cases)
    raise SystemExit(f"⛔ {control} 沒有 CASES —— 沒有案例清單的對照腳本"
                     f"不能當成一道規則的定義。")


def describe(gate_id):
    """規則的人類可讀描述,**由案例清單產生**。這是唯一的一份。"""
    g = GATES[gate_id]
    cases = _load_cases(g["control"])
    pos = [c for c in cases if c["kind"] == "positive"]
    neg = [c for c in cases if c["kind"] == "negative"]
    out = [f"這道閘門({gate_id})的定義 = 它的對照腳本 {g['control']} 的案例清單。",
           f"實作在 {g['module']}.{g['func']}()。",
           f"**它會叫**(陽性,{len(pos)} 種):"]
    out += [f"  · {c['label']}" for c in pos]
    out += [f"**它不該叫**(陰性,{len(neg)} 種):"]
    out += [f"  · {c['label']}" for c in neg]
    out += ["⚠️ 這份清單會過期。它需要定期用真案例證明它還抓得到。"]
    return "\n".join(out)


# ───────────────────────── 三個偵測器,對應三輪的三個形狀 ─────────────────────────

def detect_r1(src, gate_id):
    """R1:常數宣告了,但**沒有人讀** —— 和 `prereg_title` 零讀取者同型。"""
    tree = ast.parse(src)
    loads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Name) and n.id == "CONTROL"
             and isinstance(n.ctx, ast.Load)]
    has_def = any(isinstance(n, ast.Name) and n.id == "CONTROL"
                  and isinstance(n.ctx, ast.Store) for n in ast.walk(tree))
    if has_def and not loads:
        return (f"CONTROL 宣告了但**沒有任何地方讀它** —— "
                f"和 `prereg_title` 存進沒人讀的欄位是同一個形狀")
    if not has_def:
        return "沒有宣告 CONTROL 常數(必須是真的常數,不是註解)"
    return None


def _keyed_strings(tree):
    """程式**真的拿來取值**的字串:`.get('x')` 與 `d['x']`。"""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("get", "setdefault") and n.args \
                and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str):
            out.add(n.args[0].value)
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                and isinstance(n.slice.value, str):
            out.add(n.slice.value)
    return out


def detect_r2(src, gate_id):
    """R2:錯誤訊息點名了一個欄位,而程式**從來沒去讀它** ——
    和「並附 `display_only_why`,靠沉默不算」同型(規則只寫在訊息裡)。

    🔴 **只掃這道閘門那個函式**,不掃整個模組。第一版掃全模組,
       把別處註解裡的 `make_short`、`link_line` 這類反引號名字當成幽靈欄位,
       對 publish_shorts 誤報四筆 —— 一道會亂叫的 meta 檢查,
       下一個人的處置一定是把它關掉。
    """
    import re
    fn = None
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == GATES[gate_id]["func"]:
            fn = n
            break
    if fn is None:
        return f"找不到函式 {GATES[gate_id]['func']}() —— 註冊表和實作對不上"
    keyed = _keyed_strings(fn)
    named = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            for tok in re.findall(r"`([a-z_][a-z0-9_]{3,})`", n.value):
                named.add(tok)
    ghosts = sorted(t for t in named if t not in keyed)
    if ghosts:
        return (f"這個函式的訊息點名了 {ghosts},而它從來沒有讀過那些欄位 —— "
                f"規則只寫在訊息裡 = 提示層不是規則層")
    return None


def detect_r3(mod_path, gate_id):
    """R3:docstring 的描述**漂走了** —— 和 window_readout 描述一個被放棄的設計同型。"""
    src = pathlib.Path(mod_path).read_text(encoding="utf-8")
    BEGIN, END = _marks(gate_id)
    if BEGIN not in src or END not in src:
        return (f"docstring 裡沒有 {BEGIN} 區塊 —— "
                f"描述必須是**產生**的,不可以人手寫一份、程式跑另一份")
    cur = src.split(BEGIN, 1)[1].split(END, 1)[0].strip()
    want = describe(gate_id).strip()
    if cur != want:
        return ("docstring 的描述和案例清單對不上(有人手改了產生區塊,"
                "或案例改了沒重新產生)—— 那正是「描述一個被放棄的設計」的形狀")
    return None


def meta_check(sync=False):
    bad, seen = [], set()
    for gate_id, g in GATES.items():
        ctrl = ROOT / g["control"]
        mod_path = ROOT / f"{g['module']}.py"
        if not ctrl.exists():
            bad.append((gate_id, f"對照腳本不存在:{ctrl.name}")); continue
        try:
            cases = _load_cases(g["control"])
        except SystemExit as e:
            bad.append((gate_id, str(e))); continue
        kinds = {c["kind"] for c in cases}
        if "positive" not in kinds or "negative" not in kinds:
            bad.append((gate_id, f"案例清單缺一邊:有 {sorted(kinds)},"
                                 f"陰陽兩種都要有"))
        if g["control"] not in seen:
            seen.add(g["control"])
            r = subprocess.run([sys.executable, str(ctrl)],
                               capture_output=True, cwd=str(ROOT))
            if r.returncode != 0:
                bad.append((gate_id, f"對照腳本跑不過(rc={r.returncode})"))
        src = mod_path.read_text(encoding="utf-8")
        for det, name in ((detect_r1(src, gate_id), "R1"),
                          (detect_r2(src, gate_id), "R2")):
            if det:
                bad.append((gate_id, f"[{name}] {det}"))
        if sync:
            _sync(mod_path, gate_id)
        d3 = detect_r3(mod_path, gate_id)
        if d3:
            bad.append((gate_id, f"[R3] {d3}"))
    for gate_id, why in bad:
        print(f"  ⛔ {gate_id}: {why}")
    if not bad:
        print(f"  ✓ {len(GATES)} 道閘門(含這支自己,定義見 {CONTROL}):"
              f"對照腳本都在、都跑得過、"
              f"陰陽案例齊全,而且描述和案例清單是同一份")
    return 1 if bad else 0


def _sync(mod_path, gate_id):
    src = mod_path.read_text(encoding="utf-8")
    BEGIN, END = _marks(gate_id)
    block = "\n" + describe(gate_id).strip() + "\n"
    if BEGIN in src and END in src:
        head, rest = src.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        src = head + BEGIN + block + END + tail
    else:
        i = src.index('"""', src.index('"""') + 3)
        src = src[:i] + BEGIN + block + END + "\n" + src[i:]
    mod_path.write_text(src, encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true")
    a = ap.parse_args()
    sys.exit(meta_check(sync=a.sync))
