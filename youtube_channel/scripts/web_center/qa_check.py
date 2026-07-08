# -*- coding: utf-8 -*-
"""qa_check.py — 【檢測部門】每天自動巡檢決策中心所有功能。

檢查項目：
  A. 契約：前端每顆按鈕的 action 都有對應後端處理器（抓「擴編不能用」這種按了沒反應的）。
  B. 元素：前端 JS 參照的按鈕 id 都真的存在於 HTML（抓少了按鈕）。
  C. 起一個『測試用』server（獨立埠），GET /api/state 正常、18 部門齊、無錯。
  D. 把每顆按鈕『乾跑』按一遍（_qa 旗標，零副作用、不碰雲端），確認每個都有回應且路由正確。
  E. 靜態資源（index.html / three.module.min.js）可正常提供。

輸出：STUDIO/qa_report.json（給決策中心健康燈）＋ STUDIO/REPORTS/{date}_檢測.md（人看）。
任一項異常 → 推 ntfy 警報。全程唯讀＋乾跑，絕不觸發真實雲端動作（沿用 web-center 誤觸紅線教訓）。

用法：python scripts/web_center/qa_check.py [--port 8791]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # youtube_channel/
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
INDEX = HERE / "index.html"
SERVER = HERE / "server.py"
TW = timezone(timedelta(hours=8))

STATE_KEYS = ["ok", "kpi", "departments", "warehouse", "scoring", "pending",
              "finance", "cloud", "headcount", "published_list", "qa"]


def _now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _read(p):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _get(url, timeout=10):
    r = urllib.request.urlopen(url, timeout=timeout)
    return r.status, r.read()


def _post(url, body, timeout=10):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=timeout)
    return r.status, json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    checks = []  # (name, ok, detail)

    def chk(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    html = _read(INDEX)
    srv = _read(SERVER)

    # ── A. 契約：前端 action ⊆ 後端 KNOWN_ACTIONS ──
    fe_actions = set(re.findall(r"action:\s*['\"]([a-z_]+)['\"]", html)) | \
        set(re.findall(r'data-op="([a-z_]+)"', html))
    m = re.search(r"KNOWN_ACTIONS\s*=\s*\{([^}]*)\}", srv)
    be_actions = set(re.findall(r"['\"]([a-z_]+)['\"]", m.group(1))) if m else set()
    missing_be = sorted(fe_actions - be_actions)
    chk("契約:前端按鈕都有後端處理器", not missing_be,
        "全部對應" if not missing_be else f"這些按鈕按了不會有反應(缺後端): {missing_be}")

    # ── B. 元素：JS 參照的 g('id') 都存在於 HTML ──
    refs = set(re.findall(r"(?:getElementById\(|[^\w]g\()\s*['\"]([\w-]+)['\"]", html))
    defined = set(re.findall(r'id="([\w-]+)"', html))
    missing_ids = sorted(r for r in refs if r not in defined)
    chk("元素:JS參照的按鈕/元素都存在", not missing_ids,
        "全部存在" if not missing_ids else f"參照了不存在的元素id: {missing_ids}")

    # ── 起測試 server ──
    proc = None
    try:
        proc = subprocess.Popen([sys.executable, str(SERVER), str(args.port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT))
        up = False
        for _ in range(30):
            time.sleep(0.6)
            try:
                st, _b = _get(base + "/api/state", timeout=6)
                if st == 200:
                    up = True
                    break
            except Exception:
                continue
        chk("啟動:測試server能起來並回應", up, "已就緒" if up else "15秒內起不來/不回應")

        if up:
            # ── C. /api/state 內容完整 ──
            st, raw = _get(base + "/api/state", timeout=12)
            try:
                state = json.loads(raw)
            except Exception:
                state = {}
            miss_keys = [k for k in STATE_KEYS if k not in state]
            chk("狀態:/api/state 欄位完整", st == 200 and not miss_keys,
                "完整" if not miss_keys else f"缺欄位: {miss_keys}")
            ndept = len(state.get("departments") or [])
            chk("部門:18 個部門都在", ndept == 18, f"實際 {ndept} 個")
            chk("狀態:無錯誤旗標", state.get("ok") is not False, "ok" if state.get("ok") is not False else "state.ok=false")

            # ── D. 每顆按鈕乾跑（零副作用）都要有回應且路由正確 ──
            bad = []
            for a in sorted(be_actions):
                try:
                    s2, res = _post(base + "/api/action", {"_qa": True, "action": a}, timeout=8)
                    if not (s2 == 200 and res.get("ok")):
                        bad.append(f"{a}({res.get('msg', s2)})")
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{a}(例外:{str(e)[:30]})")
            chk("按鈕:每個 action 乾跑都有反應", not bad,
                f"{len(be_actions)} 個全通" if not bad else f"異常: {bad}")

            # ── E. 靜態資源可提供 ──
            ok_static = True
            for path in ("/", "/index.html", "/three.module.min.js"):
                try:
                    s3, _b = _get(base + path, timeout=8)
                    ok_static = ok_static and s3 == 200
                except Exception:
                    ok_static = False
            chk("資源:頁面與 three.js 可載入", ok_static, "可載入" if ok_static else "有資源載不到")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    # ── 匯總 + 寫報告 ──
    passed = sum(1 for _n, ok, _d in checks if ok)
    total = len(checks)
    fails = [{"name": n, "detail": d} for n, ok, d in checks if not ok]
    ok_all = not fails
    report = {"ts": _now(), "ok": ok_all, "passed": passed, "total": total,
              "fails": fails, "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}
    STUDIO.mkdir(parents=True, exist_ok=True)
    (STUDIO / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    REPORTS.mkdir(parents=True, exist_ok=True)
    date = datetime.now(TW).strftime("%Y-%m-%d")
    lines = [f"# 決策中心巡檢報告｜{date} {_now()}", "",
             f"**結果：{'✅ 全部正常' if ok_all else '⚠️ 發現 ' + str(len(fails)) + ' 項異常'}**（{passed}/{total} 通過）", ""]
    for n, ok, d in checks:
        lines.append(f"- {'✅' if ok else '❌'} **{n}**：{d}")
    (REPORTS / f"{date}_檢測.md").write_text("\n".join(lines), encoding="utf-8")

    # ── 異常推 ntfy ──
    if fails:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import notify
            body = "決策中心巡檢發現異常：\n" + "\n".join(f"❌ {f['name']}：{f['detail']}" for f in fails)
            notify.push("⚠️ 決策中心檢測異常", body)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ntfy 推送失敗：{e}", file=sys.stderr)

    print(f"[檢測部門] {passed}/{total} 通過。" + ("全部正常。" if ok_all else f"異常 {len(fails)} 項：" + "；".join(f['name'] for f in fails)))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
