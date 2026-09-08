# -*- coding: utf-8 -*-
"""narration_compliance_watch.py — 個股體檢旁白的「規則遵守率」守望(主頻道線,2026-09-05)

## 為什麼存在
2026-09-05 兩條新規則上線,而兩條都是「寫在模板裡、違反時不產生輸出」:
  · 收束句(`_checkup_summary_line`,確定性)——不合規只會是「沒產出」,沒有人在數覆蓋率
  · 業務介紹(`TW_STOCK_CHECKUP_RULES` ①b,純 prompt 層)——LLM 不照做完全靜默

實據:7 月有一條旁白規則的合規率是 **4%,持續整整一個月零訊號**
(8 月 54% / 9 月 89% / 最近 30 支 93%)。

🔴 **所以這支問的是「這個規則現在的遵守率是多少」,不是「有沒有出錯」。**
那兩個問句差很遠 —— 後者在 4% 的那個月裡**完全不會叫**,因為每一支片都成功產出了。

## 判準
只數**規則上線之後**產出的旁白(`RULE_DATE` 起),因為上線前的樣本必然不合規,
混進去會把分母稀釋成一個永遠慢慢爬升的數字 —— 那正是量測窗混進上線期的老坑。

| 規則 | 判準 | 地板 |
|---|---|---|
| 收束句 | 含「一句話收束今天的體檢」 | 50%(資料齊備率上限約 82%,留餘裕) |
| 業務介紹 | 含業務描述句(見 `_BIZ_PAT`) | 50%(上線前基線是 **3/20 = 15%**) |

樣本數不足(< `MIN_N`)時**只報數字不判定** —— n 小的時候比例會亂跳,
在那之上設門檻只會製造假警報。

## 正向輸出
每次跑都寫一行 log,合規的日子也寫 ⇒「沒輸出」永遠是異常。

## 演習
`--selftest=summary|biz|both`:**每一條判準各自要有引爆輸入**。
(教訓來自同日的 `seeding_watch`:第一版只有一種 fixture,它引爆了一條而另一條
完全沒被走到,而沒被走到的那條才是覆蓋歷史真實失效的那條。)

用法:
  python scripts/narration_compliance_watch.py
  python scripts/narration_compliance_watch.py --selftest=biz
"""
import sys, re, datetime, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "youtube_channel" / "output"
LOG = REPO / "docs" / "ops" / "narration-compliance-watch.log"
sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))

# 🔴 上線日設 09-06 不是 09-05:兩條規則是 09-05 **深夜** commit 的,
# 而 09-05 白天已經產了 11 支舊規則的片。設成 09-05 會把上線前的產出算進分母,
# 第一次跑就吐 0% 紅燈 —— 那正是本檔 docstring 自己寫的「量測窗混進上線期」,
# 而我在同一個檔案裡踩了一次。第一個完整的新規則批次是 09-06 06:07。
RULE_DATE = datetime.date(2026, 9, 6)
MIN_N = 8                               # 少於這個數只報不判
FLOOR_SUMMARY = 0.50
FLOOR_BIZ = 0.50

# ─────────────────────────────────────────────────────────────────────
# 🔴 2026-09-08:判準改成**從產線那一份長出來**,不再另抄一份。
#
# 為什麼改:盤點實測抓到這道哨已經在漂,而且是兩個具體缺口 ——
#   ① `_SUM_PAT` 原本寫死 `("一句話收束今天的體檢",)` **一種**措辭,
#      而產線 `produce_batch.py:1815` 認可**五種**(一句話收束/總結/整體而言/綜合來看/結論是)。
#      ⇒ 旁白自然帶出「總結…」的收尾時,**產線視為合規、本哨記成不合規**
#      (09-06 後 n=26 實測:sum_hit=10、**alt_only=1 被誤記**、neither=15)。
#   ② `_BIZ_PAT` 五條正則,**連 `TW_STOCK_CHECKUP_RULES` ①b 自己給的官方範例句
#      「台星科做積體電路測試服務」都零命中** —— 判準比它要執行的規則還窄。
#
# 修法(原則來自 prompt 洩漏閘門那道的修法:**判準要從被監控物身上長出來**):
#   · 收束句 → `from produce_batch import CHECKUP_SUMMARY_MARKERS`,誰改產線清單哨自動跟著變
#   · 業務介紹 → 規則是純 prompt 文字沒有可 import 的清單,所以改成**把規則自己給的範例句
#     抽出來當內建回歸語料**;檢查器對不上自己要執行的規則的範例 ⇒ **fail-closed 不報數字**。
#     (同 prompt 洩漏閘門用 31 支真實洩漏案例當語料、抓不到就 fail-closed 的機制。)
# ⚠️ import 失敗**不可以**靜默退回舊的抄本 —— 那正是漂的成因。失敗要大聲。
# ─────────────────────────────────────────────────────────────────────
_IMPORT_ERR = ""
try:
    from produce_batch import CHECKUP_SUMMARY_MARKERS as _SUM_PAT  # 單一真相來源
    from produce_batch import TW_STOCK_CHECKUP_RULES as _RULES_TEXT
except Exception as _e:  # noqa: BLE001
    _SUM_PAT, _RULES_TEXT, _IMPORT_ERR = (), "", f"{type(_e).__name__}: {_e}"


def _rule_examples() -> tuple:
    """從 `TW_STOCK_CHECKUP_RULES` ①b 的「例:」那行抽出官方範例句。

    **這就是回歸語料,而且它跟著規則走** —— 規則改了範例句、語料自動跟著改,
    不需要任何人記得同步。抽不到就回空,由 `_biz_selfcheck()` 判成 fail-closed。"""
    if not _RULES_TEXT:
        return ()
    m = re.search(r"例[:：]\s*((?:「[^」]+」\s*)+)", _RULES_TEXT)
    return tuple(re.findall(r"「([^」]+)」", m.group(1))) if m else ()


_BIZ_PAT = (r"這家公司主要[在從]?[^。]{6,}。", r"主要業務[是為]?[^。]{6,}。",
            r"靠(?:販售|賣|提供)[^。]{4,}(?:賺錢|營收)", r"從事[^。]{6,}(?:業務|生產|製造|研發)",
            # 🔴 2026-09-08 補:原本五條漏掉「做…服務/測試/設備」這個句型,
            # 導致規則自己的範例「台星科做積體電路測試服務」零命中。
            r"提供[^。]{4,}(?:服務|解決方案|設備|系統|產品)",
            r"[做搞][^。]{4,}(?:服務|測試|設備|系統|製造|代工|產品)",
            r"(?:生產|製造|銷售|研發)[^。]{4,}(?:產品|元件|設備|材料|系統)")


def _biz_selfcheck() -> tuple:
    """規則自己給的範例句,本檢查器抓不抓得到?回 (ok, 訊息)。

    🔴 這是這道哨的**陽性對照**:一個連自己要執行的規則的範例都認不出來的檢查器,
    算出來的「遵守率」是沒有意義的數字,**不可以拿去跟地板比**。"""
    if _IMPORT_ERR:
        return False, f"無法 import 產線常數({_IMPORT_ERR})—— 判準來源不可用"
    if not _SUM_PAT:
        return False, "產線收束句清單為空"
    ex = _rule_examples()
    if not ex:
        return False, "抽不到規則裡的官方範例句(規則格式可能改了)"
    miss = [s for s in ex if not any(re.search(p, s + "。") for p in _BIZ_PAT)]
    if miss:
        return False, f"規則自己的範例句有 {len(miss)}/{len(ex)} 條抓不到:{miss}"
    return True, f"陽性對照通過({len(ex)} 條官方範例全部命中);收束句認可 {len(_SUM_PAT)} 種措辭"

SELFTEST_MODE = next((a.split("=", 1)[1] if "=" in a else "both"
                      for a in sys.argv if a.startswith("--selftest")), None)
SELFTEST = SELFTEST_MODE is not None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(t):
    try:
        print(t)
    except Exception:
        pass


def record(line):
    if SELFTEST:
        line = "[DRILL] " + line
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    say(line)


def alert(title, body):
    if SELFTEST:
        say("[DRILL] 演習不推播")
        return
    try:
        from notify import push
        push(title, body, tag="clipboard")
    except Exception as e:
        say(f"(ntfy 推播失敗,不影響本檢查:{e!r})")


def samples():
    if SELFTEST:
        good_sum = "……前面講完。一句話收束今天的體檢，它屬於電機機械，過去約15年。"
        good_biz = "……這家公司主要在提供半導體、面板產業的製程設備與解決方案。"
        plain = "……你知道嗎？這檔股票十五年報酬只有百分之七十二。"
        if SELFTEST_MODE == "summary":      # 只有收束句掉下去
            return [good_biz + plain] * 10 + [good_biz + good_sum] * 2
        if SELFTEST_MODE == "biz":          # 只有業務句掉下去
            return [good_sum + plain] * 10 + [good_sum + good_biz] * 2
        return [plain] * 12                 # 兩條都掉
    out = []
    for f in OUT.glob("L_個股體檢*.voice.txt"):
        try:
            if datetime.date.fromtimestamp(f.stat().st_mtime) < RULE_DATE:
                continue
            out.append(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue
    return out


def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 🔴 陽性對照先跑,而且 **fail-closed**:判準本身認不出規則自己的範例句時,
    # 算出來的「遵守率」沒有意義 —— 那正是 08-25~09-03 那道 prompt 洩漏閘門的病
    # (瞎了三週、rc=0、log 一片乾淨)。這裡寧可吵也不要吐一個安靜的假數字。
    ok, msg = _biz_selfcheck()
    if not ok:
        line = f"[{now}] 🔴 判準自檢失敗,本輪不報遵守率(這不是「合規」):{msg}"
        record(line); alert("旁白合規守望:判準自檢失敗", line)
        return 1

    try:
        texts = samples()
    except Exception as e:
        line = f"[{now}] 🔴 讀不到旁白,無法判斷(這不是「合規」):{e!r}"
        record(line); alert("旁白合規守望:讀不到樣本", line)
        return 1

    n = len(texts)
    n_sum = sum(1 for t in texts if any(k in t for k in _SUM_PAT))
    n_biz = sum(1 for t in texts if any(re.search(p, t) for p in _BIZ_PAT))
    r_sum = n_sum / n if n else 0.0
    r_biz = n_biz / n if n else 0.0
    stat = (f"{RULE_DATE} 起產出 {n} 支｜收束句 {n_sum}/{n}={r_sum:.0%}"
            f"(地板 {FLOOR_SUMMARY:.0%})｜業務介紹 {n_biz}/{n}={r_biz:.0%}(地板 {FLOOR_BIZ:.0%})")

    if n < MIN_N:
        record(f"[{now}] ⏳ 樣本不足只報不判(n={n} < {MIN_N})｜{stat}")
        return 0

    bad = []
    if r_sum < FLOOR_SUMMARY:
        bad.append(f"🔴 收束句遵守率 {r_sum:.0%} 低於地板 —— 它是確定性程式碼,掉下去代表"
                   f"`_checkup_summary_line` 拿不到事實或沒被呼叫")
    if r_biz < FLOOR_BIZ:
        bad.append(f"🔴 業務介紹遵守率 {r_biz:.0%} 低於地板 —— 那條規則只寫在 prompt 層,"
                   f"上線前基線是 3/20=15%,掉回那附近代表模型沒在照做")
    if bad:
        line = f"[{now}] {stat}｜" + "｜".join(bad)
        record(line); alert("旁白合規守望:遵守率掉了", line)
        return 1

    # 正向輸出把陽性對照的結果也帶上:「它今天有沒有能力叫」本身要看得見,
    # 不然「沒叫」與「叫不出來」在 log 上又長得一樣。
    record(f"[{now}] ✅ 合規｜{stat}｜{msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
