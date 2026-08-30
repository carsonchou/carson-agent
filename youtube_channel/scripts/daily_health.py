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
    try:
        import quota_meter as _qm
        _b = (_qm._load().get("days") or {}).get(_qm._pacific_date(), {})
        _spent = int(_b.get("spent", 0))
        _rej = int(_b.get("rejected_calls", 0))
        _lim = _qm.DAILY_LIMIT
        lines.append(f"YouTube 配額: {_spent:,}/{_lim:,} = {_spent/max(_lim,1)*100:.0f}%"
                     f"｜配額用罄被拒 {_rej} 次")
        if _rej > 0:
            warns.append(f"配額撞牆({_rej}次被拒)")
            lines.append("   🔴 **有呼叫因配額用罄被拒** = 當天有東西沒做成(多半是發布少發一支,"
                         "而它不會噴錯、只會靜默跳過)。跑 python scripts/quota_meter.py 看是誰吃掉的")
        elif _spent > _lim * 0.95:
            warns.append(f"配額 {_spent/_lim*100:.0f}%")
    except Exception:  # noqa: BLE001
        pass

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
