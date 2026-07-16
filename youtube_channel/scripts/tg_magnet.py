#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tg_magnet.py — 公開名單磁鐵 bot(@CarsonQuant_message_bot,獨立於私人指令 bot)。

兩種模式:
  (無參數) poll 模式:觀眾私訊 → 自動送「新手回測避雷檢核表」+ 記名單(STUDIO/tg_leads.json)。
           每 5 分鐘 cron poll(getUpdates + offset 去重)。
  --digest 避雷雷達週報:彙整最近《拆穿》題目/避雷重點,群發給 tg_leads.json 全名單(每人一則)。
           供 cron 每週跑一次;有節流(避免 Telegram 限流)+ 去重(本週發過不重發)。
  --upsell 數位產品試算表 upsell(item12):對領檢核表滿 24h 名單推 NT$149 一次性試算表,見 run_upsell。
  --newsletter 付費電子報 pitch(item A2·經常性收入):對已買 worksheet 或名單滿 7 天的對象推 NT$99/月電子報,
           見 run_newsletter_pitch;推播完把該 lead stage 升到 3,是否真訂閱仍由 Carson 人工對帳確認。
  各模式皆支援 --dry(只印預覽/不實送,無收款方式時自動強制 dry)。

token 放雲端 .env 的 TG_MAGNET_TOKEN。與 telegram_command.py 是不同 bot/不同 token,各跑各的不衝突。
"""
import os, sys, json, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

try:  # Windows 主控台 cp950 印不出 emoji;統一導 utf-8(與其他工作室腳本一致)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
BANK = STUDIO / "topic_bank.json"
DIGEST_SENT = STUDIO / "tg_digest_sent.json"   # 週報去重:記本週已發過的 chat_id
# 《拆穿》/避雷題目辨識關鍵字(從題庫挑本週雷達內容)
_DEBUNK_KW = ("拆穿", "揭穿", "揭露", "打臉", "打假", "真相", "騙局", "智商稅", "被割", "避雷", "翻車", "韭菜")
# 群發節流:每則間隔秒數(Telegram 對 bot 群發約 30 msg/s 上限,保守放慢避免觸發限流)
_THROTTLE_SEC = 1.5
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass

try:  # 併發安全寫檔(多支腳本/cron 併發碰 tg_leads.json 時消互毀);沒有就退回原本 write_text
    from studio_common import save_json_atomic as _save_leads_atomic
except Exception:  # noqa: BLE001
    _save_leads_atomic = None

TOKEN = os.environ.get("TG_MAGNET_TOKEN", "").strip()
OFFSET = STUDIO / "tg_magnet_offset.json"
LEADS = STUDIO / "tg_leads.json"
_PIONEX = "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna"
_MAGNET = (
    "🎯 量化阿森・新手回測避雷檢核表\n\n"
    "把真錢丟給任何機器人／策略前，先過這 6 關：\n"
    "1️⃣ 手續費算了沒？來回 0.2%，交易上千次會吃光你的獲利。\n"
    "2️⃣ 加了滑價嗎？回測不含滑價＝假績效，實盤常倒賠。\n"
    "3️⃣ 做過樣本外測試嗎？只在歷史最佳參數上漂亮＝過擬合，換行情就崩。\n"
    "4️⃣ 最大回撤扛得住嗎？帳面 -30% 你睡得著？扛不住就會殺在低點。\n"
    "5️⃣ 停損設對了嗎？太緊被巴、太鬆爆倉，連敗 10 次剩多少先算過。\n"
    "6️⃣ 只押一注嗎？單一策略／標的重壓＝一次黑天鵝歸零。\n\n"
    "過不了這 6 關，先別上真錢。\n\n"
    "我自己在用的零維護做法是 Pionex 內建網格（設一次自己跑）：\n"
    f"{_PIONEX}\n"
    "（聯盟連結，透過它註冊不增加你成本、也支持頻道做真數據內容；投資有風險，不構成投資建議。）"
)

# 「聰明用 AI」magnet(opt-in 才送:打「省AI/便宜/共享/Claude…」才觸發,預設仍送上面的 Pionex 檢核表)
_PREMLOGIN = "https://premlogin.com/M9LKTnk2"
_MAGNET_AI = (
    "🎯 量化阿森・2026 便宜用 AI 全攻略\n\n"
    "Claude/ChatGPT 一個月上百鎂太貴？便宜用的方法我全試過,老實比較（這是資訊、不是推銷）：\n\n"
    "① 官方訂閱：最穩、可商用,但最貴。\n"
    "② 第三方共享合租（如 PremLogin）：省最多(可到 2 折),但 ⚠️ 非官方、帳號可能被官方停用,想省錢的自己評估風險。\n"
    "③ 走 API：用多少付多少,適合開發者/量大,需要一點技術。\n"
    "④ 免費額度：$0 但有限、會限速,輕度嘗鮮夠用。\n\n"
    "要穩就走官方；要省又扛得住「帳號可能被停」的風險,共享合租這裡：\n"
    f"{_PREMLOGIN}\n"
    "（第三方共享·非官方·可能被停用·透過連結註冊不增加你成本但請自負風險評估；本表為資訊比較非推銷。）"
)
_AI_KW = ("省ai", "省 ai", "便宜", "共享", "合租", "拼車", "claude", "chatgpt", "gemini", "ai帳號", "ai 帳號")

# 數位產品 upsell(item12):免費檢核表送出滿 24h 的名單,追加一則低價試算表 upsell(收款連結 Carson 自填 env WORKSHEET_URL)。
# 誠信:只賣真有內容的東西、不誇大不保證收益;價格對得起內容量(NT$149-249 一杯手搖等級破冰價)。
_WORKSHEET_URL = os.environ.get("WORKSHEET_URL", "").strip()
_PAYINFO = STUDIO / "payment_info.json"
_UPSELL_DELAY_SEC = 24 * 3600  # 領檢核表滿 24h 才送,避免第一次接觸就推銷感太重
_UPSELL = (
    "📊 那份免費檢核表你收到了嗎？\n\n"
    "想「自己動手算」的話——我把 6 關做成可填試算表：輸入你的手續費%、滑價%、交易頻率、槓桿，\n"
    "直接算出這些隱藏成本一年吃掉你多少報酬，再附我實際回測案例的完整數字拆解。\n\n"
    "一次性 NT$149，一杯手搖的錢，上真錢前先看清楚自己的策略會不會漏財。\n\n"
    "{pay}\n"
    "（想清楚再買，這是工具不是明牌；投資有風險，不構成投資建議。）"
)

# 付費電子報(item A2:經常性收入)。對象=已買過 worksheet(stage>=2,較有付費意願)或名單建立滿 7 天。
# 誠信:內容原料一律來自現成 STUDIO 真回測/避雷資料,不臨時編數字;不喊單不保證收益,交付走 TG 付費頻道(人工拉群,非自動)。
_NEWSLETTER_URL = os.environ.get("NEWSLETTER_URL", "").strip()
# 主金流:Portaly 訂閱連結(台灣本土·自動續訂+自動發票,免人工對帳)。env 未設或仍是 placeholder → 退回舊銀行匯款人工對帳流程。
_PORTALY_SUBSCRIPTION_URL = os.environ.get("PORTALY_SUBSCRIPTION_URL", "[PORTALY_URL_PLACEHOLDER]").strip()
_NEWSLETTER_DELAY_SEC = 7 * 24 * 3600  # 名單建立滿 7 天才推(給 worksheet 買家額外快速資格,見 run_newsletter_pitch)
_NEWSLETTER = (
    "📮 想每週固定收到避雷清單＋真回測數字嗎？\n\n"
    "我開了付費電子報，NT$99／月：\n"
    "1️⃣ 每週台股＋加密雙軌『避雷清單』——挑出正在割韭菜的話術／機器人先幫你標出來。\n"
    "2️⃣ 搭配真回測摘要數字，不是嘴巴講講，附實測結果。\n"
    "3️⃣ 透過 Telegram 付費頻道交付，訂閱就收得到。\n\n"
    "先講清楚：這是資訊整理，不是明牌，不喊單、不保證收益，你還是要自己判斷再進場。\n\n"
    "{pay}\n"
    "（想清楚再訂；投資有風險，不構成投資建議。）"
)


def _pay_instructions():
    """組付款指示:優先讀 STUDIO/payment_info.json(銀行匯款);沒有則退回 WORKSHEET_URL 連結。"""
    try:
        import json as _j
        info = _j.loads(_PAYINFO.read_text(encoding="utf-8")) if _PAYINFO.exists() else {}
    except Exception:  # noqa: BLE001
        info = {}
    if info.get("method") == "bank_transfer" and info.get("account"):
        return (f"匯款 NT$149 到：{info.get('bank_name','')}（{info.get('bank_code','')}）"
                f"{info.get('account')} 戶名 {info.get('account_name','')}\n"
                "匯款後私訊我「已匯款＋帳號末五碼」，我對帳後把試算表發給你。")
    if _WORKSHEET_URL:
        return _WORKSHEET_URL
    return ""


def run_upsell(dry=False) -> int:
    """對『領檢核表滿 24h 且未 upsell』的名單,送一則低價試算表 upsell(item12)。
    需 env WORKSHEET_URL(收款/交付連結,Carson 自填);未填則只 dry 不實送,避免送出沒連結的殘信。"""
    leads = _load_leads()
    if not leads:
        print("[upsell] 名單為空,略過。")
        return 0
    pay = _pay_instructions()
    if not pay:
        print("[upsell] 無收款方式(payment_info.json/WORKSHEET_URL 皆空),先不實送。")
        dry = True
    now = int(time.time())
    text = _UPSELL.replace("{pay}", pay or "（收款方式待設定）")
    sent = 0
    for chat_id, info in list(leads.items()):
        if not isinstance(info, dict):
            continue
        ts = int(info.get("ts", 0) or 0)
        if info.get("upsold") or ts <= 0 or (now - ts) < _UPSELL_DELAY_SEC:
            continue
        if dry:
            print(f"[dry] 會 upsell → {info.get('username') or chat_id}")
            sent += 1
            continue
        if not TOKEN:
            print("[info] 未設 TG_MAGNET_TOKEN,upsell 未送。")
            return 0
        r = _api("sendMessage", chat_id=chat_id, text=text[:3900])
        if r.get("ok"):
            info["upsold"] = int(now)
            sent += 1
            time.sleep(_THROTTLE_SEC if "_THROTTLE_SEC" in globals() else 1.5)
    if not dry and sent:
        try:
            LEADS.write_text(json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        log_ops("TG數位產品", f"試算表 upsell 送出 {sent} 人")
    print(f"[ok] upsell {'(dry)' if dry else ''} 對象 {sent} 人。")
    return 0


def _newsletter_pay_instructions():
    """組電子報訂閱付款指示(NT$99/月)。
    主路:Portaly 訂閱連結(自動續訂+自動發票,免人工對帳);env PORTALY_SUBSCRIPTION_URL 未設或仍是 placeholder → 退回舊流程。
    退路(fallback):payment_info.json 銀行匯款人工對帳拉群 → 再退 NEWSLETTER_URL 連結(Carson 自填 env)。"""
    if _PORTALY_SUBSCRIPTION_URL and _PORTALY_SUBSCRIPTION_URL != "[PORTALY_URL_PLACEHOLDER]":
        return (f"點這裡直接訂閱(每月自動續、可隨時取消):\n{_PORTALY_SUBSCRIPTION_URL}\n"
                "訂閱完成後系統自動把你加進電子報頻道,不用等我人工對帳。")
    # ── 以下為 Portaly 未設時的退路:舊「銀行匯款人工對帳」流程,刻意保留不刪 ──
    try:
        info = json.loads(_PAYINFO.read_text(encoding="utf-8")) if _PAYINFO.exists() else {}
    except Exception:  # noqa: BLE001
        info = {}
    if info.get("method") == "bank_transfer" and info.get("account"):
        return (f"匯款 NT$99／月 到：{info.get('bank_name','')}（{info.get('bank_code','')}）"
                f"{info.get('account')} 戶名 {info.get('account_name','')}\n"
                "匯款後私訊我「已匯款＋帳號末五碼」，我對帳後把你加進電子報頻道。")
    if _NEWSLETTER_URL:
        return _NEWSLETTER_URL
    return ""


def run_newsletter_pitch(dry=False) -> int:
    """對『已買 worksheet(stage>=2)』或『名單建立滿 7 天』且尚未推過電子報的名單,推 NT$99/月付費電子報 pitch(item A2)。
    推播成功即把該 lead stage 升到 3(『已推播訂閱邀約』;是否真訂閱仍由 Carson 人工對帳確認,不自動判定已付款)。
    無收款方式(payment_info.json/NEWSLETTER_URL 皆空)時強制轉 dry,不送出沒有交付路徑的殘信。"""
    leads = _load_leads()
    if not leads:
        print("[newsletter] 名單為空,略過。")
        return 0
    pay = _newsletter_pay_instructions()
    if not pay:
        print("[newsletter] 無收款方式(payment_info.json/NEWSLETTER_URL 皆空),先不實送。")
        dry = True
    now = int(time.time())
    text = _NEWSLETTER.replace("{pay}", pay or "（收款方式待設定）")
    sent = 0
    for chat_id, info in list(leads.items()):
        if not isinstance(info, dict):
            continue
        if info.get("newslettered"):  # 已推過,不重推
            continue
        stage = int(info.get("stage", 0) or 0)
        ts = int(info.get("ts", 0) or 0)
        eligible = stage >= 2 or (ts > 0 and (now - ts) >= _NEWSLETTER_DELAY_SEC)
        if not eligible:
            continue
        if dry:
            print(f"[dry] 會推電子報 → {info.get('username') or chat_id}(stage={stage})")
            sent += 1
            continue
        if not TOKEN:
            print("[info] 未設 TG_MAGNET_TOKEN,電子報未送。")
            return 0
        r = _api("sendMessage", chat_id=chat_id, text=text[:3900])
        if r.get("ok"):
            info["newslettered"] = int(now)
            info["stage"] = max(stage, 3)
            sent += 1
            time.sleep(_THROTTLE_SEC)
    if not dry and sent:
        try:
            if _save_leads_atomic:
                _save_leads_atomic(LEADS, leads)
            else:
                LEADS.write_text(json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        log_ops("TG電子報", f"付費電子報 pitch 送出 {sent} 人")
    print(f"[ok] 電子報 {'(dry)' if dry else ''} 對象 {sent} 人。")
    return 0


def _api(method, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        data = urllib.parse.urlencode(params).encode()
        return json.loads(urllib.request.urlopen(url, data=data, timeout=20).read())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _send(chat_id, text):
    _api("sendMessage", chat_id=chat_id, text=text[:3900])


def _offset():
    try:
        return int(json.loads(OFFSET.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:  # noqa: BLE001
        return 0


def _save_offset(o):
    try:
        OFFSET.write_text(json.dumps({"offset": o}), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _load_leads():
    try:
        return json.loads(LEADS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ───────────────────────── 避雷雷達週報 (--digest) ─────────────────────────
def _week_key():
    """ISO 年-週,如 2026-W27。同一週重跑不重發。"""
    y, w, _ = datetime.now(timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def _load_digest_sent():
    try:
        d = json.loads(DIGEST_SENT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    wk = _week_key()
    if d.get("week") != wk:      # 跨週 → 清空重來
        d = {"week": wk, "sent": []}
    d.setdefault("week", wk)
    d.setdefault("sent", [])
    return d


def _save_digest_sent(d):
    try:
        DIGEST_SENT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _radar_topics(n=4):
    """從題庫挑最近的《拆穿》/避雷題目(題庫最前=最新)當本週雷達內容。無題庫或無命中→回空清單。"""
    try:
        bank = json.loads(BANK.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    picks, seen = [], set()
    for t in bank:
        title = (t.get("title") or "").strip()
        blob = f"{title} {t.get('category','')} {t.get('angle','')}"
        if title and any(k in blob for k in _DEBUNK_KW):
            key = title[:24]
            if key not in seen:
                seen.add(key)
                picks.append(title)
        if len(picks) >= n:
            break
    return picks


def _build_digest():
    """組本週『避雷雷達』週報。有題庫拆穿題就列題,沒有就退回避雷心法保底,永遠有內容可發。"""
    topics = _radar_topics()
    head = "🛰️ 量化阿森・本週避雷雷達\n\n我用免費回測,把正在割韭菜的量化/AI神話一個個拆給你看:\n\n"
    if topics:
        body = "\n".join(f"🔻 {t}" for t in topics)
        tail = ("\n\n這週先把這幾個坑標出來。完整拆解＋真回測數字都在 YouTube『量化阿森』。\n"
                "想點題拆哪個神話?直接回我這則訊息 👇\n\n我幫你避雷,不賣你夢。")
    else:
        body = ("🔻『812%程式碼』被百萬人看過——真回測跑完剩多少?\n"
                "🔻 勝率88.89%神策略——扣掉手續費滑價還贏嗎?\n"
                "🔻 穩賺被動收入機器人——背後其實是100倍槓桿?\n"
                "🔻 馬丁格爾越攤越省——那是死亡數學,不是省錢術。")
        tail = ("\n\n上真錢前,先讓我用回測幫你踩一遍。完整拆解都在 YouTube『量化阿森』。\n"
                "想點題拆哪個神話?回我這則訊息 👇\n\n我幫你避雷,不賣你夢。")
    return head + body + tail


def run_digest(dry=False) -> int:
    """群發本週避雷雷達給全名單。節流 + 本週去重;dry 或無名單則空跑不真的發。"""
    leads = _load_leads()
    msg = _build_digest()
    if dry:
        print("[dry] 避雷雷達週報預覽:\n" + "-" * 40 + f"\n{msg}\n" + "-" * 40)
        print(f"[dry] 名單 {len(leads)} 人,實跑會逐一群發(節流 {_THROTTLE_SEC}s/則、本週已發者跳過)。")
        return 0
    if not TOKEN:
        print("[info] 未設 TG_MAGNET_TOKEN，週報未發送(dry 邏輯已通過)。"); return 0
    if not leads:
        print("[info] 名單為空,無人可發。"); return 0
    sent_state = _load_digest_sent()
    already = set(sent_state["sent"])
    ok = skip = fail = 0
    for chat_id in list(leads.keys()):
        if chat_id in already:
            skip += 1
            continue
        r = _api("sendMessage", chat_id=chat_id, text=msg[:3900])
        if r.get("ok"):
            ok += 1
            sent_state["sent"].append(chat_id)
        else:
            fail += 1
        _save_digest_sent(sent_state)   # 邊發邊存,中斷可續、不重發
        time.sleep(_THROTTLE_SEC)
    log_ops("TG避雷雷達", f"週報群發 ok={ok} skip={skip} fail={fail} /{len(leads)}")
    print(f"[ok] 避雷雷達週報:發送 {ok}、本週已發跳過 {skip}、失敗 {fail}(名單 {len(leads)})。")
    return 0


def main() -> int:
    if "--digest" in sys.argv:
        return run_digest(dry=("--dry" in sys.argv))
    if "--upsell" in sys.argv:
        return run_upsell(dry=("--dry" in sys.argv))
    if "--newsletter" in sys.argv:
        return run_newsletter_pitch(dry=("--dry" in sys.argv))
    if not TOKEN:
        print("[info] 未設 TG_MAGNET_TOKEN，名單 bot 未啟用。"); return 0
    off = _offset()
    r = _api("getUpdates", offset=off, timeout=0, allowed_updates='["message"]')
    if not r.get("ok"):
        print(f"[warn] getUpdates 失敗：{str(r)[:120]}", file=sys.stderr); return 0
    ups = r.get("result", [])
    leads = _load_leads()
    last, new = off, 0
    for u in ups:
        last = max(last, u.get("update_id", 0) + 1)
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat_id:
            continue
        if chat_id not in leads:  # 新名單:送磁鐵 + 記錄
            # C2 歸因:首訊暗號分流來源(各平台 caption 用不同暗號)→看哪個平台最會帶名單/賺
            _tl = text.lower()
            src = ("tiktok" if ("抖" in text or "tk" in _tl) else
                   "instagram" if "ig" in _tl else
                   "youtube")
            leads[chat_id] = {"username": chat.get("username", ""), "name": chat.get("first_name", ""),
                              "first_msg": text[:40], "ts": int(time.time()), "src": src, "stage": 1}
            # opt-in 分流:打「省AI/便宜/共享/Claude…」→ 送 AI 省錢版(含共享連結、已揭露);其餘一律送 Pionex 檢核表預設
            if any(k in text.lower() for k in _AI_KW):
                _send(chat_id, _MAGNET_AI)
            else:
                _send(chat_id, _MAGNET)
            new += 1
            log_ops("TG名單磁鐵", f"新名單 {chat.get('username') or chat_id}")
        else:  # 回頭客:輕回覆不洗版
            _send(chat_id, "完整回測數據＋每天更新都在我 YouTube『量化阿森』。有量化／網格的問題直接問我，我會看。")
    try:
        LEADS.write_text(json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    _save_offset(last)
    print(f"[ok] 名單 bot：新名單 {new}，累計 {len(leads)}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
