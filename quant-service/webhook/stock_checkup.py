"""路由層 —— 個股體檢「多檔動態選股」(T3 SKU) 即時分析 + ECPay(綠界)導轉付款。

對應 docs/ecommerce/SPEC_stock_checkup_multi_artifact.md 決策點 1/3/5:掛在既有 webhook
FastAPI 服務下(不開新服務),伺服端直接 import data_hunter 既有模組算指標。付款走
ECPay 綠界(Carson 09-16 二次拍板:LINE Pay 個人申請卡在「Online API」產品門檻未釐清,
改用綠界),見 ecpay.py 開頭說明——ECPay 跟 Gumroad/Portaly/LemonSqueezy/Whop 一樣是
**inbound 背景通知簽章驗證**,建立訂單也不打 API,是簽好章的表單交給瀏覽器直接 POST
到 ECPay 付款頁。(舊的 LINE Pay 整合 linepay.py 仍在、已測過,但本檔不再引用它——
留作日後若要切回的備案,見 config.py Settings 欄位註解。)

流程:
  1. GET  /stock-checkup                          → 前端頁面(選股 + 免費預覽)
  2. POST /api/stock-checkup/analyze              → 最多5檔即時算「個股體檢」
                                                      (query.analyze_stock + health.compute_health,
                                                      data_hunter 既有引擎,非重造)
  3. POST /api/stock-checkup/order                → 記一筆待付訂單(token=MerchantTradeNo→
                                                      codes/email),組好簽章的 ECPay 表單參數
                                                      存進訂單;密鑰/PUBLIC_BASE_URL 未設 →
                                                      回 checkout_url:null,前端顯示「尚未
                                                      上架」,不捏造連結。
  4. GET  /api/stock-checkup/ecpay/checkout/{token} → 回一頁自動送出的 HTML 表單,瀏覽器
                                                      直接 POST 到 ECPay AioCheckOut 付款頁
                                                      (checkout_url 指這裡,前端不必知道
                                                      這是 ECPay)。
  5. 使用者在 ECPay 頁面完成付款 → ECPay 主動 POST 背景通知到
     /api/stock-checkup/ecpay/notify → 驗 CheckMacValue 對得上、RtnCode=1、金額吻合
     才算真的扣款完成 → 呼叫既有 service.process_event 走記帳/名冊/交付信既有流程;
     哪 5 檔要出報告,由客服對 token(訂單編號)查待付訂單檔手動出件——與 T1/T2 現況
     一致(ECOMMERCE_DL_T3 未設時交付信帶 placeholder,不寄假連結)。回應必須是純文字
     "1|OK",否則 ECPay 會一直重送。
  6. 使用者付款後瀏覽器被導回 /api/stock-checkup/ecpay/result(OrderResultURL)——這只是
     使用者看的提示頁,不是權威判定(權威判定只看第 5 步的背景通知),不會單靠這個網址
     就標記付款完成。
"""
from __future__ import annotations

import html
import re
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import ecpay, service, vision
from .events import EventKind, NormalizedEvent
from .ledger import load_json, save_json_atomic

_HERE = Path(__file__).resolve().parent            # quant-service/webhook
_QS = _HERE.parent                                  # quant-service
_DATA_HUNTER = _QS / "data_hunter"
_STATIC_HTML = _HERE / "static" / "stock_checkup.html"

SKU_ID = "T3_multi_checkup"
PRODUCT_NAME = "個股體檢多檔組合(最多5檔)"
PRICE_NTD = 100
MAX_STOCKS = 5
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024                 # 8MB,手機庫存截圖綽綽有餘
_CODE_RE = re.compile(r"^[0-9A-Z]{4,6}$")

router = APIRouter()


def _ensure_data_hunter_on_path() -> None:
    """data_hunter 內部模組是扁平 import(非套件),要把它加進 sys.path 才 import 得到。"""
    p = str(_DATA_HUNTER)
    if p not in sys.path:
        sys.path.insert(0, p)


def _clean_codes(raw: list[str]) -> list[str]:
    seen: list[str] = []
    for c in raw or []:
        code = (c or "").strip().upper()
        if not code or code in seen:
            continue
        if not _CODE_RE.match(code):
            raise HTTPException(422, f"股票代號格式看起來不對:{c!r}")
        seen.append(code)
        if len(seen) > MAX_STOCKS:
            raise HTTPException(422, f"最多只能選 {MAX_STOCKS} 檔")
    if not seen:
        raise HTTPException(422, "至少要選 1 檔股票")
    return seen


# 免費預覽「數字+缺口式教唆」:只挑真的算得出來的欄位(見 query._merge_fundamentals /
# fundamentals.py),依吸引力排序,最多挑 2 個給使用者看,沒資料的欄位不提——避免承諾
# SPEC 裡宣稱但沒接上的估值區間/流動比等欄位(grep query.py 零命中,已三方查核確認)。
_TEASER_STAT_CANDIDATES = [
    ("dividend_yield", "殖利率", "%"),
    ("eps_yoy", "EPS 年增率", "%"),
    ("rev_yoy", "營收年增率", "%"),
    ("pe", "本益比", "倍"),
    ("gross_margin", "毛利率", "%"),
]
_PILLAR_LABEL = {"技術": "技術面", "籌碼": "籌碼面", "基本面": "基本面", "估值": "估值面"}
_PILLAR_GAP_THRESHOLD = 15  # 分差 < 這個門檻就不夠戲,改講中性句


def _pick_teaser_stats(r: dict) -> list[dict]:
    stats: list[dict] = []
    for key, label, unit in _TEASER_STAT_CANDIDATES:
        v = r.get(key)
        if v is None:
            continue
        sign = "+" if unit == "%" and v > 0 else ""
        stats.append({"label": label, "value": f"{sign}{v:g}{unit}"})
        if len(stats) == 2:
            break
    return stats


def _teaser_line(health: dict) -> str:
    pillars = health.get("pillars") or {}
    scored = [
        (name, p.get("score")) for name, p in pillars.items()
        if p.get("has_data") and p.get("score") is not None
    ]
    if len(scored) < 2:
        return "四大面向資料還在補齊,完整報告有逐項指標數值可以細看。"
    scored.sort(key=lambda x: x[1])
    weak_name, weak_score = scored[0]
    strong_name, strong_score = scored[-1]
    if strong_score - weak_score < _PILLAR_GAP_THRESHOLD:
        return "四大面向表現接近,細節差異要看完整報告才分得出來。"
    return (
        f"{_PILLAR_LABEL.get(strong_name, strong_name)}撐分({round(strong_score)}分)"
        f",{_PILLAR_LABEL.get(weak_name, weak_name)}拖分({round(weak_score)}分)"
        "——完整報告有逐項指標數值可以細看。"
    )


def _analyze_one(code: str) -> dict:
    """單檔體檢:用 data_hunter 既有 query.analyze_stock + health.compute_health,
    不重算技術/籌碼/基本面邏輯。任何例外優雅降級,不讓單一檔失敗拖垮整批。"""
    _ensure_data_hunter_on_path()
    try:
        import query as _query  # data_hunter/query.py
    except Exception as exc:  # noqa: BLE001
        return {"code": code, "ok": False, "error": f"分析引擎載入失敗:{exc}"}
    try:
        r = _query.analyze_stock(code, live=False)
    except Exception as exc:  # noqa: BLE001
        return {"code": code, "ok": False, "error": f"分析失敗:{exc}"}
    if not r.get("ok"):
        return {"code": code, "ok": False, "error": r.get("error") or "查無資料"}
    health = r.get("health") or {}
    return {
        "code": r.get("code"), "name": r.get("name"), "industry": r.get("industry"),
        "ok": True,
        "price": r.get("price"), "chg": r.get("chg"),
        "pe": r.get("pe"), "pb": r.get("pb"), "dividend_yield": r.get("dividend_yield"),
        "eps_ttm": r.get("eps_ttm"), "eps_yoy": r.get("eps_yoy"),
        "rev_yoy": r.get("rev_yoy"), "gross_margin": r.get("gross_margin"),
        "teaser_stats": _pick_teaser_stats(r),
        "teaser_line": _teaser_line(health),
        "health": {
            "overall": health.get("overall"), "grade": health.get("grade"),
            "confidence": health.get("confidence"),
            "pillars": {
                name: {"score": p.get("score"), "has_data": p.get("has_data")}
                for name, p in (health.get("pillars") or {}).items()
            },
        },
    }


class AnalyzeRequest(BaseModel):
    codes: list[str] = Field(default_factory=list)


class OrderRequest(BaseModel):
    codes: list[str] = Field(default_factory=list)
    email: str = ""


@router.get("/stock-checkup")
async def stock_checkup_page():
    if not _STATIC_HTML.exists():
        raise HTTPException(500, "頁面檔案未部署")
    return FileResponse(_STATIC_HTML, media_type="text/html")


@router.post("/api/stock-checkup/analyze")
async def analyze(body: AnalyzeRequest):
    """逐檔查詢各有本地快取未命中時的 bounded live-fetch(見 query._load_df /
    _merge_fundamentals)。
    🔴09-16 實測:Render 免費方案 WEB_CONCURRENCY=1(單一 vCPU 且被限流,且與其他
    租戶共享,實際可用 CPU 隨時間浮動,非固定值)。原本平行全開(max_workers=
    len(codes))想讓總時間貼齊單檔最慢的那一檔,但 1~3 檔平行的「安全上限」實測
    不穩定——同樣 3 檔在不同時間點測試,有時 100% 成功,有時全滅,4 檔更明顯反覆
    橫跳(3 成功1失敗 vs 1 成功3失敗)。這代表 CPU 競爭是機率性的 noisy-neighbor
    問題,不是客戶端能穩定調參解決的。付費功能寧可穩定慢(改序列跑,~90 秒/5檔)
    也不要快但會炸,故改回 max_workers=1(逐檔序列),犧牲速度換正確性。"""
    codes = _clean_codes(body.codes)
    with ThreadPoolExecutor(max_workers=1) as ex:
        results = list(ex.map(_analyze_one, codes))
    return {"results": results}


@router.post("/api/stock-checkup/extract-codes")
async def extract_codes(file: UploadFile = File(...)):
    """庫存截圖 → 股票代號清單(prototype,見 vision.py)。前端把回傳的 codes 直接
    填進選股欄位讓使用者確認/修改後才送出分析,不自動跳過去——辨識準確率未知,
    人工核對一眼比省那幾秒重要(誤判代號會體檢到別檔股票,使用者不會馬上發現)。"""
    data = await file.read()
    if not data:
        raise HTTPException(422, "檔案是空的")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(422, "圖片太大(上限 8MB)")
    try:
        codes = vision.extract_codes(data, file.content_type or "", MAX_STOCKS)
    except vision.VisionError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not codes:
        raise HTTPException(422, "沒有從圖片中辨識出股票代號,請確認截圖清楚或改用手動輸入。")
    return {"codes": codes}


_NOT_LISTED_NOTE = "付款連結尚未上架,請稍後再試或聯絡客服。"


def _save_order(settings, orders: dict, token: str, **patch) -> None:
    orders[token].update(patch)
    save_json_atomic(settings.stock_checkup_orders, orders)


def _new_merchant_trade_no() -> str:
    """ECPay MerchantTradeNo 限英數字、≤20 字元,不能沿用 token_urlsafe(含 -_)。
    當作對外(給 ECPay)也對內(訂單字典鍵、給客服的訂單編號)唯一的一組 id。"""
    return "T3" + secrets.token_hex(7).upper()   # "T3" + 14 hex 字元 = 16 字元


@router.post("/api/stock-checkup/order")
async def create_order(body: OrderRequest, request: Request):
    codes = _clean_codes(body.codes)
    email = (body.email or "").strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(422, "email 看起來不對")

    settings = request.app.state.settings
    token = _new_merchant_trade_no()
    orders = load_json(settings.stock_checkup_orders, {})
    orders[token] = {
        "token": token, "sku_id": SKU_ID, "codes": codes, "email": email,
        "ntd": PRICE_NTD, "created_at": datetime.now(timezone.utc).isoformat(),
        "paid": False, "ecpay_trade_no": None,
    }
    save_json_atomic(settings.stock_checkup_orders, orders)

    if not settings.public_base_url:
        _save_order(settings, orders, token, error="PUBLIC_BASE_URL 未設定")
        return {"token": token, "sku_id": SKU_ID, "ntd": PRICE_NTD,
                "checkout_url": None, "checkout_configured": False, "note": _NOT_LISTED_NOTE}

    base = settings.public_base_url.rstrip("/")
    try:
        params = ecpay.build_checkout_params(
            settings, merchant_trade_no=token, amount=PRICE_NTD,
            item_name=PRODUCT_NAME, trade_desc="量化阿森個股體檢",
            return_url=f"{base}/api/stock-checkup/ecpay/notify",
            client_back_url=f"{base}/stock-checkup",
            order_result_url=f"{base}/api/stock-checkup/ecpay/result",
        )
    except ecpay.ECPayError as exc:
        _save_order(settings, orders, token, error=str(exc))
        return {"token": token, "sku_id": SKU_ID, "ntd": PRICE_NTD,
                "checkout_url": None, "checkout_configured": False, "note": _NOT_LISTED_NOTE}

    _save_order(settings, orders, token, ecpay_params=params)
    return {
        "token": token, "sku_id": SKU_ID, "ntd": PRICE_NTD,
        "checkout_url": f"{base}/api/stock-checkup/ecpay/checkout/{token}",
        "checkout_configured": True,
        "note": f"訂單編號:{token}(若需聯絡客服請附上此編號)",
    }


def _order_html(title: str, body: str, status: int = 200) -> HTMLResponse:
    page = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<title>{html.escape(title)} - 量化阿森個股體檢</title>'
            f'<style>body{{background:#0A0D12;color:#E8E6E1;'
            f"font-family:'Noto Sans TC',sans-serif;max-width:560px;margin:64px auto;"
            f'padding:0 20px;line-height:1.7}}'
            f"h1{{color:#E3B45E}}.token{{font-family:'JetBrains Mono',monospace;"
            f'color:#34C77B}}</style></head><body><h1>{html.escape(title)}</h1>{body}'
            f'</body></html>')
    return HTMLResponse(page, status_code=status)


@router.get("/api/stock-checkup/ecpay/checkout/{token}")
async def ecpay_checkout(token: str, request: Request):
    """create_order 存好的簽章表單參數,包成一頁 onload 自動送出的 HTML 表單,
    瀏覽器直接 POST 到 ECPay 付款頁——這就是 create_order 回的 checkout_url。"""
    settings = request.app.state.settings
    orders = load_json(settings.stock_checkup_orders, {})
    order = orders.get(token)
    params = (order or {}).get("ecpay_params")
    if not order or not params:
        return _order_html("找不到這筆訂單",
                            "<p>請回到選股頁面重新選股並送出訂單。</p>", status=404)
    action = params.get("_action_url", "")
    inputs = "".join(
        f'<input type="hidden" name="{html.escape(str(k))}" value="{html.escape(str(v))}">'
        for k, v in params.items() if k != "_action_url"
    )
    page = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<title>前往付款 - 量化阿森個股體檢</title></head>'
            f'<body onload="document.forms[0].submit()">'
            f'<form method="post" action="{html.escape(action)}">{inputs}</form>'
            f'<p>正在前往綠界付款頁,請稍候...若無反應請按下方按鈕。</p>'
            f'<button onclick="document.forms[0].submit()">前往付款</button>'
            f'</body></html>')
    return HTMLResponse(page)


@router.post("/api/stock-checkup/ecpay/notify")
async def ecpay_notify(request: Request):
    """ECPay 背景通知(ReturnURL)——真正的付款確認在這裡,不在使用者瀏覽器導回的
    /ecpay/result。驗章失敗、訂單不存在、金額對不上一律不記帳不交付,但除了驗章失敗
    以外都要回「1|OK」(即使是 ECPay 通知的失敗付款),否則 ECPay 會一直重送。"""
    settings = request.app.state.settings
    form = dict(await request.form())
    if not ecpay.verify_notify(settings, form):
        return PlainTextResponse("0|CheckMacValueError")

    token = str(form.get("MerchantTradeNo") or "")
    orders = load_json(settings.stock_checkup_orders, {})
    order = orders.get(token)
    if not order:
        return PlainTextResponse("0|OrderNotFound")

    if str(form.get("RtnCode")) != "1":
        return PlainTextResponse("1|OK")   # 已驗證是 ECPay 本人送的失敗通知,照收不記帳

    if order.get("paid"):
        return PlainTextResponse("1|OK")   # 重複通知(ECPay 偶爾會重送),不重複記帳/交付

    if str(form.get("TradeAmt")) != str(order["ntd"]):
        # 理論上金額已綁進簽章、竄改會直接讓驗章失敗,這裡是雙重防線,不因單一防線失守而付款
        return PlainTextResponse("0|AmountMismatch")

    trade_no = str(form.get("TradeNo") or "")
    _save_order(settings, orders, token, paid=True, ecpay_trade_no=trade_no,
                paid_at=datetime.now(timezone.utc).isoformat())

    ev = NormalizedEvent(
        platform="ecpay", kind=EventKind.SALE,
        event_key=f"ecpay:{trade_no}",
        email=order["email"], name="", product=PRODUCT_NAME,
        amount=float(order["ntd"]), currency="TWD",
        order_id=token, sku_id=SKU_ID,
    )
    service.process_event(ev, settings)
    return PlainTextResponse("1|OK")


@router.api_route("/api/stock-checkup/ecpay/result", methods=["GET", "POST"])
async def ecpay_result(request: Request):
    """OrderResultURL——使用者付款後瀏覽器被導回這裡,純粹是給人看的提示頁。
    權威的付款確認只看 ecpay_notify 的背景通知,這裡的 RtnCode 只拿來決定顯示哪種
    文案,不會單靠它標記訂單完成(使用者可能在通知抵達前就先看到這頁)。"""
    if request.method == "POST":
        form = dict(await request.form())
    else:
        form = dict(request.query_params)
    token = str(form.get("MerchantTradeNo") or "")
    settings = request.app.state.settings
    orders = load_json(settings.stock_checkup_orders, {})
    order = orders.get(token)
    if str(form.get("RtnCode")) != "1":
        return _order_html("付款未完成", "<p>若已被扣款請聯絡客服。</p>")
    if order:
        return _order_html("付款處理中", _paid_body(order))
    return _order_html("付款處理中", "<p>付款已送出,請稍候查看您的信箱。</p>")


def _paid_body(order: dict) -> str:
    codes = "、".join(order.get("codes") or [])
    return (f"<p>已收到您的付款(NT$ {order.get('ntd')}),我們會將您選的 "
            f"{len(order.get('codes') or [])} 檔(<b>{html.escape(codes)}</b>)個股體檢報告"
            f"寄到 {html.escape(order.get('email', ''))}。</p>"
            f'<p>訂單編號:<span class="token">{html.escape(order.get("token", ""))}</span>'
            f"(若需聯絡客服請附上此編號)</p>")
