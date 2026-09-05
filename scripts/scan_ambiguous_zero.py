# -*- coding: utf-8 -*-
"""第 1 層掃描:找「同一個函式裡,失敗路徑與正常路徑回傳同一個『沒事』值」。

判準(來自 2026-09-05 的橫向盤點):
    一個表示「沒事」的值(0 / [] / {} / "" / None / False),
    如果有**超過一種路徑**產生它,而下游只讀值、不讀路徑 —— 就是那一族。

失效表現永遠一樣:下游拿到一個型別正確、語意合法的值,
分不出「真的沒有」和「沒量到」,而且**零錯誤訊號**。

已知實例(用來校準這支掃描器,它們應該要被命中):
  · LLM 全滅被 catch 成 return 0(靜默九天)
  · crontab 被截斷 → parse_jobs() 回 0 筆
  · 「查了榜不在」和「根本沒查」在下游長得一樣

本掃描**只產清單、不改任何檔案**。假陽性預期很高(很多 `except: return []`
是正確的),清單是給人看的起點,不是判決。
"""
import ast, io, sys, os, json

ROOT = "D:/carson-agent/youtube_channel/scripts"

EMPTYISH = {"0", "[]", "{}", "''", '""', "None", "False", "0.0", "()", "set()"}


def literal_repr(node):
    """把 return 的東西正規化成一個可比對的字串;不是『空值』就回 None。"""
    if node is None:
        return "None"                       # 裸 return
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None:
            return "None"
        if v is False:
            return "False"
        if isinstance(v, (int, float)) and v == 0:
            return "0"
        if isinstance(v, str) and v == "":
            return '""'
        return None
    if isinstance(node, ast.List) and not node.elts:
        return "[]"
    if isinstance(node, ast.Dict) and not node.keys:
        return "{}"
    if isinstance(node, ast.Tuple) and not node.elts:
        return "()"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "set" and not node.args:
        return "set()"
    return None


class FuncScan(ast.NodeVisitor):
    """對單一函式:收集『在 except/finally 內的空值 return』與『在其外的空值 return』。"""

    def __init__(self):
        self.in_handler = 0
        self.handler_rets = []      # (value, lineno)
        self.normal_rets = []

    def visit_Try(self, node):
        for n in node.body:
            self.visit(n)
        for h in node.handlers:
            self.in_handler += 1
            for n in h.body:
                self.visit(n)
            self.in_handler -= 1
        for n in node.orelse + node.finalbody:
            self.visit(n)

    def visit_Return(self, node):
        v = literal_repr(node.value)
        if v is not None:
            (self.handler_rets if self.in_handler else self.normal_rets).append((v, node.lineno))

    # 巢狀函式各自算,不要把內層的 return 算到外層頭上
    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_FunctionDef


def scan_file(path):
    try:
        src = io.open(path, encoding="utf-8").read()
        tree = ast.parse(src)
    except Exception as e:
        return [], str(e)
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        s = FuncScan()
        for n in fn.body:
            s.visit(n)
        if not s.handler_rets:
            continue
        hvals = {v for v, _ in s.handler_rets}
        nvals = {v for v, _ in s.normal_rets}
        both = hvals & nvals
        if both:
            out.append({
                "fn": fn.name, "line": fn.lineno, "kind": "COLLIDE",
                "value": sorted(both),
                "handler_lines": [l for v, l in s.handler_rets if v in both],
                "normal_lines": [l for v, l in s.normal_rets if v in both],
            })
        elif hvals:
            # 失敗路徑回空值,但正常路徑沒有回同樣的空值 —— 風險較低,
            # 但呼叫端若用 `if not x:` 判斷,仍然分不出來。列為次級。
            out.append({
                "fn": fn.name, "line": fn.lineno, "kind": "HANDLER_ONLY",
                "value": sorted(hvals),
                "handler_lines": [l for _, l in s.handler_rets],
                "normal_lines": [],
            })
    return out, None


def main():
    rows, errs = [], []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".venv", "__pycache__", "node_modules")]
        for f in sorted(filenames):
            if not f.endswith(".py"):
                continue
            p = os.path.join(dirpath, f)
            res, err = scan_file(p)
            if err:
                errs.append((p, err))
            for r in res:
                r["file"] = os.path.relpath(p, ROOT).replace("\\", "/")
                rows.append(r)

    collide = [r for r in rows if r["kind"] == "COLLIDE"]
    honly = [r for r in rows if r["kind"] == "HANDLER_ONLY"]
    print("掃描根目錄 :", ROOT)
    print("解析失敗   :", len(errs))
    print()
    print("=" * 78)
    print("第一級 COLLIDE — 失敗路徑與正常路徑回傳**同一個**空值(下游結構上分不出)")
    print("=" * 78)
    print("共 %d 個函式" % len(collide))
    for r in sorted(collide, key=lambda x: (x["file"], x["line"])):
        print("  %s:%d  %s()  回 %s   except行=%s  正常行=%s"
              % (r["file"], r["line"], r["fn"], ",".join(r["value"]),
                 r["handler_lines"], r["normal_lines"]))
    print()
    print("=" * 78)
    print("第二級 HANDLER_ONLY — 只有失敗路徑回空值(呼叫端若用 `if not x` 仍分不出)")
    print("=" * 78)
    print("共 %d 個函式(只列前 40)" % len(honly))
    for r in sorted(honly, key=lambda x: (x["file"], x["line"]))[:40]:
        print("  %s:%d  %s()  回 %s   except行=%s"
              % (r["file"], r["line"], r["fn"], ",".join(r["value"]), r["handler_lines"]))

    out = "C:/Users/User/AppData/Local/Temp/claude/D--carson-agent/5089f42d-4a3b-43bc-9c90-74fe95ea3c3c/scratchpad/ambiguous_zero_report.json"
    io.open(out, "w", encoding="utf-8").write(json.dumps(rows, ensure_ascii=False, indent=1))
    print()
    print("完整清單 →", out)


if __name__ == "__main__":
    main()
