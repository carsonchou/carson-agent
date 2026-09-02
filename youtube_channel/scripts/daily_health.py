#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_health.py — 每日工作室健檢(C1)。一眼看整條產線今天有沒有出事。

檢查(全唯讀,不改任何東西):
  1. 憑證:TG bot getMe、Gmail SMTP 登入(沿用 env_check 的邏輯,不回顯密鑰)
  2. STUDIO 關鍵 json 完整性(能不能 parse;壞了代表併發洗檔或損毀)
  3. cron 失敗:掃 logs/job_stderr.log 近一天有沒有 job 噴 traceback
  4. 變現漏斗:tg_leads.json 名單數、今日產出量
  5. 洗版洩漏:weekly_winners 基準線有沒有被突破(新洗版題溜進來)

輸出:終端摘要 + --notify 推 ntfy(給每日排程用)。
用法:python scripts/daily_health.py [--notify]
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"

KEY_JSON = ["topic_bank.json", "uploaded_ledger.json", "quality_scores.json",
            "traffic_signals.json", "tg_leads.json", "ypp_progress.json"]


def _env_status():
    """憑證健檢(沿用 env_check;不回顯密鑰)。回 (tg_ok, gmail_ok) 或 None。"""
    try:
        import env_check
        env, _ = env_check.load_env()
    except Exception:  # noqa: BLE001
        return None
    tg = bool(env.get("TG_MAGNET_TOKEN"))
    gm = bool(env.get("GMAIL_ADDRESS") and env.get("GMAIL_APP_PASSWORD"))
    return tg, gm


def _json_integrity():
    bad = []
    for name in KEY_JSON:
        p = STUDIO / name
        if not p.exists():
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            bad.append(name)
    return bad


def _cron_failures():
    log = ROOT / "logs" / "job_stderr.log"
    if not log.exists():
        return 0
    try:
        txt = log.read_text(encoding="utf-8", errors="replace")[-20000:]
        return txt.count("Traceback (most recent call last)")
    except Exception:  # noqa: BLE001
        return 0


def _funnel():
    leads = 0
    try:
        d = json.loads((STUDIO / "tg_leads.json").read_text(encoding="utf-8"))
        leads = len(d) if isinstance(d, dict) else 0
    except Exception:  # noqa: BLE001
        pass
    return leads


def _supplies():
    """🔴 產線耗材水位(2026-08-29 建)。

    一天之內連踩三次**同一型**故障:耗材耗盡 → 產線停擺 → **零警訊**。
      ① OpenRouter 餘額歸零   → 長片完全產不出來,ops_log 只寫「所有供應商都失敗」(追一小時)
      ② 救回的稿被刪掉 mp3    → 渲染迴圈報「0/0 支」,那 18 支對產線變成隱形(空轉一小時)
      ③ 題庫未用長片題歸零    → 模型自由生題沒有事實可依據 → 灌水 → 閘門擋下,
                                連續 7 小時 fail-closed,每輪都成功執行、每輪都零產出
    三個都不會壞、不會噴 traceback、cron 全部回報「✓ 完成」——現有健檢一項都看不到。
    共同特徵:**耗材是存量,而健檢只看流量**。這裡把存量本身當一等公民量出來。

    回 (lines, warns)。任何一項讀不到就跳過該項,不影響其他檢查。
    """
    lines, warns = [], []

    # ① 題庫:未用的長片題(這是長片產線唯一的燃料)
    try:
        b = json.loads((STUDIO / "topic_bank.json").read_text(encoding="utf-8"))
        if isinstance(b, dict):
            b = b.get("topics") or b.get("items") or list(b.values())[0]
        unused = [t for t in b if t.get("format", "short") == "long" and not t.get("used")]
        n_ck = sum(1 for t in unused if str(t.get("fact_key", "")).startswith("checkup_"))
        lines.append(f"題庫·未用長片題: {len(unused)} 題(個股體檢 {n_ck})")
        if len(unused) < 20:
            warns.append(f"長片題只剩{len(unused)}")
            lines.append("   ⚠️ 低於 20 題 → 抽不到題會讓模型自由生題(無事實)→ 整批灌水被閘門擋掉。"
                         "補:python scripts/seed_checkup_backfill.py --apply --max 40")
    except Exception:  # noqa: BLE001
        pass

    # ② 缺音檔:有稿沒 mp3 的片,渲染迴圈的 cloud_pending() 會靜默跳過(永遠看不到)
    try:
        out = ROOT / "output"
        miss = 0
        for vt in out.glob("*.voice.txt"):
            s = vt.name[: -len(".voice.txt")]
            if s.startswith(("S_", "L_")) and not (out / f"{s}.mp3").exists():
                miss += 1
        lines.append(f"待渲染缺音檔: {miss} 支")
        if miss:
            warns.append(f"缺音檔{miss}支")
            lines.append("   ⚠️ 渲染迴圈判準要 voice.txt+mp3,缺 mp3 會**靜默跳過**(報 0/0 支)。"
                         "補:python scripts/backfill_tts.py --apply")
    except Exception:  # noqa: BLE001
        pass

    # ③ 產線良率:昨天到底產出幾支稿。
    # 🔴 2026-08-30 加這項的理由:產線 08-29 **整天零成稿**(17 支被期間偷換閘門殺掉),
    # 而這份健檢當天照樣回報「✅ 全部正常」——因為它看的是題庫存量、音檔、LLM 餘額,
    # 沒有一項會因為「一支都沒產出來」而變紅。庫存 22 支、每天發 6.5 支,
    # 也就是**斷貨前只有三天,而三天內不會有任何警訊**。
    # 存量(題庫/庫存)看的是水位,良率看的是水龍頭有沒有出水 —— 兩個都要有。
    try:
        import re as _re
        _log = (ROOT / "STUDIO" / "ops_log.txt").read_text(encoding="utf-8", errors="replace")
        _yst = time.strftime("%m-%d", time.localtime(time.time() - 86400))
        _made = _fail = 0
        for _l in _log.splitlines():
            if not _l.startswith(f"[{_yst}"):
                continue
            if "已備妥待渲染" in _l:
                _made += 1
            elif "fail-closed" in _l or "⛔" in _l:
                _fail += 1
        lines.append(f"昨天({_yst})產線: 成稿 {_made} 支 / fail-closed {_fail} 支")
        if _made == 0 and _fail > 0:
            warns.append(f"昨天零成稿(閘門殺{_fail}支)")
            lines.append("   🔴 **一支都沒產出來而閘門殺了很多** = 閘門把正常的稿也擋掉了,"
                         "去看 output/_rejected/ 最新幾支;庫存見底前不會有別的警訊")
        elif _made and _fail > _made * 2:
            warns.append(f"昨天良率低({_made}成稿/{_fail}報廢)")
    except Exception:  # noqa: BLE001
        pass

    # ④ LLM 餘額:唯一沒被監控過的單點故障(已有 llm_credit_watch,這裡併進同一張表)
    try:
        import llm_credit_watch as lcw
        bal, _used, _tot = lcw.balance()
        if bal is not None:
            vids = int(bal / lcw.COST_PER_VIDEO) if bal > 0 else 0
            lines.append(f"OpenRouter 餘額: US${bal:.2f}(約 {vids} 支長片)")
            if vids < lcw.WARN_VIDEOS:
                warns.append(f"LLM餘額剩{vids}支")
    except Exception:  # noqa: BLE001
        pass

    return lines, warns


def _leak_check():
    """weekly_winners 基準線:有沒有新洗版題溜進來。"""
    try:
        st = json.loads((STUDIO / "weekly_winners_state.json").read_text(encoding="utf-8"))
        return st.get("leak_baseline")
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    lines = [f"量化阿森 每日健檢 · {time.strftime('%Y-%m-%d %H:%M')}"]
    warn = []

    env = _env_status()
    if env is not None:
        tg, gm = env
        lines.append(f"憑證: TG bot {'✓' if tg else '✗'}｜Gmail {'✓' if gm else '✗'}")
        if not tg:
            warn.append("TG token 缺")
        if not gm:
            warn.append("Gmail 缺")

    # 稽核D修:analytics/OAuth token 健康(過期會讓 northstar/ypp/retention 靜默寫 null 無告警)
    try:
        import yt_analytics as _ya
        ana_ok = bool(_ya.available())
    except Exception:  # noqa: BLE001
        ana_ok = False
    lines.append(f"Analytics token: {'✓' if ana_ok else '✗ 失效(northstar/ypp/留存會靜默降級,去 auth_analytics 重授權)'}")
    if not ana_ok:
        warn.append("Analytics token 失效")
        # P0-b：token 失效不能只是塞進一般健檢彙總裡等 Carson 自己爬文——northstar.ypp.subs_cur=null
        # 就是「靜默降級沒人知道」的實例。這裡獨立推一則醒目告警，跟一般健檢彙總分開。
        if "--notify" in sys.argv:
            try:
                import notify
                notify.push(
                    "量化阿森｜⚠ Analytics token 失效",
                    "Analytics token 失效→數據降級,請重生 token。\n"
                    "受影響:northstar.json(ypp.subs_cur)/ypp_progress/retention_insights 會靜默寫 null,"
                    "不是真的沒訂閱/沒留存資料,是抓不到。\n"
                    "重生:python scripts/auth_analytics.py",
                    tag="warning",
                )
            except Exception as e:  # noqa: BLE001
                print(f"[warn] token 失效告警推播失敗:{e}", file=sys.stderr)

    bad = _json_integrity()
    lines.append(f"STUDIO json 完整性: {'✓ 全正常' if not bad else '✗ 壞檔=' + '、'.join(bad)}")
    if bad:
        warn.append(f"json壞:{bad}")

    fails = _cron_failures()
    lines.append(f"cron 失敗(job_stderr traceback): {fails}")
    if fails > 3:
        warn.append(f"cron失敗{fails}")

    leads = _funnel()
    lines.append(f"TG 名單累計: {leads} 人")

    # 產線耗材水位(題庫/音檔/LLM餘額)——三種「耗盡即停產且零警訊」的故障,見 _supplies 說明
    _sl, _sw = _supplies()
    lines.extend(_sl)
    warn.extend(_sw)

    base = _leak_check()
    lines.append(f"洗版洩漏基準線: {base if base is not None else '未建'}(每週 weekly_winners 監控是否突破)")

    # 🔴 2026-08-30:配額水位 + 昨天有沒有撞牆。
    # 加這項的理由:今天把發布從 6 支/天提到 7 支(保留額度 13,200 → 15,400),
    # 等於把其餘操作壓到 4,245 units,而昨天非發布的花費約 10,000 —— **這個改動有撞牆風險**。
    # 而撞牆的樣子是「發布靜默少發一支」,不會噴錯:daily_publish 遇到 quotaExceeded 就跳過,
    # 隔天冪等補上。庫存夠的時候完全看不出來,直到某天發現時數不再成長。
    # 「被拒次數」比「已用量」更早示警:額度還沒滿就開始被拒 = 上限比我們以為的低。
    # 🔴 2026-09-02 這一段修過三個 bug,三個都是「不會叫的警報」:
    #   ① 分母寫 DAILY_LIMIT(猜的 19,645)不是 effective_limit()(實測 26,001)
    #      → 剛好花到實測牆會印成 132%。quota_meter._maybe_warn 修過同一個 bug
    #      (註解寫著「94% 會被印成 125%」)—— **修了那份沒修這份**。
    #   ② `warns.append(...)` 而 main() 裡的變數叫 `warn`(從本檔 :93 另一個函式複製來的)
    #      → NameError,被下面的 except 吞掉。**兩個分支三個月來一次都沒叫過。**
    #   ③ 撞牆判準自己寫一份(只看 rejected_calls)。739e5311 才把 quota_meter 裡的兩份
    #      統一成 _is_wall(),而第三份留在這裡。
    try:
        import quota_meter as _qm
        _today = _qm._pacific_date()
        _raw = _qm._load()
        _days = _raw.get("days") or {}

        # 🔴 2026-09-02 第三輪:一條**繞過下面那個 except** 的靜默路徑。
        # `quota_meter._load()` 自己有 try/except,JSON 壞掉或半截(排程正在 _save()
        # 而健檢同時在讀)它會回 `{"days": {}}` —— 一份**合法的空帳本**。
        # 於是這裡拿到的不是例外而是「看起來正常的謊」,健檢會印 0/26,001 = 0% 且 ✅ 全部正常。
        # 例外在下一層就被吞掉了,所以下面那個 `except Exception as _e` 一次都不會被觸發:
        # 它守的是「這一層爆炸」,守不住「上游遞給我一個合法的空值」。
        #
        # 判別點是**「解析不出任何一天,但檔案有內容」**,不是「百分比很低」——
        # 台北 15:00 換配額日之後 spent 本來就會很低,拿 0% 當壞掉的證據一定誤報。
        # 判別點是「**這份 JSON 解不解析得開**」,不是檔案大小、更不是百分比高低:
        #   · `{"days": {}}` 是**合法的空帳本**(12 bytes),不是壞掉 —— 拿大小判會誤報
        #   · 台北 15:00 換配額日之後 spent 本來就很低,拿 0% 判也一定誤報
        # 所以在這一層自己解析一次原檔:解得開 = 帳本真的空;解不開 = _load() 把它吞成空的。
        _exists, _age_h, _parse_err = _qm.STATE.exists(), None, None
        if _exists:
            try:
                _age_h = (time.time() - _qm.STATE.stat().st_mtime) / 3600.0
            except Exception:  # noqa: BLE001
                pass
            try:
                _disk = json.loads(_qm.STATE.read_text(encoding="utf-8"))
                if not isinstance(_disk, dict):
                    _parse_err = f"頂層不是 dict 而是 {type(_disk).__name__}"
            except Exception as _pe:  # noqa: BLE001
                _parse_err = repr(_pe)
        if not _exists:
            warn.append("配額帳本檔不存在")
            lines.append(f"YouTube 配額: 🔴 **帳本檔不存在**({_qm.STATE})—— 不是「沒花配額」。"
                         "計量器沒在記帳,所有配額判斷(含發布前的預留閘門)都建立在空氣上")
        elif _parse_err:
            warn.append("配額帳本讀不到(JSON 解析失敗)")
            lines.append(f"YouTube 配額: 🔴 **帳本讀不到**——{_parse_err}。"
                         "`quota_meter._load()` 自己的 except 會把這種檔吞成 `{'days': {}}`,"
                         "於是所有配額判斷都拿到「今天花了 0」。這**不是**「今天沒花配額」。"
                         "多半是讀到排程 _save() 寫到一半的檔(等一分鐘重跑就會好),"
                         "若持續出現就是檔案真的壞了")
        else:
            _b = _days.get(_today, {})
            _spent = int(_b.get("spent", 0) or 0)
            _rej = int(_b.get("rejected_calls", 0) or 0)
            _rej_units = int(_b.get("rejected_units", 0) or 0)
            _lim = _qm.effective_limit()

            # 參考點 = **今天以外、帳本裡最高的一道牆**。三個設計決定,每個都有代價:
            # ① 不含今天:天花板的定義就是「最近一次撞牆日的成功花費」,含今天則撞牆日
            #    的比值恆為 100%,判準是循環的(第一版這樣寫,「只花到 35% 就被拒」
            #    被判成預期內,測試才抓到)。
            # ② 取**最高**不取最近:取最近的話,配額被砍半後連三天在 12,000 被拒,
            #    第一天紅字、第二天起新的爛狀態就變成「正常」——參考點跟著爛下去,
            #    警報自己把自己關掉。取最高則會持續叫,直到舊的高牆被裁掉(≤30 天)
            #    才自然收斂到新基準,而那時它確實已經是新常態了。
            # ③ 這只影響**告警**,不影響 effective_limit()/remaining() 的校準路徑——
            #    校準要跟得下來,告警不該跟著爛狀態走,兩者本來就不該用同一個參考點。
            _prev_walls = [int(v.get("spent", 0) or 0) for _d, v in _days.items()
                           if _d != _today and _qm._is_wall(v)]
            # 沒有前牆時**不要就此放棄**:某天成功花掉 X 就證明那天的容量 >= X,
            # 那同樣是一個獨立於今天的參考點(quota_meter 的 floor 就是這個概念)。
            # 原本沒有這層 fallback,於是「帳本裡只有今天是牆」就走「首次觀測到撞牆」——
            # 而**平日不撞牆的產線每次撞牆都是這個狀態**,實測連跑 4 天四天都印「第一次」。
            # 一個月撞一次牆的產線,每次都在 Carson 手機上收到「這是第一次」。
            _prev_spend = [int(v.get("spent", 0) or 0) for _d, v in _days.items()
                           if _d != _today and not v.get("unreliable")]
            _ref = max(_prev_walls) if _prev_walls else (max(_prev_spend) if _prev_spend else None)
            _ref_kind = "帳本最高的牆" if _prev_walls else "帳本最高的單日成功花費"
            _base = _ref or _lim
            # 帶寬 65%。理由要說得出來,不能挑好看的數字:
            #   · 實測牆值 19,645 / 21,858 / 23,341 / 26,001,最低/最高 = **75.55%**
            #     —— 門檻 75% 距離一道**合法**的低牆只剩 0.55pp(145 units),
            #     08-27 那道真牆再低 145 units 就會被誤報成「牆變矮」。
            #   · 那個 75.55% 還跨了一次提額(19,645 是提額前的天花板);
            #     只看提額後的三道牆是 21,858/26,001 = 84.1%,抖動其實更小。
            #   · 腰斬 = 50%,砍三分之一 = 66.7%。
            # 65% 在「合法低牆 75.55%」下方留 10.55pp、在「腰斬 50%」上方留 15pp,
            # 兩邊都有 buffer 而不是貼著任一邊。
            # ⚠️ 代價寫明:**砍幅小於三分之一時它叫不出來**,那是不喊狼來了的價格;
            # 而那種砍幅若真的發生,排程會持續撞牆,由下面「沒退避」那條接住。
            _BAND = 0.65

            def _streak(pred) -> int:
                """今天(含)往回連續幾天符合 pred。日期不連續就停 —— 中間斷掉的日子
                不能當成「連續」,那會把兩段不同時期的事故黏成一段。"""
                import datetime as _d2
                n, cur = 0, _d2.date.fromisoformat(_today)
                while True:
                    b = _days.get(cur.isoformat())
                    if not b or not pred(b):
                        return n
                    n += 1
                    cur -= _d2.timedelta(days=1)
            _pct = _spent / max(_base, 1) * 100

            # 🔴 分母以前是 effective_limit(),它**涵蓋今天**,所以撞牆日恆印 100%。
            # 於是「牆變矮到 58%」那則的標題行卻寫 100%,同一段輸出兩行互相打架,
            # 而 ntfy 上先看到的就是標題行。_ref 解耦了判準,這裡把分母也解耦。
            lines.append(
                f"YouTube 配額: {_spent:,}/{_base:,} = {_pct:.0f}%"
                + (f"(分母={_ref_kind},不含今天)" if _ref
                   else f"(分母=effective_limit {_lim:,};帳本裡沒有任何一天可比)")
                + f"｜配額用罄被拒 {_rej} 次"
                + (f"、浪費 {_rej_units:,} units" if _rej_units else ""))
            if not _days:
                lines.append("   帳本目前沒有任何一天的紀錄(檔案合法,不是壞掉)")
            if _age_h is not None and _age_h > 24:
                warn.append(f"配額帳本 {_age_h:.0f} 小時沒被寫過")
                lines.append(f"   🔴 **帳本已經 {_age_h:.0f} 小時沒有被寫入** —— 每次 API 呼叫都會寫它,"
                             "這麼久沒動代表產線根本沒在打 API(而不是「配額用得很省」)")

            if _rej > 0:
                # `_is_wall()` 為 False 有三個理由(unreliable / spent=0 / 沒被拒),
                # 前兩個要**先分辨出來**,否則文案會自相矛盾:spent=26,001 + unreliable
                # 會印「這不是撞牆(撞牆的前提是先花得掉)」,而它明明花得掉。
                if _b.get("unreliable"):
                    warn.append(f"帳本 {_today} 標了 unreliable 又有 {_rej} 次被拒")
                    lines.append(f"   🔴 **當天帳本被標 unreliable,同時有 {_rej} 次被拒** —— "
                                 "這天的數字不能拿來校準天花板(所以 effective_limit 不採用它),"
                                 "但被拒是真的。先確認是誰、為什麼標 unreliable,再決定這天算不算撞牆")
                elif _spent <= 0:
                    warn.append(f"被拒 {_rej} 次但當天 spent=0")
                    lines.append(f"   🔴 **被拒 {_rej} 次而當天一 unit 都沒花成** —— 這不是撞牆"
                                 "(撞牆的前提是先花得掉)。可能是整日停權、憑證/專案有問題,"
                                 "或同一個 Cloud 專案被另一台機器吃光(Mac+MSI 共用時會)。"
                                 "先跑 python scripts/quota_meter.py 對帳,再查 assert_project()")
                else:
                    # 先算「有沒有退避」,因為它會改變牆高那行的措辭:
                    # 「配額用完了,這是設計預期」印在 🔴 沒退避的正上方會自打架 ——
                    # 用完是預期,撞牆後還白打 935 次不是。ntfy 上先看到的是這幾行,
                    # 同一段輸出不能一句說預期內、下一句說出事了而不交代兩者的關係。
                    # 兩條擇一即觸發,各自守不同的形狀:
                    #   ① 絕對值 100 次 —— 守「calls 沒被記或很小,但被拒次數爆量」。
                    #      實測正常撞牆日是 2 / 16 / 31 次,3 倍餘裕。
                    #   ② 佔當日 calls 的比例 —— 守「同樣被拒 31 次,在 calls=143 的日子
                    #      和 calls=400 的日子意義不同」。實測 rej/calls:
                    #      08-27 **326%** / 08-31 17% / 08-29 4% / 08-28 1% —— 分離很乾淨,
                    #      50% 的意思是「撞牆後白打掉的比做成的還多」。
                    #      要求 calls >= 50 才套用比例:真實日是 63~440 calls,
                    #      拿個位數 calls 去算比例是雜訊不是訊號(合成測試常是 calls=1)。
                    #   ③ 浪費 units 佔牆的 10% —— 08-27 是 232%,正常日 3.6/1.3/0.07%。
                    _cal = int(_b.get("calls", 0) or 0)
                    _no_backoff = (_rej > 100
                                   or (_cal >= 50 and _rej > _cal * 0.50)
                                   or _rej_units > _base * 0.10)

                    # ── 牆的高度 ────────────────────────────────────────────────
                    # 帶寬 75% 而不是 95%:帳本四個牆值 19,645 → 23,341 → 21,858 → 26,001,
                    # 相鄰日變動 118.8% / 93.6% / 119.0%,**±19% 是這個序列自己的常態抖動**。
                    # 5% 的帶寬比抖動窄,會把 08-29(16 次 × 1 unit,全天浪費 0.06%)
                    # 判成真陽性 —— 我原本就是這樣判的,而且引了一個**不存在的證據**
                    # (「查過 by_op」:record() 的 rejected 分支在寫 by_op 之前就 return,
                    # 結構上不可能記下哪個 op 被拒)。腰斬是 46%,離 75% 還很遠。
                    if _ref is None:
                        # 帳本裡**除了今天以外一天都沒有**。這是空帳本/首日,不是「第一次撞牆」——
                        # 舊文案寫「這是帳本裡第一次觀測到撞牆」,而它每次都會這樣講。
                        warn.append(f"撞牆於 {_spent:,},但帳本裡沒有任何一天可比")
                        lines.append(f"   🔴 **花到 {_spent:,} 開始被拒,而帳本裡除了今天沒有別的日子**"
                                     "—— 沒有參考點,無法判斷這是正常用滿還是天花板變矮。"
                                     "明天起就有得比了;若這行連續出現,代表帳本一直被清空,那是另一個問題")
                    elif _pct >= _BAND * 100:
                        # 🔴 65~95% 這段原本一律當預期內,而**溫和調降就落在這裡**:
                        # 配額砍 31%(26,001 → 18,000)= 69.2%,牆變矮不叫;而驗證員拿
                        # 我自己校準用的那四個真實撞牆日去打「沒退避會接住」這個承重理由,
                        # 四天裡有三天(2 / 16 / 31 次被拒)落在門檻之下,連跑五天全綠。
                        # **我是用一個離群值(08-27,935 次)校準的門檻,所以它只接得住離群值。**
                        # 結果是配額砍 31% 兩條都不叫、無限期靜音,而配額調整通常不是腰斬。
                        #
                        # 補法不是把門檻調鬆(單日牆值本來就在 19,645~26,001 之間擺,
                        # 調鬆就開始誤報),而是用**時間**當第二個維度:
                        # 溫和調降的特徵是「幅度不大但持續存在」——單日低一點是雜訊,
                        # 連續多天低一點才是訊號。
                        # M=3 的根據:真帳本上「牆低於當時參考點 95%」最長連續 **1 天**
                        # (08-29 那天,前後都在 95% 之上),3 留了 2 天餘裕。
                        _mild = _streak(lambda b: _qm._is_wall(b)
                                        and int(b.get("spent", 0) or 0) < _base * 0.95)
                        if _pct < 95 and _mild >= 3:
                            warn.append(f"配額牆持續偏低({_pct:.0f}%,已連續 {_mild} 天)")
                            lines.append(f"   🔴 **牆連續 {_mild} 天低於{_ref_kind} {_ref:,}"
                                         f"(今天 {_spent:,} = {_pct:.0f}%)** —— 單日低一點是雜訊,"
                                         "連續就不是了。這是溫和調降的形狀(砍幅不到三分之一,"
                                         "所以「牆變矮」那條的 65% 門檻叫不出來)。"
                                         "跑 quota_meter.py 對帳,查 assert_project(),"
                                         "並確認是不是有別的東西在吃同一個 Cloud 專案")
                        else:
                            lines.append(f"   ℹ️ 花到 {_spent:,}({_ref_kind} {_ref:,} 的 {_pct:.0f}%)"
                                         "才開始被拒 = 配額真的用完了,牆本身沒變矮"
                                         + ("(用完是預期,但下面那條不是)" if _no_backoff else
                                            ",這是設計預期(11 支/天刻意跑在 95%)。"
                                            "要多做事只有兩條路:提額,或砍非發布的花費")
                                         + (f";連續偏低 {_mild} 天(連 3 天才告警)"
                                            if _mild >= 2 and _pct < 95 else ""))
                    else:
                        # 永久調降 = 連續 30 天同一則紅字,而同一句話講 30 遍沒有人會讀到第 3 天。
                        # 帶上天數讓它從噪音變成趨勢:「已連續 17 天」在第 17 天還看得懂。
                        _n = _streak(lambda b: _qm._is_wall(b)
                                     and int(b.get("spent", 0) or 0) < _base * _BAND)
                        _d = f",已連續 {_n} 天" if _n >= 2 else ""
                        warn.append(f"配額牆變矮({_spent:,} = {_ref_kind} {_ref:,} 的 {_pct:.0f}%{_d})")
                        lines.append(f"   🔴 **只花到 {_spent:,} 就有 {_rej} 次被拒,而{_ref_kind}是"
                                     f" {_ref:,}({_pct:.0f}%){_d}** —— 天花板比我們以為的矮,或有別的"
                                     "東西在吃同一個 Cloud 專案。這是本項當初被加進來的理由:"
                                     "被拒次數比已用量更早示警。跑 quota_meter.py 對帳,查 assert_project()"
                                     + (f"。連續 {_n} 天代表這已經不是單日事故,是新的容量" if _n >= 3 else ""))

                    # ── 撞牆之後有沒有退避 ──────────────────────────────────────
                    # 和牆高**獨立**判、可同時叫。「配額用完了」和「配額用完了還白打 935 次、
                    # 浪費 45,491 units」是兩件事:後者代表排程撞牆後沒退避,而那是這個警報
                    # 唯一真正該叫的情境。08-27 在對照表裡會紅字**只因為它剛好是第一道牆**,
                    # 從今以後永遠有前牆,同樣的一天就再也不會叫 —— 一個剛修好的警報
                    # 又變回不會叫,只是換了個理由。
                    # 門檻:被拒 > 100 次(實測正常撞牆日是 2 / 16 / 31 次,3 倍餘裕)
                    #       或浪費 > 牆的 10%(08-27 浪費 45,491 = 牆的 232%;
                    #       正常日 850 / 325 / 16 units = 3.6% / 1.3% / 0.07%)。
                    # 兩個都收是因為 rejected_units 可能沒被記(今天就是 None)。
                    if _no_backoff:
                        _nb = _streak(lambda b: int(b.get("rejected_calls", 0) or 0) > 100
                                      or int(b.get("rejected_units", 0) or 0) > _base * 0.10)
                        _nd = f",已連續 {_nb} 天" if _nb >= 2 else ""
                        warn.append(f"撞牆後沒退避(被拒 {_rej} 次"
                                    + (f"、浪費 {_rej_units:,} units" if _rej_units else "") + _nd + ")")
                        lines.append(f"   🔴 **撞牆之後還被拒了 {_rej} 次"
                                     + (f",白打掉 {_rej_units:,} units(牆的 {_rej_units/max(_base,1)*100:.0f}%)"
                                        if _rej_units else "")
                                     + _nd
                                     + "** —— 配額用完不是問題,問題是排程**沒有退避**,"
                                     "撞牆後還在照跑。查 YT_QUOTA_ENFORCE 是不是關著,"
                                     "以及哪支腳本沒有接 QuotaExhausted")
            elif _pct >= 95:
                # 花很多但**零被拒** = 該做的都做成了。舊版在這裡進 warn,
                # 那是把「刻意跑滿」報成異常,天天紅字。
                lines.append(f"   ℹ️ 已用 {_pct:.0f}% 但零被拒 = 全部做成了,不是異常"
                             "(這條線設計上就跑在 95%)")
    except Exception as _e:  # noqa: BLE001
        # 🔴 這裡原本是 `pass`。一個 NameError 因此靜音了三個月,而健檢**看起來一切正常**——
        # 那正是 memory verification-that-cannot-fail 的第①種「不會叫的警報」。
        # 檢查本身壞掉,是比被檢查的東西壞掉更該叫的事:一個不會叫的健檢會讓整條線
        # 無限期「看起來健康」。所以改成留下痕跡並計入告警,而不是無聲吞。
        lines.append(f"YouTube 配額: ⚠️ 這項檢查自己壞了({_e!r})—— 不是「配額正常」")
        warn.append(f"配額檢查壞掉({type(_e).__name__})")

    summary = "\n".join(lines)
    verdict = ("🔴 有異常: " + "、".join(warn)) if warn else "✅ 全部正常"
    print(summary)
    print(verdict)

    if "--notify" in sys.argv:
        try:
            import notify
            notify.push("量化阿森｜每日健檢", verdict + "\n" + "\n".join(lines[1:]),
                        tag="green_heart" if not warn else "rotating_light")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ntfy 失敗:{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
