"""
webhook_server.py — FastAPI 訂單接收器

接收 n8n 從 Google Form 送來的 webhook，
觸發 AI agent，發 ntfy 通知 Carson 審核。

啟動: uvicorn webhook_server:app --host 0.0.0.0 --port 8020
"""

import os
import json
import hmac
import base64
import hashlib
import asyncio
import smtplib
import tempfile
import threading
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

try:  # Windows 主控台預設 cp950/ascii，中文 print 會 UnicodeEncodeError；統一導 utf-8（與其他工作室腳本一致）
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

app = FastAPI(title="量化阿森 AI 接單系統", version="1.0.0")

QUEUE_DIR = Path(__file__).parent / "queue"
OUTPUT_DIR = Path(__file__).parent / "output"
QUEUE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "carsonquant-hc-9k3x7m2q")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # 可選：n8n webhook 驗證用


# ── 資料結構 ──────────────────────────────────────────────

class OrderRequest(BaseModel):
    order_id: Optional[str] = None
    client_email: str
    client_name: Optional[str] = ""
    product_type: str  # technical / grid_bot / portfolio / strategy / custom
    task: str          # 任務描述（Google Form 填的）
    payment_amount: Optional[float] = 0.0
    payment_currency: Optional[str] = "USD"


class ApproveRequest(BaseModel):
    order_id: str
    report_path: str
    client_email: str
    custom_note: Optional[str] = ""


# ── 核心 Endpoints ────────────────────────────────────────

@app.post("/order")
async def receive_order(order: OrderRequest, background_tasks: BackgroundTasks):
    """接收新訂單，排入佇列並觸發 AI agent"""
    if not order.order_id:
        order.order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    order_dict = order.model_dump()
    order_dict["received_at"] = datetime.now().isoformat()
    order_dict["status"] = "queued"

    queue_path = QUEUE_DIR / f"{order.order_id}.json"
    queue_path.write_text(json.dumps(order_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    background_tasks.add_task(_process_order, order_dict)

    return {"status": "queued", "order_id": order.order_id}


@app.post("/approve")
async def approve_order(req: ApproveRequest, background_tasks: BackgroundTasks):
    """Carson 審核通過後，自動寄信給客戶"""
    background_tasks.add_task(_deliver_report, req.order_id, req.report_path, req.client_email, req.custom_note)
    return {"status": "delivering", "order_id": req.order_id}


@app.get("/orders")
async def list_orders():
    """列出所有待審核訂單"""
    orders = []
    for f in QUEUE_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            orders.append({
                "order_id": data.get("order_id"),
                "status": data.get("status"),
                "client_email": data.get("client_email"),
                "task": data.get("task", "")[:80],
                "received_at": data.get("received_at"),
            })
        except Exception:
            pass
    return sorted(orders, key=lambda x: x.get("received_at", ""), reverse=True)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "量化阿森 AI 接單系統"}


# ── 背景任務 ─────────────────────────────────────────────

async def _process_order(order: dict):
    """在背景執行 AI agent"""
    order_id = order["order_id"]
    print(f"[{order_id}] 開始 AI 處理...")

    _update_queue_status(order_id, "processing")

    try:
        from real_task_runner import run_task, build_task_text
        task_text = build_task_text(order)
        result = await asyncio.to_thread(
            run_task,
            task_text,
            order_id,
            order["client_email"],
            order.get("product_type", "custom"),
        )
        _update_queue_status(order_id, "pending_review", report_path=result["report_path"])
        print(f"[{order_id}] AI 完成，等待 Carson 審核")
    except Exception as e:
        _update_queue_status(order_id, "error", error=str(e))
        _send_ntfy(f"❌ 訂單 {order_id} 處理失敗: {str(e)[:200]}", f"[量化阿森] 錯誤 {order_id}")
        print(f"[{order_id}] 錯誤: {e}")


async def _deliver_report(order_id: str, report_path: str, client_email: str, custom_note: str = ""):
    """審核通過後寄信交付"""
    try:
        report_content = Path(report_path).read_text(encoding="utf-8")
        _send_report_email(client_email, order_id, report_content, custom_note)
        _update_queue_status(order_id, "delivered")
        print(f"[{order_id}] 已交付給 {client_email}")
        _send_ntfy(f"✅ 訂單 {order_id} 已交付給 {client_email}", f"[量化阿森] 交付完成 {order_id}")
    except Exception as e:
        print(f"[{order_id}] 交付失敗: {e}")
        _send_ntfy(f"❌ 訂單 {order_id} 交付失敗: {e}", f"[量化阿森] 交付錯誤 {order_id}")


# ── 工具函式 ─────────────────────────────────────────────

def _update_queue_status(order_id: str, status: str, **extra):
    queue_path = QUEUE_DIR / f"{order_id}.json"
    if not queue_path.exists():
        return
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    data["status"] = status
    data.update(extra)
    data["updated_at"] = datetime.now().isoformat()
    queue_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _send_ntfy(message: str, title: str = "量化阿森"):
    try:
        import httpx
        httpx.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            content=message.encode("utf-8"),
            headers={"Title": title},
            timeout=10,
        )
    except Exception as e:
        print(f"ntfy 失敗: {e}")


def _smtp_send(to_email: str, subject: str, body: str, ctx: str = "") -> bool:
    """寄一封純文字信；SMTP 未設定則跳過（回 False）。回 True 代表實際送出。"""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")

    if not smtp_user or not smtp_pass:
        print(f"[{ctx}] SMTP 未設定，跳過寄信（收件人 {to_email}）")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
    return True


def _send_report_email(to_email: str, order_id: str, report_md: str, custom_note: str = ""):
    body = f"""您好，

感謝您訂購量化阿森的 AI 分析報告！

{f'附註：{custom_note}' if custom_note else ''}

以下是您的報告內容：

{'─' * 60}

{report_md}

{'─' * 60}

如有任何問題，歡迎回覆此信。

祝投資順利！
量化阿森 Carson Quant
YouTube: https://www.youtube.com/@carsonquant
"""
    _smtp_send(to_email, f"[量化阿森] 您的分析報告已完成 - {order_id}", body, ctx=order_id)


# ══════════════════════════════════════════════════════════════════════════
#  電商金流閉環：平台銷售 webhook → 驗簽 → 記帳 + 交付 + 名單
#  四平台各一個子路徑（content-type / 簽章機制各異，分開最乾淨），
#  驗簽通過後全部收斂進 _process_sale() 做去重/記帳/交付。
# ══════════════════════════════════════════════════════════════════════════

# 記帳/名單簿與 finance.json 同置於 youtube_channel/STUDIO（revenue_dashboard.py 讀得到）
_YT_STUDIO = Path(__file__).resolve().parent.parent / "youtube_channel" / "STUDIO"
_YT_SCRIPTS = Path(__file__).resolve().parent.parent / "youtube_channel" / "scripts"
SALES_LEDGER = _YT_STUDIO / "ecommerce_sales.json"
CUSTOMERS_BOOK = _YT_STUDIO / "ecommerce_customers.json"

# 每平台簽章密鑰（環境變數，不寫死）；未設定 → 該平台 fail-closed（回 503，不接受無法驗證的請求）
GUMROAD_SELLER_ID = os.getenv("GUMROAD_SELLER_ID", "").strip()
# Gumroad Ping 無 HMAC 簽章、seller_id 又是公開資訊(出現在賣家頁/URL)不算密鑰。真正的驗真靠這個私密 token：
# Gumroad Ping URL 由賣家自訂，把 token 加在 query(…/sale-ping/gumroad?token=xxx)或 X-Ping-Token header，
# 收端以 compare_digest timing-safe 比對，沒設或不符即 fail-closed。這是 shared-secret 驗證，非「靠 seller_id 驗真」。
GUMROAD_PING_TOKEN = os.getenv("GUMROAD_PING_TOKEN", "").strip()
PORTALY_WEBHOOK_SECRET = os.getenv("PORTALY_WEBHOOK_SECRET", "").strip()
LEMONSQUEEZY_WEBHOOK_SECRET = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "").strip()
WHOP_WEBHOOK_SECRET = os.getenv("WHOP_WEBHOOK_SECRET", "").strip()

_LEDGER_LOCK = threading.Lock()


def _save_json_atomic(path: Path, data) -> None:
    """唯一 tmp + os.replace 原子寫入（對齊 studio_common 併發安全寫檔慣例）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _verify_hmac_hex(secret: str, body: bytes, provided: str) -> bool:
    """HMAC-SHA256 hex digest 比對（Lemon Squeezy / Portaly）。timing-safe。"""
    if not secret or not provided:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.strip().lower())


def _verify_standard_webhooks(secret: str, wh_id: str, wh_ts: str, body: bytes, sig_header: str) -> bool:
    """Standard Webhooks 規格（Whop）：簽章內容 = f"{id}.{ts}.{body}"，
    HMAC-SHA256 以 base64 解碼後的密鑰，輸出 base64，比對 header 內任一 v1 簽章。
    密鑰常帶 whsec_ 前綴，前綴後為 base64。"""
    if not (secret and wh_id and wh_ts and sig_header):
        return False
    raw_secret = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw_secret)
    except Exception:  # noqa: BLE001
        key = raw_secret.encode("utf-8")
    signed = f"{wh_id}.{wh_ts}.".encode("utf-8") + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in sig_header.split():
        candidate = part.split(",", 1)[1] if part.startswith("v1,") else part
        if hmac.compare_digest(expected, candidate):
            return True
    return False


def _to_float(v) -> float:
    try:
        return round(float(v), 2)
    except Exception:  # noqa: BLE001
        return 0.0


# ── 四平台 parser：回傳 normalized sale dict 或 raise HTTPException ──────────
# normalized: {platform, event_key(去重), email, name, product, amount, currency, order_id, is_refund}

def _parse_gumroad(form: dict, token: str = "") -> dict:
    """Gumroad Ping：application/x-www-form-urlencoded。Gumroad 不簽 HMAC，seller_id 是公開資訊不是密鑰，
    故驗真靠賣家自訂 Ping URL 上的私密 shared-secret token(query ?token= 或 X-Ping-Token header)，
    以 compare_digest timing-safe 比對；seller_id 僅作次級比對。兩者任一未設或不符即 fail-closed。
    欄位依 https://gumroad.com/ping：seller_id/product_name/email/price(分)/currency/sale_id/order_number/refunded/disputed。"""
    if not GUMROAD_PING_TOKEN:
        raise HTTPException(503, "GUMROAD_PING_TOKEN 未設定，無法驗證 Gumroad 來源")
    if not hmac.compare_digest((token or "").strip(), GUMROAD_PING_TOKEN):
        raise HTTPException(401, "Gumroad ping token 不符（偽造來源已擋）")
    if not GUMROAD_SELLER_ID:
        raise HTTPException(503, "GUMROAD_SELLER_ID 未設定，無法驗證來源")
    if (form.get("seller_id") or "") != GUMROAD_SELLER_ID:
        raise HTTPException(401, "Gumroad seller_id 不符")
    sale_id = form.get("sale_id") or form.get("order_number") or ""
    is_refund = str(form.get("refunded", "")).lower() == "true" or str(form.get("disputed", "")).lower() == "true"
    return {
        "platform": "gumroad",
        "event_key": f"gumroad:{sale_id}",
        "email": (form.get("email") or "").strip(),
        "name": form.get("full_name") or form.get("purchaser_id") or "",
        "product": form.get("product_name") or form.get("permalink") or "",
        "amount": _to_float(form.get("price", 0)) / 100.0,  # Gumroad price 以最小幣值單位（分）計
        "currency": (form.get("currency") or "usd").upper(),
        "order_id": sale_id,
        "is_refund": is_refund,
    }


def _parse_lemonsqueezy(body: bytes, sig: str) -> dict:
    """Lemon Squeezy：JSON + X-Signature(hex HMAC-SHA256 of raw body)。
    payload: meta.event_name / data.attributes.{user_email,order_number,total(分),currency,first_order_item.product_name}。"""
    if not LEMONSQUEEZY_WEBHOOK_SECRET:
        raise HTTPException(503, "LEMONSQUEEZY_WEBHOOK_SECRET 未設定")
    if not _verify_hmac_hex(LEMONSQUEEZY_WEBHOOK_SECRET, body, sig or ""):
        raise HTTPException(401, "Lemon Squeezy 簽章驗證失敗")
    p = json.loads(body.decode("utf-8"))
    event = (p.get("meta") or {}).get("event_name", "")
    attrs = (p.get("data") or {}).get("attributes") or {}
    first_item = attrs.get("first_order_item") or {}
    order_id = str(attrs.get("order_number") or (p.get("data") or {}).get("id") or "")
    return {
        "platform": "lemonsqueezy",
        "event_key": f"lemonsqueezy:{order_id}",
        "email": (attrs.get("user_email") or "").strip(),
        "name": attrs.get("user_name") or "",
        "product": first_item.get("product_name") or attrs.get("product_name") or "",
        "amount": _to_float(attrs.get("total", 0)) / 100.0,  # total 以分計
        "currency": (attrs.get("currency") or "USD").upper(),
        "order_id": order_id,
        "is_refund": event in ("order_refunded", "subscription_payment_refunded"),
        "_event": event,
    }


def _parse_whop(body: bytes, wh_id: str, wh_ts: str, wh_sig: str) -> dict:
    """Whop：JSON + Standard Webhooks 簽章（webhook-id/webhook-timestamp/webhook-signature）。
    payload: type(如 payment.succeeded) / data{...}。data 內欄位名 Whop 官方未第一手明列 → 防禦式多鍵擷取（標為暫定）。"""
    if not WHOP_WEBHOOK_SECRET:
        raise HTTPException(503, "WHOP_WEBHOOK_SECRET 未設定")
    if not _verify_standard_webhooks(WHOP_WEBHOOK_SECRET, wh_id, wh_ts, body, wh_sig or ""):
        raise HTTPException(401, "Whop 簽章驗證失敗")
    p = json.loads(body.decode("utf-8"))
    etype = p.get("type") or p.get("action") or ""
    d = p.get("data") or {}
    user = d.get("user") if isinstance(d.get("user"), dict) else {}
    did = str(d.get("id") or wh_id or "")
    return {
        "platform": "whop",
        "event_key": f"whop:{wh_id or did}",
        "email": (d.get("email") or d.get("user_email") or user.get("email") or "").strip(),
        "name": d.get("name") or user.get("username") or user.get("name") or "",
        "product": d.get("product") or d.get("plan") or d.get("product_name") or "",
        "amount": _to_float(d.get("final_amount") or d.get("amount") or d.get("subtotal") or 0),
        "currency": (d.get("currency") or "USD").upper(),
        "order_id": did,
        "is_refund": etype in ("payment.refunded", "membership.cancelled", "membership.went_invalid"),
        "_event": etype,
    }


def _parse_portaly(body: bytes, sig: str) -> dict:
    """Portaly（台灣）：JSON。⚠️ 官方無第一手 webhook spec 文件（僅 n8n 教學證實 webhook 存在且含 姓名/email）；
    此處簽章採 HMAC-SHA256 hex（header X-Portaly-Signature）+ 欄位名皆為暫定，上線前需以真實 Portaly 測試 webhook 校準。"""
    if not PORTALY_WEBHOOK_SECRET:
        raise HTTPException(503, "PORTALY_WEBHOOK_SECRET 未設定")
    if not _verify_hmac_hex(PORTALY_WEBHOOK_SECRET, body, sig or ""):
        raise HTTPException(401, "Portaly 簽章驗證失敗")
    p = json.loads(body.decode("utf-8"))
    d = p.get("data") if isinstance(p.get("data"), dict) else p
    order_id = str(d.get("order_id") or d.get("id") or d.get("order_number") or "")
    return {
        "platform": "portaly",
        "event_key": f"portaly:{order_id}",
        "email": (d.get("email") or d.get("buyer_email") or d.get("customer_email") or "").strip(),
        "name": d.get("name") or d.get("buyer_name") or d.get("姓名") or "",
        "product": d.get("product_name") or d.get("product") or d.get("item_name") or "",
        "amount": _to_float(d.get("amount") or d.get("price") or d.get("total") or 0),
        "currency": (d.get("currency") or "TWD").upper(),
        "order_id": order_id,
        "is_refund": str(d.get("status", "")).lower() in ("refunded", "refund", "cancelled"),
    }


# ── 路由（各平台一個；讀 raw body 供驗簽） ──────────────────────────────────

@app.post("/sale-ping/gumroad")
async def sale_gumroad(request: Request, background_tasks: BackgroundTasks,
                       x_ping_token: str = Header(default="")):
    import urllib.parse
    body = await request.body()
    form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8")).items()}
    token = request.query_params.get("token", "") or x_ping_token
    sale = _parse_gumroad(form, token)
    return _accept_sale(sale, background_tasks)


@app.post("/sale-ping/lemonsqueezy")
async def sale_lemonsqueezy(request: Request, background_tasks: BackgroundTasks,
                            x_signature: str = Header(default="")):
    body = await request.body()
    sale = _parse_lemonsqueezy(body, x_signature)
    ev = sale.get("_event")
    # 退款事件(order_refunded 等)必須放行進 _accept_sale→_record_refund 沖銷；只有「非退款且非成交」才略過。
    if ev and not sale.get("is_refund") and ev not in ("order_created", "subscription_payment_success"):
        return {"status": "ignored", "event": ev}
    return _accept_sale(sale, background_tasks)


@app.post("/sale-ping/whop")
async def sale_whop(request: Request, background_tasks: BackgroundTasks,
                    webhook_id: str = Header(default=""), webhook_timestamp: str = Header(default=""),
                    webhook_signature: str = Header(default="")):
    body = await request.body()
    sale = _parse_whop(body, webhook_id, webhook_timestamp, webhook_signature)
    ev = sale.get("_event")
    # 退款/退會事件(payment.refunded 等)必須放行進 _accept_sale→_record_refund 沖銷；只有「非退款且非成交」才略過。
    if ev and not sale.get("is_refund") and ev not in ("payment.succeeded", "membership.went_valid", "membership.activated"):
        return {"status": "ignored", "event": ev}
    return _accept_sale(sale, background_tasks)


@app.post("/sale-ping/portaly")
async def sale_portaly(request: Request, background_tasks: BackgroundTasks,
                       x_portaly_signature: str = Header(default="")):
    body = await request.body()
    sale = _parse_portaly(body, x_portaly_signature)
    return _accept_sale(sale, background_tasks)


def _accept_sale(sale: dict, background_tasks: BackgroundTasks):
    if sale.get("is_refund"):
        _record_refund(sale)
        return {"status": "refund_logged", "order_id": sale.get("order_id")}
    if not sale.get("email"):
        raise HTTPException(422, "缺少買家 email，無法交付")
    background_tasks.add_task(_process_sale, sale)
    return {"status": "accepted", "platform": sale["platform"], "order_id": sale.get("order_id")}


# ── 收斂處理：去重 → 記帳簿 → finance.json → 交付信 → 顧客簿 → ntfy ──────────

async def _process_sale(sale: dict):
    key = sale["event_key"]
    with _LEDGER_LOCK:
        ledger = _load_json(SALES_LEDGER, [])
        if any(isinstance(r, dict) and r.get("event_key") == key for r in ledger):
            print(f"[sale] 重複事件 {key}，略過（webhook at-least-once 去重）")
            return
        record = {
            "event_key": key, "platform": sale["platform"], "order_id": sale.get("order_id", ""),
            "email": sale["email"], "name": sale.get("name", ""), "product": sale.get("product", ""),
            "amount": sale.get("amount", 0.0), "currency": sale.get("currency", ""),
            "received_at": datetime.now().isoformat(), "delivered": False,
        }
        ledger.append(record)
        _save_json_atomic(SALES_LEDGER, ledger)
        _record_customer(sale)

    _record_revenue(sale)

    delivered = await asyncio.to_thread(_deliver_product, sale)

    if delivered:
        with _LEDGER_LOCK:
            ledger = _load_json(SALES_LEDGER, [])
            for r in ledger:
                if isinstance(r, dict) and r.get("event_key") == key:
                    r["delivered"] = True
                    r["delivered_at"] = datetime.now().isoformat()
            _save_json_atomic(SALES_LEDGER, ledger)

    _send_ntfy(
        f"💰 {sale['platform']} 新訂單：{sale.get('product','')} "
        f"{sale.get('currency','')}{sale.get('amount',0):.2f}｜{sale['email']}"
        + ("｜已寄交付信" if delivered else "｜⚠️交付信未送(SMTP未設定)"),
        f"[量化阿森] 電商成交 {sale['platform']}",
    )


def _record_customer(sale: dict):
    """顧客簿（email 為 key）。⚠️不寫入 tg_leads.json：那本以 TG chat_id 為 key、
    tg_magnet.py 會逐一 sendMessage；電商買家只有 email 無 chat_id，混入會造成失敗發送並污染轉換率統計。
    真 TG 推播需買家先私訊磁鐵 bot 才有 chat_id，故此處只『記錄』顧客，不做 TG 推播。"""
    book = _load_json(CUSTOMERS_BOOK, {})
    if not isinstance(book, dict):
        book = {}
    email = sale["email"].lower()
    entry = book.get(email) or {"first_seen": datetime.now().isoformat(), "orders": 0, "src": sale["platform"]}
    entry["orders"] = int(entry.get("orders", 0)) + 1
    entry["last_product"] = sale.get("product", "")
    entry["last_order_at"] = datetime.now().isoformat()
    entry["name"] = sale.get("name", "") or entry.get("name", "")
    entry["tg_pushed"] = False  # 無 chat_id，尚未做 TG 推播
    book[email] = entry
    _save_json_atomic(CUSTOMERS_BOOK, book)


def _record_revenue(sale: dict, refund: bool = False):
    """記入 finance.json（走既有 finance_dept.add_entry，schema 單一真相來源）→ revenue_dashboard.py 讀得到。
    refund=True 時記一筆負值沖銷，讓退款不再把原始銷售收入永久留在 revenue_dashboard（修營收高估）。
    幣別原樣傳給 add_entry（分幣別加總，不混加 TWD/USD）。"""
    try:
        import sys
        if str(_YT_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_YT_SCRIPTS))
        import finance_dept
        currency = (sale.get("currency") or "").upper() or "USD"
        signed = -abs(sale.get("amount", 0.0)) if refund else sale.get("amount", 0.0)
        tag = "REFUND 退款沖銷 " if refund else ""
        note = f"{tag}{sale['platform']} {currency}{signed:.2f} " \
               f"order={sale.get('order_id','')} {sale.get('product','')}".strip()
        finance_dept.add_entry("product", signed, note=note,
                               platform=sale["platform"], stream="product", currency=currency)
    except Exception as e:  # noqa: BLE001
        print(f"[sale] {'退款沖銷' if refund else '記帳'}失敗 {sale.get('event_key')}: {e}")


def _record_refund(sale: dict):
    """退款：ecommerce_sales.json 記負值 + finance.json 記負值沖銷。用退款專屬 event_key 去重，
    webhook at-least-once 重送同一筆退款不會重複沖銷。"""
    refund_key = sale["event_key"] + ":refund"
    with _LEDGER_LOCK:
        ledger = _load_json(SALES_LEDGER, [])
        if any(isinstance(r, dict) and r.get("event_key") == refund_key for r in ledger):
            print(f"[sale] 重複退款事件 {refund_key}，略過（去重，不重複沖銷）")
            return
        ledger.append({
            "event_key": refund_key, "platform": sale["platform"],
            "order_id": sale.get("order_id", ""), "email": sale.get("email", ""),
            "amount": -abs(sale.get("amount", 0.0)), "currency": sale.get("currency", ""),
            "type": "refund", "received_at": datetime.now().isoformat(),
        })
        _save_json_atomic(SALES_LEDGER, ledger)
    # 只有非重複的退款才沖銷 finance.json（在鎖外呼叫，避免與 add_entry 的檔案 IO 疊鎖）
    _record_revenue(sale, refund=True)
    print(f"[sale] 退款記錄+finance 沖銷 {refund_key}")


def _deliver_product(sale: dict) -> bool:
    """寄出商品交付信（placeholder 內容；實際商品打包由 product_factory 另行產生）。"""
    product = sale.get("product") or "您購買的量化阿森數位商品"
    body = f"""您好{('　' + sale['name']) if sale.get('name') else ''}，

感謝您在 {sale['platform']} 購買「{product}」！

這是您的商品交付信。（📦 商品內容/下載連結為 placeholder，正式打包上線後此處會帶實際下載連結與內容）

訂單編號：{sale.get('order_id','')}
金額：{sale.get('currency','')} {sale.get('amount',0):.2f}

如有任何問題，直接回覆此信即可。

量化阿森 Carson Quant
YouTube: https://www.youtube.com/@carsonquant
"""
    try:
        return _smtp_send(sale["email"], f"[量化阿森] 您的商品已送達 - {product}", body, ctx=sale["event_key"])
    except Exception as e:  # noqa: BLE001
        print(f"[sale] 交付信寄送失敗 {sale.get('event_key')}: {e}")
        return False
