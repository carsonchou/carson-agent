#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_ffmpeg.py — 純 ffmpeg 渲染後端(本機 GPU 主力,雲端 moviepy 當備案)。

為什麼:moviepy 1.0.3 逐幀把 raw frame 透過 stdin pipe 餵 ffmpeg,在 Windows+Py3.9
極慢(實測本機 5 分鐘 vs 雲端 170s,CPU/GPU 全程閒置)。本後端改用「靜態切片合成 PNG
→ ffmpeg concat demuxer + 一次 filtergraph + NVENC」,完全繞過逐幀 pipe,本機秒級出片。

重用 make_video 的卡片/字幕 PIL 生成(純函數),只換掉「組裝+編碼」。
Phase 1:純字卡 + 字幕 + intro/outro + 開場淡入(最常見)。b-roll = Phase 2(暫走卡片)。

用法:python scripts/render_ffmpeg.py --slug <slug> [--width 1080 --height 1920 --fps 30]
編碼器:MV_CODEC 強制 / MV_NO_GPU 關 GPU / 預設偵測 NVENC 就用,否則 libx264。
fps 地板:render() 內部強制 max(fps, MIN_FPS=30)，呼叫端傳更低值(如舊的 15)也會被拉到 30，
避免 15fps 頓、廉價感傷完播；呼叫端仍可傳更高值(如 60)。
"""
from __future__ import annotations
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import make_video as mv  # 重用卡片/字幕/解析等純函數


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"


# --------------------------------------------------------------------------- #
# P5-a 產線止血：組片 cmd 一律先寫暫存檔、探測(視訊軌/音軌/片長)過了才搬進正式
# out_mp4 路徑；沒過就重試一次；兩次都不過絕不留壞檔在 output/ ——
# 這是 07-09 audit_fail 由 0-2 暴衝到 10（0KB/無視訊軌/片長 0-1秒）的根因修復：
# 舊寫法讓 ffmpeg `-y` 直接寫正式路徑，一旦被 batch 逾時整組砍掉(produce_batch 的
# 殭屍防護)或 concat/編碼中途失敗，正式路徑上就留下半成品，audit_video 才在事後抓到。
# --------------------------------------------------------------------------- #


def _probe_media(path: Path):
    """回傳 (duration, has_video, has_audio)；探測失敗回 (0.0, False, False)。"""
    try:
        ff = _ffmpeg_exe()
        out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20)
        txt = out.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
        dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
        return dur, ("Video:" in txt), ("Audio:" in txt)
    except Exception:  # noqa: BLE001
        return 0.0, False, False


def _log_ops(stage: str, msg: str) -> None:
    """寫進既有 STUDIO/ops_log.txt；ops 模組不可用時安靜略過，絕不影響渲染主流程。"""
    try:
        import ops
        ops.log_ops(stage, msg)
    except Exception:  # noqa: BLE001
        pass


def _encode_and_validate(cmd, final_out: Path, tmp_dir: Path, *, stage: str, timeout: int,
                         min_dur: float = 1.0) -> bool:
    """執行組片 cmd（cmd 最後一個元素會被改寫成暫存輸出路徑，呼叫端傳入的原值僅供參考）。
    成功且通過探測驗證才搬到 final_out；失敗（含逾時）重試一次；兩次都失敗絕不在
    final_out 留下壞檔，並把原因寫進 STUDIO/ops_log.txt。回傳 True/False。"""
    tmp_out = tmp_dir / f"_render_tmp_{final_out.stem}.mp4"
    cmd = list(cmd)
    cmd[-1] = str(tmp_out)
    last_err = ""
    for attempt in (1, 2):
        try:
            tmp_out.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        r = None
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last_err = f"逾時（{timeout}s）"
        if r is not None and r.returncode == 0:
            dur, has_v, has_a = _probe_media(tmp_out)
            size = tmp_out.stat().st_size if tmp_out.exists() else 0
            if tmp_out.exists() and size > 0 and has_v and has_a and dur >= min_dur:
                try:
                    final_out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(tmp_out), str(final_out))
                except Exception as mv_exc:  # noqa: BLE001
                    last_err = f"搬移失敗：{mv_exc}"
                    if attempt == 2:
                        break
                    continue
                if attempt == 2:
                    print(f"[ffmpeg後端·{stage}] 重試後成功", file=sys.stderr)
                    _log_ops(f"render_ffmpeg/{stage}", f"{final_out.name}：重試後成功")
                return True
            last_err = f"輸出無效（dur={dur:.1f}s video={has_v} audio={has_a} size={size}B）"
        elif r is not None:
            last_err = (r.stderr or "")[-400:]
        if attempt == 1:
            print(f"[ffmpeg後端·{stage}] 第1次失敗（{last_err[:200]}），重試一次…", file=sys.stderr)
            _log_ops(f"render_ffmpeg/{stage}", f"{final_out.name}：第1次失敗，重試：{last_err[:150]}")
    try:
        tmp_out.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    print(f"[ffmpeg後端·{stage}] 兩次都失敗，不留壞檔：{last_err[:300]}", file=sys.stderr)
    _log_ops(f"render_ffmpeg/{stage}", f"{final_out.name}：兩次都失敗，不留壞檔：{last_err[:200]}")
    return False


def _pick_codec(ff: str):
    """回傳 (codec, [encode args])。
    預設 libx264:純字卡編碼非瓶頸,純 ffmpeg 架構下 libx264 已快 ~13x(本機 22s)。
    NVENC 本機 RTX4050 驅動在 filter 鏈後開不了 encoder(-40),且純字卡省不了多少,故不自動用;
    要用 GPU 設 MV_CODEC=h264_nvenc(留待 Phase 2 b-roll 大量編碼時再解驅動相容)。"""
    forced = os.environ.get("MV_CODEC", "").strip()
    if forced:
        if "nvenc" in forced:
            return forced, ["-preset", "p4", "-b:v", "3500k", "-pix_fmt", "yuv420p"]
        return forced, ["-preset", "ultrafast", "-b:v", "3500k"]
    return "libx264", ["-preset", "ultrafast", "-b:v", "3500k"]


def _pick_bgm(slug):
    """從 assets/audio/bgm/*.mp3 依 slug 穩定挑一支配樂床;目錄無檔則回 None(整條混音路徑照舊走單軌)。
    絕不因缺素材而炸——任何失敗一律安靜回 None。"""
    try:
        bgm_dir = ROOT / "assets" / "audio" / "bgm"
        if not bgm_dir.is_dir():
            return None
        files = sorted(p for p in bgm_dir.glob("*.mp3") if p.is_file() and p.stat().st_size > 0)
        if not files:
            return None
        import hashlib
        h = int(hashlib.md5((slug or "x").encode("utf-8")).hexdigest(), 16)
        return str(files[h % len(files)])  # 依 slug 穩定挑，同片每次同曲
    except Exception:  # noqa: BLE001
        return None


def _make_seg_card(seg, i, *, width, height, watermark, accent, vid_seed, video_concept, tmp_dir,
                   force_key=None):
    """產一段的卡片 PNG(concept → K線 → 字卡 三級降級)。回傳 PNG 路徑。
    force_key 有值＝硬指定概念圖(用於強制回測對比 beat)。"""
    card = None
    try:
        card = mv.render_concept_card(
            width, height, heading=seg.heading or "", narration=seg.narration,
            watermark=watermark, accent=accent, seed=f"{vid_seed}_{i}",
            dest=tmp_dir / f"concept_{i:02d}.png", default_key=video_concept, force_key=force_key)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 概念圖失敗,退 K 線卡:{exc}", file=sys.stderr)
        card = None
    if card is None:
        try:
            card = mv.render_candle_card(
                width, height, big_text=seg.heading or "", watermark=watermark,
                accent=accent, seed=f"{vid_seed}_{i}", dest=tmp_dir / f"kcard_{i:02d}.png")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] K 線卡失敗,退字卡:{exc}", file=sys.stderr)
            card = None
    if card is None:
        # 三級降級的最後一級本身也要防呆:字卡理論上最不該失敗,但若真的失敗(如字型載入炸掉),
        # 不能讓整個 render() 崩潰而拿不到 _encode_and_validate 的重試/不留壞檔機制。
        try:
            card = mv.render_card_image(
                width, height, big_text=seg.heading or "", small_text="",
                watermark=watermark, dest=tmp_dir / f"card_{i:02d}.png", accent=accent)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 字卡也失敗,退最小純色保底圖:{exc}", file=sys.stderr)
            card = None
    if card is None:
        try:
            from PIL import Image
            fallback_path = tmp_dir / f"fallback_{i:02d}.png"
            Image.new("RGB", (width, height), color=accent or (20, 20, 20)).save(fallback_path)
            card = fallback_path
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 純色保底圖也失敗:{exc}", file=sys.stderr)
            raise
    return str(card)


def _make_watermark_png(text, width, height, tmp_dir):
    """產右下角浮水印 PNG(給 b-roll 段用;卡片段已內建浮水印)。"""
    from PIL import Image, ImageDraw
    if not text:
        return None
    fsize = max(20, int(height * 0.020))
    font = mv._load_font(fsize, bold=False)
    tmp = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    try:
        b = d.textbbox((0, 0), text, font=font)
        tw, th = b[2] - b[0], b[3] - b[1]
    except Exception:  # noqa: BLE001
        tw, th = len(text) * fsize, fsize
    pad = int(fsize * 0.55)
    iw, ih = tw + pad * 2, th + pad * 2
    img = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([0, 0, iw - 1, ih - 1], radius=int(ih * 0.28), fill=(8, 12, 24, 150))
    dr.text((pad, pad - int(th * 0.1)), text, fill=(235, 235, 235, 235), font=font)
    dest = tmp_dir / "watermark.png"
    img.save(dest, "PNG")
    return str(dest)


def _render_hook_card(title, width, height, accent, tmp_dir):
    """開場大數字衝擊卡(階段1炫炮):抽 title 最衝擊的數字滿屏砸出——視覺衝擊鉤子,降前3秒滑走。抽不到數字回 None。"""
    import re
    from PIL import Image, ImageDraw
    # 挑「最衝擊的短數字」當主視覺:優先 %/倍/萬,取數值最大那個(常是 punchline);再退次/天/年
    cands = re.findall(r'\d+\.?\d*\s*[%倍萬]', title)
    if cands:
        num = max(cands, key=lambda s: float(re.findall(r'[\d.]+', s)[0])).replace(" ", "")
    else:
        m = re.search(r'\d+\s*[次天年]|\d{2,}', title)
        num = m.group(0).replace(" ", "") if m else None
    if not num:  # 阿拉伯抓不到→抓中文數字(十年/一萬/三倍/九成)
        m = re.search(r'[一二三四五六七八九十百千兩]+\s*[%倍萬年天次成億]', title)
        num = m.group(0).replace(" ", "") if m else None
    if not num:
        return None
    try:
        bg = mv._card_background(width, height, accent, seed=title).convert("RGBA")
    except Exception:  # noqa: BLE001
        bg = Image.new("RGBA", (width, height), (10, 14, 26, 255))
    d = ImageDraw.Draw(bg)
    # 巨大數字(紅色衝擊+厚黑描邊,砸臉)
    fsize = int(height * 0.24)
    font = mv._load_font(fsize, bold=True)
    while fsize > 48:  # 字級自適應:太寬就縮,絕不爆框
        bb = d.textbbox((0, 0), num, font=font)
        if (bb[2] - bb[0]) <= width * 0.86:
            break
        fsize = int(fsize * 0.88); font = mv._load_font(fsize, bold=True)
    bb = d.textbbox((0, 0), num, font=font); tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x = (width - tw) // 2; y = int(height * 0.40)
    e = max(4, int(fsize * 0.04))
    for dx, dy in ((-e, 0), (e, 0), (0, -e), (0, e), (e, e), (-e, -e), (e, -e), (-e, e)):
        d.text((x + dx, y + dy), num, fill=(0, 0, 0, 255), font=font)
    d.text((x, y), num, fill=(255, 90, 90, 255), font=font)
    # 上方鉤子句(去 hashtag 後前段)
    # 完播節奏修復同批順手修(2026-07-15,獨立驗收抓到):原本這裡用 title.replace(num, "")
    # 想把已經在大紅字砸過的數字從鉤子句挖掉、避免視覺重複——但 num 只是「裸數字」子字串
    # (如 "77"),str.replace 預設整字串「全部」取代,若 title 內另一個更大的數字剛好內含
    # 這串子字串(如 "3.77億" 內含 "77"),會被一併挖空,砍出「3.億」這種懸空殘句;就算沒撞
    # 到子字串碰撞,單純的「挖掉裸數字、留下單位/量詞」也會產生「台股檔全算過」這種缺主詞
    # 的破碎中文(量詞「檔」失去前面的數字就不成句)。兩種都是「暴力砍字串」的產物。
    # 改法:鉤子句不再嘗試從 title 挖數字,完整保留 title(下方大紅字數字重複出現一次無傷
    # 大雅,遠比破碎殘句安全);只做原本就有的 hashtag 清理。
    hook = re.sub(r'#\S+', '', title).strip("？?，,。、 ")
    hook = re.split(r'[，,。]', hook)[0][:14] or "你知道嗎"  # 取第一段、限長
    hfs = int(height * 0.048)
    hf = mv._load_font(hfs, bold=True)
    while hfs > 28:  # 鉤子句也自適應防爆框
        hb = d.textbbox((0, 0), hook, font=hf)
        if (hb[2] - hb[0]) <= width * 0.90:
            break
        hfs = int(hfs * 0.9); hf = mv._load_font(hfs, bold=True)
    hb = d.textbbox((0, 0), hook, font=hf)
    hx = (width - (hb[2] - hb[0])) // 2
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        d.text((hx + dx, int(height * 0.27) + dy), hook, fill=(0, 0, 0, 255), font=hf)
    d.text((hx, int(height * 0.27)), hook, fill=(240, 240, 240, 255), font=hf)
    # 下方懸念
    sf2 = mv._load_font(int(height * 0.040), bold=True)
    sub = "你猜是多少？"
    sbb = d.textbbox((0, 0), sub, font=sf2)
    d.text(((width - (sbb[2] - sbb[0])) // 2, y + th + int(height * 0.045)), sub, fill=accent + (255,), font=sf2)
    dest = tmp_dir / "hookcard.png"
    bg.convert("RGB").save(dest, "PNG")
    return str(dest)


def _seg_subs(cues, seg_start, seg_end, width, height, tmp_dir, accent):
    """產此段視窗內的字幕 PNG + 段內相對時間。回傳 [(png, local_start, local_end)]。"""
    out = []
    for k, cu in enumerate(cues):
        if cu.end <= seg_start or cu.start >= seg_end:
            continue
        ls = max(0.0, cu.start - seg_start)
        le = max(ls + 0.05, min(seg_end, cu.end) - seg_start)
        png = mv._render_subtitle_image(width, height, cu.text, tmp_dir, accent=accent)
        if png is not None:
            out.append((str(png), ls, le))
    return out


def _seg_clip(ff, *, src, is_video, dur, subs, fade_in, width, height, fps, tmp_dir, idx, watermark=None,
              seg_start=0.0) -> str:
    """把一段(卡片圖 或 b-roll 影片)正規化成 WxH 無聲 mp4,字幕用 overlay 燒上。回傳路徑。
    seg_start:此段在「整支成片」時間軸上的絕對起點(秒)。卡片脈衝鏡的相位用它算,
    確保脈衝橫跨多段 concat 邊界仍連續(見下方完播節奏修復 2026-07-15 註解)。"""
    out = tmp_dir / f"piece_{idx:03d}.mp4"
    inputs = []
    if is_video:
        # P0 止血(2026-07-13 斷尾壞檔根因)：b-roll 來源片常比要分配到的 dur 短(Pexels
        # 素材動輒 3-15s，per_seg 常 20-40s)。舊寫法只有「-t dur -i src」是純輸入端裁切，
        # 來源比 dur 短就整段悄悄縮水(實測 dur=10s、來源 3s → 輸出僅 2.97s)；concat 起來
        # 總長就會比旁白短，卻沒有任何檢查攔下——這是 4 支已知斷尾片(含 3 支已發布)的主因
        # 之一。改成 -stream_loop -1 先把來源無限循環，仍由 -t dur 裁到精確長度，保證這段
        # 輸出永遠等於 dur，絕不再因素材太短而截斷。
        inputs += ["-stream_loop", "-1", "-t", f"{dur:.3f}", "-i", src]
        # 完播節奏(2026-07-15 二修):b-roll 分支原本**完全沒有**脈衝——只有卡片分支有。
        # 旗艦2(全片 Pexels b-roll)實測 scene=0:慢鏡/空拍素材+短素材循環,自身畫面變化
        # 量不到 gt(scene,0.1)。補上與卡片同週期同相位的亮度脈衝(±8%,每 3.5 秒),
        # 讓 b-roll 段也有可量測、人眼可感的節奏跳動。
        base = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p,"
                f"trim=0:{dur:.3f},setpts=PTS-STARTPTS,"
                f"eq=eval=frame:brightness='0.08*mod(floor((t+{seg_start:.3f})/3.5)\\,2)'")
    else:
        # 卡片不再靜止:Ken Burns 緩推鏡(先放大 2x→zoompan 縮回,讓位移是次像素、字幕不抖)。
        # 有影片感、又 100% 是自家數據/圖表(護城河),解決「靜態卡」+「素材脫題」兩難。
        frames = max(1, int(round(dur * fps)))
        inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", src]
        # 完播節奏根修(2026-07-15,獨立驗收判定 86ec25d 沒真正落地後複查):舊版只在
        # 「單一 segment 時長 >7 秒」才套脈衝,<=7 秒走原本連續緩推(0.0007~0.0013/frame)。
        # 但 production 腳本把大多數卡切成對應字幕換氣的短 segment(常見 3-7 秒),per_seg
        # 幾乎從未跨過 7 秒門檻——緩推速率量到的位移是次像素級,ffmpeg scene detection
        # (甚至人眼)完全看不到,於是「一堆短 segment 背靠背」串成 20~42 秒(Shorts)甚至
        # 332 秒(長片,per_seg 有時也 <=7 秒)的視覺凍結。根因不是脈衝公式本身失效,是
        # 「>7 秒」門檻把大多數 production 內容排除在脈衝之外。
        #
        # 改法:拿掉門檻,不分長短一律套脈衝(反正 base pipeline 本來就是同一條 2x 預縮放
        # +zoompan,不多算 render cost)。相位用「此段在整支片時間軸上的絕對起點」
        # (seg_start,呼叫端傳入)而非每段各自從 on=0 起跳——每次 _seg_clip 都是獨立
        # ffmpeg 行程,若相位各自歸零,一串短 segment(尤其彼此在同一半週期內、卡片視覺
        # 又相近)仍可能疊出跨段的長凍結感;用絕對時間相位讓脈衝在 concat 後的整支片時間軸
        # 上連續,保證每 3.5 秒有一次真正的構圖跳動,不論被切成幾段。
        #
        # 二次覆查(2026-07-15,用真正的 production 卡片圖+ffmpeg select='gte(scene,0)',
        # metadata=print:key=lavfi.scene_score 實測量出來的,不是憑感覺調):純幾何縮放
        # (zoompan)不管振幅開多大(實測 0.07~0.5 都試過)分數都卡在 0.04~0.05,穩定量
        # 不到 gt(scene,0.1)!原因是卡片背景大面積深色、縮放只是同一批像素搬移,ffmpeg
        # scene 偵測看的是整體色彩/直方圖變化,對純幾何變換本來就不敏感——舊註解「0.07
        # 才能穩定跨過 0.1」這句話從沒被真正驗證過,是這次複查才發現的。改法:脈衝跳動時
        # 疊一段極短暫的亮度脈衝(eq=eval=frame:brightness,同一 3.5 秒週期、同相位),
        # 才是真正讓數值躍過去的關鍵——實測卡片 0.08 亮度脈衝 + 0.07 縮放,分數穩定落在
        # 0.20~0.29(深色圖表卡+亮色大數字卡都測過),對 gt(scene,0.1) 有 2 倍安全margin。
        # 亮度脈衝幅度小(±8%,一瞬間)人眼觀感是「呼吸感」不是閃爍。
        _start_frame = int(round(seg_start * fps))
        zexpr = f"1.0+0.07*mod(floor((on+{_start_frame})/({fps}*3.5)),2)"
        beq = f"eq=eval=frame:brightness='0.08*mod(floor((t+{seg_start:.3f})/3.5)\\,2)'"
        # 推鏡上限 1.06(僅供參考,脈衝公式本身封在 1.0~1.07 內):邊緣裁切夠小,
        # 保住卡片燒入的浮水印(別被放大切到底邊)
        base = (f"[0:v]scale={width*2}:{height*2}:flags=lanczos,"
                f"zoompan=z='{zexpr}':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},"
                f"setsar=1,format=yuv420p,{beq}")
    if fade_in:
        # P-封面修:純 fade=t=in:st=0 讓輸出的 t=0 那一幀是 100% 純黑(fade 從 alpha=0
        # 起跳),TikTok/IG 自動抓片頭幀當封面 → 全部抓到黑。改用 tpad 在最前面複製墊
        # 0.35s(clone 第一幀),把淡入起點藏在墊片裡、輸出前再 trim 掉墊片——真正輸出
        # 的 t=0 幀此時已淡入 ~70% 亮度(不是黑),淡入尾段(~0.15s)仍保留在畫面內,
        # 美感不變、封面不再黑。trim 後 setpts 重置時間軸,長度淨變化為 0。
        base += (",tpad=start_duration=0.35:start_mode=clone,fade=t=in:st=0:d=0.5,"
                 "trim=start=0.35,setpts=PTS-STARTPTS")
    parts = [f"{base}[bg]"]
    prev = "bg"
    for j, (sp, ls, le) in enumerate(subs):
        inputs += ["-loop", "1", "-i", sp]
        nxt = f"ov{j}"
        parts.append(f"[{prev}][{1+j}:v]overlay=x=(W-w)/2:y=H*0.78-h:"
                     f"enable='between(t,{ls:.3f},{le:.3f})'[{nxt}]")
        prev = nxt
    if watermark:  # b-roll 段補浮水印(右下,全程),與卡片段一致
        m = int(width * 0.022)
        inputs += ["-loop", "1", "-i", watermark]
        parts.append(f"[{prev}][{1+len(subs)}:v]overlay=x=W-w-{m}:y=H-h-{m}[wm]")
        prev = "wm"
    fc = ";".join(parts)
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", *inputs,
           "-filter_complex", fc, "-map", f"[{prev}]", "-an",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-r", str(fps), "-t", f"{dur:.3f}", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"段 {idx} 正規化失敗: {r.stderr[-300:]}")
    return str(out)


def _broll_query(seg, title, idx):
    """把『一段在講什麼』對映到一個 Pexels 保證有金融/加密實拍的具體 query。
    LLM 寫的 b-roll 常是抽象概念(liquidation cascade/emotional trading),Pexels 沒有對應實拍會配到亂源
    (瀑布/哭臉)→ 主題脫鉤。這裡無視抽象詞,改用主題偵測挑具體白名單,保證畫面永遠是幣/K線/交易螢幕/鈔票。"""
    import re as _r
    txt = (title or "") + " " + (seg.heading or "") + " " + (seg.narration or "") + " " + " ".join(seg.broll or [])
    low = txt.lower()
    # (中文/英文偵測詞, 對映的具體 Pexels query 池) — 由上而下,先命中先用;池內依段序輪替避免重複
    RULES = [
        (r'比特幣|btc|以太|eth|加密|虛擬貨幣|crypto|bitcoin|幣價|代幣|鏈上',
         ["bitcoin cryptocurrency", "crypto trading screen", "bitcoin coin gold", "cryptocurrency market chart"]),
        (r'爆倉|清算|崩|暴跌|liquidat|crash|風險|risk|虧|套牢|回撤|drawdown|連輸',
         ["stock market crash chart", "red trading chart falling", "financial crisis screen", "stock market down"]),
        (r'網格|grid|區間|波段|高頻|做多|做空|槓桿|leverage|合約',
         ["candlestick chart trading", "forex trading screen", "trading chart monitor", "stock market candlestick"]),
        (r'定投|dca|複利|長期|存錢|被動|存股|累積|滾雪球|compound',
         ["money savings growth", "coins stacking growth", "investment growth chart", "piggy bank savings"]),
        (r'賺|獲利|報酬|profit|賺錢|收益|終值|翻倍|財富|rich|money',
         ["money cash counting", "gold coins money", "wealth success money", "hundred dollar bills"]),
        (r'回測|勝率|夏普|數據|公式|機率|統計|backtest|data|算',
         ["financial data analytics screen", "stock data dashboard", "trading data monitor", "market analytics screen"]),
    ]
    for pat, pool in RULES:
        if _r.search(pat, low):
            return [pool[idx % len(pool)]]
    # 沒命中主題詞 → 給一組通用但「一定是金融感」的輪替,絕不放生到無關素材
    GENERIC = ["stock market chart", "trading screen monitor", "financial graph data",
               "candlestick chart", "stock exchange trading", "money finance business"]
    return [GENERIC[idx % len(GENERIC)]]


def _render_with_broll(slug_paths, *, segments, seg_cards, intro_png, outro_png, cues,
                       audio_duration, per_seg, width, height, fps, pexels_key, accent,
                       watermark, tmp_dir, ff) -> bool:
    """b-roll 後端:每段正規化成 mp4(b-roll 影片或卡片)+字幕,concat+音軌。回傳 True/False(失敗交回卡片路徑)。"""
    try:
        n = len(segments)
        wm_png = _make_watermark_png(watermark, width, height, tmp_dir)
        pieces = []
        # intro
        pieces.append(_seg_clip(ff, src=intro_png, is_video=False, dur=mv.INTRO_DURATION,
                                subs=[], fade_in=True, width=width, height=height, fps=fps,
                                tmp_dir=tmp_dir, idx=0, seg_start=0.0))
        broll_used = 0
        broll_cap = max(1, n // 3)  # 卡片(會動的數據/圖表)是護城河,讓它主導;通用實拍封頂 ~1/3 段
        import re as _re
        DATA = (r'百分之|\d+\.?\d*\s*[%倍萬]|回測|勝率|夏普|複利|期望值|回撤|一張表|數據|算給你|終值'
                r'|公式|連[輸贏]|機率|點[零一二三四五六七八九]|實測|平均|對比')
        for i, seg in enumerate(segments):
            seg_start, seg_end = i * per_seg, (i + 1) * per_seg
            src, is_video = seg_cards[i], False
            # 混合:數據段(講具體數字/回測)用會動的圖表卡保留說服力;鋪陳/情境段才用 b-roll,且封頂
            is_data = bool(_re.search(DATA, (seg.heading or "") + " " + (seg.narration or "")))
            if not is_data and per_seg <= 30 and broll_used < broll_cap:  # 長片 Pexels 填不滿又超慢→維持卡片
                kws = _broll_query(seg, getattr(slug_paths, "slug", "") or "", i)  # 主題對映具體 query,不用 LLM 抽象詞
                clip = mv.fetch_pexels_clip(kws, api_key=pexels_key, width=width,
                                            height=height, dest_dir=tmp_dir, index=i)
                if clip is not None:
                    src, is_video = str(clip), True
                    broll_used += 1
            subs = _seg_subs(cues, seg_start, seg_end, width, height, tmp_dir, accent)
            pieces.append(_seg_clip(ff, src=src, is_video=is_video, dur=per_seg, subs=subs,
                                    fade_in=False, width=width, height=height, fps=fps,
                                    tmp_dir=tmp_dir, idx=i + 1,
                                    watermark=(wm_png if is_video else None),
                                    seg_start=mv.INTRO_DURATION + seg_start))
        # outro
        pieces.append(_seg_clip(ff, src=outro_png, is_video=False, dur=mv.OUTRO_DURATION,
                                subs=[], fade_in=False, width=width, height=height, fps=fps,
                                tmp_dir=tmp_dir, idx=n + 1,
                                seg_start=mv.INTRO_DURATION + audio_duration))

        total = mv.INTRO_DURATION + audio_duration + mv.OUTRO_DURATION
        list_txt = tmp_dir / "pieces.txt"
        with open(list_txt, "w", encoding="utf-8") as f:
            for p in pieces:
                f.write(f"file '{Path(p).as_posix()}'\n")
        intro_ms = int(mv.INTRO_DURATION * 1000)
        # 配樂床:有 BGM 素材才混,人聲為主(BGM≈-20dB),缺素材完全照舊走單軌
        bgm = _pick_bgm(getattr(slug_paths, "slug", "") or "")
        voice_fc = f"[1:a]adelay={intro_ms}:all=1,apad,atrim=0:{total:.3f}[voice]"
        inputs_a = ["-i", str(slug_paths.audio)]
        if bgm:
            inputs_a = ["-i", str(slug_paths.audio), "-stream_loop", "-1", "-i", str(bgm)]
            af = (f"{voice_fc};[2:a]volume=0.10,atrim=0:{total:.3f}[bgm];"
                  f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        else:
            af = f"[1:a]adelay={intro_ms}:all=1,apad,atrim=0:{total:.3f}[a]"
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(list_txt),
               *inputs_a,
               "-filter_complex", af,
               "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
               "-t", f"{total:.3f}", "-movflags", "+faststart", str(slug_paths.out_mp4)]
        print(f"[ffmpeg後端·b-roll] b-roll={broll_used}/{n}段  字幕={len(cues)}  "
              f"BGM={'有' if bgm else '無'}  總長={total:.1f}s")
        # P0 止血：成品長度必須 ≥ 旁白長度，否則 fail-closed 不留壞檔(見 _encode_and_validate 註解)。
        ok = _encode_and_validate(cmd, slug_paths.out_mp4, tmp_dir, stage="b-roll", timeout=300,
                                  min_dur=max(1.0, total * 0.95))
        if ok:
            mb = slug_paths.out_mp4.stat().st_size / (1024 * 1024)
            print(f"[ffmpeg後端·b-roll] ✅ 完成 {slug_paths.out_mp4.name}（{mb:.1f} MB, b-roll {broll_used} 段）")
        else:
            print("[ffmpeg後端·b-roll] 交回卡片路徑", file=sys.stderr)
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[ffmpeg後端·b-roll] 失敗({exc}),交回卡片路徑", file=sys.stderr)
        return False


def _render_animated(slug_paths, *, segments, seg_cards, intro_png, outro_png, cues,
                     audio_duration, per_seg, width, height, fps, accent, watermark, title,
                     tmp_dir, ff) -> bool:
    """Tier-2 動畫後端(opt-in RENDER_ANIM):每段依特效意圖產動畫 clip(數字爆現/紅刀/montage/字卡彈出),
    降級鏈:特效失敗→popup 現有卡片→靜態 _seg_clip。concat+音軌同 b-roll 路徑。回 True/False(失敗交回其他路徑)。"""
    try:
        import anim_fx as afx
    except Exception as exc:  # noqa: BLE001
        print(f"[動畫後端] anim_fx 載入失敗({exc}),交回", file=sys.stderr)
        return False
    try:
        n = len(segments)
        is_debunk = bool(re.search(r"拆穿|揭穿|揭露|打假|神話|真相|騙|智商稅|翻車", title or ""))
        mascot_on = mv._mascot_enabled()
        wm_png = _make_watermark_png(watermark, width, height, tmp_dir)
        pieces = []

        # intro:品牌片頭卡（ffmpeg 緩推鏡+淡入，快；不用逐幀 PIL）
        pieces.append(_seg_clip(ff, src=intro_png, is_video=False, dur=mv.INTRO_DURATION,
                                subs=[], fade_in=True, width=width, height=height, fps=fps,
                                tmp_dir=tmp_dir, idx=0, seg_start=0.0))
        fx_count = {"smash": 0, "knife": 0, "montage": 0, "popup": 0}
        for i, seg in enumerate(segments):
            seg_start, seg_end = i * per_seg, (i + 1) * per_seg
            subs = _seg_subs(cues, seg_start, seg_end, width, height, tmp_dir, accent)
            # 該段吉祥物表情(逐段情緒,重用 tier-1 邏輯)
            mp = None
            if mascot_on:
                try:
                    mp = mv._mascot_expr_for_text((seg.narration or "") + " " + (seg.heading or "")) or None
                except Exception:  # noqa: BLE001
                    mp = None
            fx, payload = afx.detect_fx(seg.heading, seg.narration, is_debunk=is_debunk,
                                        explicit=getattr(seg, "fx", None))
            # 效能閘：PIL 逐幀的 FX 只在短段觸發(FX 本是短促爆點);長段(per_seg 大,如長片)一律走
            # ffmpeg 緩推鏡 popup,避免一段畫上千幀拖垮長片。門檻可用 ANIM_FX_MAX_SEG 覆寫。
            try:
                _fx_max = float(os.environ.get("ANIM_FX_MAX_SEG", "8"))
            except Exception:  # noqa: BLE001
                _fx_max = 8.0
            if per_seg > _fx_max:
                fx, payload = "popup", None
            seed = f"{getattr(slug_paths, 'slug', '') or title}_{i}"
            clip = None
            try:
                if fx == "smash" and payload:
                    clip = afx.number_smash_clip(payload, dur=per_seg, subs=subs, width=width, height=height,
                                                 fps=fps, accent=accent, seed=seed, tmp_dir=tmp_dir, idx=i + 1,
                                                 mascot_png=mp, watermark_png=wm_png, debunk=is_debunk,
                                                 sub_label=("他吹的神話" if is_debunk else None))
                elif fx == "knife" and payload:
                    clip = afx.knife_slash_clip(payload, dur=per_seg, subs=subs, width=width, height=height,
                                                fps=fps, accent=(255, 96, 96), seed=seed, tmp_dir=tmp_dir,
                                                idx=i + 1, mascot_png=mp, watermark_png=wm_png)
                elif fx == "montage" and payload:
                    clip = afx.montage_clip(payload, dur=per_seg, subs=subs, width=width, height=height,
                                            fps=fps, accent=accent, seed=seed, tmp_dir=tmp_dir, idx=i + 1,
                                            mascot_png=mp, watermark_png=wm_png)
            except Exception:  # noqa: BLE001
                clip = None
            used = fx if clip else "popup"
            # 預設 / 特效失敗 → 現有卡片走 ffmpeg 緩推鏡+淡入（快，不逐幀 PIL）；卡片已含 concept/HUD/吉祥物/浮水印
            if not clip:
                clip = _seg_clip(ff, src=seg_cards[i], is_video=False, dur=per_seg, subs=subs,
                                 fade_in=(i == 0), width=width, height=height, fps=fps, tmp_dir=tmp_dir, idx=i + 1,
                                 seg_start=mv.INTRO_DURATION + seg_start)
            fx_count[used if used in fx_count else "popup"] = fx_count.get(used, 0) + 1
            pieces.append(clip)

        # outro:品牌卡 ffmpeg 緩推鏡(快)
        pieces.append(_seg_clip(ff, src=outro_png, is_video=False, dur=mv.OUTRO_DURATION,
                                subs=[], fade_in=False, width=width, height=height, fps=fps,
                                tmp_dir=tmp_dir, idx=n + 1,
                                seg_start=mv.INTRO_DURATION + audio_duration))

        # 無縫 loop 尾(item9):片尾補 0.6s 封面(=片頭首幀),讓 Shorts 重播無縫→拉高 loop 完播
        # (2026 演算法:結尾 2 秒內重看算部分新觀看)。音訊 apad 自動補靜音、body 時序不動→不 desync。
        # 純加法+try 防呆:失敗只是不加尾。MV_NO_LOOP_TAIL=1 可關。
        _loop_tail = 0.0
        if os.environ.get("MV_NO_LOOP_TAIL") != "1":
            try:
                pieces.append(_seg_clip(ff, src=intro_png, is_video=False, dur=0.6,
                                        subs=[], fade_in=True, width=width, height=height, fps=fps,
                                        tmp_dir=tmp_dir, idx=n + 2,
                                        seg_start=mv.INTRO_DURATION + audio_duration + mv.OUTRO_DURATION))
                _loop_tail = 0.6
            except Exception as _lte:  # noqa: BLE001
                print(f"[ffmpeg後端·動畫] loop 尾略過:{str(_lte)[:60]}", file=sys.stderr)

        # concat + 音軌(人聲 adelay + BGM amix),比照 _render_with_broll
        total = mv.INTRO_DURATION + audio_duration + mv.OUTRO_DURATION + _loop_tail
        list_txt = tmp_dir / "pieces_anim.txt"
        with open(list_txt, "w", encoding="utf-8") as f:
            for p in pieces:
                f.write(f"file '{Path(p).as_posix()}'\n")
        intro_ms = int(mv.INTRO_DURATION * 1000)
        bgm = _pick_bgm(getattr(slug_paths, "slug", "") or "")
        voice_fc = f"[1:a]adelay={intro_ms}:all=1,apad,atrim=0:{total:.3f}[voice]"
        inputs_a = ["-i", str(slug_paths.audio)]
        if bgm:
            inputs_a = ["-i", str(slug_paths.audio), "-stream_loop", "-1", "-i", str(bgm)]
            af = (f"{voice_fc};[2:a]volume=0.10,atrim=0:{total:.3f}[bgm];"
                  f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        else:
            af = f"[1:a]adelay={intro_ms}:all=1,apad,atrim=0:{total:.3f}[a]"
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(list_txt),
               *inputs_a, "-filter_complex", af,
               "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
               "-t", f"{total:.3f}", "-movflags", "+faststart", str(slug_paths.out_mp4)]
        print(f"[ffmpeg後端·動畫] 特效={fx_count}  字幕={len(cues)}  BGM={'有' if bgm else '無'}  總長={total:.1f}s")
        # P0 止血：成品長度必須 ≥ 旁白長度，否則 fail-closed 不留壞檔(見 _encode_and_validate 註解)。
        ok = _encode_and_validate(cmd, slug_paths.out_mp4, tmp_dir, stage="動畫", timeout=600,
                                  min_dur=max(1.0, total * 0.95))
        if ok:
            mb = slug_paths.out_mp4.stat().st_size / (1024 * 1024)
            print(f"[ffmpeg後端·動畫] ✅ 完成 {slug_paths.out_mp4.name}（{mb:.1f} MB, 特效 {fx_count}）")
        else:
            print("[ffmpeg後端·動畫] 交回其他路徑", file=sys.stderr)
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[ffmpeg後端·動畫] 失敗({exc}),交回其他路徑", file=sys.stderr)
        return False


MIN_FPS = 30  # A5：短片 15fps 太頓、廉價感傷完播；不論呼叫端傳什麼一律吃 30fps 地板(呼叫端仍可傳更高)。


def render(slug_paths, branding, *, width, height, fps, no_subtitles=False) -> bool:
    """純 ffmpeg 組片。回傳 True=成功;False=此片不適用(交回 moviepy 備案)。"""
    from PIL import Image

    fps = max(int(fps or 0), MIN_FPS)
    title, segments = mv.parse_script_md(slug_paths.script_md)
    audio_duration = mv.probe_audio_duration(slug_paths.audio)
    if audio_duration <= 0:
        print("[ffmpeg後端] 配音時長 0,交回備案", file=sys.stderr)
        return False

    n = len(segments)
    if n == 0:
        # 腳本解析不到任何段落:後面 seg_cards[-1] 等邏輯會對空陣列取值直接 IndexError 崩潰,
        # 且發生在呼叫 ffmpeg 之前，接不到 _encode_and_validate 的重試/不留壞檔機制。
        # 交回 moviepy 備案，而不是讓整個 render() 硬崩潰。
        print("[ffmpeg後端] 腳本解析不到任何段落,交回備案", file=sys.stderr)
        return False
    per_seg = audio_duration / n if n else audio_duration
    watermark = branding.get("watermark_text", "")
    accent = mv.pick_accent(getattr(slug_paths, "slug", "") or title)
    vid_seed = getattr(slug_paths, "slug", "") or title

    video_concept = None
    if getattr(mv, "_concept", None) is not None:
        try:
            video_concept = mv._concept.classify(
                title + " " + " ".join(s.heading for s in segments if s.heading))
        except Exception:  # noqa: BLE001
            video_concept = None

    tmp_dir = Path(tempfile.mkdtemp(prefix="carson_ff_"))
    try:
        # 1) 每段卡片 PNG
        seg_cards = [
            _make_seg_card(seg, i, width=width, height=height, watermark=watermark,
                           accent=accent, vid_seed=vid_seed, video_concept=video_concept, tmp_dir=tmp_dir)
            for i, seg in enumerate(segments)
        ]

        # 1.2) 強制一個「回測期 vs 驗證期」對比 beat：每支片至少出現一次 split-chart。
        # 挑一個最像資料/回測的 body 段（非首非尾）硬渲染 backtest 概念卡蓋回；
        # concept_visuals 不可用、產不出、或無合適段落 → 安靜跳過保留原卡，絕不強塞到崩。
        try:
            if getattr(mv, "_concept", None) is not None and n >= 2:
                _DATA_RE = re.compile(r"回測|驗證|樣本|勝率|夏普|數據|實測|績效|歷史|\d+\.?\d*\s*[%倍]")
                _cand = None
                for _i in range(1, len(segments) - 1):  # 保留片頭尾語氣，挑中間 body 段
                    _txt = (segments[_i].heading or "") + " " + (segments[_i].narration or "")
                    if _DATA_RE.search(_txt):
                        _cand = _i
                        break
                if _cand is None and len(segments) >= 3:
                    _cand = len(segments) // 2  # 沒明顯資料段就挑正中段
                if _cand is not None and seg_cards[_cand]:
                    _btp = None
                    try:
                        _btp = mv.render_concept_card(
                            width, height, heading=segments[_cand].heading or "",
                            narration=segments[_cand].narration or "", watermark=watermark,
                            accent=accent, seed=f"{vid_seed}_{_cand}",
                            dest=tmp_dir / f"forcebt_{_cand:02d}.png", force_key="backtest")
                    except Exception:  # noqa: BLE001
                        _btp = None
                    if _btp:  # 產得出才蓋；產不出（回 None）保留原卡
                        seg_cards[_cand] = str(_btp)
                        print(f"[ffmpeg後端] 強制回測對比 beat：段 {_cand}")
        except Exception:  # noqa: BLE001
            pass

        # 1.5) 實測EP招牌HUD / A vs B 賽跑對比：烤進段卡（非實測/非對比片零影響）
        try:
            _is_exp = bool(re.search(r"EP|實測|實驗", title or ""))
            _is_race = bool(re.search(r"vs|VS|對決|對打|賽跑", title or ""))
            if _is_exp or _is_race:
                _vt = mv.read_voice_text(slug_paths) or " ".join(s.narration for s in segments if s.narration)
                _nums = mv._parse_experiment_numbers(_vt)
                # ep_data 權威真數字只在「本片真的屬於該系列」時才蓋（判定與 make_video 共用同一個
                # _ep_data_applies，不各自複製一份——這個 HUD bug 當初就是兩邊複製貼上同時中鏢）。
                try:
                    if mv._ep_data_applies(title or "", getattr(slug_paths, "slug", ""), _nums):
                        _nums.update(mv._ep_data_numbers())
                except Exception:  # noqa: BLE001
                    pass
                _pr, _pct = _nums.get("principal"), _nums.get("pct")
                _bal, _dtot = _nums.get("balance"), _nums.get("days")
                if _bal is None and _pr is not None and _pct is not None:
                    _bal = int(_pr * (1 + _pct / 100.0))
                _ns = max(1, len(seg_cards))
                if any(v is not None for v in (_pr, _pct, _bal, _dtot)) or _is_race:
                    for i in range(len(seg_cards)):
                        if not seg_cards[i]:
                            continue
                        frac = (i + 1) / _ns
                        try:
                            if _is_race and not _is_exp:
                                _parts = re.split(r"vs|VS|對決|對打|賽跑", title)
                                _la = (_parts[0].strip()[-10:] or "A")
                                _lb = (_parts[1].strip()[:10] if len(_parts) > 1 and _parts[1].strip() else "B")
                                hud_png = mv.render_race_split(width, height, dest=tmp_dir / f"hud_{i:02d}.png",
                                                              labelA=_la, labelB=_lb, progA=frac, progB=frac * 0.82, accent=accent)
                            else:
                                # 用 is not None 而非 or:_dtot==0(合法「第0天」)不該被當 falsy
                                # 誤退回用段落數 _ns 當總天數,導致 HUD 顯示的天數跟旁白脫鉤。
                                _day = int(round((_dtot if _dtot is not None else _ns) * frac)) \
                                    if (_dtot is not None or _is_exp) else None
                                _bal_i = int(_pr + (_bal - _pr) * frac) if (_pr is not None and _bal is not None) else _bal
                                _pct_i = round(_pct * frac, 2) if _pct is not None else None
                                hud_png = mv.render_hud_strip(width, height, dest=tmp_dir / f"hud_{i:02d}.png",
                                                             day=_day, principal=_pr, balance=_bal_i, pct=_pct_i, accent=accent)
                            if hud_png:
                                _bc = Image.open(seg_cards[i]).convert("RGBA")
                                _bc.alpha_composite(Image.open(str(hud_png)).convert("RGBA"))
                                _op = tmp_dir / f"cardhud_{i:02d}.png"
                                _bc.convert("RGB").save(str(_op))
                                seg_cards[i] = str(_op)
                        except Exception:  # noqa: BLE001
                            pass
        except Exception:  # noqa: BLE001
            pass

        # 1.6) 吉祥物 IP（預設關；design_system.mascot_enabled=true 才貼；false 時跳過、輸出不變）
        if mv._mascot_enabled():
            try:
                _mpct = mv._ep_data_numbers().get("pct")
                _mn = len(seg_cards)
                for i in range(_mn):
                    if not seg_cards[i]:
                        continue
                    # 逐段依該段旁白情緒換表情;收官段維持 smug;該段抓不到才退整片 pct 表情
                    if i == _mn - 1:
                        _mp = mv._mascot_path_for(_mpct, closing=True)
                    else:
                        _seg_txt = ""
                        try:
                            _seg_txt = (segments[i].narration or "") + " " + (segments[i].heading or "")
                        except Exception:  # noqa: BLE001
                            _seg_txt = ""
                        _mp = mv._mascot_expr_for_text(_seg_txt) or mv._mascot_path_for(_mpct)
                    if not _mp:
                        continue
                    try:
                        _mimg = mv.paste_mascot(seg_cards[i], _mp, position="br", scale=0.16)
                        _mout = tmp_dir / f"cardmas_{i:02d}.png"
                        _mimg.convert("RGB").save(str(_mout))
                        seg_cards[i] = str(_mout)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

        # P1 首幀視覺 gate:演算法看前 2 秒滑走率,開場第一幀絕不能是空鏡/鋪陳的純品牌卡。
        # 舊優先序是「品牌卡優先、hook_card 只在無品牌素材時當備案」——但 assets/brand/intro_template.png
        # 常態存在,結果 hook_card(大數字衝擊卡)幾乎從沒被用到,首幀變成平淡標題卡。
        # 改成:能從標題抽到數字就優先用 hook_card(大數字/反直覺句/懸念,衝擊力最強);
        # 抽不到數字(標題本身無量化衝擊點)才退回品牌卡;品牌卡也產不出才退通用卡片。
        intro_png = _render_hook_card(title, width, height, accent, tmp_dir)
        if intro_png:
            print(f"[ffmpeg後端] 首幀=大數字衝擊卡 (hook_card)", file=sys.stderr)
        else:
            print("[warn] 首幀抽不到數字,退品牌卡/通用卡(建議檢查標題是否含具體數字)", file=sys.stderr)
            try:
                _mpath_i = mv._mascot_path_for(mv._ep_data_numbers().get("pct")) if mv._mascot_enabled() else None
                intro_png = mv.render_brand_intro(width, height, title=title,
                                                  dest=tmp_dir / "brand_intro.png",
                                                  tagline=branding.get("intro_tagline"), mascot_path=_mpath_i)
            except Exception:  # noqa: BLE001
                intro_png = None
        if not intro_png:
            intro_png = _make_seg_card(
                mv.Segment(heading=title, narration=""), 900,
                width=width, height=height, watermark=watermark, accent=accent,
                vid_seed=f"{vid_seed}_intro", video_concept=None, tmp_dir=tmp_dir)
        outro_png = _make_seg_card(mv.Segment(heading=watermark or "感謝收看", narration=""), 901,
                                   width=width, height=height, watermark=watermark, accent=accent,
                                   vid_seed=f"{vid_seed}_outro", video_concept=None, tmp_dir=tmp_dir)

        # 2) 字幕 cue
        cues = []
        if not no_subtitles:
            vt = mv.read_voice_text(slug_paths) or " ".join(s.narration for s in segments if s.narration).strip()
            # 優先用 TTS 逐字時間戳精準對齊(解決字幕漂移);無 sidecar 才退回字數估算法
            cues = (mv.load_word_cues(slug_paths, vt, audio_duration)
                    or mv.build_subtitle_cues(mv.split_subtitle_units(vt), audio_duration))

        # 2.4) Tier-2 動畫路徑:數字爆現/紅刀/montage/字卡彈出。
        #      開關二擇一:環境變數 RENDER_ANIM(臨時/單片) 或 design_system.json 的 render_anim=true(全線預設)。
        #      關=完全不影響主路徑;開了失敗也自動 fall through 到 b-roll/靜態,渲染永不崩。
        _anim_on = bool(os.environ.get("RENDER_ANIM"))
        if not _anim_on:
            try:
                _anim_on = bool(mv._design_system().get("render_anim", False))
            except Exception:  # noqa: BLE001
                _anim_on = False
        if _anim_on:
            _anim_tmp = Path(tempfile.mkdtemp(prefix="carson_anim_"))
            try:
                if _render_animated(slug_paths, segments=segments, seg_cards=seg_cards,
                                    intro_png=intro_png, outro_png=outro_png, cues=cues,
                                    audio_duration=audio_duration, per_seg=per_seg, width=width,
                                    height=height, fps=fps, accent=accent, watermark=watermark,
                                    title=title, tmp_dir=_anim_tmp, ff=_ffmpeg_exe()):
                    return True
                print("[ffmpeg後端] 動畫路徑未成,退回 b-roll/靜態", file=sys.stderr)
            except Exception as _ae:  # noqa: BLE001
                print(f"[ffmpeg後端] 動畫路徑例外({_ae}),退回", file=sys.stderr)
            finally:
                try:
                    import shutil as _sh
                    _sh.rmtree(_anim_tmp, ignore_errors=True)  # 清動畫 temp(幀/piece),防磁碟洩漏
                except Exception:  # noqa: BLE001
                    pass

        # 2.5) b-roll 路徑:有 Pexels key 且段有 broll → 走 b-roll(影片段);失敗自動退卡片靜態切片
        pexels_key = os.environ.get("PEXELS_API_KEY", "").strip() or None
        if pexels_key:  # 有 pexels key 就全片走 b-roll 動態影片(Carson 要影片、不要靜態卡)
            if _render_with_broll(slug_paths, segments=segments, seg_cards=seg_cards,
                                  intro_png=intro_png, outro_png=outro_png, cues=cues,
                                  audio_duration=audio_duration, per_seg=per_seg, width=width,
                                  height=height, fps=fps, pexels_key=pexels_key, accent=accent,
                                  watermark=watermark,
                                  tmp_dir=Path(tempfile.mkdtemp(prefix="carson_ffb_")), ff=_ffmpeg_exe()):
                return True
            print("[ffmpeg後端] b-roll 路徑未成,改用卡片靜態切片", file=sys.stderr)

        # 3) body 切片邊界(段邊界 ∪ 字幕邊界),每片合成「卡+當下字幕」PNG
        marks = {0.0, float(audio_duration)}
        for k in range(n + 1):
            marks.add(min(max(k * per_seg, 0.0), audio_duration))
        for cu in cues:
            marks.add(min(max(cu.start, 0.0), audio_duration))
            marks.add(min(max(cu.end, 0.0), audio_duration))
        bounds = sorted(marks)

        sub_cache = {}
        timeline = [(intro_png, mv.INTRO_DURATION)]  # (png, dur)
        for a, b in zip(bounds, bounds[1:]):
            dur = b - a
            if dur < 0.04:
                continue
            mid = (a + b) / 2.0
            seg_idx = min(int(mid / per_seg) if per_seg else 0, n - 1)
            base = seg_cards[seg_idx]
            cue = next((c for c in cues if c.start <= mid < c.end), None)
            png = base
            if cue is not None:
                key = (seg_idx, cue.text)
                if key not in sub_cache:
                    composed = base
                    sub_png = mv._render_subtitle_image(width, height, cue.text, tmp_dir, accent=accent)
                    if sub_png is not None:
                        try:
                            bimg = Image.open(base).convert("RGBA")
                            simg = Image.open(str(sub_png)).convert("RGBA")
                            x = max(0, (width - simg.width) // 2)
                            y = max(0, int(height * 0.78) - simg.height)  # 字幕底邊錨安全線
                            bimg.alpha_composite(simg, (x, y))
                            outp = tmp_dir / f"slice_{seg_idx:02d}_{len(sub_cache):03d}.png"
                            bimg.convert("RGB").save(str(outp), "PNG")
                            composed = str(outp)
                        except Exception:  # noqa: BLE001
                            composed = base
                    sub_cache[key] = composed
                png = sub_cache[key]
            timeline.append((png, dur))
        timeline.append((outro_png, mv.OUTRO_DURATION))

        # 3.5) 無縫 loop 尾(完播工程 2026-07-14):片尾補 0.6s 封面(=片頭首幀),讓 Shorts
        # 重播無縫接回開頭→誘導重看(2026 演算法:結尾 2 秒內重看算部分新觀看;頻道最高完播
        # 片曾被重看到 200~372%)。同 _render_animated 已用的手法,這裡補進「靜態切片」路徑
        # (實測目前多數 Shorts 最終走的就是這條路徑,之前只有動畫/b-roll 路徑有 loop 尾)。
        # 純加法+try 防呆:失敗只是不加尾,不影響主渲染。MV_NO_LOOP_TAIL=1 可關。
        _loop_tail = 0.0
        if os.environ.get("MV_NO_LOOP_TAIL") != "1":
            try:
                timeline.append((intro_png, 0.6))
                _loop_tail = 0.6
            except Exception as _lte:  # noqa: BLE001
                print(f"[ffmpeg後端] loop 尾略過:{str(_lte)[:60]}", file=sys.stderr)

        total = mv.INTRO_DURATION + audio_duration + mv.OUTRO_DURATION + _loop_tail

        # 4) concat demuxer 清單(每張圖一段時長;最後一張要再列一次,ffmpeg quirk)
        list_txt = tmp_dir / "concat.txt"
        with open(list_txt, "w", encoding="utf-8") as f:
            for png, dur in timeline:
                f.write(f"file '{Path(png).as_posix()}'\n")
                f.write(f"duration {dur:.4f}\n")
            f.write(f"file '{Path(timeline[-1][0]).as_posix()}'\n")

        # 5) 一次 ffmpeg:concat 圖片→fps/scale/fade + 音軌(延後 intro、補尾、截總長)→ NVENC
        ff = _ffmpeg_exe()
        codec, enc_args = _pick_codec(ff)
        intro_ms = int(mv.INTRO_DURATION * 1000)
        # 同 _seg_clip 的封面修法:tpad 墊片藏黑幀、trim 掉墊片,輸出 t=0 保證有內容(見上方註解)。
        # 完播工程(2026-07-14):此「靜態切片」路徑原本整張卡片凍結到字幕换完才切下一張——
        # 實測 ffmpeg scene detection(gt(scene,0.3))量到單片可以連續 20-40 秒零場景變化,
        # 只有底部字幕小範圍在動,人眼會覺得「畫面死掉」(完播殺手)。b-roll/動畫路徑本來就
        # 有 Ken Burns 緩推鏡(_seg_clip 的 zoompan),但這條「靜態」路徑實測是目前多數 Shorts
        # 實際落地的路徑,之前完全沒有鏡頭動態。改法:呼吸式 zoompan(正弦波在 1.0~1.035 間
        # 用「脈衝式」推鏡(每 3.5 秒在 1.0/1.045 兩級之間跳一次,不是連續正弦緩推)——連續緩推
        # 幅度小到 ffmpeg 自己的 scene 偵測都量不到(實測 sin 波驗證過,gt(scene,0.1) 幾乎抓不到
        # 任何幀,因為連續漸變沒有「瞬間跳動」);改成離散階梯跳動,每 3.5 秒一次真正的構圖跳動,
        # 才會被 gt(scene,0.3) 判定為真正的畫面變化,同時人眼也感受得到「畫面在動」。
        # 只加一段 filter,不多一次編碼、不多幀,渲染時間不變;唯一一次 ffmpeg pass 內完成。
        #
        # 二次覆查(2026-07-15,獨立驗收判定完播節奏修復沒真正落地後複查):上面這段
        # 「純 zoompan 脈衝」的舊註解說「才會被 gt(scene,0.3) 判定為真正的畫面變化」,
        # 但這句話從沒被實測驗證過——用 ffmpeg select='gte(scene,0)',metadata=print:
        # key=lavfi.scene_score 直接量,純 zoompan(不論振幅多大)對這類大面積深色卡片
        # 背景只能量到 ~0.044,連 gt(scene,0.1) 都量不到,更別說 0.3(根因跟 _seg_clip
        # 那條完全一樣:純幾何縮放對 histogram/整體色彩為主的 scene 偵測本來就不敏感)。
        # 改法同 _seg_clip:疊一段極短暫的亮度脈衝(eq=eval=frame:brightness,同一 3.5
        # 秒週期、同相位,這裡是單一 ffmpeg pass 處理整支已 concat 的片,'t' 本來就是
        # 全片絕對時間、不用另外算 offset)。實測 0.08 亮度脈衝穩定量到 0.20~0.29,
        # 對 gt(scene,0.1) 有 2 倍安全margin。
        vf = (f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
              f"zoompan=z='1.0+0.045*mod(floor(on/({fps}*3.5)),2)':d=1:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},"
              f"eq=eval=frame:brightness='0.08*mod(floor(t/3.5)\\,2)',"
              f"tpad=start_duration=0.35:start_mode=clone,fade=t=in:st=0:d=0.5,"
              f"trim=start=0.35,setpts=PTS-STARTPTS,format=yuv420p")
        af = f"adelay={intro_ms}:all=1,apad,atrim=0:{total:.3f}"
        # 配樂床:有 BGM 素材才混(人聲為主,BGM≈-20dB);缺素材完全照舊走單軌
        bgm = _pick_bgm(getattr(slug_paths, "slug", "") or "")
        audio_inputs = ["-i", str(slug_paths.audio)]
        if bgm:
            audio_inputs = ["-i", str(slug_paths.audio), "-stream_loop", "-1", "-i", str(bgm)]
            filt_a = (f"[1:a]{af}[voice];[2:a]volume=0.10,atrim=0:{total:.3f}[bgm];"
                      f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        else:
            filt_a = f"[1:a]{af}[a]"
        cmd = [
            ff, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_txt),
            *audio_inputs,
            "-filter_complex", f"[0:v]{vf}[v];{filt_a}",
            "-map", "[v]", "-map", "[a]",
            "-c:v", codec, *enc_args,
            "-c:a", "aac", "-b:a", "128k",
            "-t", f"{total:.3f}",
            "-movflags", "+faststart",
            str(slug_paths.out_mp4),
        ]
        print(f"[ffmpeg後端] 編碼器={codec}  切片={len(timeline)}段  字幕={len(cues)}  "
              f"BGM={'有' if bgm else '無'}  總長={total:.1f}s")
        # P0 止血(2026-07-13)：成品長度必須 ≥ 旁白長度(0.95 容錯)，否則 fail-closed 不留壞檔——
        # 根因是 04_0056 事故：舊版 min_dur 預設只查 >=1.0s，任何遠比旁白短的斷尾片都能通過驗證、
        # 被搬進正式路徑、甚至發布到 YouTube(旁白 218.9s、成品僅 61.7s 也照樣 PASS)。
        ok = _encode_and_validate(cmd, slug_paths.out_mp4, tmp_dir, stage="靜態", timeout=600,
                                  min_dur=max(1.0, total * 0.95))
        if ok:
            mb = slug_paths.out_mp4.stat().st_size / (1024 * 1024)
            print(f"[ffmpeg後端] ✅ 完成 {slug_paths.out_mp4.name}（{mb:.1f} MB）")
        else:
            print("[ffmpeg後端] 兩次都失敗,交回備案", file=sys.stderr)
        return ok
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="純 ffmpeg 渲染後端(本機 GPU 主力)")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--audio", default=None)
    ap.add_argument("--script", default=None)
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--width", type=int, default=mv.DEFAULT_WIDTH)
    ap.add_argument("--height", type=int, default=mv.DEFAULT_HEIGHT)
    ap.add_argument("--fps", type=int, default=mv.DEFAULT_FPS)
    ap.add_argument("--no-subtitles", action="store_true")
    args = ap.parse_args(argv)

    branding = mv.load_branding(Path(args.config) if args.config else None)
    slug_paths = mv.resolve_slug_paths(args)
    ok = render(slug_paths, branding, width=args.width, height=args.height,
                fps=args.fps, no_subtitles=args.no_subtitles)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
