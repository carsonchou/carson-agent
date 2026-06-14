#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py — 量化阿森｜Carson Quant 一鍵端到端編排器
====================================================

頻道：量化阿森｜Carson Quant（faceless 全自動 YouTube 產線）

用途
----
吃「一個影片題目」，依序串接整條產線：

    題目
      │
      ▼  ① generate_script.py   →  output/{slug}.md + output/{slug}.voice.txt
      ▼  ② tts_pipeline.py       →  output/{slug}.mp3
      ▼  ③ make_video.py         →  output/{slug}.mp4
      ▼  ④ upload_youtube.py     →  YouTube 上架

每一階段都用 subprocess 呼叫對應的 .py（同一個 Python 直譯器
``sys.executable``），任何一階段失敗就立刻停止並印出清楚的錯誤，不會
往下硬跑。

安全預設（很重要）
------------------
* ``--stop-after`` 預設 ``video``：**預設「不」自動上傳**，產出 mp4 就停，
  讓 Carson 先人工檢查成片，確認沒問題再手動上傳。
* 要真的上傳，必須明確加 ``--upload``（等同 ``--stop-after upload``）或
  直接 ``--stop-after upload``。
* 上傳隱私預設 ``private``（私人），避免半成品直接公開。
* ``--dry-run`` 會把每一階段都帶上各自的 dry-run 旗標，整條串一遍，
  不花錢、不呼叫付費 API、不上傳，方便驗證流程接線是否正確。

檔名約定（與既有產線對齊）
--------------------------
全線以「題目 → slug」推導各階段檔案路徑，slug 規則與
``generate_script.py`` 的 ``slugify()`` 完全一致（保留中文、移除 Windows
非法字元、空白轉底線、長度上限 60）：

    output/{slug}.md          完整腳本（含視覺指示）
    output/{slug}.voice.txt   純配音稿（給 TTS）
    output/{slug}.mp3         配音
    output/{slug}.mp4         成片

各階段子程式的實際 CLI 介面（已與各子程式對齊；本編排器以 slug 推導路徑為主）
------------------------------------------------------------------------
* generate_script.py <題目> [--config C] [--output DIR] [--no-llm]
      位置參數吃「題目」，內部 slugify() 寫出 output/{slug}.md + .voice.txt。
* tts_pipeline.py    <output/{slug}.voice.txt> [--config C] [--output-dir DIR] [--dry-run]
      位置參數吃 .voice.txt，輸出 output/{slug}.mp3。
* make_video.py      --slug {slug} [--config C] [--output-dir DIR] [--dry-run]
      無位置參數！用 --slug 自行推導 output/{slug}.mp3/.md/.voice.txt → .mp4。
* upload_youtube.py  {slug} [--video PATH] [--output DIR] [--config C] [--privacy P] [--dry-run]
      位置參數是 slug（非路徑），用來找 output/{slug}.md 取標題/描述/標籤；
      --video 明確指定成片 mp4；--privacy 控制 public/unlisted/private。

CLI 用法請見檔案底部 ``build_arg_parser()`` 或執行 ``--help``。

Windows + Python 3.9 相容（from __future__ import annotations）；全程
pathlib、UTF-8；subprocess 呼叫包 try/except；提供 --dry-run。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# 路徑常數
# --------------------------------------------------------------------------- #

# 專案根目錄 = 本檔案所在的 scripts/ 的上一層 (youtube_channel/)
# Windows 主控台預設常是 cp950（Big5），印 emoji / 特殊符號會 UnicodeEncodeError。
# 把 stdout/stderr 重設為 UTF-8（errors="replace" 保底），確保中文與符號都能印。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "channel_config.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

# 各階段子程式（皆位於 scripts/ 下）
GENERATE_SCRIPT = SCRIPTS_DIR / "generate_script.py"
TTS_PIPELINE = SCRIPTS_DIR / "tts_pipeline.py"
MAKE_VIDEO = SCRIPTS_DIR / "make_video.py"
UPLOAD_YOUTUBE = SCRIPTS_DIR / "upload_youtube.py"

# 階段順序（用於 --stop-after 的「跑到哪一階段為止」判斷）
STAGES = ["script", "tts", "video", "upload"]


# --------------------------------------------------------------------------- #
# slug 推導（與 generate_script.py 的 slugify() 完全一致）
# --------------------------------------------------------------------------- #

def slugify(topic: str) -> str:
    """把題目轉成安全的檔名 slug（保留中文，去掉檔名非法字元）。

    這個函式刻意與 ``generate_script.py`` 的 ``slugify()`` 完全相同，
    以確保本編排器推導出的檔名與腳本產生器實際寫出的檔名一致。
    """
    text = unicodedata.normalize("NFKC", topic).strip()
    # 移除 Windows 檔名非法字元 \ / : * ? " < > | 及控制字元。
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text)
    # 空白與多餘符號收斂成底線。
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:60] or "untitled"


# --------------------------------------------------------------------------- #
# 階段執行小工具
# --------------------------------------------------------------------------- #

def run_stage(name: str, cmd: list[str]) -> None:
    """執行單一階段（subprocess）。失敗（含子程式不存在、非零退出）就拋例外。

    參數
    ----
    name:
        階段名稱（顯示用，例如 "① 產腳本"）。
    cmd:
        完整命令列 list（第一個元素已是 sys.executable）。

    例外
    ----
    RuntimeError:
        子程式回傳非零退出碼，或無法啟動（FileNotFoundError/OSError）時。
    """
    print()
    print("=" * 72)
    print(f"▶ 階段 {name}")
    # 把指令印出來，方便除錯與手動重跑（路徑含中文/空白時加引號示意）。
    printable = " ".join(_quote(a) for a in cmd)
    print(f"  指令：{printable}")
    print("=" * 72)

    try:
        completed = subprocess.run(cmd)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"階段「{name}」啟動失敗：找不到程式或直譯器（{exc}）。"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"階段「{name}」啟動失敗：{type(exc).__name__}: {exc}。"
        ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            f"階段「{name}」失敗，退出碼 {completed.returncode}。"
            f"\n  → 已中止整條流水線。請看上方該階段的輸出修正後再重跑。"
        )


def _quote(arg: str) -> str:
    """顯示用：含空白的參數加雙引號（僅供印出，非實際 shell 跳脫）。"""
    return f'"{arg}"' if (" " in arg or not arg) else arg


def _require_script(path: Path, stage: str) -> None:
    """確認子程式檔案存在；不存在就拋出清楚的錯誤（含提示）。"""
    if not path.exists():
        raise RuntimeError(
            f"階段「{stage}」需要的程式不存在：{path}\n"
            f"  → 請確認 {path.name} 已放在 scripts/ 下。"
        )


def _check_exists(path: Path, stage: str) -> None:
    """確認某階段「應該產出」的檔案確實存在；缺檔就拋錯（dry-run 時略過呼叫端不會用到）。"""
    if not path.exists():
        raise RuntimeError(
            f"階段「{stage}」宣稱完成，但預期產物不存在：{path}\n"
            f"  → 檔名約定可能對不上，請檢查該階段子程式的輸出路徑。"
        )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def orchestrate(args: argparse.Namespace) -> int:
    """依旗標串接各階段。回傳 process exit code。"""
    py = sys.executable  # 同一個 Python 直譯器，確保用對虛擬環境

    topic = args.topic
    slug = slugify(topic)

    output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    # 依 slug 推導各階段檔案路徑（檔名約定的單一事實來源）
    md_path = output_dir / f"{slug}.md"
    voice_path = output_dir / f"{slug}.voice.txt"
    mp3_path = output_dir / f"{slug}.mp3"
    mp4_path = output_dir / f"{slug}.mp4"

    # 決定要跑到哪一階段
    #   --upload 是 --stop-after upload 的捷徑
    stop_after = "upload" if args.upload else args.stop_after
    stop_idx = STAGES.index(stop_after)

    config_arg = ["--config", str(config_path)] if config_path.exists() else []

    print("#" * 72)
    print("# 量化阿森｜Carson Quant — 一鍵端到端編排器 run_all.py")
    print("#" * 72)
    print(f"  題目        : {topic}")
    print(f"  slug        : {slug}")
    print(f"  輸出資料夾  : {output_dir}")
    print(f"  設定檔      : {config_path}"
          f"{'' if config_path.exists() else '（不存在，子程式將用內建預設）'}")
    print(f"  跑到階段    : {stop_after}"
          f"（{'含上傳' if stop_after == 'upload' else '不含上傳'}）")
    print(f"  上傳隱私    : {args.privacy}")
    print(f"  dry-run     : {'是（全程不花錢/不上傳）' if args.dry_run else '否'}")
    print("#" * 72)

    # 推導出的各階段產物路徑（先公告，方便對齊檢查）
    print("  預期產物路徑：")
    print(f"    腳本   .md        : {md_path}")
    print(f"    配音稿 .voice.txt : {voice_path}")
    print(f"    配音   .mp3       : {mp3_path}")
    print(f"    成片   .mp4       : {mp4_path}")

    # ----------------------------------------------------------------- #
    # ① 產腳本：題目 → output/{slug}.md + output/{slug}.voice.txt
    # ----------------------------------------------------------------- #
    if stop_idx >= STAGES.index("script"):
        _require_script(GENERATE_SCRIPT, "① 產腳本")
        cmd = [py, str(GENERATE_SCRIPT), topic, *config_arg,
               "--output", str(output_dir)]
        # generate_script.py 沒有 --dry-run；其離線等價是 --no-llm
        # （不呼叫付費 LLM，改用內建模板產骨架），符合「dry-run 不花錢」精神。
        if args.dry_run:
            cmd.append("--no-llm")
        run_stage("① 產腳本（generate_script.py）", cmd)
        # 驗證檔名約定有對上（dry-run 也會實際寫出檔案，所以一律檢查）
        _check_exists(md_path, "① 產腳本")
        _check_exists(voice_path, "① 產腳本")

    # ----------------------------------------------------------------- #
    # ② 產配音：output/{slug}.voice.txt → output/{slug}.mp3
    # ----------------------------------------------------------------- #
    if stop_idx >= STAGES.index("tts"):
        _require_script(TTS_PIPELINE, "② 產配音")
        # 防呆：tts 要吃上一步的 voice.txt，若不存在直接報清楚
        if not voice_path.exists():
            raise RuntimeError(
                f"階段「② 產配音」缺少輸入：{voice_path}\n"
                f"  → 請先跑 ① 產腳本（不要用 --stop-after script 跳過）。"
            )
        cmd = [py, str(TTS_PIPELINE), str(voice_path), *config_arg,
               "--output-dir", str(output_dir)]
        if args.dry_run:
            cmd.append("--dry-run")
        run_stage("② 產配音（tts_pipeline.py）", cmd)
        # dry-run 不會真的產 mp3，故僅在非 dry-run 時驗證產物
        if not args.dry_run:
            _check_exists(mp3_path, "② 產配音")

    # ----------------------------------------------------------------- #
    # ③ 剪輯成片：output/{slug}.mp3 → output/{slug}.mp4
    # ----------------------------------------------------------------- #
    if stop_idx >= STAGES.index("video"):
        _require_script(MAKE_VIDEO, "③ 剪輯成片")
        if not args.dry_run and not mp3_path.exists():
            raise RuntimeError(
                f"階段「③ 剪輯成片」缺少輸入：{mp3_path}\n"
                f"  → 請先跑 ② 產配音。"
            )
        # make_video.py 實際介面：用 --slug 推導 output/{slug}.mp3/.md/.voice.txt → .mp4
        # （它沒有位置參數；以 slug 自行推導所有檔名，與本編排器一致）。
        cmd = [py, str(MAKE_VIDEO), "--slug", slug, *config_arg,
               "--output-dir", str(output_dir)]
        if args.dry_run:
            cmd.append("--dry-run")
        run_stage("③ 剪輯成片（make_video.py）", cmd)
        if not args.dry_run:
            _check_exists(mp4_path, "③ 剪輯成片")

    # ----------------------------------------------------------------- #
    # ④ 上傳 YouTube：output/{slug}.mp4 → 上架
    # ----------------------------------------------------------------- #
    if stop_idx >= STAGES.index("upload"):
        _require_script(UPLOAD_YOUTUBE, "④ 上傳 YouTube")
        if not args.dry_run and not mp4_path.exists():
            raise RuntimeError(
                f"階段「④ 上傳 YouTube」缺少輸入：{mp4_path}\n"
                f"  → 請先跑 ③ 剪輯成片。"
            )
        # upload_youtube.py 實際介面：位置參數是 slug（非路徑），用來推導
        # output/{slug}.md（取標題/描述/標籤）與 output/{slug}.mp4。這裡同時
        # 用 --video 明確指定成片路徑（避免任何輸出目錄不一致），並傳 --privacy。
        cmd = [py, str(UPLOAD_YOUTUBE), slug, "--video", str(mp4_path),
               "--output", str(output_dir), *config_arg, "--privacy", args.privacy]
        if args.dry_run:
            cmd.append("--dry-run")
        run_stage("④ 上傳 YouTube（upload_youtube.py）", cmd)

    # ----------------------------------------------------------------- #
    # 結束摘要
    # ----------------------------------------------------------------- #
    print()
    print("#" * 72)
    print("# ✅ 流水線完成")
    print("#" * 72)
    print(f"  題目 : {topic}")
    print(f"  slug : {slug}")
    print(f"  跑到 : {stop_after}")
    print("  產物狀態：")
    _summarize(md_path, "腳本 .md")
    _summarize(voice_path, "配音稿 .voice.txt")
    _summarize(mp3_path, "配音 .mp3", skip=stop_idx < STAGES.index("tts"))
    _summarize(mp4_path, "成片 .mp4", skip=stop_idx < STAGES.index("video"))

    if stop_after != "upload":
        print()
        print("  ⏸ 預設停在產出成片，未自動上傳（安全預設）。")
        print("    人工檢查成片 OK 後，要上傳請執行：")
        print(f'      python scripts\\run_all.py "{topic}" --upload --privacy {args.privacy}')
    else:
        print()
        print(f"  ⬆ 已執行上傳階段（隱私：{args.privacy}）。"
              f"{' [dry-run：未真的上傳]' if args.dry_run else ''}")
    print("#" * 72)
    return 0


def _summarize(path: Path, label: str, skip: bool = False) -> None:
    """印出單一產物的狀態行。"""
    if skip:
        print(f"    - {label:<18}: （本次未執行該階段，略過）")
        return
    if path.exists():
        try:
            size_kb = path.stat().st_size / 1024.0
            print(f"    - {label:<18}: ✓ {path}（{size_kb:.1f} KB）")
        except OSError:
            print(f"    - {label:<18}: ✓ {path}")
    else:
        print(f"    - {label:<18}: ✗ 不存在 {path}（dry-run 或該階段未產出）")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    """建立 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog="run_all.py",
        description=(
            "量化阿森｜Carson Quant 一鍵端到端編排器：吃一個題目，依序跑 "
            "generate_script.py → tts_pipeline.py → make_video.py → "
            "upload_youtube.py。預設跑到產出 mp4 就停（不自動上傳），上傳預設 private。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "範例：\n"
            "  # 全自動串到成片就停（預設，不上傳）：產出 .md/.voice.txt/.mp3/.mp4\n"
            '  python scripts\\run_all.py "派網網格機器人新手設定＋回測驗證"\n'
            "\n"
            "  # 只產腳本就停（最便宜，先看文案）：\n"
            '  python scripts\\run_all.py "馬丁格爾策略回測拆解" --stop-after script\n'
            "\n"
            "  # 產到配音就停（試聽 mp3）：\n"
            '  python scripts\\run_all.py "三重 SuperTrend 策略" --stop-after tts\n'
            "\n"
            "  # 全程 dry-run（不花錢、不上傳，驗證流程接線）：\n"
            '  python scripts\\run_all.py "測試題目" --dry-run --stop-after upload\n'
            "\n"
            "  # 確認成片 OK 後才上傳（預設 private 私人）：\n"
            '  python scripts\\run_all.py "派網網格機器人新手設定＋回測驗證" --upload\n'
            "\n"
            "  # 上傳並設為 unlisted（不公開但有連結者可看）：\n"
            '  python scripts\\run_all.py "派網網格機器人新手設定＋回測驗證" --upload --privacy unlisted\n'
        ),
    )
    parser.add_argument(
        "topic",
        help="影片題目（標題／主題）。會自動轉成 slug 推導各階段檔名。",
    )
    parser.add_argument(
        "--stop-after",
        choices=STAGES,
        default="video",
        help=(
            "跑到哪一階段為止：script(腳本) / tts(配音) / video(成片，預設) / "
            "upload(上傳)。預設 video，亦即「不」自動上傳，產出 mp4 就停讓你先檢查。"
        ),
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="明確要求上傳（等同 --stop-after upload）。不加這個就不會上傳。",
    )
    parser.add_argument(
        "--privacy",
        choices=["public", "unlisted", "private"],
        default="private",
        help="上傳隱私設定（傳給 upload_youtube.py），預設 private（私人，最安全）。",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=f"頻道設定 JSON 路徑（預設：{DEFAULT_CONFIG_PATH}）。",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"輸出資料夾（預設：{DEFAULT_OUTPUT_DIR}）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "全程 dry-run：每一階段都帶上各自的 dry-run（腳本用 --no-llm，"
            "tts/video/upload 用 --dry-run），不花錢、不呼叫付費 API、不真的上傳。"
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 進入點。回傳 process exit code。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return orchestrate(args)
    except RuntimeError as exc:
        print()
        print("!" * 72)
        print(f"[FATAL] {exc}")
        print("!" * 72)
        return 1
    except KeyboardInterrupt:
        print("\n[ABORT] 使用者中斷。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
