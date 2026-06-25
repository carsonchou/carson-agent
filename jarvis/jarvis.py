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
WHISPER_SIZE = os.environ.get("JARVIS_WHISPER", "small")   # tiny/base/small/medium
WAKE_WORD = os.environ.get("JARVIS_WAKEWORD", "hey_jarvis")  # openWakeWord 內建模型
WAKE_THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
BRAIN_TIMEOUT = int(os.environ.get("JARVIS_BRAIN_TIMEOUT", "300"))
SAMPLE_RATE = 16000

# 人設：因為回答會「被念出來」，務必要求口語、簡短、不要 markdown/emoji/清單。
PERSONA = (
    "你是 Jarvis，Carson（叫他『老闆』）的私人 AI 管家，跑在他的電腦上。"
    "你的回答會被語音念出來給他聽，所以：用繁體中文、口語、簡短（盡量兩三句內），"
    "絕對不要用 markdown、條列、表格、程式碼區塊或 emoji，就像真人在講話。"
    "你能實際操作這台電腦與他的專案（trading_bot 交易機器人、youtube_channel 工作室）；"
    "能直接做完的事就做完再簡短回報結果，需要他決定的才問。回答中文數字與口語化的金額/時間。"
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
    def __init__(self) -> None:
        self._engine = None
        try:
            import pyttsx3
            eng = pyttsx3.init()
            eng.setProperty("rate", 185)
            # 盡量挑中文嗓音（Hanhan / Yating / Zhiwei / Huihui…），挑不到就用預設
            for v in eng.getProperty("voices"):
                blob = f"{getattr(v,'id','')} {getattr(v,'name','')}".lower()
                if any(k in blob for k in ("zh", "chinese", "hanhan", "yating", "zhiwei", "huihui")):
                    eng.setProperty("voice", v.id)
                    break
            self._engine = eng
        except Exception as e:  # noqa: BLE001
            print(f"[warn] TTS 初始化失敗，改用純文字輸出：{e!r}", file=sys.stderr)

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        print(f"🔊 Jarvis：{text}")
        if self._engine is None:
            return
        try:
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 念字失敗：{e!r}", file=sys.stderr)


# ════════════════════════════════════════════════════════════
# 大腦：claude -p（無頭 Claude Code，全工具）
# ════════════════════════════════════════════════════════════
def ask_brain(text: str) -> str:
    """把使用者的話交給 Claude Code，回傳她要說的話（純文字）。"""
    prompt = f"{PERSONA}\n\n老闆對你說：「{text}」\n\n請依人設用簡短口語回答（會被念出來）。"
    cmd = [
        CLAUDE_BIN, "-p", prompt,
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


# ════════════════════════════════════════════════════════════
# 耳朵：錄音（靜音偵測）+ Whisper 聽寫
# ════════════════════════════════════════════════════════════
class Ears:
    def __init__(self) -> None:
        self._whisper = None

    def _model(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            print(f"[init] 載入 Whisper（{WHISPER_SIZE}）…")
            self._whisper = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
        return self._whisper

    def record_until_silence(self, max_sec: float = 12.0, silence_sec: float = 0.9):
        """喚醒後開始錄音，偵測到你講完（持續靜音）就停。回傳 float32 波形。"""
        import numpy as np
        import sounddevice as sd

        block = int(SAMPLE_RATE * 0.05)  # 50ms
        frames = []
        silent_for = 0.0
        spoke = False
        threshold = 0.012  # RMS 門檻（依環境可微調）
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=block) as stream:
            start = time.time()
            while time.time() - start < max_sec:
                buf, _ = stream.read(block)
                mono = buf[:, 0]
                frames.append(mono.copy())
                rms = float(np.sqrt(np.mean(mono ** 2)) if len(mono) else 0.0)
                if rms >= threshold:
                    spoke = True
                    silent_for = 0.0
                elif spoke:
                    silent_for += 0.05
                    if silent_for >= silence_sec:
                        break
        if not frames:
            return None
        return np.concatenate(frames)

    def transcribe(self, audio) -> str:
        if audio is None or len(audio) < SAMPLE_RATE * 0.3:
            return ""
        segments, _ = self._model().transcribe(audio, language="zh", beam_size=1)
        return "".join(s.text for s in segments).strip()


# ════════════════════════════════════════════════════════════
# 喚醒：openWakeWord 一直聽「Hey Jarvis」
# ════════════════════════════════════════════════════════════
def wake_loop(on_wake) -> None:
    import numpy as np
    import sounddevice as sd
    from openwakeword.model import Model
    try:
        import openwakeword
        openwakeword.utils.download_models()  # 首次自動下載內建模型
    except Exception:
        pass

    model = Model(wakeword_models=[WAKE_WORD])
    block = 1280  # openWakeWord 要 80ms@16k = 1280 samples
    print(f"👂 待命中——對著麥克風說「Hey Jarvis」叫醒我。(Ctrl-C 結束)")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=block) as stream:
        while True:
            buf, _ = stream.read(block)
            scores = model.predict(buf[:, 0])
            if scores.get(WAKE_WORD, 0.0) >= WAKE_THRESHOLD:
                model.reset()
                on_wake()


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def run_voice() -> int:
    mouth = Mouth()
    ears = Ears()
    ears._model()  # 預載，避免第一句很慢
    mouth.say("賈維斯待命中，老闆。")

    def on_wake():
        try:
            print("✨ 喚醒！請說…")
            mouth.say("在")
            audio = ears.record_until_silence()
            text = ears.transcribe(audio)
            if not text:
                mouth.say("我沒聽清楚，再說一次？")
                return
            print(f"🗣  你：{text}")
            mouth.say("好的，我看一下。")
            reply = ask_brain(text)
            mouth.say(reply)
        except Exception as e:  # noqa: BLE001 一輪出錯不可讓整個待命崩潰
            print(f"[warn] 本輪處理失敗：{e!r}", file=sys.stderr)
            mouth.say("剛剛出了點狀況，再試一次。")

    try:
        wake_loop(on_wake)
    except KeyboardInterrupt:
        print("\n👋 賈維斯下線。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="語音版賈維斯（Claude Code 為大腦）")
    ap.add_argument("--text", metavar="MSG", help="只測大腦：把這句送給 Claude 並印出回答（不用音訊）")
    ap.add_argument("--say", metavar="MSG", help="只測 TTS：把這句念出來")
    ap.add_argument("--listen", action="store_true", help="只測喚醒+聽寫，印出聽到什麼")
    args = ap.parse_args()

    if args.say is not None:
        Mouth().say(args.say)
        return 0
    if args.text is not None:
        print(ask_brain(args.text))
        return 0
    if args.listen:
        ears = Ears(); ears._model()
        def on_wake():
            print("✨ 喚醒！請說…")
            print(f"🗣  聽到：{ears.transcribe(ears.record_until_silence())!r}")
        try:
            wake_loop(on_wake)
        except KeyboardInterrupt:
            pass
        return 0
    return run_voice()


if __name__ == "__main__":
    raise SystemExit(main())
