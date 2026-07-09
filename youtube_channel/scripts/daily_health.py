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

    base = _leak_check()
    lines.append(f"洗版洩漏基準線: {base if base is not None else '未建'}(每週 weekly_winners 監控是否突破)")

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
