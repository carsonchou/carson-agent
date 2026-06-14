#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Faceless YouTube 影片腳本產生器（繁體中文）。

吃一個影片題目（標題／主題），產出一份符合 faceless YouTube 標準的
結構化腳本：

    [HOOK 0-5秒] -> [INTRO] -> [主體 分段] -> [CTA] -> [結尾]

每個主體分段同時包含「旁白文字」與「建議畫面 / B-roll 關鍵字」。

設計重點
--------
* 可串接 LLM：``build_prompt()`` 產生給 LLM 的提示，``call_llm()`` 是
  可被 stub 的 Anthropic API 介面（模型預設 ``claude-opus-4-8``，金鑰讀
  環境變數 ``ANTHROPIC_API_KEY``）。
* 無 API key 或呼叫失敗時，自動 fallback 用內建模板產生骨架腳本，讓使
  用者手動填內容。
* 輸出兩個檔案到 ``output/``：
    1. ``<slug>.md``        —— 完整腳本（含畫面標註）。
    2. ``<slug>.voice.txt`` —— 純配音稿（只有旁白，給 TTS 用）。
  ``<slug>.voice.txt`` 正是 ``tts_pipeline.py`` 預期吃的檔名約定
  （``xxx.voice.txt`` → ``output/xxx.mp3``）。
* 讀取 ``channel_config.json`` 頻道設定；不存在則用合理預設。
* Windows 相容：路徑用 ``pathlib``，寫檔一律 UTF-8。
* 不主動連網：API 呼叫包在 try/except，可被 stub。

CLI 用法請見檔案底部 ``build_arg_parser()`` 或執行 ``--help``。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# 路徑常數
# --------------------------------------------------------------------------- #

# 專案根目錄 = 本檔案所在的 scripts/ 的上一層 (youtube_channel/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "channel_config.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "high"


# --------------------------------------------------------------------------- #
# 頻道預設設定（當 channel_config.json 不存在時使用）
# --------------------------------------------------------------------------- #

DEFAULT_CHANNEL_CONFIG: dict[str, Any] = {
    "channel_name": "我的頻道",
    "channel_handle": "@my-channel",
    "language": "zh-Hant",
    "niche": "通用",
    "target_audience": "一般觀眾",
    "tone": "口語化、節奏明快",
    "video_length_minutes": 8,
    "narration": {
        "voice_style": "自然口語",
        "words_per_minute": 240,
        "tts_provider": "generic",
    },
    "branding": {
        "intro_tagline": "歡迎回到我的頻道。",
        "outro_tagline": "感謝收看，我們下次見。",
        "watermark_text": "我的頻道",
    },
    "cta": {
        "subscribe_text": "如果你喜歡這支影片，別忘了訂閱並開啟小鈴鐺。",
        "like_text": "順手幫我點個讚，這對頻道很有幫助。",
        "comment_prompt": "你的看法是什麼？留言告訴我。",
        "affiliate_intro": "影片中提到的資源放在資訊欄：",
        "affiliate_links": [
            {"label": "【推薦資源】", "url": "https://example.com/affiliate/REPLACE_ME"},
        ],
        "affiliate_disclaimer": "（以上為聯盟行銷連結，透過連結購買我可獲得分潤，不會增加你的費用。）",
    },
    "seo": {
        "default_hashtags": ["#影片", "#推薦"],
        "keywords": [],
    },
    "llm": {
        "model": DEFAULT_MODEL,
        "effort": DEFAULT_EFFORT,
        "max_tokens": DEFAULT_MAX_TOKENS,
    },
}


# --------------------------------------------------------------------------- #
# 資料結構
# --------------------------------------------------------------------------- #


@dataclass
class ScriptSection:
    """主體中的一個分段。"""

    heading: str
    narration: str
    broll: list[str] = field(default_factory=list)


@dataclass
class VideoScript:
    """一份完整的影片腳本（與 LLM 的 JSON 輸出對應）。"""

    topic: str
    title: str
    hook: str
    intro: str
    sections: list[ScriptSection]
    cta: str
    outro: str
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    generated_by: str = "template"  # "llm" 或 "template"

    @classmethod
    def from_llm_json(cls, topic: str, data: dict[str, Any]) -> "VideoScript":
        """把 LLM 回傳的 JSON dict 轉成 VideoScript。

        對缺漏欄位採容錯處理，避免 LLM 偶爾少給欄位就整個爆掉。
        """
        sections: list[ScriptSection] = []
        for raw in data.get("sections", []) or []:
            broll = raw.get("broll", []) or []
            if isinstance(broll, str):
                broll = [b.strip() for b in re.split(r"[,，、]", broll) if b.strip()]
            sections.append(
                ScriptSection(
                    heading=str(raw.get("heading", "（未命名段落）")),
                    narration=str(raw.get("narration", "")),
                    broll=[str(b) for b in broll],
                )
            )
        return cls(
            topic=topic,
            title=str(data.get("title", topic)),
            hook=str(data.get("hook", "")),
            intro=str(data.get("intro", "")),
            sections=sections,
            cta=str(data.get("cta", "")),
            outro=str(data.get("outro", "")),
            description=str(data.get("description", "")),
            hashtags=[str(h) for h in (data.get("hashtags", []) or [])],
            generated_by="llm",
        )


# --------------------------------------------------------------------------- #
# 設定載入
# --------------------------------------------------------------------------- #


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """遞迴合併 override 到 base 的副本上（override 優先）。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_channel_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """載入頻道設定 JSON；不存在或解析失敗則回傳合理預設。

    使用者自訂的設定會合併到預設值之上，因此即使設定檔只寫了部分欄位，
    缺漏的欄位仍會由預設值補齊。
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        print(f"[info] 找不到設定檔 {path}，使用內建預設值。", file=sys.stderr)
        return dict(DEFAULT_CHANNEL_CONFIG)
    try:
        user_config = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[warn] 設定檔 {path} 讀取失敗（{exc}），改用內建預設值。", file=sys.stderr)
        return dict(DEFAULT_CHANNEL_CONFIG)
    return _deep_merge(DEFAULT_CHANNEL_CONFIG, user_config)


# --------------------------------------------------------------------------- #
# LLM 提示組裝
# --------------------------------------------------------------------------- #


def build_prompt(topic: str, channel_config: dict[str, Any]) -> str:
    """組裝給 LLM 的提示字串。

    參數
    ----
    topic:
        影片題目（標題／主題）。
    channel_config:
        頻道設定 dict（``load_channel_config`` 的回傳值）。

    回傳
    ----
    一段繁體中文提示，要求 LLM 以 **純 JSON** 回傳結構化腳本，方便程式
    解析。
    """
    narration = channel_config.get("narration", {})
    length_min = channel_config.get("video_length_minutes", 8)
    wpm = narration.get("words_per_minute", 240)
    target_words = int(length_min) * int(wpm)

    hashtags = channel_config.get("seo", {}).get("default_hashtags", [])

    # JSON schema 用文字描述，避免 LLM 自由發揮成不可解析的格式。
    prompt = f"""你是一位專業的 faceless YouTube 影片腳本編劇，專精於「{channel_config.get('niche', '通用')}」類型。

請為以下影片主題撰寫一份**繁體中文**的完整影片腳本。

# 頻道設定
- 頻道名稱：{channel_config.get('channel_name')}
- 目標觀眾：{channel_config.get('target_audience')}
- 語氣風格：{channel_config.get('tone')}
- 影片長度：約 {length_min} 分鐘（旁白總字數約 {target_words} 字）
- 旁白語音風格：{narration.get('voice_style', '自然口語')}

# 影片主題
{topic}

# 腳本結構要求（faceless YouTube 標準）
1. HOOK（0-5 秒）：用一句強力的鉤子抓住觀眾，製造懸念或反差，禁止平淡開場。
2. INTRO：簡短介紹今天要講什麼、為什麼值得看下去。
3. 主體：分成 3-6 個段落，每段聚焦一個重點。**每段都要有旁白文字，以及該段建議的畫面 / B-roll 關鍵字**（給找素材用，英文或中文皆可，3-6 個關鍵字）。
4. CTA：自然帶出訂閱、點讚、留言（聯盟連結由程式另外插入，你不需要寫連結）。
5. 結尾（OUTRO）：收束主題、呼應開頭，留下記憶點。

# 額外要求
- 同時產出 YouTube 影片描述（description）與 {len(hashtags)} 個以上的 hashtags。
- 旁白文字要口語化、可直接拿去配音，不要出現括號舞台指示混在旁白裡。

# 輸出格式（**只輸出 JSON，不要任何其他文字、不要 markdown code fence**）
{{
  "title": "優化後的影片標題",
  "hook": "0-5 秒鉤子旁白",
  "intro": "開場介紹旁白",
  "sections": [
    {{
      "heading": "段落小標",
      "narration": "這一段的旁白文字",
      "broll": ["畫面關鍵字1", "畫面關鍵字2", "畫面關鍵字3"]
    }}
  ],
  "cta": "行動呼籲旁白（訂閱/點讚/留言，不含連結）",
  "outro": "結尾旁白",
  "description": "YouTube 影片描述",
  "hashtags": ["#標籤1", "#標籤2"]
}}
"""
    return prompt


# --------------------------------------------------------------------------- #
# LLM 呼叫介面（可被 stub）
# --------------------------------------------------------------------------- #


def call_llm(
    prompt: str,
    channel_config: dict[str, Any],
    *,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """呼叫 Anthropic API 取得腳本（回傳 LLM 的原始文字，通常是 JSON）。

    設計成可被測試 stub：整段網路呼叫包在 try/except，任何失敗（沒裝
    SDK、沒金鑰、網路錯誤、API 錯誤）都回傳 ``None``，讓上層 fallback 到
    模板。

    參數
    ----
    prompt:
        ``build_prompt`` 產生的提示。
    channel_config:
        頻道設定（用來取 model / effort / max_tokens）。
    api_key:
        Anthropic API 金鑰；預設讀環境變數 ``ANTHROPIC_API_KEY``。

    回傳
    ----
    LLM 回傳的文字，或在無法呼叫時回傳 ``None``。
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("[info] 未提供 ANTHROPIC_API_KEY，略過 LLM 呼叫，改用內建模板。", file=sys.stderr)
        return None

    llm_cfg = channel_config.get("llm", {})
    model = llm_cfg.get("model", DEFAULT_MODEL)
    max_tokens = int(llm_cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
    effort = llm_cfg.get("effort", DEFAULT_EFFORT)

    try:
        import anthropic  # 延遲匯入：沒裝 SDK 也不會在沒用到時報錯。
    except ImportError:
        print("[warn] 未安裝 anthropic 套件（pip install anthropic），改用內建模板。", file=sys.stderr)
        return None

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
        )
        # 取第一個 text block。
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        print("[warn] LLM 回應中沒有 text 內容，改用內建模板。", file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001 - 任何 API/網路錯誤都優雅 fallback
        print(f"[warn] LLM 呼叫失敗（{type(exc).__name__}: {exc}），改用內建模板。", file=sys.stderr)
        return None


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """從 LLM 回傳文字中盡力抽出 JSON 物件。

    容錯處理：即使 LLM 不小心包了 markdown code fence 或前後有雜訊，也
    試著抓出第一個 ``{`` 到最後一個 ``}`` 之間的內容解析。
    """
    text = text.strip()
    # 去掉可能的 ```json ... ``` 包裹。
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------- #
# 模板 fallback（無 LLM 時產生骨架腳本）
# --------------------------------------------------------------------------- #


def build_template_script(topic: str, channel_config: dict[str, Any]) -> VideoScript:
    """不靠 LLM，產生一份可供使用者手動填寫的骨架腳本。"""
    branding = channel_config.get("branding", {})
    seo = channel_config.get("seo", {})
    fill = "（請在此填入內容）"

    sections = [
        ScriptSection(
            heading=f"重點 {i}：{fill}",
            narration=fill,
            broll=["（B-roll 關鍵字）", "（畫面建議）"],
        )
        for i in range(1, 4)
    ]

    return VideoScript(
        topic=topic,
        title=topic,
        hook=branding.get("intro_tagline", fill),
        intro=fill,
        sections=sections,
        cta="（CTA 將由程式自動插入頻道設定中的訂閱／點讚／留言文案）",
        outro=branding.get("outro_tagline", fill),
        description=f"{topic}\n\n{fill}",
        hashtags=list(seo.get("default_hashtags", [])),
        generated_by="template",
    )


# --------------------------------------------------------------------------- #
# CTA 組裝（含聯盟連結）
# --------------------------------------------------------------------------- #


def build_cta_block(channel_config: dict[str, Any], llm_cta: str = "") -> str:
    """組裝完整 CTA 文字：旁白 CTA + 訂閱/點讚/留言 + 聯盟連結。"""
    cta = channel_config.get("cta", {})
    parts: list[str] = []
    if llm_cta.strip():
        parts.append(llm_cta.strip())
    if cta.get("subscribe_text"):
        parts.append(cta["subscribe_text"])
    if cta.get("like_text"):
        parts.append(cta["like_text"])
    if cta.get("comment_prompt"):
        parts.append(cta["comment_prompt"])

    affiliate_links = cta.get("affiliate_links", []) or []
    if affiliate_links:
        if cta.get("affiliate_intro"):
            parts.append(cta["affiliate_intro"])
        for link in affiliate_links:
            label = link.get("label", "連結")
            url = link.get("url", "")
            parts.append(f"{label} {url}")
        if cta.get("affiliate_disclaimer"):
            parts.append(cta["affiliate_disclaimer"])

    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 輸出渲染
# --------------------------------------------------------------------------- #


def slugify(topic: str) -> str:
    """把題目轉成安全的檔名 slug（保留中文，去掉檔名非法字元）。"""
    text = unicodedata.normalize("NFKC", topic).strip()
    # 移除 Windows 檔名非法字元 \ / : * ? " < > | 及控制字元。
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text)
    # 空白與多餘符號收斂成底線。
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:60] or "untitled"


def render_markdown(script: VideoScript, channel_config: dict[str, Any]) -> str:
    """渲染完整腳本（含畫面標註）為 Markdown 字串。"""
    branding = channel_config.get("branding", {})
    narration = channel_config.get("narration", {})
    cta_block = build_cta_block(channel_config, script.cta)

    lines: list[str] = []
    lines.append(f"# 🎬 {script.title}")
    lines.append("")
    lines.append(f"> 頻道：{channel_config.get('channel_name')}　|　"
                 f"主題：{script.topic}　|　產生方式：{script.generated_by}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # HOOK
    lines.append("## ⚡ HOOK（0-5 秒）")
    lines.append("")
    lines.append(f"**旁白：** {script.hook}")
    lines.append("")
    lines.append("**建議畫面：** 高張力、快節奏開場畫面，搭配音效強調懸念。")
    lines.append("")

    # INTRO
    lines.append("## 🎯 INTRO")
    lines.append("")
    lines.append(f"**旁白：** {script.intro}")
    lines.append("")
    if branding.get("watermark_text"):
        lines.append(f"**建議畫面：** 顯示頻道浮水印「{branding['watermark_text']}」，主題大字卡。")
        lines.append("")

    # 主體分段
    lines.append("## 📦 主體")
    lines.append("")
    for idx, section in enumerate(script.sections, start=1):
        lines.append(f"### 段落 {idx}：{section.heading}")
        lines.append("")
        lines.append(f"**旁白：** {section.narration}")
        lines.append("")
        broll = "、".join(section.broll) if section.broll else "（待補 B-roll 關鍵字）"
        lines.append(f"**建議畫面 / B-roll：** {broll}")
        lines.append("")

    # CTA
    lines.append("## 📣 CTA（訂閱 + 聯盟連結）")
    lines.append("")
    lines.append(cta_block)
    lines.append("")

    # OUTRO
    lines.append("## 🏁 結尾（OUTRO）")
    lines.append("")
    lines.append(f"**旁白：** {script.outro}")
    lines.append("")
    if branding.get("outro_tagline") and branding["outro_tagline"] not in script.outro:
        lines.append(f"**建議畫面：** 片尾卡，下集預告 / 推薦影片，搭配收尾語「{branding['outro_tagline']}」。")
        lines.append("")

    # 影片描述與 hashtags
    lines.append("---")
    lines.append("")
    lines.append("## 📝 YouTube 影片描述")
    lines.append("")
    lines.append(script.description or "（待補）")
    lines.append("")
    hashtags = script.hashtags or channel_config.get("seo", {}).get("default_hashtags", [])
    if hashtags:
        lines.append("**Hashtags：** " + " ".join(hashtags))
        lines.append("")

    # 旁白語音備註
    lines.append("---")
    lines.append("")
    lines.append(f"_配音備註：語音風格「{narration.get('voice_style', '自然口語')}」，"
                 f"語速約 {narration.get('words_per_minute', 240)} 字/分，"
                 f"TTS 供應商「{narration.get('tts_provider', 'generic')}」。_")
    lines.append("")

    return "\n".join(lines)


def render_voiceover(script: VideoScript, channel_config: dict[str, Any]) -> str:
    """渲染純配音稿（只有旁白，無畫面標註），給 TTS 用。

    包含 HOOK -> INTRO -> 各段旁白 -> CTA -> OUTRO，段落間以空行分隔。
    不含任何 markdown 標記、畫面描述或舞台指示。
    """
    cta_block = build_cta_block(channel_config, script.cta)

    blocks: list[str] = []
    if script.hook.strip():
        blocks.append(script.hook.strip())
    if script.intro.strip():
        blocks.append(script.intro.strip())
    for section in script.sections:
        if section.narration.strip():
            blocks.append(section.narration.strip())
    if cta_block.strip():
        blocks.append(cta_block.strip())
    if script.outro.strip():
        blocks.append(script.outro.strip())

    return "\n\n".join(blocks) + "\n"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def generate_script(
    topic: str,
    channel_config: dict[str, Any],
    *,
    api_key: Optional[str] = None,
    use_llm: bool = True,
    llm_caller: Callable[..., Optional[str]] = call_llm,
) -> VideoScript:
    """產生一份 VideoScript：先試 LLM，失敗則 fallback 到模板。

    ``llm_caller`` 參數讓測試可以注入 stub，避免實際連網。
    """
    if use_llm:
        prompt = build_prompt(topic, channel_config)
        raw = llm_caller(prompt, channel_config, api_key=api_key)
        if raw:
            data = _extract_json(raw)
            if data:
                return VideoScript.from_llm_json(topic, data)
            print("[warn] 無法從 LLM 回應解析出 JSON，改用內建模板。", file=sys.stderr)
    return build_template_script(topic, channel_config)


def write_outputs(
    script: VideoScript,
    channel_config: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, Path]:
    """把腳本寫成 .md（完整）與 .txt（純配音稿）兩個檔案，回傳兩條路徑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(script.topic)

    md_path = output_dir / f"{slug}.md"
    txt_path = output_dir / f"{slug}.voice.txt"

    md_path.write_text(render_markdown(script, channel_config), encoding="utf-8")
    txt_path.write_text(render_voiceover(script, channel_config), encoding="utf-8")

    return md_path, txt_path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    """建立 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog="generate_script.py",
        description="Faceless YouTube 影片腳本產生器（繁體中文，可串接 Anthropic Claude）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "範例：\n"
            '  python scripts\\generate_script.py "我把 10 萬丟給自動交易機器人跑 90 天"\n'
            '  python scripts\\generate_script.py "派網網格機器人新手教學" --config ./channel_config.json\n'
            '  python scripts\\generate_script.py "Triple SuperTrend 策略拆解" --no-llm\n'
            '  python scripts\\generate_script.py "馬丁格爾策略回測" --output ./output --api-key sk-ant-...\n'
        ),
    )
    parser.add_argument("topic", help="影片題目（標題／主題）。")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"頻道設定 JSON 路徑（預設：{DEFAULT_CONFIG_PATH}）。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"輸出資料夾（預設：{DEFAULT_OUTPUT_DIR}）。",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API 金鑰（預設讀環境變數 ANTHROPIC_API_KEY）。",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="不呼叫 LLM，直接用內建模板產生骨架腳本。",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 進入點。回傳 process exit code。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    channel_config = load_channel_config(args.config)
    output_dir = args.output or DEFAULT_OUTPUT_DIR

    script = generate_script(
        args.topic,
        channel_config,
        api_key=args.api_key,
        use_llm=not args.no_llm,
    )

    md_path, txt_path = write_outputs(script, channel_config, output_dir)

    print(f"[ok] 產生方式：{script.generated_by}")
    print(f"[ok] 完整腳本： {md_path}")
    print(f"[ok] 純配音稿： {txt_path}")
    if script.generated_by == "template":
        print("[note] 此為模板骨架，請手動填寫內容（或設定 ANTHROPIC_API_KEY 後重跑以自動產生）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
