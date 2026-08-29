#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tts_edge.py — 免費・無限量配音引擎（微軟 Edge TTS）。

吃 output/<slug>.voice.txt → output/<slug>.mp3，與 tts_pipeline.py 同檔名約定，
make_video.py 可直接沿用。需網路，但完全免費、無字數上限——適合每日量產。

預設聲音 zh-TW-YunJheNeural（台灣男聲，沉穩顧問感）。
其他可選：zh-TW-HsiaoChenNeural(女)、zh-CN-YunxiNeural(陸男)、zh-CN-YunyangNeural(播報男)。

用法：
  python scripts\\tts_edge.py output\\<slug>.voice.txt
  python scripts\\tts_edge.py output\\<slug>.voice.txt --voice zh-CN-YunyangNeural --rate +10%
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import edge_tts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "zh-TW-YunJheNeural"
# 機房 IP 常被微軟間歇節流（「No audio received」）；多次重試 + 退避 + 語音輪替＝接近 100% 成片。
FALLBACK_VOICES = ["zh-TW-HsiaoChenNeural", "zh-TW-HsiaoYuNeural",
                   "zh-CN-YunyangNeural", "zh-CN-YunxiNeural"]
MAX_ATTEMPTS = 12

# 關鍵情緒詞加重（標點停頓法）：Edge TTS 對中文 SSML emphasis/prosody 實測「不支援」——
# 標籤會被當字面念出來（<emphasis level='strong'>賠光…</> 音檔比純文字長 2.4 倍），故不走 SSML。
# 改在關鍵詞前補一個頓號，製造「頓一下、再砸重點」的語氣停頓＝聽感上的重音。
# 預設保守：可用環境變數 TTS_EMPHASIS=0 關閉；只加前側一個頓號、只處理每詞首次出現、全篇最多 4 處，
# 且前一字已是標點就不加、任何例外一律回原文——絕不讓這增強弄壞或拖長配音。
_EMPHASIS_WORDS = ("賠光", "歸零", "爆倉", "血本無歸", "割韭菜", "韭菜", "被割",
                   "假的", "詐騙", "騙局", "慘賠", "一無所有", "全賠")
_PAUSE = "、"
_NO_PAUSE_BEFORE = "。！？，、；：「」『』（）…、 \n\t"


def _emphasize(text: str) -> str:
    """關鍵情緒詞前補頓號製造重音停頓（保守·可 TTS_EMPHASIS=0 關）。任何狀況出錯都回原文，絕不弄壞配音。"""
    import os
    if os.environ.get("TTS_EMPHASIS", "1").strip() == "0" or not text:
        return text
    try:
        out = text
        used = 0
        for w in _EMPHASIS_WORDS:
            if used >= 4:
                break
            idx = out.find(w)
            if idx <= 0:  # 找不到(-1)或就在開頭(前面沒東西可頓)都跳過
                continue
            if out[idx - 1] in _NO_PAUSE_BEFORE:
                continue  # 前面已有標點/停頓，不重複加
            out = out[:idx] + _PAUSE + out[idx:]
            used += 1
        return out
    except Exception:
        return text


async def _synth(text: str, voice: str, rate: str, out_path: Path) -> list:
    """串流合成:一邊寫音檔,一邊擷取 WordBoundary 真實時間戳(供字幕精準同步)。
    回傳 [{"t":秒,"d":秒,"text":詞}]。串流失敗則退回 .save(無時間戳,回 [])——絕不讓字幕同步需求弄壞配音。"""
    # 🔴 2026-08-29 改成「寫暫存檔 → 原子改名」。原本 `open(out_path,"wb")` 直接開在**最終
    # 路徑**上邊收邊寫,長片配音要 140 秒,那 140 秒裡 output/{slug}.mp3 一直存在而且一直在
    # 長大 —— 讀到的人會拿到一個**格式合法、內容不全**的 mp3(不是壞檔,所以任何
    # 「檔案在不在 / 能不能解析」的檢查都看不出來)。
    # 實際後果:渲染迴圈每 180 秒掃一次,判準只有 `mp3.exists()`(hybrid_render.cloud_pending),
    # 兩個窗口撞上就用半截音檔開渲。實測 08-29 中美晶5483:
    #     01:28 開始配音 → 01:30:20 mp3 寫完(722.4s)
    #     01:34 成片完成,音軌只有 553.9s(**少 168 秒 = 23% 的旁白**)
    # 而同一批的加高8182(mp3 寫完後隔 14 分鐘才渲)完全正常(比值 1.01)。
    # 這也解釋了為什麼三道截斷閘門(make_video/render_ffmpeg/build_video)全都沒響:
    # 渲染當下影片與音檔**是自洽的**,兩邊都是那個半截的長度,閘門無從發現。
    # → 半成品不該出現在最終路徑上。os.replace 在同一磁碟是原子的,讀者只會看到完整檔。
    marks = []
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        with open(tmp_path, "wb") as f:
            async for chunk in communicate.stream():
                ct = chunk.get("type")
                if ct == "audio" and chunk.get("data"):
                    f.write(chunk["data"])
                elif ct in ("SentenceBoundary", "WordBoundary"):
                    # offset/duration 單位為 100 奈秒(1e7=1 秒)。zh-TW 實測吐 SentenceBoundary(句級);
                    # 也一併收 WordBoundary(若該語音有吐)。供字幕真實對齊。
                    marks.append({"t": round(chunk.get("offset", 0) / 1e7, 3),
                                  "d": round(chunk.get("duration", 0) / 1e7, 3),
                                  "text": chunk.get("text", ""), "type": ct})
        if tmp_path.exists() and tmp_path.stat().st_size > 0:
            os.replace(str(tmp_path), str(out_path))   # 原子:讀者看到的一定是完整檔
            return marks
        raise RuntimeError("串流輸出為空")
    except Exception:
        # 退回最穩的 save(可能因串流被節流),此時無逐字時間戳。
        # 這條路徑同樣不能直接寫最終路徑——.save 一樣是邊下載邊寫。
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(tmp_path))
        os.replace(str(tmp_path), str(out_path))
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("voice_txt", help="output/<slug>.voice.txt 路徑")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default="+8%", help="語速，如 +8% / -5%")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = Path(args.voice_txt)
    if not src.is_absolute():
        src = PROJECT_ROOT / src
    if not src.exists():
        print(f"[FATAL] 找不到配音稿：{src}", file=sys.stderr)
        return 2
    text = src.read_text(encoding="utf-8").strip()
    if not text:
        print("[FATAL] 配音稿為空。", file=sys.stderr)
        return 2
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from tts_text import normalize
        text = normalize(text)  # 數字/%/小數→口語念法、長句斷句
    except Exception:
        pass

    text = _emphasize(text)  # 關鍵情緒詞前補頓號＝聽感重音（保守·出錯回原文·TTS_EMPHASIS=0 可關）

    if args.out:
        out = Path(args.out)
    else:
        name = src.name
        name = name[:-10] if name.endswith(".voice.txt") else src.stem
        out = PROJECT_ROOT / "output" / f"{name}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)

    # 語音輪替清單：主聲音先試，連續失敗就換備援聲音（避開單一聲音被節流）。
    voices = [args.voice] + [v for v in FALLBACK_VOICES if v != args.voice]
    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        voice = voices[(attempt // 3) % len(voices)]  # 每 3 次換一個聲音
        try:
            words = asyncio.run(_synth(text, voice, args.rate, out))
            if out.exists() and out.stat().st_size > 0:
                # 寫逐字時間戳 sidecar(供 make_video 精準字幕)。
                # 🔴 2026-08-11 血案:被節流退回 .save 時 words 為空,舊版「靜默略過」——
                # 但**上一版 mp3 的舊 sidecar 還在磁碟上**,make_video 拿舊時間軸配新音檔,
                # 實測重配音的片(片中多插一句訂閱鉤,+15s)後 2/3 字幕整段錯位。
                # fail-safe 方向=拿掉:新 mp3 拿不到時間戳,就把過期 sidecar 刪掉,
                # 讓 make_video 退回按字數估算(略有漂移但大致同步),絕不能留著精準地錯。
                wt = out.parent / f"{out.stem}.wordtimes.json"
                if words:
                    try:
                        import json as _json
                        wt.write_text(_json.dumps(words, ensure_ascii=False), encoding="utf-8")
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    try:
                        if wt.exists():
                            wt.unlink()
                            print(f"[warn] 無詞時戳(節流退回),已刪過期 sidecar:{wt.name}", file=sys.stderr)
                    except Exception:  # noqa: BLE001
                        pass
                print(f"[ok] 配音完成：{out}（{out.stat().st_size/1024:.0f} KB）voice={voice} chars={len(text)} 詞時戳={len(words)} 第{attempt+1}次")
                return 0
            raise RuntimeError("輸出檔為空")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[warn] 第 {attempt+1}/{MAX_ATTEMPTS} 次失敗（voice={voice}）：{exc}", file=sys.stderr)
            time.sleep(min(1.5 * (attempt + 1), 8.0))  # 退避等待，避免持續撞節流

    print(f"[FATAL] 配音失敗（網路/節流？）：{last_err}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
