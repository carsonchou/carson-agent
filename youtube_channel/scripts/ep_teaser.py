#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ep_teaser.py — 【EP 回測系列·預告/切片自動化】
產出導流到「回測往死裡測機器人」EP 系列的 Shorts：用回測最戲劇性的數字/懸念當鉤子，結尾 CTA 追 EP 正片。
資料源 STUDIO/ep_data.json（有回測數據就用那些數字；沒有就用回測premise+懸念）。
全自動路線：PC 端 trading_bot 寫 ep_data.json → 同步到雲端 → 本程式產預告。

用法：python scripts/ep_teaser.py [--count 1]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import produce_batch as pb  # 重用 slugify/build_md/_run_tts/call API 等機制保持一致
import requests
from ops import log_ops

EP_DATA = ROOT / "STUDIO" / "ep_data.json"
DEFAULT_EP = {
    "premise": "我用回測『丟十萬給自動交易機器人』往死裡測，規則先講死",
    "series_name": "自動交易機器人回測企劃",
    "current_ep": 0,
    "day": 0,
    "return_pct": None,        # 真實報酬率(含負)；None=尚無數據
    "max_drawdown": None,
    "cliffhanger": "結果可能打臉所有人",
    "highlights": [],
    # EP franchise 引擎新欄位（缺就用預設，不報錯）
    "season": 1,
    "character_state": "cautious",
    "cumulative": {},
    "last_episode": {},
}


def load_ep():
    d = dict(DEFAULT_EP)
    try:
        if EP_DATA.exists():
            d.update({k: v for k, v in json.loads(EP_DATA.read_text(encoding="utf-8")).items() if v is not None})
    except Exception:
        pass
    return d


def gen_teaser(ep):
    has_num = ep.get("return_pct") is not None
    if has_num:
        data_line = (f"目前實測到第 {ep['day']} 天，帳戶報酬率 {ep['return_pct']}%"
                     + (f"，最大回撤 {ep['max_drawdown']}%" if ep.get("max_drawdown") is not None else "")
                     + "。" + ("　亮點：" + "；".join(ep.get("highlights", [])[:3]) if ep.get("highlights") else ""))
        hook_seed = f"用真實數字當鉤子（如『機器人跑了{ep['day']}天，帳戶{ep['return_pct']}%，你猜賺還賠？』）"
    else:
        # 優先用 EP 引擎記的上集懸念（last_episode），退回頂層 cliffhanger
        cliff = (ep.get("last_episode") or {}).get("cliffhanger") or ep.get("cliffhanger", "")
        data_line = f"實測企劃前提：{ep['premise']}。{cliff}"
        hook_seed = "用『回測丟十萬給機器人』的懸念當鉤子（如『我回測丟十萬給機器人，三十天後帳戶剩多少？』）"

    prompt = (f"你是量化阿森頻道腳本寫手。為「{ep['series_name']}」(EP 回測系列;是回測不是真錢實盤,別假稱丟真錢)產一支**預告/切片 Shorts**，導流到 EP 正片。\n"
              f"實測現況：{data_line}\n"
              f"{pb.GUARD if hasattr(pb,'GUARD') else ''}\n"
              "【完播率鐵律】1.第一句(前1秒)就砸最戲劇性的具體數字或懸念，0開場白。" + hook_seed + "。"
              "2.好奇缺口：結果/答案留到最後一句才揭曉。3.全程快節奏、每句一衝擊點、二十到三十秒。"
              "4.結尾 CTA：『完整實測每集追蹤量化阿森，看機器人到底賺還賠』。誠信:不編損益不保證收益不喊單。\n"
              "voice_text 80-150 字、口語短句、數字寫口語念法(如百分之八)。\n"
              '只輸出 JSON：{"title":"含EP字樣與數字懸念的標題","voice_text":"...","segments":[{"heading":"...","broll":["trading chart","money"]}],'
              '"description":"SEO描述,結尾含『投資有風險,不構成投資建議』","hashtags":["#Shorts","#自動交易","#實測"]}')
    body = {"model": pb.MODEL, "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]}
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": pb.API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json=body, timeout=120)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))


def make_teaser(ep):
    d = gen_teaser(ep)
    title = d["title"]
    slug = pb.slugify(title, "S_")
    voice = d.get("voice_text", "").strip()
    if not voice:
        return None
    (pb.OUT / f"{slug}.voice.txt").write_text(voice, encoding="utf-8")
    (pb.OUT / f"{slug}.md").write_text(pb.build_md(d), encoding="utf-8")
    pb._run_tts(slug)  # 配音(Kokoro)；渲染交給 hybrid_render / cron
    ok = (pb.OUT / f"{slug}.mp3").exists()
    log_ops("EP預告", f"{'已備妥待渲染' if ok else '配音失敗'}：{title[:36]}")
    print(f"[{'ok' if ok else 'FAIL'}] EP 預告：{title}")
    return slug if ok else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1)
    args = ap.parse_args()
    if not pb.API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr); return 2
    ep = load_ep()
    print(f"[info] EP 現況：EP.{ep['current_ep']} 第{ep['day']}天 報酬={ep.get('return_pct','尚無數據')}")
    made = 0
    for _ in range(args.count):
        try:
            if make_teaser(ep):
                made += 1
        except Exception as e:  # noqa: BLE001
            print(f"[err] {str(e)[:100]}", file=sys.stderr)
    print(f"完成 EP 預告 {made}/{args.count} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
