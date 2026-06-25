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
    "能力：你能實際操作這台電腦和他的專案（trading_bot 交易機器人、youtube_channel 工作室），"
    "能查資料、開程式、實際做事。能直接做掉的就做掉再簡短回報，需要他拍板的才問他。"
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

    def __init__(self) -> None:
        import glob
        import shutil
        import tempfile
        tmp = tempfile.gettempdir()
        self._mp3 = os.path.join(tmp, "jarvis_say.mp3")
        self._txt = os.path.join(tmp, "jarvis_say.txt")
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

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        print(f"🔊 Jarvis：{text}", flush=True)
        if self._ffplay and self._speak_edge(text):
            return
        self._speak_sapi(text)  # 沒網路/edge 失敗 → 退回 SAPI 女聲

    def _speak_edge(self, text: str) -> bool:
        try:
            import asyncio
            import edge_tts

            async def _gen():
                c = edge_tts.Communicate(text, self._voice, rate=self._rate, pitch=self._pitch)
                await c.save(self._mp3)
            asyncio.run(_gen())
            subprocess.run([self._ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", self._mp3],
                           timeout=90, capture_output=True)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Edge 語音失敗，改用系統語音：{e!r}", file=sys.stderr)
            return False

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
# 需要「實際動手做事/讀即時資料」才走較慢的全能腦；其餘純聊天/問答走直連快路。
_ACTION_INTENT = re.compile(
    r"打開|開啟|開一下|執行|跑一?下|跑個|啟動|產片?|補產|上架|發布|發片|刪|移除|"
    r"格式化|關機|重開|重啟|設定|改成|改一下|搜尋|上網|爬蟲?|看一下我的|查一下我的|"
    r"交易機器人|工作室|頻道(數據|狀況)|部位|淨值|倉庫|餘額|存檔|寫檔|開程式|記事本|瀏覽器", re.I)

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
    """分流：要動手做事/讀即時資料→全能腦；純聊天/問答→直連快路（失敗自動退回全能腦）。"""
    if _ACTION_INTENT.search(text or ""):
        return _ask_brain_full(text, history)
    try:
        out = _ask_brain_fast(text, history)
        if out:
            return out
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 快路失敗，改用全能腦：{e!r}", file=sys.stderr)
    return _ask_brain_full(text, history)


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
        threshold = float(os.environ.get("JARVIS_RMS_THRESHOLD", "0.004"))
        start = time.time()
        while time.time() - start < max_sec:
            buf, _ = stream.read(block)
            mono = buf[:, 0].astype(np.float32) / 32768.0
            frames.append(mono)
            rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
            max_rms = max(max_rms, rms)
            if rms >= threshold:
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
        # 自動增益：峰值拉到 ~0.3，補償低輸入音量（上限放大 25 倍，免放大純噪音）
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        gain = 1.0
        if 1e-4 < peak < 0.3:
            gain = min(25.0, 0.3 / peak)
            audio = np.clip(audio * gain, -1.0, 1.0)
        print(f"[聽] 講話={spoke} 原始峰值={peak:.4f} 增益x{gain:.1f} "
              f"最大RMS={max_rms:.4f} 長度={len(frames)*blk_sec:.1f}s", flush=True)
        # 全程近乎純靜音（連微弱人聲都沒有）才放棄；否則交給 Whisper+VAD 判斷
        if max_rms < 0.0025:
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
    print("👂 待命中——對著麥克風說「Hey Jarvis」叫醒我。(Ctrl-C 結束)")
    history = []  # 最近幾輪對話，讓她記得前文、像同一個人從頭聊到尾
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=block) as stream:
        while True:
            buf, _ = stream.read(block)
            pcm = buf[:, 0]
            pre.append(pcm.copy())
            if model.predict(pcm).get(WAKE_WORD, 0.0) >= WAKE_THRESHOLD:
                model.reset()
                idle_limit = float(os.environ.get("JARVIS_CONVO_SEC", "300"))
                print(f"✨ 喚醒！嗶——進入對話模式（閒置 {int(idle_limit)} 秒才回待命）")
                _beep()
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
                        print(f"🗣  你：{text}")
                        if not brain:
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
                            reply = ask_brain(text, history)
                            history.append((text, reply))
                            del history[:-8]   # 只留最近 8 輪
                            mouth.say(reply)
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
                print("💤 閒置太久，回待命。喊「Hey Jarvis」再叫醒我。")
                model.reset()


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def run_voice() -> int:
    mouth = Mouth()
    ears = Ears()
    ears._model()  # 預載，避免第一句很慢
    mouth.say("賈維斯待命中，老闆。")
    try:
        converse_loop(ears, mouth, brain=True)
    except KeyboardInterrupt:
        print("\n👋 賈維斯下線。")
    except Exception as e:  # noqa: BLE001 多半是找不到麥克風/音訊裝置
        print(f"\n[音訊錯誤] 起不來，通常是沒偵測到麥克風或音訊裝置：{e!r}", file=sys.stderr)
        print("請確認：① 這台電腦有接麥克風、② Windows 隱私設定允許程式存取麥克風、"
              "③ 在你自己的終端機（非遠端/無音訊環境）執行。", file=sys.stderr)
        return 1
    return 0


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
    ap.add_argument("--selftest", action="store_true", help="逐項自我診斷（不進監聽），找出哪裡壞")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

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
