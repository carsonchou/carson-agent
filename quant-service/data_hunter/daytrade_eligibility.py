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


def _fetch_json(url: str, timeout: int = 12) -> list | None:
    """回 list = **抓到了**(可能是 TWSE「今天沒資料」的哨兵列);回 **None = 抓不到**。

    🔴 這個 None/list 的區分是整支檔案的關鍵(fail-open 的根就在這):
    舊版抓不到時回 `[]`,而 TWSE「今天真的沒資料」時回的是 **[哨兵列]**(非空),
    於是「抓不到」與「今天 0 檔」在上層**完全無法區分** → refresh() 照樣寫出
    `disposition: []` → M1 印「處置股 0 檔」= 告訴當沖客這檔可以沖。
    實測(2026-07-17 唯讀 curl):
      /announcement/notice → [{"Number":"0","Code":"","Name":"","NumberOfAnnouncement":"0"}]  ← 哨兵列
      /announcement/punish → [{"Number":"1","Code":"052974",...}]                              ← 真資料
    所以:**非空 list = 抓到了**(哨兵列會在下面被 Code 空字串濾掉,自然變 0 檔但 ok=True);
    None / 空 list / 形狀不對 = 抓不到 → 一律當不可信(fail-closed,寧可說「不知道」也不說「0 檔」)。
    """
    try:
        req = urllib.request.Request(url, headers=_HDR)
        raw = urllib.request.urlopen(req, timeout=timeout, context=_CTX).read().decode("utf-8", "replace")
        d = json.loads(raw)
        if not isinstance(d, list):
            print(f"[elig] ⚠️ {url} 回傳形狀非 list({type(d).__name__}) → 視為抓不到")
            return None
        return d
    except Exception as e:  # noqa: BLE001
        # 留痕:舊版這裡靜默吞掉,於是「TWSE 掛了」與「今天沒事」長得一模一樣。
        print(f"[elig] ⚠️ 抓取失敗 {url}:{type(e).__name__}: {e}")
        return None


def _codes_of(rows: list) -> list:
    """從 TWSE 回傳列抽代號。哨兵列的 Code 是空字串 → 自然被濾掉(不會產生幽靈空代號)。"""
    return sorted({str(r.get("Code", "")).strip() for r in rows
                   if isinstance(r, dict) and str(r.get("Code", "")).strip()})


def refresh() -> dict:
    """抓當日處置/注意股 → 快取。回 {ok, disposition, attention, updated, sources, reason}。

    🔴 fail-CLOSED(2026-07-17 修):**抓不到就不寫檔**,絕不寫出無法與「今天 0 檔」區分的空清單。
    為什麼不寫比寫 ok:false 好:今天稍早可能已經抓成功過一次(09:00 cron),那份是**好資料**;
    若失敗時還去寫檔,就會把好資料蓋掉——跟 gauge_history 那個「確認值被盤中值蓋掉」同型的坑。
    不寫 → load() 讀到的仍是稍早那份好資料;真的一次都沒成功過 → 沒有檔 → load() 回不可信狀態。

    兩個端點都要抓到才算可信:disposition(punish)是安全關鍵、attention(notice)是風險提示,
    少一個就無法完整回答「這檔能不能沖」,寧可整份標不可信,也不要給半套當全套。
    """
    punish = _fetch_json(_PUNISH)
    notice = _fetch_json(_NOTICE)
    ok_p = isinstance(punish, list) and len(punish) > 0
    ok_n = isinstance(notice, list) and len(notice) > 0
    ok = ok_p and ok_n
    out = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "ok": ok,
        "disposition": _codes_of(punish) if ok_p else [],
        "attention": _codes_of(notice) if ok_n else [],
        "sources": {"punish": {"ok": ok_p, "rows": len(punish) if isinstance(punish, list) else 0},
                    "notice": {"ok": ok_n, "rows": len(notice) if isinstance(notice, list) else 0}},
        "reason": None,
    }
    if not ok:
        bad = [n for n, o in (("處置股 punish", ok_p), ("注意股 notice", ok_n)) if not o]
        out["reason"] = f"TWSE OpenAPI 抓取失敗:{'、'.join(bad)}(回空/無回應)"
        print(f"[elig] 🔴 {out['reason']} → **不寫檔**(避免以不可信的空清單覆蓋今天稍早的好資料);"
              f"下游應以「無法確認」呈現,不可顯示 0 檔。")
        return out
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _cache_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        import os
        os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        print(f"[elig] ⚠️ 快取寫入失敗:{type(e).__name__}: {e}(本輪資料仍回傳給呼叫端)")
    return out


def is_trusted(doc: dict | None) -> bool:
    """這份清單可不可信(= 能不能拿來說「處置股 N 檔」)。

    舊格式相容:2026-07-17 之前的檔沒有 `ok` 欄位,而舊 refresh() **抓不到也會寫空檔**,
    所以「沒有 ok 欄位且清單全空」無法分辨是「真的 0 檔」還是「抓取失敗」→ 一律當不可信。
    有資料的舊檔(實際 21~34 檔)顯然是抓成功的 → 當可信。
    """
    if not isinstance(doc, dict):
        return False
    if "ok" in doc:
        return bool(doc["ok"])
    return bool(doc.get("disposition") or doc.get("attention"))


def load(offline: bool = True) -> dict:
    """讀當日快取;缺且非 offline → 抓一次。

    🔴 fail-CLOSED:抓不到/沒有檔 **不再回空清單當作「全部可當沖」**,而是回 `ok=False` 的
    明確「不可信」狀態。呼叫端必須看 `ok`(或用 status() 的 `trusted`)才知道能不能下結論。
    仍保留 disposition/attention 兩個鍵(空 list),讓既有呼叫端不會 KeyError。
    """
    p = _cache_path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d.setdefault("disposition", [])
                d.setdefault("attention", [])
                d["ok"] = is_trusted(d)
                if not d["ok"]:
                    d.setdefault("reason", "當日快取內容無法確認可信度(舊格式且清單全空)")
                return d
        except Exception as e:  # noqa: BLE001
            print(f"[elig] ⚠️ 當日快取解析失敗:{type(e).__name__}: {e}")
    if not offline:
        return refresh()
    return {"ok": False, "reason": "當日清單尚未抓取(無快取檔)",
            "disposition": [], "attention": []}


_CACHE: dict | None = None


def status(code: str, elig: dict | None = None) -> dict:
    """回 {can_daytrade, disposition, attention, trusted}。處置股視為不可現沖(分盤)。

    ⚠️ `disposition`/`attention` 的語意是「**這檔在清單裡**」——資料不可信時它們是 **False**,
    因為我們**不知道**,不能反過來宣稱它是處置股(那是說謊,且會讓 1900 檔全被標成「處置分盤」)。
    要 fail-closed 的責任在 `trusted`:呼叫端看到 trusted=False 就該擋單並說「無法確認」,
    而不是拿 disposition 來假裝知道。這樣既安全又誠實。
    """
    global _CACHE
    if elig is None:
        if _CACHE is None:
            _CACHE = load()
        elig = _CACHE
    disp = code in (elig.get("disposition") or [])
    attn = code in (elig.get("attention") or [])
    return {"can_daytrade": not disp, "disposition": disp, "attention": attn,
            "trusted": is_trusted(elig)}


if __name__ == "__main__":
    r = refresh() if "--refresh" in sys.argv else load()
    if not is_trusted(r):
        print(f"🔴 清單不可信:{r.get('reason') or '未知原因'}")
        print("   → 無法確認處置/注意股,請自行至證交所查證後再下單(**不要**當成 0 檔)。")
        raise SystemExit(1)
    print(f"處置股 {len(r.get('disposition', []))} 檔：{r.get('disposition', [])[:10]}")
    print(f"注意股 {len(r.get('attention', []))} 檔：{r.get('attention', [])[:10]}")
