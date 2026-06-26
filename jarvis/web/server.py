#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""賈維斯 Web 版後端 — 服務 orb 前端 + 把瀏覽器聽到的話接到大腦/電腦操控/嗓音。

瀏覽器負責「耳朵」(Chrome Web Speech API，可靠、免費、免裝模型) 與「畫面」(Three.js orb)；
這支後端負責「大腦＋手腳＋嘴」：
  POST /ask   {text}        → 先試電腦操控(computer.route)，沒命中走分流大腦(ask_brain) → {reply, kind}
  GET  /tts?text=...        → edge-tts 生成磁性男聲 mp3 回傳(瀏覽器播放並讓 orb 跟著脈動)
  GET  /                    → orb 前端頁

跑：python jarvis/web/server.py  → 開 http://127.0.0.1:8788
能力 = 我之前做好的那套(聊天快路/全能腦/看螢幕/開程式/控音量媒體…)，這裡只是換成瀏覽器當門面。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
JARVIS_DIR = HERE.parent
sys.path.insert(0, str(JARVIS_DIR))

import computer  # noqa: E402  手腳：電腦操控 + 語音意圖路由
import jarvis as J  # noqa: E402  大腦：ask_brain（聊天快路 / 全能腦分流）

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
HISTORY: list[tuple[str, str]] = []          # 最近幾輪對話，給大腦記前文
_VOICE = os.environ.get("JARVIS_VOICE", "zh-CN-YunjianNeural")
_RATE = os.environ.get("JARVIS_RATE", "-8%")
_PITCH = os.environ.get("JARVIS_PITCH", "-13Hz")


def think(text: str) -> dict:
    """一句話進來 → 決定怎麼回。先看是不是直接操控電腦，否則交給分流大腦。"""
    text = (text or "").strip()
    if not text:
        return {"reply": "", "kind": "empty"}
    # 1) 直接操控電腦（開程式/音量/媒體/截圖/看螢幕/打字/視窗…）秒做
    try:
        hit = computer.route(text)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] route 出錯：{e!r}", file=sys.stderr)
        hit = None
    if hit:
        return {"reply": hit[0], "kind": "action"}
    # 2) 其餘 → 分流大腦（聊天/問答走快路秒回；要碰專案/做事才升級全能腦）
    reply = J.ask_brain(text, HISTORY)
    HISTORY.append((text, reply))
    del HISTORY[: -8]
    return {"reply": reply, "kind": "chat"}


def gen_tts(text: str) -> bytes:
    import edge_tts
    out = os.path.join(tempfile.gettempdir(), "jarvis_web_tts.mp3")

    async def _g():
        c = edge_tts.Communicate(text, _VOICE, rate=_RATE, pitch=_PITCH)
        await c.save(out)
    asyncio.run(_g())
    return Path(out).read_bytes()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 安靜
        pass

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?")[0] == "/ask":
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) or b"{}"
                data = json.loads(raw.decode("utf-8", errors="replace"))
                res = think(str(data.get("text", "")))
                print(f"🗣  {data.get('text','')!r}  →  [{res['kind']}] {res['reply'][:60]}", flush=True)
                self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"reply": f"後端出錯：{e}", "kind": "error"},
                                           ensure_ascii=False).encode("utf-8"))
            return
        self._send(404, b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/tts":
            q = parse_qs(urlparse(self.path).query)
            text = (q.get("text", [""])[0]).strip()
            if not text:
                self._send(400, b"no text", "text/plain")
                return
            try:
                self._send(200, gen_tts(text), "audio/mpeg")
            except Exception as e:  # noqa: BLE001
                self._send(500, str(e).encode("utf-8"), "text/plain")
            return
        if path in ("/", "/index.html"):
            try:
                self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                self._send(500, str(e).encode("utf-8"), "text/plain")
            return
        self._send(404, b"not found", "text/plain")


if __name__ == "__main__":
    fp = "全能" if J._FULL_POWER else "安全"
    print(f"賈維斯 Web 版：http://127.0.0.1:{PORT}   模式={fp}   (Ctrl-C 結束)")
    print("用 Chrome 開，點一下畫面授權麥克風，就能直接對它講話。")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
