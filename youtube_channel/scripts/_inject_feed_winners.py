# -*- coding: utf-8 -*-
"""_inject_feed_winners.py — 把 2026-07-01 Shorts feed 爆款 DNA(實測框架+反直覺數字)插隊題庫最前。"""
import sys
sys.path.insert(0, "scripts")
import topic_bank

DNA = "回測/實驗框架(我回測/我讓/我用)+具體數字+反直覺結果+破除直覺;問句懸念、<35秒"
TOPICS = [
    {"title": "我回測『丟30萬給網格機器人』跑一個月,結果跟你想的完全相反", "angle": "回測懸念,開頭具體金額數字", "category": "回測", "format": "short"},
    {"title": "同樣10萬本金回測,DCA定投 vs 交易機器人,90天後差多少?算出來嚇一跳", "angle": "回測對比,反直覺結論", "category": "對比", "format": "short"},
    {"title": "我回測機器人在BTC暴跌那天硬撐,20天後帳戶剩多少?", "angle": "危機情境回測,懸念", "category": "回測", "format": "short"},
    {"title": "機器人連續停損8次,你以為快歸零?實際數字破除直覺", "angle": "反直覺數字+你以為互動", "category": "觀念", "format": "short"},
    {"title": "每月加碼10%聽起來很穩,3年後你其實少賺一半", "angle": "複利迷思,數字戳破", "category": "觀念", "format": "short"},
    {"title": "我用5000本金回測機器人跑一季,能不能贏過大盤?", "angle": "小資回測問句,可搜尋", "category": "回測", "format": "short"},
    {"title": "兩台機器人同一策略只差一個參數,一個月報酬差3倍", "angle": "反直覺對比,參數敏感度", "category": "對比", "format": "short"},
    {"title": "機器人賺錢時我按兵不動,30天後竟比停利多賺?", "angle": "破除停利直覺,懸念", "category": "觀念", "format": "short"},
]
n = topic_bank.add_topics(TOPICS, source="feed_winner_2026-07-01", front=True)
print(f"插隊題庫最前 {n} 題(feed 爆款 DNA:{DNA})")
print("下批 produce_batch 會優先抽到這些。")
