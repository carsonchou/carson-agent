"""路由層 —— FastAPI，四平台 /sale-ping/* 串起 驗簽→正規化→業務處理。

每平台一個路徑（content-type / 簽章機制各異，分開最乾淨）。路由只做三件事：
讀 raw body（驗簽需要原文）→ verify.require_*（fail-closed）→ normalize.parse_*
→ service.process_event。build_app(settings) 是工廠：正式 app 用 Settings.from_env()，
測試傳自訂 Settings（tmp 路徑 + 假 adder/sender）。

啟動：uvicorn quant-service.webhook.app:app --host 0.0.0.0 --port 8021
"""
from __future__ import annotations

import json
import sys
import urllib.parse

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from . import normalize, service, verify
from .config import Settings
from .events import EventKind

try:  # Windows 主控台中文 print 防呆（與其他工作室腳本一致）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _json_or_400(body: bytes):
    """驗簽通過後才解析 body；壞 JSON 一律 400 不是 500。

    為什麼重要：webhook 平台對 5xx 會**持續重試**（retry storm），4xx 才會停。
    平台送出截斷/空 body 的邊界事件時，裸奔的 json.loads 會噴 JSONDecodeError
    → FastAPI 回 500 → 平台無限重投同一顆壞蛋。回 400 明確告訴平台「這顆別再送」。
    （VERIFY_REPORT_phase3a B1）
    """
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"malformed JSON payload: {e.__class__.__name__}") from e


def _run(ev, settings, background_tasks: BackgroundTasks):
    """成交/訂閱進帳走背景處理（記帳/交付有 IO）；退款/取消同步做（要即時反映名冊）。"""
    if ev.kind in (EventKind.REFUND, EventKind.SUB_CANCEL, EventKind.IGNORED):
        return service.process_event(ev, settings)
    if ev.kind not in (EventKind.SALE, EventKind.SUB_NEW, EventKind.SUB_RENEW):
        return {"status": "ignored", "event": ev.raw_event}
    if not ev.email:
        raise HTTPException(422, "缺少買家 email，無法交付")
    background_tasks.add_task(service.process_event, ev, settings)
    return {"status": "accepted", "platform": ev.platform, "kind": ev.kind.value,
            "order_id": ev.order_id}


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    api = FastAPI(title="量化阿森 電商金流 webhook", version="2.0.0")
    api.state.settings = settings

    @api.get("/health")
    async def health():
        from .subscribers import count_active
        return {"status": "ok", "service": "量化阿森 電商金流 v2",
                "active_subscribers": count_active(settings.subscribers_book)}

    @api.post("/sale-ping/gumroad")
    async def sale_gumroad(request: Request, background_tasks: BackgroundTasks,
                           x_ping_token: str = Header(default="")):
        body = await request.body()
        form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8")).items()}
        token = request.query_params.get("token", "") or x_ping_token
        verify.require_gumroad(settings, form, token)
        ev = normalize.parse_gumroad(form)
        return _run(ev, settings, background_tasks)

    @api.post("/sale-ping/lemonsqueezy")
    async def sale_lemonsqueezy(request: Request, background_tasks: BackgroundTasks,
                                x_signature: str = Header(default="")):
        body = await request.body()
        verify.require_lemonsqueezy(settings, body, x_signature)
        ev = normalize.parse_lemonsqueezy(_json_or_400(body))
        return _run(ev, settings, background_tasks)

    @api.post("/sale-ping/whop")
    async def sale_whop(request: Request, background_tasks: BackgroundTasks,
                        webhook_id: str = Header(default=""),
                        webhook_timestamp: str = Header(default=""),
                        webhook_signature: str = Header(default="")):
        body = await request.body()
        verify.require_whop(settings, body, webhook_id, webhook_timestamp, webhook_signature)
        ev = normalize.parse_whop(_json_or_400(body), webhook_id)
        return _run(ev, settings, background_tasks)

    @api.post("/sale-ping/portaly")
    async def sale_portaly(request: Request, background_tasks: BackgroundTasks,
                           x_portaly_signature: str = Header(default="")):
        body = await request.body()
        verify.require_portaly(settings, body, x_portaly_signature)
        ev = normalize.parse_portaly(_json_or_400(body))
        return _run(ev, settings, background_tasks)

    return api


# 正式入口（uvicorn quant-service.webhook.app:app）
app = build_app()
