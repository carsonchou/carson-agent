"""交付層 —— 交付信（config 驅動 SKU 對照、下載連結 placeholder、預設 dry_run）+ ntfy。

交付信的商品對照「讀 config.SKU_CATALOG / download_url_for」而非 hardcode：
新增 SKU 只改 config。下載連結維持 placeholder 機制——對應環境變數未設 → 不寄真連結，
信裡帶「正式打包上線後帶實際下載連結」佔位語。訂閱 SUB_NEW 寄歡迎信、SUB_RENEW 不重寄。

依賴注入：settings.email_sender 非 None 就用它（測試傳假 sender 收集寄信內容）；
否則用 smtplib。settings.dry_run=True（預設）時一律不真寄，只回 dry-run 結果。
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import DISCLAIMER, download_url_for
from .events import EventKind

_FOOTER = ("\n\n量化阿森 Carson Quant\nYouTube: https://www.youtube.com/@carsonquant\n"
           + DISCLAIMER)


def _smtp_send(to_email: str, subject: str, body: str) -> bool:
    """真寄一封純文字信；SMTP 未設定 → 跳過回 False。"""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pw = os.getenv("SMTP_PASS", "")
    if not user or not pw:
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, pw)
        server.sendmail(user, to_email, msg.as_string())
    return True


def _download_block(sku_id: str) -> str:
    url = download_url_for(sku_id)
    if url:
        return f"下載連結：{url}"
    return ("（📦 下載連結為 placeholder，正式打包上線後此處帶實際下載連結；"
            f"設定環境變數 ECOMMERCE_DL_* 即可帶入 SKU={sku_id} 的真連結）")


def _compose(ev) -> tuple[str, str]:
    """依事件類型組交付信主旨與內文（config 驅動，非 hardcode 商品表）。"""
    who = ("　" + ev.name) if ev.name else ""
    product = ev.product or "您購買的量化阿森數位商品"
    if ev.kind == EventKind.SUB_NEW:
        subject = f"[量化阿森] 訂閱開通 - {product}"
        body = (f"您好{who}，\n\n感謝您訂閱「{product}」（層級：{ev.tier or '—'}）！\n"
                f"您將開始收到每週的台股全市場週報與每日掃描。\n\n"
                f"訂單編號：{ev.order_id}\n金額：{ev.currency} {ev.amount:.2f}\n\n"
                f"第一份週報會在下個排程寄達。如有問題直接回覆此信即可。{_FOOTER}")
        return subject, body
    if ev.kind == EventKind.SUB_RENEW:
        # 續訂不重寄歡迎信（避免每期打擾）；回空主旨代表「不需寄信」。
        return "", ""
    # 一次性商品
    subject = f"[量化阿森] 您的商品已送達 - {product}"
    body = (f"您好{who}，\n\n感謝您在 {ev.platform} 購買「{product}」！\n\n"
            f"{_download_block(ev.sku_id)}\n\n"
            f"訂單編號：{ev.order_id}\n金額：{ev.currency} {ev.amount:.2f}\n\n"
            f"如有任何問題，直接回覆此信即可。{_FOOTER}")
    return subject, body


def needs_manual_delivery(ev) -> bool:
    """一次性商品但下載連結未設 → 這封信不能寄給真的付錢的客人。

    為什麼(2026-07-16 加):`_download_block()` 在 ECOMMERCE_DL_* 未設時會塞一段
    「下載連結為 placeholder,正式打包上線後此處帶實際下載連結;設定環境變數…」——
    那是寫給開發者看的內部字。以前 dry_run 恆為 True(沒人載 .env)所以不會外流;
    現在 .env 載入器修好、SMTP 憑證一被讀到 dry_run 就自動關 → **付了 NT$990 的客人
    會收到一封叫他自己去設環境變數的信**。收錢給壞連結,踩動錢+對外雙紅線。

    故 fail-safe:連結沒備妥就**不寄**,改用 ntfy 緊急叫 Carson 手動交付。
    客人等幾分鐘拿到真東西 >> 立刻收到一封開發者筆記。
    """
    return ev.kind == EventKind.SALE and not download_url_for(ev.sku_id)


def deliver(ev, settings) -> dict:
    """交付商品/開通信。回 {sent, dry_run, reason?}。
    dry_run（預設）或 SUB_RENEW（不重寄）→ 不真寄。
    下載連結未備妥 → 拒寄(見 needs_manual_delivery)。"""
    subject, body = _compose(ev)
    if not subject:
        return {"sent": False, "dry_run": settings.dry_run, "reason": "續訂不重寄"}
    if not ev.email:
        return {"sent": False, "dry_run": settings.dry_run, "reason": "缺 email"}
    if not settings.dry_run and needs_manual_delivery(ev):
        # 寧可不寄也不能把 placeholder 內部字寄給付錢的客人
        print(f"[delivery] ⚠️ 拒寄:SKU={ev.sku_id} 下載連結未設(ECOMMERCE_DL_*)。"
              f"訂單 {ev.order_id} / {ev.email} 需手動交付。")
        return {"sent": False, "dry_run": False, "manual_required": True,
                "reason": f"下載連結未設(SKU={ev.sku_id}),已擋下 placeholder 信,需手動交付",
                "to": ev.email}
    if settings.dry_run:
        return {"sent": False, "dry_run": True, "to": ev.email,
                "subject": subject, "preview": body[:160]}
    sender = settings.email_sender or _smtp_send
    try:
        ok = bool(sender(ev.email, subject, body))
        return {"sent": ok, "dry_run": False, "to": ev.email}
    except Exception as e:  # noqa: BLE001
        print(f"[delivery] 交付信寄送失敗 {ev.event_key}: {e}")
        return {"sent": False, "dry_run": False, "reason": str(e)}


def _httpx_ntfy(topic: str, title: str, body: str) -> None:
    """真打 ntfy。Title 必須 ASCII（HTTP header 限制）→ 中文只放 body(utf-8 content)。"""
    import httpx
    httpx.post(f"https://ntfy.sh/{topic}", content=body.encode("utf-8"),
               headers={"Title": title}, timeout=10)


def notify(ev, settings, delivered: dict) -> None:
    """ntfy 通知 Carson。dry_run 只印；否則走 settings.ntfy_poster（測試注入假的，
    不打外網）或預設 httpx。Title 保持 ASCII 避免 header 編碼錯誤，中文放 body。"""
    if delivered.get("manual_required"):
        # 有人真的付錢了但東西寄不出去 → 這是最該吵醒 Carson 的一種通知,別跟一般成交同級
        tail = f"｜🚨需你手動交付({delivered.get('reason','')})"
    elif delivered.get("sent"):
        tail = "｜已寄交付信"
    elif delivered.get("dry_run"):
        tail = "｜(dry_run 未寄)"
    else:
        tail = "｜⚠️交付信未送"
    body = (f"💰 {ev.platform} {ev.kind.value}：{ev.product} "
            f"{ev.currency}{ev.amount:.2f}｜{ev.email}{tail}")
    title = ("CarsonQuant MANUAL DELIVERY NEEDED" if delivered.get("manual_required")
             else f"CarsonQuant ecommerce {ev.platform}")   # ASCII only（header 安全）
    if settings.dry_run:
        print("[ntfy dry_run]", title, body)
        return
    poster = settings.ntfy_poster or _httpx_ntfy
    try:
        poster(settings.ntfy_topic, title, body)
    except Exception as e:  # noqa: BLE001
        print(f"[ntfy] 失敗: {e}")
