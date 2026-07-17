# -*- coding: utf-8 -*-
"""_boost_ep_series.py — 把「實測EP系列」設為常態產線(持久directive)+注入研究挖出的更爆題庫。
在雲端 run.sh 下跑(讀雲端 STUDIO/boss_directives.json + topic_bank)。"""
import sys, json, os
sys.path.insert(0, "scripts")
import topic_bank
from studio_common import save_json_atomic

# ── 1) 持久 steering：加兩條非「自省」tag 的 directive(retro 不會清、decision 每天注入為最高優先) ──
DIRPATH = "STUDIO/boss_directives.json"
d = {}
if os.path.exists(DIRPATH):
    try: d = json.load(open(DIRPATH, encoding="utf-8"))
    except Exception: d = {}
if not isinstance(d, dict): d = {}
ds = list(d.get("directives", []))

DUR = [
    "【常態產線｜回測EP系列】固定每週優先產「回測 EP 續集」(EP2、EP3…延續『我用回測往死裡測——丟十萬給機器人』世界觀,是回測不是真錢實盤別假稱丟真錢;金額/條件逐集升級、中段安排真回撤危機集、每集結尾留 cliffhanger 勾下一集)。這是頻道爆款招牌 franchise,優先於一般選題,別讓它斷。",
    "【加爆鐵律｜Shorts結構】每支 Shorts:前1.5秒直接喊結果數字/衝突(禁片頭與自我介紹)、全程燒大字幕、最終數字答案壓到最後3秒、結尾留開放式懸念+二選一留言題、盡量做無縫loop。完播率是 Shorts 的**觀看**命門(<30秒需~65%),絕大多數流量來自 Shorts feed。⚠️ 但完播率**不是**訂閱命門:實測本頻道完播率最高的那批片幾乎不帶訂閱。**Shorts 的任務是曝光與導流(連看鉤指向長片),訂閱轉換靠長片與 EP.0 開播預告**——別再把完播率當成長的唯一解。",
]
# 依前綴去重(可重跑覆蓋)
def tag(s): return s.split("】")[0] + "】"
tags = {tag(x) for x in DUR}
ds = [x for x in ds if tag(x) not in tags] + DUR
d["directives"] = ds
save_json_atomic(DIRPATH, d)
print(f"[directives] 現有 {len(ds)} 條(已設 2 條常態 steering)")

# ── 2) 注入更爆題庫(研究A+B合併,front=True 下批優先;add_topics 自動去重) ──
TOPICS = [
    # 實測 EP 續集 franchise(延續世界觀,序列化=追劇)
    {"title": "我回測丟十萬開兩隻機器人對打,30天後誰先爆?｜實測EP2", "angle": "0秒:兩帳戶餘額賽跑條起跑;賭注升級對決(回測不假稱真錢)", "category": "實測EP", "format": "short"},
    {"title": "機器人連虧7天,我到底該不該關掉它?｜實測EP3", "angle": "0秒:紅字-連7天;結尾留二選一給留言", "category": "實測EP", "format": "short"},
    {"title": "加碼!回測把二十萬全押給最強那隻機器人｜實測EP4", "angle": "賭注升級到20萬;金額往上跳一階(回測不假稱真錢)", "category": "實測EP", "format": "short"},
    {"title": "崩盤那天我的機器人在做什麼?真實危機直擊｜實測EP5", "angle": "0秒:市場一天跌12%我不敢看帳戶;危機集情緒最高", "category": "實測EP", "format": "short"},
    {"title": "我照網紅參數設定,結果比亂設還慘?｜實測EP7", "angle": "0秒:抄作業真的有用嗎;真回測打臉", "category": "實測EP", "format": "short"},
    {"title": "機器人帳面賺8%,扣掉手續費實拿剩多少?｜實測EP8", "angle": "揭真相:沒人告訴你的成本;反差數字", "category": "實測EP", "format": "short"},
    {"title": "極限測試:拿掉停損讓機器人裸奔30天會怎樣?｜實測EP9", "angle": "0秒:沒安全網是印鈔機還是自殺;移除安全網升級", "category": "實測EP", "format": "short"},
    {"title": "三個月總結算:十萬變成多少?值不值得?｜實測EP10", "angle": "收官判決+開下一季更狠的賭", "category": "實測EP", "format": "short"},
    {"title": "新挑戰:機器人能不能100天不虧一塊錢?｜實測EP11", "angle": "開新季:規則升級只要虧1元整個實驗失敗", "category": "實測EP", "format": "short"},
    # 全新實驗 franchise 首集
    {"title": "AI機器人 vs 我,同樣十萬,誰先在這波爆倉?", "angle": "人性弱點vs冷血演算法對決;分割畫面賽跑", "category": "實驗franchise", "format": "short"},
    {"title": "十萬買0050 vs 十萬丟加密機器人,一年後差多少?", "angle": "台股vs加密在地共鳴;真回測對比", "category": "實驗franchise", "format": "short"},
    {"title": "我把機器人丟回312暴跌那天,它撐得住嗎?", "angle": "壓力測試:歷史最恐怖行情重播;天生高張力", "category": "實驗franchise", "format": "short"},
    # 研究A 高爆格式(編號揭曉/反差/可視化對比)
    {"title": "所有人都說AI交易穩贏,我實測20天後笑不出來", "angle": "0秒:你以為機器人不會虧?看這數字;反直覺", "category": "觀念", "format": "short"},
    {"title": "這3個網格新手都死錯,第2個我也犯過", "angle": "編號揭曉;完播+234%的格式", "category": "觀念", "format": "short"},
    {"title": "回測賺40%,實盤上線後現實給我一巴掌", "angle": "0秒:回測+40%實盤第一週;畫面由綠翻紅", "category": "觀念", "format": "short"},
    {"title": "回測『每月薪水全丟去定投』,一年後這數字讓我沉默", "angle": "0秒:薪水一到就全買一年後;計數器狂跳(回測情境)", "category": "實測EP", "format": "short"},
    {"title": "1萬 vs 10萬,本金差10倍,網格報酬率會一樣嗎?", "angle": "反直覺對比;同策略只差本金你猜哪個賺更多%", "category": "對比", "format": "short"},
    {"title": "我讓AI回測選幣,一週後它幫我賠了多少?", "angle": "0秒:把選幣權交給AI回測結果第一天就;懸念(回測不假稱真錢)", "category": "實驗franchise", "format": "short"},
]
n = topic_bank.add_topics(TOPICS, source="viral_research_2026-07-01", front=True)
print(f"[topics] 插隊題庫最前 {n} 題(去重後新增;研究A+B合併爆款DNA)")
print("下批 produce_batch 會優先抽到 EP 續集與新 franchise。")
