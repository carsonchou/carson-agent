# -*- coding: utf-8 -*-
"""
daytrade_eligibility.py — 當沖資格/處置/注意股 每日清單（免費 TWSE OpenAPI）

盤中當沖前的防呆：避免報了「處置分盤(不能現沖)」或「注意股(風險高)」的單。
來源（免 key、每日更新）：
  處置有價證券  https://openapi.twse.com.tw/v1/announcement/punish
  注意股票      https://openapi.twse.com.tw/v1/announcement/notice

＊誠實：TWSE 未提供穩定的「可現股當沖」單一清單，故以「處置股＝分盤交易、視為不可當沖」近似；
  一般流動性個股預設可當沖。上櫃(TPEX)處置清單本版未併(best-effort，缺則不擋)。每日一次即可。

用法：python daytrade_eligibility.py --refresh
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CACHE_DIR = ROOT / "twdata"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_PUNISH = "https://openapi.twse.com.tw/v1/announcement/punish"
_NOTICE = "https://openapi.twse.com.tw/v1/announcement/notice"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _cache_path(d: date | None = None) -> Path:
    return CACHE_DIR / f"daytrade_eligibility_{(d or date.today()):%Y%m%d}.json"


def _fetch_json(url: str, timeout: int = 12) -> list:
    try:
        req = urllib.request.Request(url, headers=_HDR)
        raw = urllib.request.urlopen(req, timeout=timeout, context=_CTX).read().decode("utf-8", "replace")
        d = json.loads(raw)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def refresh() -> dict:
    """抓當日處置/注意股 → 快取。回 {disposition:[code], attention:[code], updated}。"""
    punish = _fetch_json(_PUNISH)
    notice = _fetch_json(_NOTICE)
    disp = sorted({str(r.get("Code", "")).strip() for r in punish if str(r.get("Code", "")).strip()})
    attn = sorted({str(r.get("Code", "")).strip() for r in notice if str(r.get("Code", "")).strip()})
    out = {"updated": datetime.now().isoformat(timespec="seconds"),
           "disposition": disp, "attention": attn}
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _cache_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        import os
        os.replace(tmp, p)
    except Exception:
        pass
    return out


def load(offline: bool = True) -> dict:
    """讀當日快取；缺且非 offline → 抓一次。缺→空(全部視為可當沖、不擋)。"""
    p = _cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not offline:
        return refresh()
    return {"disposition": [], "attention": []}


_CACHE: dict | None = None


def status(code: str, elig: dict | None = None) -> dict:
    """回 {can_daytrade, disposition, attention}。處置股視為不可現沖(分盤)。"""
    global _CACHE
    if elig is None:
        if _CACHE is None:
            _CACHE = load()
        elig = _CACHE
    disp = code in (elig.get("disposition") or [])
    attn = code in (elig.get("attention") or [])
    return {"can_daytrade": not disp, "disposition": disp, "attention": attn}


if __name__ == "__main__":
    r = refresh() if "--refresh" in sys.argv else load()
    print(f"處置股 {len(r.get('disposition', []))} 檔：{r.get('disposition', [])[:10]}")
    print(f"注意股 {len(r.get('attention', []))} 檔：{r.get('attention', [])[:10]}")
