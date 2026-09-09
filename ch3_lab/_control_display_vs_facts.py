"""畫面 vs 事實庫 / 畫面 vs 旁白 —— 兩道閘門的對照。**陽性對照用真案例。**

背景:2026-09-09 獨立驗證 6 支全驗、18 列全比,抓到兩列:
  · `focus_techniques` 列 1:畫面 **η² = 0.03**,而事實庫存的是 **0.026**
    根因 `make_rechecked.val_str()` 對 eta2 寫死 `.2f`,而**同一個函式的
    docstring 自己寫著「精度跟著存的值」**。全 20 集只有這一集用 eta2
    ⇒ **這條路徑從來沒被跑過**。偏誤方向 0.026 → 0.03 是**往上**。
  · `how_to_remember` 列 3:畫面 **d = 1.10**,而旁白同一刻唸的是 **64 percent**
    —— 同一句 verbatim 裡有兩個統計量,畫面挑了旁白沒挑的那個。

原本的孤兒閘門**沒壞**(陰性安靜、陽性會叫),它**量錯對象**:
比的是原始值 `f"{es:g}"`,而觀眾看到的是 `val_str()` 的輸出,中間隔著一次格式化。
⇒ 換比對對象才堵得住整類;只改 eta2 那一行,下一個新的 `es_kind` 會再犯。

判準:把被測的機制弄壞,對照會不會跟著失敗?必須是「會」。
"""
import json
import pathlib
import sys

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import make_reel  # noqa: E402
import make_rechecked  # noqa: E402

SRC = pathlib.Path(r"D:\carson-agent\ch3_lab\facts\rechecked_episodes.json")
EPS = {e["slug"]: e for e in
       json.loads(SRC.read_text(encoding="utf-8"))["episodes"]}


def audits(E):
    """跑真的那支 audit。回傳 (有沒有擋下, 訊息第一行)。"""
    try:
        make_reel.audit(E, make_reel.build_script(E))
        return False, ""
    except SystemExit as ex:
        return True, str(ex).splitlines()[0][:96]


def show(tag, blocked, msg, want):
    mark = "✓" if blocked == want else "🔴"
    print(f"  {mark} {tag}: {'擋下' if blocked else '通過'}"
          + (f" —— {msg}" if blocked else ""))
    return blocked == want


ok = []

print("【真案例 1】eta2 的精度 —— 0.026 不可以被印成 0.03")
got = make_rechecked.val_str("eta2", 0.026)
ok.append(got == "η² = 0.026")
print(f"  {'✓' if ok[-1] else '🔴'} val_str('eta2', 0.026) = {got!r}"
      f"(修好前是 'η² = 0.03',而偏誤方向往上)")
got2 = make_rechecked.val_str("eta2", 0.014)
ok.append(got2 == "η² = 0.014")
print(f"  {'✓' if ok[-1] else '🔴'} val_str('eta2', 0.014) = {got2!r}")

print("【真案例 1b】把 val_str 換回舊行為,閘門必須抓到 focus_techniques")
_orig = make_reel.val_str
try:
    make_reel.val_str = (lambda kind, v, is_max=False:
                         f"η² = {v:.2f}" if kind == "eta2"
                         else _orig(kind, v, is_max))
    b, m = audits(json.loads(json.dumps(EPS["focus_techniques"])))
    ok.append(show("舊的 .2f 行為(0.026 → 畫面 0.03)", b, m, True))
finally:
    make_reel.val_str = _orig

print("【真案例 1c】修好之後,同一集必須安靜(不誤擋)")
b, m = audits(json.loads(json.dumps(EPS["focus_techniques"])))
ok.append(show("focus_techniques 現況", b, m, False))

print("【真案例 2】how_to_remember 列 3 —— 畫面 d = 1.10 / 旁白 64 percent")
e = json.loads(json.dumps(EPS["how_to_remember_what_you_read"]))
r = e["twist_rows"][2]
r["es"], r["es_kind"] = 1.1, "d"
r.pop("display_only", None)
b, m = audits(e)
ok.append(show("把那一列改回 d = 1.10", b, m, True))

b, m = audits(json.loads(json.dumps(EPS["how_to_remember_what_you_read"])))
ok.append(show("現況(畫面 64% = 旁白 64 percent)", b, m, False))

print("【單位符號不是值】pts/10、pts/7 的 10 和 7 不可以被當成畫面上的數字")
b, m = audits(json.loads(json.dumps(EPS["facial_feedback"])))
ok.append(show("facial_feedback(實測曾被誤擋四列)", b, m, False))

print("【逃生門要付代價】display_only 為真時,理由必須存在且非空白")
# 🔴 原本錯誤訊息寫著「並附 display_only_why —— 靠沉默不算」,
#    而程式只檢查 display_only。**規則只寫在錯誤訊息裡 = 提示層不是規則層。**
#    這和 is_prereg 那格是同一個形狀,而它在隔壁又長了一次。
for bad_why, tag in ((None, "① 不附 why"),
                     ("", "② why 是空字串"),
                     ("   ", "③ why 只有空白")):
    e = json.loads(json.dumps(EPS["focus_techniques"]))
    row = next(x for x in e["twist_rows"]
               if x.get("label") == "phone in another room")
    if bad_why is None:
        row.pop("display_only_why", None)
    else:
        row["display_only_why"] = bad_why
    b, m = audits(e)
    ok.append(show(tag, b, m, True))

print("【陰性】現況的理由是一段真話,必須安靜")
b, m = audits(json.loads(json.dumps(EPS["focus_techniques"])))
ok.append(show("focus_techniques 現況", b, m, False))

print()
print("結論:", "✓ 兩道閘門都會叫,而且不誤擋真資料" if all(ok)
      else "🔴 對照失敗 —— 有一格不算數")
sys.exit(0 if all(ok) else 1)
