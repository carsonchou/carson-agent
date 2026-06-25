#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""computer.py — 賈維斯的手腳：直接操控整台 Windows 電腦（秒回，不繞大腦）。

提供開程式、切視窗、打字、點滑鼠、控音量/媒體、截圖、看螢幕、鎖機、開網頁、
複製貼上…等本機操作。語音常用指令由 route() 直接命中、立刻執行，不必等大腦
spin-up；route() 沒命中的複雜任務才交還給全能腦（claude -p）用 PowerShell 慢慢做。

設計：
- 所有重的 import（pyautogui / win32 / PIL / requests）都「延遲到函式內」才載入，
  讓主程式啟動快、headless 也不會在 import 階段就炸。
- 每個動作都回傳一句「給賈維斯念出來」的口語確認字串（繁中、無符號）。
- 真正危險的動作（關機/重開機）這裡不直接做，交給上層語音確認後再呼叫。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import webbrowser

# ── 常用程式中文/英文別名 → 啟動目標 ─────────────────────────────
# 值是丟給 `cmd /c start "" <target>` 的字串；ms-settings: 之類也能直接開。
_APPS = {
    "記事本": "notepad", "筆記本": "notepad", "notepad": "notepad",
    "小算盤": "calc", "計算機": "calc", "計算器": "calc", "calculator": "calc", "calc": "calc",
    "小畫家": "mspaint", "畫圖": "mspaint", "paint": "mspaint",
    "檔案總管": "explorer", "資料夾": "explorer", "explorer": "explorer", "我的電腦": "explorer",
    "工作管理員": "taskmgr", "工作管理": "taskmgr", "taskmgr": "taskmgr",
    "控制台": "control", "設定": "ms-settings:", "系統設定": "ms-settings:", "settings": "ms-settings:",
    "命令提示字元": "cmd", "cmd": "cmd", "終端機": "wt", "terminal": "wt",
    "powershell": "powershell", "power shell": "powershell",
    "瀏覽器": None, "chrome": "chrome", "谷歌瀏覽器": "chrome", "google": "chrome",
    "edge": "msedge", "微軟瀏覽器": "msedge",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt", "ppt": "powerpnt",
    "outlook": "outlook", "記事": "notepad",
    "vscode": "code", "vs code": "code", "編輯器": "code", "code": "code",
    "小工具": "snippingtool", "截圖工具": "snippingtool", "剪取工具": "snippingtool",
    "小算": "calc", "天氣": "ms-settings:", "相機": "microsoft.windows.camera:",
    "spotify": "spotify", "discord": "discord", "line": "line", "telegram": "telegram",
    "錄音機": "soundrecorder", "媒體播放器": "wmplayer",
}
# 常用網站別名 → URL（說「打開 YouTube」直接開網頁）
_SITES = {
    "youtube": "https://www.youtube.com", "yt": "https://www.youtube.com",
    "google": "https://www.google.com", "谷歌": "https://www.google.com",
    "gmail": "https://mail.google.com", "信箱": "https://mail.google.com",
    "facebook": "https://www.facebook.com", "臉書": "https://www.facebook.com", "fb": "https://www.facebook.com",
    "instagram": "https://www.instagram.com", "ig": "https://www.instagram.com",
    "twitter": "https://twitter.com", "x": "https://twitter.com",
    "github": "https://github.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "pionex": "https://www.pionex.com", "派網": "https://www.pionex.com",
    "tradingview": "https://www.tradingview.com", "幣安": "https://www.binance.com",
    "binance": "https://www.binance.com", "youtube studio": "https://studio.youtube.com",
    "yt studio": "https://studio.youtube.com", "youtube工作室": "https://studio.youtube.com",
}


def _pg():
    """延遲載入 pyautogui 並關掉 failsafe（滑鼠移到角落不要丟例外）。"""
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.02
    return pyautogui


def _run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _ps(script: str, timeout: int = 20) -> str:
    """跑一段 PowerShell，回 stdout（去頭尾空白）。"""
    r = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout)
    return (r.stdout or "").strip()


# ════════════════════════════════════════════════════════════
# 開程式 / 開網頁 / 搜尋
# ════════════════════════════════════════════════════════════
def open_app(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "你要我開什麼？"
    key = name.lower()
    # 先看是不是網站
    for k, url in _SITES.items():
        if k in key:
            webbrowser.open(url)
            return f"好，幫你開{name}了。"
    # 程式別名
    target = None
    for k, v in _APPS.items():
        if k in key:
            target = v if v is not None else None
            if v is not None:
                target = v
                break
    if target is None:
        target = name  # 直接拿原字串丟給 start，碰運氣（很多程式名 = 執行檔名）
    try:
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        return f"好，開{name}。"
    except Exception:
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return f"好，開{name}。"
        except Exception:
            return f"我試著開{name}，但好像找不到這個程式。"


def open_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "你要開哪個網址？"
    if not re.match(r"^https?://", url):
        url = "https://" + url
    webbrowser.open(url)
    return "好，幫你開網頁了。"


def web_search(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return "你要搜尋什麼？"
    from urllib.parse import quote
    webbrowser.open("https://www.google.com/search?q=" + quote(query))
    return f"好，幫你搜「{query}」。"


def youtube_search(query: str) -> str:
    query = (query or "").strip()
    from urllib.parse import quote
    webbrowser.open("https://www.youtube.com/results?search_query=" + quote(query))
    return f"好，幫你在 YouTube 找「{query}」。"


# ════════════════════════════════════════════════════════════
# 音量 / 媒體
# ════════════════════════════════════════════════════════════
def volume(action: str, times: int = 1) -> str:
    pg = _pg()
    a = action.lower()
    if a in ("mute", "靜音", "toggle"):
        pg.press("volumemute")
        return "靜音切換好了。"
    key = "volumeup" if a in ("up", "大", "大聲", "increase") else "volumedown"
    for _ in range(max(1, min(times, 25))):
        pg.press(key)
    return "音量調大了。" if key == "volumeup" else "音量調小了。"


def set_volume(percent: int) -> str:
    """設定到大約某個百分比（用按鍵逼近，每下約 2%）。"""
    pg = _pg()
    percent = max(0, min(100, int(percent)))
    for _ in range(55):
        pg.press("volumedown")   # 先歸零
    for _ in range(round(percent / 2)):
        pg.press("volumeup")
    return f"音量調到大約{percent}趴。"


def media(action: str) -> str:
    pg = _pg()
    a = action.lower()
    table = {
        "playpause": "playpause", "暫停": "playpause", "播放": "playpause", "play": "playpause", "pause": "playpause",
        "next": "nexttrack", "下一首": "nexttrack", "下一個": "nexttrack",
        "prev": "prevtrack", "上一首": "prevtrack", "上一個": "prevtrack",
        "stop": "stop", "停止": "stop",
    }
    k = table.get(a, "playpause")
    pg.press(k)
    return {"nexttrack": "下一首。", "prevtrack": "上一首。", "stop": "停了。"}.get(k, "好。")


# ════════════════════════════════════════════════════════════
# 鍵盤 / 滑鼠 / 打字
# ════════════════════════════════════════════════════════════
def type_text(text: str) -> str:
    """打字到目前游標處。用剪貼簿貼上以支援中文（pyautogui 直接打中文會失敗）。"""
    text = text or ""
    if not text:
        return "你要我打什麼？"
    try:
        import pyperclip
        old = ""
        try:
            old = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(text)
        pg = _pg()
        pg.hotkey("ctrl", "v")
        time.sleep(0.15)
        try:
            pyperclip.copy(old)  # 還原剪貼簿
        except Exception:
            pass
        return "打好了。"
    except Exception:
        _pg().typewrite(text, interval=0.01)
        return "打好了。"


def press_keys(combo: str) -> str:
    """按組合鍵，如 'ctrl+s'、'alt+tab'、'win+d'、'enter'。"""
    pg = _pg()
    keys = [k.strip().lower() for k in re.split(r"[+\-\s]+", combo) if k.strip()]
    if not keys:
        return "你要我按什麼鍵？"
    if len(keys) == 1:
        pg.press(keys[0])
    else:
        pg.hotkey(*keys)
    return "按好了。"


def click(button: str = "left", x: int | None = None, y: int | None = None) -> str:
    pg = _pg()
    if x is not None and y is not None:
        pg.click(x=x, y=y, button=button)
    else:
        pg.click(button=button)
    return "點好了。"


def scroll(amount: int) -> str:
    _pg().scroll(amount)
    return "捲好了。"


# ════════════════════════════════════════════════════════════
# 視窗管理
# ════════════════════════════════════════════════════════════
def _find_window(title: str):
    import pygetwindow as gw
    title = (title or "").strip().lower()
    for w in gw.getAllWindows():
        if w.title and title in w.title.lower():
            return w
    return None


def window(action: str, title: str | None = None) -> str:
    pg = _pg()
    a = action.lower()
    if a in ("minimize_all", "桌面", "回桌面", "show_desktop"):
        pg.hotkey("win", "d")
        return "回到桌面了。"
    if a in ("switch", "切換", "alt_tab"):
        pg.hotkey("alt", "tab")
        return "切換視窗了。"
    if a in ("task_view", "任務檢視"):
        pg.hotkey("win", "tab")
        return "打開任務檢視了。"
    w = _find_window(title) if title else None
    try:
        if a in ("focus", "切到", "activate", "前景"):
            if not w:
                return f"我找不到{title}那個視窗。"
            w.activate()
            return f"切到{title}了。"
        if a in ("close", "關閉", "關掉"):
            if not w:
                return f"沒看到{title}的視窗。"
            w.close()
            return f"關掉{title}了。"
        if a in ("minimize", "最小化"):
            (w or _find_window("")).minimize()
            return "最小化了。"
        if a in ("maximize", "最大化"):
            (w or _find_window("")).maximize()
            return "最大化了。"
    except Exception as e:  # noqa: BLE001
        return f"視窗操作有點問題：{str(e)[:40]}"
    return "好。"


def list_windows() -> list[str]:
    import pygetwindow as gw
    return [w.title for w in gw.getAllWindows() if w.title.strip()]


# ════════════════════════════════════════════════════════════
# 截圖 / 看螢幕（視覺）
# ════════════════════════════════════════════════════════════
def screenshot(path: str | None = None, downscale_width: int = 0) -> str:
    """全螢幕截圖存檔，回傳路徑。"""
    from PIL import ImageGrab
    img = ImageGrab.grab()
    if downscale_width and img.width > downscale_width:
        h = round(img.height * downscale_width / img.width)
        img = img.resize((downscale_width, h))
    if not path:
        path = os.path.join(tempfile.gettempdir(), f"jarvis_screen_{int(time.time())}.png")
    img.save(path)
    return path


def see_screen(question: str = "") -> str:
    """截圖→送 Claude 視覺模型→回一句口語描述/回答（賈維斯『看螢幕』）。"""
    import base64
    import requests
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return "我現在沒辦法看螢幕，少了 API 金鑰。"
    p = screenshot(downscale_width=1280)
    with open(p, "rb") as f:
        b64 = base64.standard_b64encode(f.read()).decode()
    q = question.strip() or "螢幕上現在是什麼？簡短說重點。"
    prompt = ("你是賈維斯，正在幫老闆看他的電腦螢幕。用繁體中文、自然口語、兩三句內講重點，"
              "不要用任何符號或條列。問題：" + q)
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.environ.get("JARVIS_FAST_MODEL", "claude-sonnet-4-6"),
                  "max_tokens": 400,
                  "messages": [{"role": "user", "content": [
                      {"type": "image", "source": {"type": "base64",
                       "media_type": "image/png", "data": b64}},
                      {"type": "text", "text": prompt}]}]},
            timeout=40,
        )
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip() or "我看了，但說不太上來。"
    except Exception as e:  # noqa: BLE001
        return f"看螢幕的時候出了點狀況：{str(e)[:50]}"


# ════════════════════════════════════════════════════════════
# 系統
# ════════════════════════════════════════════════════════════
def lock() -> str:
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "電腦鎖好了。"


def sleep_pc() -> str:
    _ps("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    return "讓電腦睡了。"


def shutdown(restart: bool = False) -> str:
    _run(["shutdown", "/r" if restart else "/s", "/t", "5"])
    return "好，五秒後重開機。" if restart else "好，五秒後關機。"


def cancel_shutdown() -> str:
    _run(["shutdown", "/a"])
    return "取消關機了。"


def clipboard_get() -> str:
    import pyperclip
    return pyperclip.paste() or ""


def clipboard_set(text: str) -> str:
    import pyperclip
    pyperclip.copy(text or "")
    return "複製好了。"


def run_ps(script: str) -> str:
    """逃生艙：直接跑一段 PowerShell，回 stdout。"""
    return _ps(script, timeout=60)


# ════════════════════════════════════════════════════════════
# 語音意圖路由：把一句中文指令直接對應到上面的動作（命中→秒做，沒命中→回 None）
# ════════════════════════════════════════════════════════════
_OPEN = re.compile(r"^(?:幫我|麻煩|請|可以)?\s*(?:打開|開啟|開一?下|啟動|執行|開)\s*(.+)$")
_SEARCH = re.compile(r"^(?:幫我|請)?\s*(?:google|谷歌|上網)?\s*(?:搜尋|搜一?下|查一?下|查詢|查)\s*(.+)$")
_YTSEARCH = re.compile(r"(?:youtube|油管|yt).*(?:找|搜|看)\s*(.+)$|(?:找|搜)\s*(.+)\s*的?影片")
_TYPE = re.compile(r"^(?:幫我)?(?:打字|打入|輸入文字|輸入|key\s*in)[：:，,\s]*[「\"']?(.+?)[」\"']?$")
_VOL_SET = re.compile(r"音量.*?(\d+)\s*(?:趴|%|％|分)")
_CLOSEWIN = re.compile(r"關(?:閉|掉)\s*(.+?)\s*(?:視窗|的視窗)?$")
_FOCUSWIN = re.compile(r"(?:切到|切換到|跳到|前往)\s*(.+?)\s*(?:視窗)?$")


def route(text: str):
    """回 (reply, action_done:bool) 若命中本機動作；回 None 表示交給大腦。

    只命中『明確的操作指令』；一般問答/聊天/要查資料做事的複雜任務一律放給大腦。"""
    t = (text or "").strip().rstrip("。.！!？?～~ ")
    if not t:
        return None
    low = t.lower()

    # 看螢幕（視覺）
    if re.search(r"(看一?下|幫我看|瞄一?下).*(螢幕|畫面|這個|目前)|螢幕上(是什麼|有什麼)|"
                 r"(畫面|螢幕)(現在)?(是什麼|顯示什麼)|這(是|畫面)什麼|你看得到.*(螢幕|畫面)", t):
        return (see_screen(t), True)

    # 截圖
    if re.search(r"截(個|張)?圖|截屏|螢幕截圖|擷取(畫面|螢幕)|capture|screenshot", low):
        p = screenshot()
        return (f"截好了，存到{os.path.basename(p)}。", True)

    # 鎖電腦 / 睡眠
    if re.search(r"鎖(電腦|螢幕|機|屏|住)", t):
        return (lock(), True)
    if re.search(r"(讓|把)?(電腦|你)?(去)?睡(眠|覺)|休眠", t):
        return (sleep_pc(), True)

    # 媒體控制
    if re.search(r"(暫停|播放|停一?下|繼續播?)(音樂|影片|歌|播放)?$|^(暫停|播放|繼續)$", t):
        return (media("playpause"), True)
    if re.search(r"下一(首|個|集)|跳過|next", low):
        return (media("next"), True)
    if re.search(r"上一(首|個|集)|prev", low):
        return (media("prev"), True)

    # 音量
    m = _VOL_SET.search(t)
    if m:
        return (set_volume(int(m.group(1))), True)
    if re.search(r"靜音|mute|把聲音關", t):
        return (volume("mute"), True)
    if re.search(r"(音量|聲音).*(大|高)|大聲(一?點)?|(調|轉)大聲|turn up", t):
        return (volume("up", 4), True)
    if re.search(r"(音量|聲音).*(小|低)|小聲(一?點)?|(調|轉)小聲|turn down", t):
        return (volume("down", 4), True)

    # 打開儀表板（要在通用「打開 X」之前攔下）
    if re.search(r"(打開|開|看|叫出).{0,3}儀表板|dashboard", t):
        open_url("http://127.0.0.1:8787")
        return ("幫你開儀表板了。", True)

    # 常用快捷鍵 / 作用中視窗
    if re.search(r"全螢幕|全屏|fullscreen", low):
        press_keys("f11")
        return ("好，全螢幕。", True)
    if re.search(r"重新整理|刷新|reload|refresh", low):
        press_keys("f5")
        return ("刷新了。", True)
    if re.search(r"關(掉|閉)\s*(這個|目前|當前|現在)?\s*(視窗|頁面|分頁|程式)$|alt\s*f4", t):
        press_keys("alt+f4")
        return ("關掉了。", True)
    if re.fullmatch(r"(幫我)?最小化(這個)?(視窗)?", t):
        press_keys("win+down")
        return ("縮小了。", True)
    if re.fullmatch(r"(幫我)?(最大化|放到?最大)(這個)?(視窗)?", t):
        press_keys("win+up")
        return ("放大了。", True)
    if re.fullmatch(r"(幫我)?全選", t):
        press_keys("ctrl+a")
        return ("全選了。", True)
    if re.fullmatch(r"(幫我)?複製", t):
        press_keys("ctrl+c")
        return ("複製了。", True)
    if re.fullmatch(r"(幫我)?(貼上|貼一?下)", t):
        press_keys("ctrl+v")
        return ("貼上了。", True)
    if re.fullmatch(r"(幫我)?(存檔|儲存|存一?下)", t) or low in ("save", "幫我save"):
        press_keys("ctrl+s")
        return ("存好了。", True)

    # 視窗
    if re.search(r"回(到)?桌面|顯示桌面|最小化全部", t):
        return (window("minimize_all"), True)
    if re.search(r"切換視窗|alt\s*tab", low):
        return (window("switch"), True)
    m = _CLOSEWIN.search(t)
    if m and re.search(r"視窗", t):
        return (window("close", m.group(1)), True)
    m = _FOCUSWIN.search(t)
    if m and re.search(r"視窗", t):
        return (window("focus", m.group(1)), True)

    # 打字 / 輸入
    m = _TYPE.match(t)
    if m:
        return (type_text(m.group(1)), True)

    # YouTube 找影片
    m = _YTSEARCH.search(t)
    if m and re.search(r"youtube|油管|yt|影片", low):
        q = next((g for g in m.groups() if g), "").strip()
        q = re.sub(r"(的|這首?|那首?)?(影片|歌|音樂|mv|MV)?$", "", q).strip(" 的")
        if q:
            return (youtube_search(q), True)

    # 搜尋
    m = _SEARCH.match(t)
    if m and not re.search(r"資料|為什麼|怎麼|如何|是誰|多少|幾", m.group(1)):
        return (web_search(m.group(1)), True)

    # 打開程式 / 網站（放最後，因為 _OPEN 很廣）
    m = _OPEN.match(t)
    if m:
        what = m.group(1).strip().rstrip("。.，, ")
        # 別把「打開話匣子/打開天窗」之類誤判——太短或含明顯非程式詞就放給大腦
        if 1 <= len(what) <= 24 and not re.search(r"來說|來看|天窗|心房|話", what):
            return (open_app(what), True)

    return None  # 沒命中 → 交給大腦


# ── CLI 測試：python jarvis/computer.py "打開記事本" ──────────────
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    arg = " ".join(sys.argv[1:]).strip()
    if not arg:
        print("用法：python jarvis/computer.py \"打開記事本\" / \"音量大一點\" / \"看一下螢幕\"")
        raise SystemExit(0)
    r = route(arg)
    if r is None:
        print(f"[未命中本機動作，會交給大腦] {arg!r}")
    else:
        print(f"[做了] {r[0]}")
