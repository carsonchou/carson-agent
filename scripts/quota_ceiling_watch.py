# -*- coding: utf-8 -*-
"""quota_ceiling_watch.py — 配額天花板變化守望(基建線,2026-09-02)

為什麼存在:premises.md 第 3 條寫「核准可自驗:quota_meter 天花板變了就是核准」,
但沒有任何東西每天去看它——這支就是去看的那個。

設計約束(督導指令 + verify-ceiling-watch 驗證後修正):
  · 正向輸出:**每次跑都寫一行 log**,天花板沒變的日子也有——「沒輸出」因此永遠是異常。
  · log 先寫、print 後印(印壞了紀錄還在;cp950 炸點已被驗證員重現過)。
  · print 全程可失敗(pythonw 下 stdout=None),log 才是主要輸出通道。
  · assert_project() 回傳警告字串(不 raise),**要接住當警報**,不能默默比錯帳。
  · 比對直接用 effective_limit():它「忽略 floor」的 bug 已由 w9 修復(cefa9ba8,floor 只採
    撞牆日後的日子)。**不要在這裡再包 max(eff, 全期 floor)**——配額被調降時,舊高 floor 會把
    watch 值釘死在舊值,把 ⚠️ 下移遮成「無變化」,正是 cefa9ba8 避開的鏡像病。
  · 只讀 w9 的模組與帳本,不改它們;變化時推 ntfy(失敗不擋主流程)。

用法:python scripts/quota_ceiling_watch.py   (排程每天台北 15:20,配額日剛關帳後)
輸出:docs/ops/quota-ceiling-watch.log 追加一行 + 更新 .state.json + stdout(若有)
"""
import json, sys, datetime, pathlib, traceback

REPO = pathlib.Path(__file__).resolve().parent.parent
LOG   = REPO / "docs" / "ops" / "quota-ceiling-watch.log"
STATE = REPO / "docs" / "ops" / "quota-ceiling-watch.state.json"
sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))

# --selftest:演習模式。教訓(2026-09-02):驗證員手改 state 模擬提額,兩行 🎉 落在正式 log,
# 和真事件一模一樣——假證據落在自己指定的權威來源裡,比沒有守望更糟。
# 演習從此只准走這裡:每行帶 [DRILL] 前綴、用獨立 state 檔、永不推播。真實路徑永遠不產生 [DRILL]。
SELFTEST_MODE = next((a.split("=", 1)[1] if "=" in a else "up"
                      for a in sys.argv if a.startswith("--selftest")), None)  # None|"up"|"down"
SELFTEST = SELFTEST_MODE is not None
if SELFTEST:
    STATE = REPO / "docs" / "ops" / "quota-ceiling-watch.state.selftest.json"

try:  # 排程/重導向下編碼不保證 utf-8;stdout 可能是 None(pythonw)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(text: str) -> None:
    """print 的可失敗版:log 是主通道,stdout 只是順帶。"""
    try:
        print(text)
    except Exception:
        pass


def record(line: str) -> None:
    if SELFTEST:
        line = "[DRILL] " + line
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    say(line)


def alert(title: str, body: str) -> None:
    if SELFTEST:
        say("[DRILL] 演習不推播")
        return
    try:
        from notify import push
        push(title, body, tag="chart_with_upwards_trend")
    except Exception as e:
        say(f"(ntfy 推播失敗,不影響本檢查:{e!r})")


def main() -> int:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        import quota_meter as qm
        warn = qm.assert_project()          # 回傳字串不 raise:非空=帳本可能換了專案
        if warn:
            line = f"[{now}] 🔴 專案不一致,拒絕比對(比錯帳比沒比更糟):{warn}"
            record(line); alert("配額守望:專案不一致", line)
            return 1
        eff = qm.effective_limit()
        floor, ceil = qm.observed()
        cur = eff                           # 見檔頭:cefa9ba8 後直接信 effective_limit,別再包 max
        try:                                # 帳本日數:用來把「帳本遺失/重置」從「真調降」裡分出來
            days_n = len(json.loads(pathlib.Path(qm.STATE).read_text("utf-8")).get("days") or {})
        except Exception:
            days_n = None
    except Exception as e:
        record(f"[{now}] 🔴 讀不到 quota_meter:{e!r} —— 這本身是警報,不是「沒事」")
        say(traceback.format_exc())
        return 1

    prev = {}
    if STATE.exists():
        try: prev = json.loads(STATE.read_text("utf-8"))
        except Exception: pass
    base = prev.get("effective")
    if SELFTEST:
        if SELFTEST_MODE == "down":     # 演習「下移+days 驟減」:走 ⚠️+帳本遺失標註路徑
            base = cur + 1234
            prev = {"days_n": (days_n or 0) + 40}
        else:                           # 演習「上移」:走 🎉 路徑
            base = cur - 1234

    if base is None:
        verdict = f"基準建立:watch={cur:,}(effective={eff:,}, floor={floor}, ceiling={ceil})"
        changed = False
    elif cur > base:
        verdict = (f"🎉 天花板上移 {base:,} → {cur:,} —— 依 premises.md 第 3 條,"
                   f"這就是提額核准的證據(effective={eff:,}, floor={floor}, ceiling={ceil})")
        changed = True
    elif cur < base:
        verdict = f"⚠️ 天花板下移 {base:,} → {cur:,} —— 配額被調降?查 quota_meter 帳本"
        days_prev = prev.get("days_n")
        if days_n is not None and days_prev and days_n < days_prev - 5:
            verdict += f"(🔴 但 days 筆數 {days_prev}→{days_n} 驟減:更像帳本遺失/重置,不是真調降——先查帳本檔再信這個 ⚠️)"
        changed = True
    else:
        verdict = (f"無變化:watch={cur:,}(effective={eff:,}, floor={floor}, ceiling={ceil});"
                   f"提額若核准,產線成功花超舊牆當天 effective_limit 會上移(cefa9ba8 後含撞牆日後 floor)")
        changed = False

    record(f"[{now}] {verdict}")
    STATE.write_text(json.dumps({"effective": cur, "raw_effective": eff, "floor": floor,
                                 "ceiling": ceil, "days_n": days_n,
                                 "checked_at": now}, ensure_ascii=False), "utf-8")
    if changed:
        alert("配額天花板變化", verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
