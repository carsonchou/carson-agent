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


def _encode_timeout(total_sec: float) -> int:
    """依成品長度換算渲染逾時。**不要改回固定值。**

    2026-08-04:逾時原本寫死 600s,不看片長。長片產稿接上 OpenRouter 後 max_tokens 從
    2800 還原成 7000,稿子變長 → 片長從約 8 分鐘變成 **11.8 分鐘**,600s 只剩 0.85 倍
    實時,第一支就撞逾時(L_大家說網格穩賺…)。片長會隨稿子浮動,固定值必然遲早不夠。
    給 1.5 倍實時 + 240s 開銷,並保底 600s(短片維持原行為)。
    """
    return int(max(600, total_sec * 1.5 + 240))


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
    # 🔴 2026-07-28 連續運鏡後的編碼調整:舊設定 `-preset ultrafast -b:v 3500k` 是為「純靜態字卡」
    # 選的(靜止幀壓縮到幾乎不花位元,實測舊片只有 1279kb/s)。改成連續運鏡後每一幀都不同,
    # ultrafast(壓縮效率最差的檔位)直接把 3500k 吃滿 → 同一支 9m34s 片 92MB 暴增到 246MB,
    # 每日 5 支 = 1.2GB 上傳,會拖慢/卡住上架排程。
    # 改用品質導向(CRF)+ 效率合理的 preset:同畫質下位元率大幅下降,且位元率隨內容自適應
    # (慢速圖表段自動省、資訊密集段自動給),maxrate/bufsize 封頂避免尖峰爆量。
    # veryfast 相對 ultrafast 編碼慢一些但壓縮效率高得多;此管線瓶頸在合成不在編碼,可接受。
    _q = ["-preset", "veryfast", "-crf", "21", "-maxrate", "5000k", "-bufsize", "10000k"]
    forced = os.environ.get("MV_CODEC", "").strip()
    if forced:
        if "nvenc" in forced:
            return forced, ["-preset", "p4", "-b:v", "3500k", "-pix_fmt", "yuv420p"]
        return forced, _q
    return "libx264", _q


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
                   force_key=None, video_ticker=None, variant=0):
    """產一段的卡片 PNG(concept → 字卡 二級降級;不再退 rng K線卡)。回傳 PNG 路徑。
    force_key 有值＝硬指定概念圖(用於強制回測對比 beat)。
    video_ticker：整片主題代號,傳給 concept 當 fallback,讓沒點名代號的段落也能畫整片的真圖。"""
    card = None
    try:
        card = mv.render_concept_card(
            width, height, heading=seg.heading or "", narration=seg.narration,
            watermark=watermark, accent=accent, seed=f"{vid_seed}_{i}",
            dest=tmp_dir / f"concept_{i:02d}.png", default_key=video_concept, force_key=force_key,
            fallback_ticker=video_ticker, variant=variant)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 概念圖失敗,退 K 線卡:{exc}", file=sys.stderr)
        card = None
    # ⚠️ 2026-07-17 誠信:concept 回 None(拿不到真資料/主題無對應圖)時,**不再退 render_candle_card**。
    #   K線卡的底圖是 make_video._render_candles_strip = `rng.randn().cumsum()` 隨機漫步(見該處
    #   「價格隨機walk」註解)—— 那是一張滿版、看起來像真行情的假 K 線圖。concept 剛因為「沒有真資料」
    #   而不畫,若立刻退到另一張亂數假圖,等於 fail-safe 是假的(這正是 concept_visuals.py:47 記的坑)。
    #   改退純文字卡(render_card_image:標題+品牌底,資訊都在、不宣稱任何行情),
    #   且傳 decor_line=False 連底圖那條 rng 裝飾走勢線也一併關掉(見下方呼叫)——徹底零 rng 假圖。
    if card is None:
        # 三級降級的最後一級本身也要防呆:字卡理論上最不該失敗,但若真的失敗(如字型載入炸掉),
        # 不能讓整個 render() 崩潰而拿不到 _encode_and_validate 的重試/不留壞檔機制。
        try:
            # decor_line=False:這是 concept 無真資料才退下來的卡,底圖不擺 rng 假走勢線(誠信)。
            card = mv.render_card_image(
                width, height, big_text=seg.heading or "", small_text="",
                watermark=watermark, dest=tmp_dir / f"card_{i:02d}.png", accent=accent,
                decor_line=False)
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
    # 挑「最衝擊的短數字」當主視覺——**只認帶『結果單位』的數字**。
    #
    # ⚠️ 2026-07-17 誠信修:舊版抓不到 %/倍/萬 就退而用 `\d+\s*[次天年]|\d{2,}`,
    #    那是**無單位的裸數字撈取**,撈到什麼就把什麼演成「砸臉大紅字 + 你猜是多少？」:
    #      · 「已經拆完 14 集」→ 巨大紅色「14」壓在上升淨值曲線上 = 把**集數**演成績效;
    #      · 「0050定期定額…」→ `\d{2,}` 會撈到**股票代號 0050** 當衝擊數字。
    #    根因與 fact_pool 無單位池同一個:**數字沒有單位就沒有意義**,撈到的東西不是 punchline。
    #    判準(2026-07-17 定):集數不是績效,它就不該長得像績效 → 方向錯的那邊(膨脹)。
    # 修法:只有帶「結果單位」(%/倍/萬/成/億)的數字才配當衝擊主視覺;
    #      撈不到 → 回 None → **不畫這張卡**(fail-safe:寧可少一張卡,不要把集數演成報酬)。
    cands = re.findall(r'\d+\.?\d*\s*[%倍萬]', title)
    if cands:
        num = max(cands, key=lambda s: float(re.findall(r'[\d.]+', s)[0])).replace(" ", "")
    else:  # 阿拉伯抓不到→抓中文數字結果詞(三倍/九成/一萬);**不含**年/天/次(那是區間與次數,不是結果)
        m = re.search(r'[一二三四五六七八九十百千兩]+\s*[%倍萬成億]', title)
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
    # ⚠️ 2026-07-17:舊版 `[:14]` 是**硬切字元**,把「台股真相實驗室｜已經拆完 14 集」
    #    切成「台股真相實驗室｜已經拆完 1」——螢幕上印的是**錯的數字**(1 vs 真實 14)。
    #    切字 bug 一旦切在數字中間就直接變成假話,不是排版瑕疵。
    #    修法:①先在「｜」這種天然分隔處收尾(比硬切乾淨);②真的還太長才切,且**絕不切在
    #    數字中間**;③字級本來就會自適應縮到不爆框(見下),所以限長只是最後一道保險。
    hook = re.sub(r'#\S+', '', title).strip("？?，,。、 ")
    hook = re.split(r'[，,。]', hook)[0].strip()
    _LIM = 16
    if len(hook) > _LIM:
        for _sep in ("｜", "|"):
            if _sep in hook:
                _head = hook.split(_sep)[0].strip()
                if _head:
                    hook = _head
                break
    if len(hook) > _LIM:
        _cut = _LIM
        while _cut > 1 and hook[_cut - 1].isdigit() and hook[_cut].isdigit():
            _cut -= 1  # 退到數字串邊界,不把 14 切成 1
        hook = hook[:_cut].strip()
    hook = hook or "你知道嗎"
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
        # 🔴 2026-07-28:b-roll 分支的亮度方波一併移除(獨立審查指出電影感修復漏了這條)。
        # 舊碼疊 `brightness='0.08*mod(floor((t+seg_start)/3.5),2)'` = 每 3.5 秒整段畫面閃一階,
        # 目的同樣只是為了讓 scene detection 量得到分數(而沒有任何閘門在讀那個分數)。
        # 若只修卡片路徑,混合片會變成「卡片段平滑漂移 / b-roll 段每 3.5 秒閃一下」的割裂感,
        # 比全片一致地閃更糟。b-roll 是**實拍影片本來就在動**,不需要外加節奏,直接拿掉脈衝即可。
        base = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p,"
                f"trim=0:{dur:.3f},setpts=PTS-STARTPTS")
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
        # 🔴 2026-07-28 電影感修復(Carson:「不要一幕一幕的出現,我要像電影不是投影片」):
        # 舊碼同下方靜態切片路徑,是**方波**:zoom 在 1.0/1.07 兩級硬跳 + 每 3.5 秒亮度閃一階。
        # 上面那句「人眼觀感是呼吸感不是閃爍」從來沒被人眼驗證過(整段推導全繞著 scene_score
        # 這個**沒有任何閘門在讀**的指標),而觀眾實際看到的就是每 3.5 秒跳一格投影片。
        # 改成連續運鏡:三條不同週期(20/27/33s,互質故軌跡長時間不重複)的正弦疊加=有機緩慢
        # 漂移。相位一律用「整支片絕對時間」((on+_start_frame)/fps)——每個 _seg_clip 是獨立
        # ffmpeg 行程,相位若各自歸零,concat 後會在每個段邊界看到運鏡瞬間跳回原點(鋸齒)。
        # 亮度脈衝(beq)整條移除:那是閃爍源,不是呼吸感。渲染成本不變(同一條 filter)。
        _start_frame = int(round(seg_start * fps))
        _gt = f"((on+{_start_frame})/{fps})"   # 全片絕對時間(秒)
        # 🔴 2026-07-28 二修:同下方靜態路徑,第一版振幅開太大會把燒入的浮水印切掉
        # (make_video.py:1096 浮水印右/下緣在 0.97,只留 3% 邊界)。
        # z ∈ [1.016, 1.036] → 最大裁切 (1-1/1.036)/2 = 1.74%;位移 0.5%/0.4% → 最壞 2.24% < 3% ✓
        zexpr = f"1.026+0.010*sin(2*PI*{_gt}/20)"
        base = (f"[0:v]scale={width*2}:{height*2}:flags=lanczos,"
                f"zoompan=z='{zexpr}':d={frames}:"
                f"x='iw/2-(iw/zoom/2)+(iw*0.005)*sin(2*PI*{_gt}/27)':"
                f"y='ih/2-(ih/zoom/2)+(ih*0.004)*cos(2*PI*{_gt}/33)':s={width}x{height}:fps={fps},"
                f"setsar=1,format=yuv420p")
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


def _narration_seg_starts(segments, cues, audio_duration):
    """各段旁白在音軌上的真實起點(秒),供卡片邊界對齊旁白(2026-08-12 留存工程)。

    對映:每段旁白前 8 字去字幕 cues 找包含它的那句的 start(字幕本來就跟 TTS 時間戳
    對齊,是現成的真實時間軸)。對不到的段用相鄰錨點線性插值。
    fail-open 條件(回 None=呼叫端走原本 per_seg 等分,行為與舊版一致):
      ·段數 <2 或無 cues ·錨到的段少於一半 ·邊界洞在頭尾 ·相鄰邊界 <1.5s(對映錯亂)
      ·最後一段起點貼到音軌尾(明顯錯位)。"""
    try:
        n = len(segments)
        if n < 2 or not cues:
            return None
        starts = [0.0] + [None] * (n - 1)
        for i in range(1, n):
            probe = (segments[i].narration or "").strip()[:8]
            if len(probe) < 6:
                continue
            for cu in cues:
                if probe in (cu.text or ""):
                    starts[i] = float(cu.start)
                    break
        idxs = [i for i, t in enumerate(starts) if t is not None]
        if len(idxs) < max(2, (n + 1) // 2):
            return None
        for i in range(n):
            if starts[i] is None:
                prev = max((j for j in idxs if j < i), default=None)
                nxt = min((j for j in idxs if j > i), default=None)
                if prev is None or nxt is None:
                    return None
                starts[i] = starts[prev] + (starts[nxt] - starts[prev]) * (i - prev) / (nxt - prev)
        for a, b in zip(starts, starts[1:]):
            if b <= a + 1.5:
                return None
        if starts[-1] >= float(audio_duration) - 1.5:
            return None
        return starts
    except Exception:  # noqa: BLE001
        return None


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
                    # 🔴 2026-07-30 拿掉 sub_label=「他吹的神話」。payload 是 detect_fx 從
                    # **本片自己的 heading/narration** 用 _MYTH_RE 抓的第一個帶 %／倍 的數字,
                    # 而本頻道旁白全由自家 fact_key 產生 → 那是**我們自己算出來的數字**,
                    # 掛上「他吹的神話」等於發明一個講過這句話的人,再把自己的真數據劃掉。
                    # (縮圖同型事故有照片存證:自家回測 824%／「少賺58%」被印成「他說能賺」,
                    #  見 commit f0e4138。)紅刀/轉紅的視覺保留——那表達的是「這說法被推翻」,
                    # 不是「某人講過」;但指名道姓的標籤不能由產線自己憑空生出來。
                    clip = afx.number_smash_clip(payload, dur=per_seg, subs=subs, width=width, height=height,
                                                 fps=fps, accent=accent, seed=seed, tmp_dir=tmp_dir, idx=i + 1,
                                                 mascot_png=mp, watermark_png=wm_png, debunk=is_debunk)
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
        ok = _encode_and_validate(cmd, slug_paths.out_mp4, tmp_dir, stage="動畫", timeout=_encode_timeout(total),
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
    # 🔴 2026-08-02 健檢必須放在**這裡**,不能放在 main()。
    # 我第一版把它加在 main()(命令列入口),結果完全沒生效——因為產線是
    # `make_video.py:2659` **直接呼叫 render()**,根本不經過 main()。
    # 證據:加了守門之後同一支壞片照樣再撞一次 600s 逾時。
    # 這正是本專案反覆出現的「同一規則多份實作/修在沒人走的路上」——這次是我自己犯。
    # ⚠️ 回傳 False 的語意在這裡剛好對:呼叫端會把它當「此片不適用 ffmpeg 路徑」,
    #    但 make_video 的 moviepy 備案是**逐幀 PIL(float32 1080x1920)**,更吃記憶體,
    #    實測那支壞片掉進備案後直接噴 MemoryError。所以**備案端也要擋**(見 make_video)。
    if not _speech_rate_sane(slug_paths):
        return False
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
    # 🔴 2026-07-28 解封 video_ticker(舊註解的啟用條件已經成立,但沒人回來重新評估):
    # 舊註解說「plumbing 已備妥但刻意不啟用,因為多段同 concept 會畫出同一張圖 → 加重同圖輪播;
    # **要啟用得配合『每段不同視圖(漸進揭露)』的 ②**」。而 ② 早已上線(design_system
    # progressive_reveal=True),前提條件滿足了,封印卻留著。
    # 實測代價比想像大得多:抽幀顯示 9 幀有 3 幀**完全空白**(只有標題+字幕,整片無視覺)——
    # 因為 `_drawdown`/`_dca` 這類圖沒有真資料就 return None → 退純文字卡。而 fallback_ticker
    # 是它們拿到真資料的唯一途徑(該段文字沒點名代號時)。實測同一段:傳 "2376" → 有圖;
    # 傳 None → 空白卡。**空白卡比「相似的圖」糟得多**,這個取捨在漸進揭露上線後已經反轉。
    # 代號取自**標題**(整片主題;個股體檢的標題一定帶標的與代號),不是旁白——旁白順口提到
    # 別檔(如比較用的 0050)不該蓋掉整片主題;段內文字若真的點名代號,resolve_ticker 仍優先。
    video_ticker = None
    try:
        if getattr(mv, "_concept", None) is not None:
            video_ticker = mv._concept.resolve_ticker(title or "")
    except Exception:  # noqa: BLE001 — 取不到就維持 None(退回舊行為,不影響渲染)
        video_ticker = None
    if getattr(mv, "_concept", None) is not None:
        try:
            video_concept = mv._concept.classify(
                title + " " + " ".join(s.heading for s in segments if s.heading))
        except Exception:  # noqa: BLE001
            video_concept = None
    # 🔴 2026-07-28:整片概念抓不到、但有真實標的時,退到 "trend"(現在的 _trend 在旁白沒有明確
    # 方向時會畫**完整真實走勢**、不挑區間也不做方向宣稱)。實測有一支 0056 vs 00878 的片,
    # 標題與所有小標都不含任何概念關鍵字 → video_concept=None → 5 段有 4 段完全空白。
    # 「認不出主題」不該等於「整支片沒有畫面」——把該檔的真實歷史攤開是最保守的誠實選項。
    if video_concept is None and video_ticker:
        video_concept = "trend"

    tmp_dir = Path(tempfile.mkdtemp(prefix="carson_ff_"))
    try:
        # 1) 每段卡片 PNG
        # 🔴 2026-07-28 同圖輪播防治(解封 video_ticker 的必要配套):整片統一用主題標的之後,
        # 兩個都被判成同一種圖(如都是 drawdown)的段落會畫出**一模一樣**的圖。
        # 先算出每段的概念 key,同一個 key 第 n 次出現就給 variant=n —— concept_visuals 會據此
        # 改看不同時間窗(完整歷史 → 近 45% → 近 25%),讓同一檔的同種圖呈現「長期全景→近期特寫」。
        _seen_key: dict = {}
        _variants = []
        for seg in segments:
            try:
                _k = (mv._concept.classify((seg.heading or "") + " " + (seg.narration or ""))
                      or video_concept) if getattr(mv, "_concept", None) else None
            except Exception:  # noqa: BLE001
                _k = None
            _n = _seen_key.get(_k, 0) if _k else 0
            _variants.append(_n)
            if _k:
                _seen_key[_k] = _n + 1
        seg_cards = [
            _make_seg_card(seg, i, width=width, height=height, watermark=watermark,
                           accent=accent, vid_seed=vid_seed, video_concept=video_concept,
                           tmp_dir=tmp_dir, video_ticker=video_ticker, variant=_variants[i])
            for i, seg in enumerate(segments)
        ]
        # ② 漸進揭露(PROGRESSIVE_REVEAL)重合成用:記住每段疊了哪些 overlay,好在段內逐切片
        # 重畫「揭露到不同程度」的真資料圖時,把同一組 HUD 條/吉祥物原封不動再疊回去(段內這兩者不變)。
        seg_hud_png = [None] * len(seg_cards)
        seg_mascot_path = [None] * len(seg_cards)

        # 1.2)【已拆除 2026-07-17·誠信】「強制回測對比 beat」——不要重建。
        # 舊行為：每支長片都硬插一張 concept_visuals._backtest 的「回測期 | 驗證期」split-chart，
        # 字卡寫「真正能信的是樣本外」。三個致命點：
        #   1. **我們根本沒有樣本外驗證**(tw_facts_engine 全是全期間/近10年/固定崩盤區間)，
        #      這張圖是在宣稱**一個我們沒有的嚴謹度**。
        #   2. 曲線是 rng.randn() 亂數、漲跌 rng.rand()>0.5 擲骰 —— 純虛構。
        #   3. 「強制、每支片至少一次」→ 這個假宣稱是**全頻道規模**的。
        # 判準：方向是自我設限還是膨脹?誠實揭露限制(「我的回測沒算手續費」)最壞只是低報自己；
        # 宣稱沒有的嚴謹度 = 膨脹 = 紅線。**與下方賽跑計分板同 species，同樣整條拆除。**
        # (_backtest 本體也已從 concept_visuals 移除，見該檔拆除說明。)

        # 1.5) 實測EP招牌HUD：烤進段卡（非實測片零影響）
        # A vs B 賽跑計分板已整條拆除（理由見 mv.render_race_split docstring）：畫面印的
        # 百分比是「段落進度 × 0.82」的合成值，與本片數據無關，已發布 46 支中鏢。
        try:
            # 片型判定共用 mv._hud_applies（與 _ep_data_applies 同一份）：非機器人實測片不上 HUD。
            # 逐字稿先讀：第 3 道門檻要看「稿子裡有沒有帳戶」，沒帳戶的片整組 HUD 不上。
            _vt = mv.read_voice_text(slug_paths) or " ".join(s.narration for s in segments if s.narration)
            _is_exp = mv._hud_applies(title or "", getattr(slug_paths, "slug", ""), _vt)
            if _is_exp:
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
                if any(v is not None for v in (_pr, _pct, _bal, _dtot)):
                    for i in range(len(seg_cards)):
                        if not seg_cards[i]:
                            continue
                        frac = (i + 1) / _ns
                        try:
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
                                seg_hud_png[i] = str(hud_png)  # ② reveal 段內重合成用
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
                        seg_mascot_path[i] = _mp  # ② reveal 段內重合成用(同段吉祥物表情不變)
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

        # ② 漸進揭露旗標(PROGRESSIVE_REVEAL,預設關)。**提前算**,因為它會改路徑選擇。
        # 為什麼要改路徑:長片在 render_watcher.render_one() 會設 PEXELS_API_KEY → 走下面的
        # _render_with_broll;而長片 per_seg>30 讓 b-roll「一段 footage 都抓不到」(閘門 per_seg<=30
        # 永遠 False),只是把 seg_cards[i] 當**一張靜態卡 Ken Burns 播 130s** —— 這正是 Carson
        # 「同一張圖播兩分鐘」的病灶本身,且 b-roll 成功就 return、根本到不了下面能漸進揭露的靜態切片。
        # 所以 reveal 開時**刻意跳過 b-roll**,讓長片落到靜態切片路徑吃到段內漸進揭露。
        # (且「真資料圖表 > 通用實拍空景」本來就是本頻道護城河,長片跳過 b-roll 無損失。)
        # 關=完全走舊路徑(有 PEXELS 照走 b-roll),明天產線零變化。
        _reveal_on = bool(os.environ.get("PROGRESSIVE_REVEAL"))
        if not _reveal_on:
            try:
                _reveal_on = bool(mv._design_system().get("progressive_reveal", False))
            except Exception:  # noqa: BLE001
                _reveal_on = False

        # 2.5) b-roll 路徑:有 Pexels key 且非 reveal 模式 → 走 b-roll(影片段);失敗自動退卡片靜態切片
        pexels_key = os.environ.get("PEXELS_API_KEY", "").strip() or None
        if pexels_key and not _reveal_on:  # 有 pexels key 就全片走 b-roll 動態影片(Carson 要影片、不要靜態卡)
            if _render_with_broll(slug_paths, segments=segments, seg_cards=seg_cards,
                                  intro_png=intro_png, outro_png=outro_png, cues=cues,
                                  audio_duration=audio_duration, per_seg=per_seg, width=width,
                                  height=height, fps=fps, pexels_key=pexels_key, accent=accent,
                                  watermark=watermark,
                                  tmp_dir=Path(tempfile.mkdtemp(prefix="carson_ffb_")), ff=_ffmpeg_exe()):
                return True
            print("[ffmpeg後端] b-roll 路徑未成,改用卡片靜態切片", file=sys.stderr)
        elif pexels_key and _reveal_on:
            print("[ffmpeg後端] PROGRESSIVE_REVEAL 開:跳過 b-roll,走靜態切片(段內漸進揭露真資料圖)", file=sys.stderr)

        # 3) body 切片邊界(段邊界 ∪ 字幕邊界),每片合成「卡+當下字幕」PNG
        # ③b 卡片邊界對齊旁白(2026-08-12 留存工程):字幕逐句跟時間戳對齊,但**卡片邊界**
        # 一直是等分切(k*per_seg)——旁白各段長短不一時,講回撤時畫面還停在基本面圖。
        # 用「段首句在字幕 cues 的真實開始時間」當卡片邊界;錨點不足/亂序 → 回 None,
        # 下面全部走原本的 per_seg 等分(行為與舊版一致,fail-open)。
        seg_starts = _narration_seg_starts(segments, cues, audio_duration)
        if seg_starts is not None:
            print(f"[ffmpeg後端] 卡片邊界對齊旁白:{len(seg_starts)} 段錨到真實時間", file=sys.stderr)

        def _seg_at(t):
            """t 秒落在第幾段 + 該段起訖(對齊模式用真邊界,否則等分)。"""
            if seg_starts is not None:
                import bisect as _bs
                si = min(max(_bs.bisect_right(seg_starts, t) - 1, 0), n - 1)
                s0 = seg_starts[si]
                s1 = seg_starts[si + 1] if si + 1 < n else float(audio_duration)
                return si, s0, s1
            si = min(int(t / per_seg) if per_seg else 0, n - 1)
            return si, si * per_seg, (si + 1) * per_seg

        marks = {0.0, float(audio_duration)}
        for k in range(n + 1):
            if seg_starts is not None:
                _mk = seg_starts[k] if k < n else float(audio_duration)
            else:
                _mk = k * per_seg
            marks.add(min(max(_mk, 0.0), audio_duration))
        for cu in cues:
            marks.add(min(max(cu.start, 0.0), audio_duration))
            marks.add(min(max(cu.end, 0.0), audio_duration))
        bounds = sorted(marks)

        # ② 子段切分／漸進揭露(_reveal_on 已於 b-roll 決策前算好)。
        # 病灶:一段 per_seg≈130s,段內每個字幕切片都拿**同一張** seg_cards[seg_idx],
        #   只有字幕在變 → Carson 講的「幾張圖輪著播、同一張圖播兩分鐘」。
        # 修法:開關打開時,依「切片在段內的相對位置」把真資料圖**漸進揭露**(講到 2018 就畫到
        #   2018、講到 464% 就畫到 464%),段內從 1 張變 8 張、張張不同且切題。
        # **關=完全走舊路徑**(base=seg_cards[seg_idx],bucket 恆 -1,輸出 byte-identical)。
        # fail-safe:reveal 圖只來自真 CSV(render_concept_card 拿不到真資料→回 None)→退回 seg_cards
        #   原卡,**絕不畫亂數**;文字卡段落 render_concept_card 也回 None → 一樣退原卡,不受影響。
        _REVEAL_BUCKETS = 8
        reveal_base_cache = {}   # (seg_idx, bucket) -> png 路徑 或 None(該段非真資料圖,退回 seg_cards)

        def _reveal_base(seg_idx, bucket):
            """回傳該段揭露到 bucket 級別的底卡(concept@reveal + 同段 HUD/吉祥物重合成);
            該段不是真資料圖(concept 回 None)→ 回 None,呼叫端退回 seg_cards[seg_idx]。"""
            ck = (seg_idx, bucket)
            if ck in reveal_base_cache:
                return reveal_base_cache[ck]
            out = None
            try:
                seg = segments[seg_idx]
                # 🔴 2026-07-28:舊式 (bucket+1)/N 讓第一格只揭露 1/8 = 12.5%,26 年的走勢只畫出
                # 最左邊約 3 年 → **每一段開頭都是一條細線、畫面近乎空白**(抽幀實測第 1、9 幀都是)。
                # 漸進揭露的用意是「講到哪畫到哪」,不是「開場什麼都沒有」。改成從 35% 起跳:
                # 一開場就有看得懂的圖,之後仍持續長到 100%(生長感保留,只是不再從近乎零開始)。
                r = 0.35 + 0.65 * (bucket + 1) / _REVEAL_BUCKETS
                card = mv.render_concept_card(
                    width, height, heading=seg.heading or "", narration=seg.narration,
                    watermark=watermark, accent=accent, seed=f"{vid_seed}_{seg_idx}",
                    dest=tmp_dir / f"reveal_{seg_idx:02d}_{bucket}.png",
                    default_key=video_concept, fallback_ticker=video_ticker, reveal=r)
                if card is not None:
                    bimg = Image.open(str(card)).convert("RGBA")
                    if seg_hud_png[seg_idx]:            # 疊回同段那張 HUD 條(段內不變)
                        try:
                            bimg.alpha_composite(Image.open(seg_hud_png[seg_idx]).convert("RGBA"))
                        except Exception:  # noqa: BLE001
                            pass
                    if seg_mascot_path[seg_idx]:        # 疊回同段吉祥物表情(段內不變)
                        try:
                            bimg = mv.paste_mascot(bimg, seg_mascot_path[seg_idx], position="br", scale=0.16)
                        except Exception:  # noqa: BLE001
                            pass
                    op = tmp_dir / f"revealbase_{seg_idx:02d}_{bucket}.png"
                    bimg.convert("RGB").save(str(op))
                    out = str(op)
            except Exception:  # noqa: BLE001 - 任何失敗都退回 seg_cards,渲染永不因 reveal 崩
                out = None
            reveal_base_cache[ck] = out
            return out

        sub_cache = {}
        timeline = [(intro_png, mv.INTRO_DURATION)]  # (png, dur)
        for a, b in zip(bounds, bounds[1:]):
            dur = b - a
            if dur < 0.04:
                continue
            mid = (a + b) / 2.0
            seg_idx, _s0, _s1 = _seg_at(mid)
            base = seg_cards[seg_idx]
            bucket = -1
            if _reveal_on and (_s1 - _s0) > 0:
                pos = (mid - _s0) / (_s1 - _s0)              # 段內相對位置 0..1
                bucket = min(max(int(pos * _REVEAL_BUCKETS), 0), _REVEAL_BUCKETS - 1)
                rb = _reveal_base(seg_idx, bucket)
                if rb is not None:                           # 只有真資料圖段落才換;否則保留原卡
                    base = rb
            cue = next((c for c in cues if c.start <= mid < c.end), None)
            png = base
            if cue is not None:
                key = (seg_idx, bucket, cue.text)  # bucket 進 key:同段不同揭露級別的字幕卡要分開快取
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
        # 🔴 2026-07-28 電影感修復(Carson:「不要一幕一幕的出現,我要像電影不是投影片」):
        # 舊碼是**方波**——zoom `mod(floor(on/(fps*3.5)),2)` 在 1.0/1.045 兩級間硬跳、外加
        # `brightness 0.08*mod(floor(t/3.5),2)` 每 3.5 秒整張畫面閃一階。那不是運鏡,是每 3.5 秒
        # 「跳一格投影片+閃一下」,正是觀眾說的「一幕一幕的出現」。它當初純粹是為了讓
        # ffmpeg scene detection(gt(scene,0.3))量得到數字而加的——**而全產線沒有任何閘門在讀
        # 那個分數**(已 grep 確認 audit_video/quality_score 都不檢查),等於為了討好一個沒人看的
        # 指標,犧牲了人眼唯一看得到的東西。教訓同 memory「指標量像素不量畫面,只能人眼驗」。
        # 改成真正的連續運鏡:三條**不同週期**的正弦(20s 推拉 / 27s 橫移 / 33s 直移)疊加,
        # 週期互質故軌跡長時間不重複=有機的緩慢漂移(慢推鏡+微幅浮動),永遠不跳、不閃。
        # zoom 基線 1.06 保證恆有裁切餘裕(最低 1.035),位移振幅 (1.0%/0.8%) 遠小於餘裕故不會被
        # 夾邊而卡住。t 用 on/fps 算(zoompan 保證支援 on);此 filter 作用在 concat **之後**的整條
        # 串流,故 on 是全片絕對幀號——運鏡跨越所有切片邊界連續,不會每片重來(那又會變鋸齒跳)。
        # 成本:同樣一次 ffmpeg pass、同樣一個 filter,渲染時間不變。
        # 🔴 2026-07-28 二修(獨立審查抓到):第一版 z 基線 1.06(峰值 1.085)每邊裁掉
        # (1-1/1.085)/2 = **3.9%**,再加位移 1.0% = 4.9%;而 make_video.py:1096 把燒入的浮水印
        # 右/下緣放在 **0.97W / 0.97H**(只留 3% 邊界)→ 實測重渲成片在 zoom 峰值時
        # 「量化阿森｜Carson Quant」被切成「…Carson Quan」,每 20 秒週期性切一次品牌標。
        # 舊的方波 z∈{1.0, 1.045} 反而從不裁到它——我把運鏡做連續的同時把振幅開太大了。
        # 重算預算:最大裁切 (1-1/z_max)/2 + 位移振幅 **必須 < 3%**。
        # z ∈ [1.016, 1.036] → 最大裁切 1.74%;位移 0.5%/0.4% → 最壞 2.24% < 3% ✓
        # 代價是運鏡幅度變小(2% 縮放而非 8.5%),但那本來就該是「緩慢漂移」不是「推鏡」,
        # 而且真正治好投影片感的是**連續**(去掉每 3.5 秒的跳與閃),不是幅度大。
        _t = f"(on/{fps})"
        # ③c 換卡拉遠 punch(2026-08-12 純ffmpeg動畫v1):每個卡片邊界做 0.45s 的
        # 「拉遠再回」——讓換卡是一個有重量的剪輯 beat,不是幻燈片翻頁。方向用**拉遠**
        # 不用推近:推近會瞬間超出 3% 裁切預算切到浮水印(2026-07-28 血案);拉遠時裁切
        # 只會更少,永遠安全。z 下限 clamp 1.002(zoompan z<1 非法)。邊界用 ③b 的真實
        # 旁白時間(對齊模式),退化時用等分;最多 8 個 punch 項防表達式爆長。
        _pz = []
        _bnds = ([mv.INTRO_DURATION + s for s in seg_starts[1:]] if seg_starts is not None
                 else [mv.INTRO_DURATION + k * per_seg for k in range(1, n)])
        for _b in _bnds[:8]:
            _pz.append(f"0.022*max(0,1-abs({_t}-{_b:.2f})/0.45)")
        _punch = ("-(" + "+".join(_pz) + ")") if _pz else ""
        # 引號內逗號受 filtergraph 引號保護,不需反斜線跳脫(跳脫反而把 \\ 塞進運算式)
        _zexpr = f"max(1.002,1.026+0.010*sin(2*PI*{_t}/20){_punch})"
        vf = (f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
              f"zoompan=z='{_zexpr}':d=1:"
              f"x='iw/2-(iw/zoom/2)+(iw*0.005)*sin(2*PI*{_t}/27)':"
              f"y='ih/2-(ih/zoom/2)+(ih*0.004)*cos(2*PI*{_t}/33)':s={width}x{height}:fps={fps},"
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
        ok = _encode_and_validate(cmd, slug_paths.out_mp4, tmp_dir, stage="靜態", timeout=_encode_timeout(total),
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


# 🔴 2026-08-02 渲染前的語速健檢。起因是一支個股體檢片(玉晶光3406)連續兩次撞 600s 渲染逾時,
# 追下去發現**稿子完全正常、壞的是語音**:
#     全體長片語速中位 **312 中文字/分**(n=26,正常範圍 279~333)
#     那支                **175 字/分** ← 同樣字數被拉成 1.8 倍長的音檔(3,412 字 → 19.5 分鐘)
# 它的稿長 3,412 字落在正常區間內(中位 2,768、最大 3,741),所以**任何「稿長上限」都攔不到它**
# ——我一開始就是照那個方向猜,查了才發現猜錯。
# 代價是實打實的:渲染器為一個壞掉的音檔燒掉兩次 600 秒逾時才放棄,而且沒有任何一層說得出原因
# (只會看到「逾時」,看不到「音檔本來就不對」)。
# 這裡不去追那個難重現的 TTS bug,而是**在燒機器時間之前先擋**,並且把原因講清楚。
_RATE_MIN = 200.0   # 中文字/分。比實測最慢的正常片(279)再放寬約 3 成,只抓真正離譜的
_RATE_MAX = 460.0   # 上限同樣留餘裕:真的講太快也是壞掉(音檔被截斷/加速),一樣不該進渲染


def _speech_rate_sane(slug_paths) -> bool:
    """比對旁白字數與音檔長度,語速離譜就擋下(回 False = 不要渲染)。

    fail-**open** 是刻意的:任何一項資料缺失(沒有 voice.txt、沒有 mp3、探測失敗、字數太少)
    一律放行。這道檢查的目的是攔「明確壞掉」的音檔,不是多加一道會誤殺的關卡——
    渲染本身還有 min_dur / 旁白截斷 等既有 fail-closed 防線在後面守著。
    """
    try:
        mp3 = getattr(slug_paths, "audio", None) or getattr(slug_paths, "mp3", None)
        voice = getattr(slug_paths, "voice", None)
        if voice is None:
            voice = Path(str(getattr(slug_paths, "out_mp4", ""))).with_suffix("")
            voice = voice.parent / (voice.name + ".voice.txt")
        if not mp3 or not Path(mp3).exists() or not Path(voice).exists():
            return True
        import re as _re
        txt = Path(voice).read_text(encoding="utf-8", errors="replace")
        n = len(_re.findall(r"[一-鿿]", txt))
        if n < 500:                      # 太短的片(如系列說明片)語速估計不穩,不判
            return True
        ff = _ffmpeg_exe()
        r = subprocess.run([ff, "-i", str(mp3)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
        if not m:
            return True
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if secs < 30:
            return True
        # 🔴 2026-08-02 追加:旁白稿混入 LLM 內部思考(英文)。
        # 實例:玉晶光3406 那支的 voice.txt 有 3,412 中文字**但 5,174 個英文字母**,內容是
        #   「We need to produce a single paragraph … of 520-620 Chinese characters, as a
        #    script for a long video」「Also we may talk about percentages like annualized
        #    return? Not given. But we can compute…」——**LLM 的思考過程被當成旁白寫進檔案**,
        #   TTS 照著唸,所以 19.5 分鐘。
        # ⚠️ 這條**必須獨立於語速檢查**:當初我只數中文字(3,412,看起來完全正常)就以為稿子沒問題,
        #    差點修錯方向。中文字數這把尺看不見混進來的英文。
        # ⚠️ 更要緊的是:這支是**剛好撞到渲染逾時才被發現**的。稿子短一點就會渲染成功、直接發布,
        #    觀眾會聽到一段英文的 AI 內心獨白。不能靠運氣攔。
        # 門檻 0.35 取得寬鬆:全庫掃描 n=全部 voice.txt,唯一命中的那支比值 1.52,
        #   其餘全部低於 0.35(正常稿只會零星出現 ETF 代號、vs、Fed 這類英文)。
        _en = len(_re.findall(r"[A-Za-z]", txt))
        if _en / max(1, n) > 0.35:
            print(f"[旁白健檢] ✗ 拒絕渲染:{Path(str(voice)).name} 有 {n} 中文字但 "
                  f"**{_en} 個英文字母**(比值 {_en/max(1,n):.2f} > 0.35)。"
                  f"這通常代表 **LLM 的內部思考被寫進旁白稿**(TTS 會照著唸出來)。"
                  f"請重產腳本後再渲染。", file=sys.stderr)
            try:
                from ops import log_ops
                log_ops("旁白健檢", f"⚠️ 擋下混入英文思考的稿({_en}英文/{n}中文):"
                                    f"{Path(str(voice)).stem[:30]}")
            except Exception:  # noqa: BLE001
                pass
            return False

        rate = n / (secs / 60.0)
        if _RATE_MIN <= rate <= _RATE_MAX:
            return True
        print(f"[語速健檢] ✗ 拒絕渲染 {Path(str(mp3)).name}:"
              f"旁白 {n} 中文字 / 音檔 {secs/60:.1f} 分 = **{rate:.0f} 字/分**,"
              f"超出正常區間 {_RATE_MIN:.0f}~{_RATE_MAX:.0f}(全體中位約 312)。"
              f"稿子字數正常時,這代表**語音合成壞了**(過慢多半是長靜音/重複段,過快多半是截斷)。"
              f"請重產語音後再渲染——先擋下來,免得白燒兩次 600 秒逾時。", file=sys.stderr)
        try:
            from ops import log_ops
            log_ops("語速健檢", f"⚠️ 擋下語速異常片({rate:.0f}字/分,正常約312):"
                                f"{Path(str(mp3)).stem[:34]}")
        except Exception:  # noqa: BLE001
            pass
        return False
    except Exception:  # noqa: BLE001  健檢自己壞掉不可以擋住產線
        return True


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
    if not _speech_rate_sane(slug_paths):
        return 1
    ok = render(slug_paths, branding, width=args.width, height=args.height,
                fps=args.fps, no_subtitles=args.no_subtitles)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
