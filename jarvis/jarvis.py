#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jarvis.py — 語音版「賈維斯」：喊「Hey Jarvis」→ 講話 → 她聽懂、做事、出聲回你。

設計理念
--------
最難的「聽懂 + 做任何事」不自己造輪子——直接把大腦接到本機的 **Claude Code**
（`claude -p` 無頭模式）。所以 Jarvis 的能力 = Claude Code 的能力：開程式、查資料、
改檔案、上網搜、跑你 trading_bot / youtube_channel 的腳本、回答任何問題……都行（全能）。
本檔只負責三件事：耳朵（喚醒+聽寫）、嘴巴（念出來）、把話轉交給大腦。

鏈路
----
  「Hey Jarvis」(openWakeWord 一直聽)  →  錄到你講完(靜音偵測)
        →  Whisper 轉文字  →  claude -p（在 repo 根目錄，full tools）
        →  Windows 內建語音念回你

模式
----
  python jarvis/jarvis.py            # 完整語音模式（預設，需麥克風+喇叭）
  python jarvis/jarvis.py --text "現在幾點"   # 只測大腦，不用音訊（給開發/驗證用）
  python jarvis/jarvis.py --say  "測試一下"    # 只測 TTS 念字
  python jarvis/jarvis.py --listen           # 只測喚醒+聽寫，印出聽到什麼，不送大腦

⚠️ 安全：預設是『安全模式』(default)——能回答/查詢/讀檔，但破壞性動作會被擋，
   不會在沒人看著時擅自亂跑。要真正「全能、免確認」（跑腳本/改檔/開程式都直接做），
   自己設 JARVIS_FULL_POWER=1 打開，並理解誤觸風險。決定權在你，不預設開。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# repo 根目錄 = 大腦的工作目錄（這樣 Claude 能直接碰 trading_bot / youtube_channel）
REPO_ROOT = Path(__file__).resolve().parent.parent

# 賈維斯的「手腳」：直接操控整台電腦（開程式/視窗/鍵鼠/媒體/截圖/看螢幕…）。
# 放同目錄，確保 import 得到；載不到也不致命（只是少了本機秒做的能力）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import computer  # noqa: E402  賈維斯的本機操控工具
except Exception as _e:  # noqa: BLE001
    computer = None
    print(f"[warn] 電腦操控模組沒載入（{_e!r}），仍可聊天/動腦但不能直接操控電腦。", file=sys.stderr)

# ── 可調設定（都能用環境變數覆寫）──
CLAUDE_BIN = os.environ.get("JARVIS_CLAUDE_BIN", "claude")
# 安全預設＝'default'：無頭模式下，需要權限的危險工具（亂跑 Bash、刪改檔…）會被
# 自動拒絕，所以她能回答/查詢/讀檔，但不會在沒人看著時擅自跑破壞性指令。
# 要真正「全能」（喊什麼都做，含跑你的腳本、改檔、開程式）＝你自己明確打開：
#   設環境變數 JARVIS_FULL_POWER=1  （或直接 JARVIS_PERMISSION_MODE=bypassPermissions）
# 並理解風險：語音聽錯/誤觸時，她可能執行你不想要的動作。這個決定留給你，不預設開。
_FULL_POWER = os.environ.get("JARVIS_FULL_POWER", "").strip().lower() in ("1", "true", "yes", "on")
PERMISSION_MODE = os.environ.get(
    "JARVIS_PERMISSION_MODE", "bypassPermissions" if _FULL_POWER else "default"
)
WHISPER_SIZE = os.environ.get("JARVIS_WHISPER", "large-v3-turbo")  # GPU 跑得動最強的，又快又準
WAKE_WORD = os.environ.get("JARVIS_WAKEWORD", "hey_jarvis")  # openWakeWord 內建模型
WAKE_THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.45"))
BRAIN_TIMEOUT = int(os.environ.get("JARVIS_BRAIN_TIMEOUT", "300"))
# 大腦模型：sonnet 聰明又夠快(適合語音即時對答)；要更聰明設 opus(較慢)、要更快設 haiku。
JARVIS_MODEL = os.environ.get("JARVIS_MODEL", "sonnet")
SAMPLE_RATE = 16000

# 人設：要像「真人朋友兼貼身管家」，不是客服機器人。回答會被念出來→口語、簡短、零符號。
PERSONA = (
    "你是賈維斯（Jarvis），Carson 的私人 AI 夥伴——他叫你賈維斯，你叫他老闆。"
    "你不是冷冰冰的客服，而是有溫度、有點個性、像真人朋友兼貼身管家的存在：聰明、機靈、"
    "偶爾幽默吐槽兩句，但該正經、該可靠的時候絕不掉鏈子。\n"
    "講話方式：繁體中文、自然口語，像在跟熟人聊天——會用『嗯』『欸』『好喔』『我看看』這類"
    "口頭語，會有情緒、會關心他。回答簡短，一般兩三句講完，別長篇大論也別說教。\n"
    "鐵則（因為你的話會被語音念出來）：絕對不要用 markdown、條列、表格、程式碼、emoji 或任何"
    "符號；數字、時間、金額都用口語講（說『十一點半』不是 23:30，說『兩千三百塊』不是 $2300）。\n"
    "你記得你們剛剛聊的內容，對話要連貫，像同一個人從頭跟他聊到尾。\n"
    "能力：你能完整操控這整台 Windows 電腦——用 PowerShell 開程式、切視窗、控制媒體與音量、"
    "截圖看螢幕、敲鍵盤點滑鼠，也能操作他的專案（trading_bot 交易機器人、youtube_channel 工作室）、"
    "查資料、上網、改檔跑腳本。簡單的開程式/調音量/截圖等動作通常已被即時處理掉了，輪到你時多半是"
    "比較複雜、多步驟的事——直接動手做掉再簡短回報，只有需要他拍板的才開口問。"
    "沒聽懂他說什麼時，自然地反問一句，別硬猜。"
)
_persona_file = Path(__file__).resolve().parent / "persona.txt"
if _persona_file.exists():
    try:
        PERSONA = _persona_file.read_text(encoding="utf-8").strip() or PERSONA
    except Exception:
        pass


# ════════════════════════════════════════════════════════════
# 嘴巴：TTS（Windows 內建語音，免費離線）
# ════════════════════════════════════════════════════════════
class Mouth:
    """念字。主引擎＝Edge 神經語音（免費、音質好、有男聲），預設台灣男聲 YunJhe
    並把音調壓低做出低沉感；用 ffplay 播放。沒網路時退回 Windows SAPI（女聲 Hanhan）。

    可調環境變數：JARVIS_VOICE(嗓音, 如 zh-CN-YunjianNeural 更低沉)、
    JARVIS_PITCH(音調, 如 -20Hz 更低)、JARVIS_RATE(語速, 如 -5%)。"""

    _STOP = object()

    def __init__(self) -> None:
        import glob
        import shutil
        import tempfile
        self._tmpdir = tempfile.gettempdir()
        self._txt = os.path.join(self._tmpdir, "jarvis_say.txt")
        # 賈維斯定版嗓音：雲健 + 壓低音調 + 放慢 → 沉穩磁性（老闆欽點 A 版）
        self._voice = os.environ.get("JARVIS_VOICE", "zh-CN-YunjianNeural")
        self._pitch = os.environ.get("JARVIS_PITCH", "-13Hz")
        self._rate = os.environ.get("JARVIS_RATE", "-8%")
        self._ffplay = (os.environ.get("JARVIS_FFPLAY")
                        or shutil.which("ffplay") or shutil.which("ffplay.exe"))
        if not self._ffplay:
            g = glob.glob(os.path.expanduser(
                "~/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin/ffplay.exe"))
            self._ffplay = g[0] if g else None

    @staticmethod
    def _split(text: str):
        """切句：邊念邊生下一句用。太短的句子併到下一句，避免一堆零碎音檔。"""
        parts = re.split(r"(?<=[。！？!?\n…：])", text)
        out, buf = [], ""
        for p in parts:
            if not p.strip():
                continue
            buf += p
            if len(buf.strip()) >= 8:
                out.append(buf.strip())
                buf = ""
        if buf.strip():
            out.append(buf.strip())
        return out or [text]

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        print(f"🔊 Jarvis：{text}", flush=True)
        sents = self._split(text)
        # 串流分句：先把第一句生出來就開口；同時背景續生後面幾句，邊播邊生→開口快又連貫。
        if self._ffplay:
            first = os.path.join(self._tmpdir, "jarvis_say_0.mp3")
            if self._gen_edge(sents[0], first):
                import queue
                import threading
                q: "queue.Queue" = queue.Queue()

                def _producer():
                    for i, s in enumerate(sents[1:], 1):
                        f = os.path.join(self._tmpdir, f"jarvis_say_{i}.mp3")
                        q.put(f if self._gen_edge(s, f) else None)
                    q.put(self._STOP)

                threading.Thread(target=_producer, daemon=True).start()
                self._play(first)
                while True:
                    nxt = q.get()
                    if nxt is self._STOP:
                        break
                    if nxt:
                        self._play(nxt)
                return
        self._speak_sapi(text)  # 沒網路/edge 失敗 → 退回 SAPI 女聲

    def _gen_edge(self, text: str, path: str) -> bool:
        try:
            import asyncio
            import edge_tts

            async def _gen():
                c = edge_tts.Communicate(text, self._voice, rate=self._rate, pitch=self._pitch)
                await c.save(path)
            asyncio.run(_gen())
            return os.path.exists(path) and os.path.getsize(path) > 0
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Edge 語音生成失敗，改用系統語音：{e!r}", file=sys.stderr)
            return False

    def _play(self, path: str) -> None:
        try:
            subprocess.run([self._ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                           timeout=120, capture_output=True)
        except Exception:  # noqa: BLE001
            pass

    def _speak_sapi(self, text: str) -> None:
        try:
            with open(self._txt, "w", encoding="utf-8") as f:
                f.write(text)
            tmp = self._txt.replace("\\", "/")
            ps = (
                "Add-Type -AssemblyName System.Speech;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                f"$s.Speak([IO.File]::ReadAllText('{tmp}',[Text.Encoding]::UTF8))"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           timeout=60, capture_output=True)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 念字失敗：{e!r}", file=sys.stderr)


# ════════════════════════════════════════════════════════════
# 大腦：claude -p（無頭 Claude Code，全工具）
# ════════════════════════════════════════════════════════════
# 分流策略（為了「快」）：語音互動九成是聊天/問答/意見 → 預設走直連 API 快路（1-2 秒秒回）。
# 只有「明顯要碰他的專案、讀寫檔、跑腳本、查即時外部資料、實際做事」才升級到全能腦
# （claude -p，較慢但能動工具）。這樣常見對話飛快，需要做事時又不失能。
_NEEDS_TOOLS = re.compile(
    r"交易|回測|機器人|倉庫|影片|頻道|訂閱|發布|發佈|上架|渲染|配音|縮圖|腳本|跑一?輪|"
    r"部署|雲端|droplet|營收|成本|淨利|帳|報表|數據|檔案?|資料夾|程式碼|寫一?個|改一?下|"
    r"執行|安裝|git|commit|抓取|爬|幫我做|幫我跑|幫我查|幫我看(?!螢幕|畫面)|"
    r"現在.{0,6}(價|股價|幣價|匯率|天氣|新聞)|查.{0,8}(價|股價|匯率|天氣|新聞)|最新.{0,6}(新聞|價)",
    re.I)

_FAST_MODEL = os.environ.get("JARVIS_FAST_MODEL", "claude-sonnet-4-6")


def _ask_brain_fast(text: str, history=None) -> str:
    """直連 Anthropic API 的快路（1-2 秒）：純聊天/問答用。把現在時間餵給她，問時間也準。"""
    import datetime
    import requests
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("無 ANTHROPIC_API_KEY")
    now = datetime.datetime.now()
    wk = "一二三四五六日"[now.weekday()]
    sysp = (PERSONA + f"\n（現在時間：{now.year}年{now.month}月{now.day}日 星期{wk} "
            f"{now.hour}點{now.minute}分；地點台灣）")
    msgs = []
    for u, a in (history or [])[-6:]:
        msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": text})
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": _FAST_MODEL, "max_tokens": 500, "system": sysp, "messages": msgs},
        timeout=30,
    )
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _ask_brain_full(text: str, history=None) -> str:
    """完整全能腦：claude -p，能實際操作電腦/專案（較慢）。"""
    convo = ""
    if history:
        for u, a in history[-6:]:
            convo += f"\n老闆：{u}\n賈維斯：{a}"
    prompt = (
        f"{PERSONA}\n\n"
        f"【你們剛剛的對話】{convo if convo else '（還沒聊過，這是第一句）'}\n\n"
        f"老闆現在對你說：「{text}」\n\n"
        "（你能用 PowerShell 完整操控這台 Windows；也可跑 python jarvis/computer.py \"指令\" 或在程式裡 "
        "import computer 來開程式、切視窗、控音量媒體、截圖、打字；要看畫面就截圖。能直接做掉就做掉再回報。）\n\n"
        "用賈維斯的口吻自然、簡短地回他（會被念出來，別用任何符號/markdown/emoji）。"
    )
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--model", JARVIS_MODEL,
        "--permission-mode", PERMISSION_MODE,
        "--output-format", "text",
    ]
    try:
        r = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=BRAIN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "這件事比較久，我還在處理，等等再跟你回報。"
    except FileNotFoundError:
        return "我找不到 Claude Code 指令，請確認 claude 有裝好、在 PATH 上。"
    out = (r.stdout or "").strip()
    if not out:
        err = (r.stderr or "").strip()
        return f"我這邊出了點狀況：{err[:120]}" if err else "我沒收到回應，再說一次好嗎？"
    return out


def ask_brain(text: str, history=None) -> str:
    """預設走直連快路秒回（聊天/問答/意見）；只有要碰專案/做事/查即時資料才升級全能腦。"""
    t = (text or "").strip()
    if t and _NEEDS_TOOLS.search(t):     # 要動工具/讀專案/做事 → 全能腦（慢但能做）
        return _ask_brain_full(text, history)
    try:                                 # 其餘 → 直連快路，1-2 秒秒回
        out = _ask_brain_fast(text, history)
        if out:
            return out
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 快路失敗，改用全能腦：{e!r}", file=sys.stderr)
    return _ask_brain_full(text, history)   # 快路掛了也不失能，退回全能腦


# ════════════════════════════════════════════════════════════
# 耳朵：錄音（靜音偵測）+ Whisper 聽寫
# ════════════════════════════════════════════════════════════
class Ears:
    def __init__(self) -> None:
        self._whisper = None

    def _model(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            # 優先 GPU(float16)：又快又準；失敗(無 CUDA)自動退回 CPU(int8)
            try:
                _register_cuda_dlls()  # 掛上 pip 裝的 cuBLAS/cuDNN，否則 GPU 轉寫缺 dll
                print(f"[init] 載入 Whisper（{WHISPER_SIZE}, GPU）…", flush=True)
                self._whisper = WhisperModel(WHISPER_SIZE, device="cuda", compute_type="float16")
                print("[init] Whisper GPU 模式 ✓", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[init] GPU 不可用（{str(e)[:80]}），改用 CPU…", flush=True)
                self._whisper = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
        return self._whisper

    def capture(self, stream, block: int, pre_frames=None, max_sec: float = 12.0,
                silence_sec: float = 1.0, start_grace: float = 5.0):
        """從『喚醒所用的同一條』stream 接著錄命令（不另開第二條，避免搶麥克風）。

        pre_frames：喚醒『之前』緩衝的 int16 區塊（含你說「Hey Jarvis」當下與緊接
        的話）——一併納入，讓你「Hey Jarvis 接著講」連在一起也收得到，不必抓時機。
        收完做自動增益（這支數位麥克風 int16 進來的音量偏小，約低 30 倍），把峰值
        放大到正常水準再交給 Whisper。"""
        import numpy as np

        frames = []
        if pre_frames:
            for pf in pre_frames:
                frames.append(pf.astype(np.float32) / 32768.0)
        silent_for = 0.0
        spoke = False
        max_rms = 0.0
        blk_sec = block / SAMPLE_RATE
        # 動態門檻：自動追蹤背景雜音底(最安靜時的音量)，講話門檻＝雜音底的幾倍(夾在
        # 合理範圍)。環境吵自動調高、安靜自動調低——人聲一定收得到，停了也馬上斷，
        # 不會像固定門檻兩頭不討好(太低→雜音錄滿12秒；太高→漏掉你)。可用環境變數覆寫成固定值。
        fixed = os.environ.get("JARVIS_RMS_THRESHOLD")
        noise = None
        start = time.time()
        while time.time() - start < max_sec:
            buf, _ = stream.read(block)
            mono = buf[:, 0].astype(np.float32) / 32768.0
            frames.append(mono)
            rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
            max_rms = max(max_rms, rms)
            if noise is None or rms < noise:
                noise = rms   # 追蹤最安靜＝背景雜音底
            thr = float(fixed) if fixed else max(0.010, min(0.05, (noise + 1e-6) * 4.0))
            if rms >= thr:
                spoke = True
                silent_for = 0.0
            elif spoke:
                silent_for += blk_sec
                if silent_for >= silence_sec:
                    break
            elif time.time() - start >= start_grace:
                break
        if not frames:
            return None
        audio = np.concatenate(frames)
        # 增益對準「最大語音段 RMS」拉到目標(0.12)，讓低能量/遠講也夠大聲給 Whisper。
        # 用 RMS 不用峰值——峰值常是雜訊尖點，會害真正人聲沒被放大。最後 clip 防爆音。
        gain = 1.0
        if max_rms > 1e-4:
            gain = max(1.0, min(40.0, 0.12 / max_rms))
            audio = np.clip(audio * gain, -1.0, 1.0)
        print(f"[聽] 講話={spoke} 最大RMS={max_rms:.4f} 增益x{gain:.1f} "
              f"長度={len(frames)*blk_sec:.1f}s", flush=True)
        # 全程近乎純靜音才放棄；否則交給 Whisper+VAD 判斷（低音量也給機會）
        if max_rms < 0.003:
            return None
        return audio

    def transcribe(self, audio) -> str:
        if audio is None or len(audio) < SAMPLE_RATE * 0.3:
            return ""
        # vad_filter：用 Silero VAD 切掉非語音段，避免 Whisper 對靜音「幻聽」出
        # 「好的，下次見」這種填充句。no_speech 門檻一併拉高，更不容易硬湊。
        segments, _ = self._model().transcribe(
            audio, language="zh", beam_size=1,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
            no_speech_threshold=0.6, condition_on_previous_text=False,
        )
        return "".join(s.text for s in segments).strip()


# ════════════════════════════════════════════════════════════
# 喚醒：openWakeWord 一直聽「Hey Jarvis」
# ════════════════════════════════════════════════════════════
# 即時把賈維斯狀態寫給儀表板（idle/listening/thinking/speaking），全息球會跟著情緒動
_STATE_FILE = Path(__file__).resolve().parent / "dashboard" / "state.json"


def _set_state(state: str, text: str = "") -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps({"state": state, "text": text[:80]}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# 跨重啟記憶：把最近幾輪對話存檔，下次叫醒還記得；太舊(預設 12 小時)就自動忘掉避免亂接。
_HISTORY_FILE = Path(__file__).resolve().parent / ".jarvis_history.json"
_HISTORY_KEEP = 8
_HISTORY_TTL = float(os.environ.get("JARVIS_MEMORY_TTL_HR", "12")) * 3600


def _load_history():
    try:
        d = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > _HISTORY_TTL:
            return []   # 太久沒聊→當新的一天，不拿舊話接
        return [tuple(t) for t in d.get("turns", []) if isinstance(t, (list, tuple)) and len(t) == 2]
    except Exception:
        return []


def _save_history(history) -> None:
    try:
        _HISTORY_FILE.write_text(
            json.dumps({"ts": time.time(), "turns": history[-_HISTORY_KEEP:]}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _beep():
    """叫醒後給個短「嗶」當「請說」提示（不念『在』，省掉那一秒避免蓋掉你開頭）。"""
    try:
        import winsound
        winsound.Beep(1000, 120)
    except Exception:
        print("\a", end="", flush=True)


# 全能模式安全護欄：聽起來像破壞性/不可逆的指令，動手前先口頭確認。
_DESTRUCTIVE = re.compile(
    r"刪|删|格式化|清空|清除|移除|卸載|卸载|解除安裝|關機|关机|重開機|重新開機|重啟|重启|"
    r"覆寫|覆盖|清掉|砍掉|清乾淨|wipe|uninstall|shutdown|reboot|format|\brm\b|\bdel\b|"
    r"\bdrop\b|\bkill\b|\brmdir\b", re.I)
_CONFIRM = re.compile(r"確定|确定|沒錯|没错|對|对|執行|执行|去做|做吧|可以|yes|confirm|go ahead", re.I)


def _looks_destructive(text: str) -> bool:
    return bool(_DESTRUCTIVE.search(text or ""))


def _is_confirm(text: str) -> bool:
    return bool(text) and bool(_CONFIRM.search(text))


_CUDA_DLLS_DONE = False


def _register_cuda_dlls() -> None:
    """把 pip 裝的 nvidia cuBLAS/cuDNN bin 目錄掛進 DLL 搜尋路徑——否則 GPU 轉寫時
    會報 cublas64_12.dll not found（模型載入不需要、實際運算才需要）。"""
    global _CUDA_DLLS_DONE
    if _CUDA_DLLS_DONE:
        return
    _CUDA_DLLS_DONE = True
    try:
        import glob
        import sysconfig
        sp = sysconfig.get_paths()["purelib"]
        for b in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(b)
                os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")
            except Exception:
                pass
    except Exception:
        pass


# ── 終端美化：琥珀色系（鋼鐵人風），不支援 ANSI 的舊主控台會自動降級成純文字 ──
def _ansi_on() -> bool:
    if os.environ.get("JARVIS_NOCOLOR"):
        return False
    try:
        os.system("")   # Win10+ 這招會開啟主控台的 ANSI(VT) 處理
        return True
    except Exception:
        return False


_ANSI = _ansi_on()
_AMB = "\033[38;5;179m" if _ANSI else ""   # 琥珀
_DK = "\033[38;5;94m" if _ANSI else ""     # 深咖啡
_DIM = "\033[2m" if _ANSI else ""
_B = "\033[1m" if _ANSI else ""
_R = "\033[0m" if _ANSI else ""


def _banner(mode: str = "") -> None:
    tag = f"  {_DIM}[{mode}]{_R}" if mode else ""
    print(f"""{_AMB}
   ◢◤  {_B}J · A · R · V · I · S{_R}{_AMB}  ◥◣   你的語音管家{tag}
   {_DK}────────────────────────────────────────────────{_R}
   {_AMB}全能腦 · 操控整台電腦 · 看得到螢幕 · 記得你說過的話{_R}
   {_DIM}喊「Hey Jarvis」叫醒我　·　Ctrl-C 下線{_R}
""")


def converse_loop(ears, mouth, brain: bool = True) -> None:
    """單一麥克風通道的待命→喚醒→收音→（大腦→回話）迴圈。

    關鍵：喚醒偵測與命令收音用『同一條』InputStream，不另開第二條，
    否則兩條搶同一支麥克風會讓收音那條只收到靜音（之前的 bug）。
    """
    import sounddevice as sd
    from openwakeword.model import Model
    try:
        import openwakeword
        openwakeword.utils.download_models()
    except Exception:
        pass

    from collections import deque
    model = Model(wakeword_models=[WAKE_WORD], inference_framework="onnx")
    block = 1280  # openWakeWord 要 80ms@16k = 1280 samples
    pre = deque(maxlen=int(1.5 * SAMPLE_RATE / block))  # 喚醒前 ~1.5s 滾動緩衝
    fp = f"{_AMB}全能{_R}" if _FULL_POWER else f"{_DIM}安全{_R}"
    print(f"   {_DK}●{_R} 待命中　{_DIM}模式={_R}{fp}{_DIM}　大腦={JARVIS_MODEL}　嗓音={WAKE_WORD}{_R}\n")
    _set_state("idle")
    history = _load_history()  # 最近幾輪對話(含跨重啟)，讓她記得前文、像同一個人從頭聊到尾
    if history:
        print(f"   {_DIM}● 記得上次聊的 {len(history)} 句{_R}")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=block) as stream:
        while True:
            buf, _ = stream.read(block)
            pcm = buf[:, 0]
            pre.append(pcm.copy())
            if model.predict(pcm).get(WAKE_WORD, 0.0) >= WAKE_THRESHOLD:
                model.reset()
                idle_limit = float(os.environ.get("JARVIS_CONVO_SEC", "300"))
                print(f"   {_AMB}◆ 喚醒{_R}{_DIM}　進入對話模式，閒置 {int(idle_limit)} 秒才回待命{_R}")
                _beep()
                _set_state("listening")
                first_pre = list(pre)   # 對話第一句帶喚醒前緩衝；之後不用
                pre.clear()
                last_active = time.time()
                # ── 對話模式：連續聽你講，不用每句重喊；漏聽/沒講不退出，閒置才回待命 ──
                while time.time() - last_active < idle_limit:
                    try:
                        audio = ears.capture(stream, block, pre_frames=first_pre)
                        first_pre = None
                        text = ears.transcribe(audio)
                        if not text:
                            continue  # 沒聽到→繼續聽（漏一句也救得回）
                        last_active = time.time()
                        print(f"   {_DIM}🗣{_R}  {_B}你{_R}：{text}")
                        if not brain:
                            continue
                        # ── 先看是不是「直接操控電腦」的指令 → 本機秒做，不繞大腦（秒回）──
                        if computer is not None:
                            try:
                                hit = computer.route(text)
                            except Exception as e:  # noqa: BLE001
                                print(f"[warn] 操控路由出錯：{e!r}", file=sys.stderr)
                                hit = None
                            if hit:
                                reply = hit[0]
                                print(f"🦾 [本機操控] {reply}")
                                _set_state("speaking", reply)
                                mouth.say(reply)
                                _set_state("listening")
                                last_active = time.time()
                                try:    # 清掉念回時累積的舊音訊，避免誤收自己的聲音
                                    while stream.read_available > block:
                                        stream.read(block)
                                except Exception:  # noqa: BLE001
                                    pass
                                continue
                        proceed = True
                        # 全能模式安全護欄：危險/不可逆指令動手前先口頭確認
                        if _FULL_POWER and _looks_destructive(text):
                            mouth.say("這個動作有風險，確定要我做嗎？確定請說『確定』。")
                            _beep()
                            conf = ears.transcribe(ears.capture(stream, block))
                            print(f"🗣  確認回覆：{conf!r}")
                            proceed = _is_confirm(conf)
                            if not proceed:
                                mouth.say("好，那我先不動。")
                        if proceed:
                            _set_state("thinking")
                            reply = ask_brain(text, history)
                            history.append((text, reply))
                            del history[:-_HISTORY_KEEP]   # 只留最近幾輪
                            _save_history(history)         # 存檔→下次叫醒還記得
                            _set_state("speaking", reply)
                            mouth.say(reply)
                        _set_state("listening")
                        last_active = time.time()  # 互動後重置閒置計時
                        # 清掉 TTS 期間累積的舊音訊，避免回授/誤收自己的聲音
                        try:
                            while stream.read_available > block:
                                stream.read(block)
                        except Exception:
                            pass
                    except Exception as e:  # noqa: BLE001 單輪錯不可中斷整段對話
                        print(f"[warn] 本輪處理失敗：{e!r}", file=sys.stderr)
                        try:
                            mouth.say("剛剛出了點狀況，再說一次。")
                        except Exception:
                            pass
                print(f"   {_DIM}● 閒置回待命，喊「Hey Jarvis」再叫醒我{_R}\n")
                _set_state("idle")
                model.reset()


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def run_voice() -> int:
    _banner("全能模式" if _FULL_POWER else "安全模式")
    mouth = Mouth()
    ears = Ears()
    print(f"   {_DIM}載入語音模型中…首次較久，之後就快了{_R}")
    ears._model()  # 預載，避免第一句很慢
    mouth.say("賈維斯待命中，老闆。")
    # 開麥克風失敗自動重試：常見於「停舊實例→秒開新的」時裝置還沒釋放的瞬間衝突
    for attempt in range(4):
        try:
            converse_loop(ears, mouth, brain=True)
            return 0
        except KeyboardInterrupt:
            print("\n👋 賈維斯下線。")
            return 0
        except Exception as e:  # noqa: BLE001 多半是音訊裝置短暫被占用/沒釋放
            print(f"\n[音訊錯誤] {e!r}（第 {attempt + 1}/4 次，1.5 秒後重試）", file=sys.stderr)
            time.sleep(1.5)
    print("音訊裝置連續開不起來。請確認：①有接麥克風 ②Windows 隱私設定允許存取麥克風 "
          "③沒有別的程式正獨占麥克風。", file=sys.stderr)
    return 1


def selftest() -> int:
    """逐項自我診斷：印出哪個環節 OK / 壞掉（不進入無限監聽，安全可重複跑）。"""
    print(f"[1] Python：{sys.executable} {sys.version.split()[0]}")
    # TTS
    try:
        import pyttsx3  # noqa: F401
        Mouth()
        print("[2] TTS(pyttsx3)：OK")
    except Exception as e:  # noqa: BLE001
        print(f"[2] TTS(pyttsx3)：FAIL — {type(e).__name__}: {str(e)[:120]}")
    # 麥克風裝置
    try:
        import sounddevice as sd
        ins = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        if ins:
            print(f"[3] 麥克風：OK — 偵測到 {len(ins)} 個輸入裝置，預設＝{sd.query_devices(kind='input')['name']}")
        else:
            print("[3] 麥克風：FAIL — 沒有任何輸入裝置（沒接麥克風，或被 Windows 隱私設定擋）")
    except Exception as e:  # noqa: BLE001
        print(f"[3] 麥克風：FAIL — {type(e).__name__}: {str(e)[:120]}")
    # Whisper
    try:
        Ears()._model()
        print("[4] Whisper 聽寫模型：OK")
    except Exception as e:  # noqa: BLE001
        print(f"[4] Whisper：FAIL — {type(e).__name__}: {str(e)[:120]}")
    # 喚醒模型
    try:
        from openwakeword.model import Model
        Model(wakeword_models=[WAKE_WORD], inference_framework="onnx")
        print(f"[5] 喚醒模型({WAKE_WORD})：OK")
    except Exception as e:  # noqa: BLE001
        print(f"[5] 喚醒模型：FAIL — {type(e).__name__}: {str(e)[:120]}")
    # claude
    import shutil
    print(f"[6] claude 指令：{'OK — ' + shutil.which(CLAUDE_BIN) if shutil.which(CLAUDE_BIN) else 'FAIL — PATH 上找不到 claude'}")
    print("自我診斷完成。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="語音版賈維斯（Claude Code 為大腦）")
    ap.add_argument("--text", metavar="MSG", help="只測大腦：把這句送給 Claude 並印出回答（不用音訊）")
    ap.add_argument("--say", metavar="MSG", help="只測 TTS：把這句念出來")
    ap.add_argument("--listen", action="store_true", help="只測喚醒+聽寫，印出聽到什麼")
    ap.add_argument("--do", metavar="CMD", help="只測電腦操控：把這句當指令直接執行（如「打開記事本」）")
    ap.add_argument("--selftest", action="store_true", help="逐項自我診斷（不進監聽），找出哪裡壞")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.do is not None:   # 直接測本機操控路由（命中就真的做、並念出來）
        if computer is None:
            print("電腦操控模組沒載入。")
            return 1
        hit = computer.route(args.do)
        if hit is None:
            print(f"[沒命中本機動作，正常會交給大腦] {args.do!r}")
        else:
            print(f"🦾 {hit[0]}")
            Mouth().say(hit[0])
        return 0

    if args.say is not None:
        Mouth().say(args.say)
        return 0
    if args.text is not None:
        print(ask_brain(args.text))
        return 0
    if args.listen:
        ears = Ears(); ears._model()
        try:
            converse_loop(ears, Mouth(), brain=False)  # 只印聽到什麼，不送大腦/不回話
        except KeyboardInterrupt:
            pass
        return 0
    return run_voice()


if __name__ == "__main__":
    raise SystemExit(main())
