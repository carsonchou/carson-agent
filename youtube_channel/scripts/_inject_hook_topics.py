#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_inject_hook_topics.py — 把「會紅選題題庫(資料反推版)」插隊進雲端 topic_bank。
Carson 用 ! 跑(他本人動作才放行寫雲端):
  ! /d/carson-agent/youtube_channel/.venv/Scripts/python.exe /d/carson-agent/youtube_channel/scripts/_inject_hook_topics.py
做:① SFTP 上傳這批題目 json ② 在雲端呼叫 topic_bank.add_topics(front=True) 插到題庫最前面
   → 下批 produce_batch 優先抽到。去重內建(重複跑不會灌爆)。純 append 不燒 API。
對照人類可讀版: STUDIO/會紅選題題庫_2026-06-28.md"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 批次 A：確定性(蒸餾自自己已紅片的 DNA：反直覺數字對比+破除迷思) ──
CONFIDENT = [
    {"title": "定投買在最高點，10年後居然還是賺——我算給你看",
     "angle": "最慘進場點仍正報酬，破除定投=無腦", "category": "定投DCA", "format": "short"},
    {"title": "同一支策略，你切資料的方式不同，夏普會差一倍",
     "angle": "樣本切割陷阱，數字反差差一倍", "category": "回測數據", "format": "short"},
    {"title": "勝率70%還是賠光，問題出在你沒算的這個數字",
     "angle": "盈虧比/期望值才是生死，補上具體落差", "category": "風控心法", "format": "short"},
    {"title": "凱利公式叫你押80%，活下來的人只押20%——差在哪",
     "angle": "估算誤差的破產陷阱，80→20 狠對比", "category": "風控心法", "format": "short"},
    {"title": "網格機器人連輸15次，本金剩多少？比你想的慘",
     "angle": "連輸複利衰減具體數字+網格主入口", "category": "網格交易", "format": "short"},
    {"title": "72法則：你的錢幾年翻倍，心算3秒就知道",
     "angle": "純技巧、可搜尋、結尾可 loop", "category": "風控心法", "format": "short"},
    {"title": "馬丁格爾加碼攤平，第7次就爆倉——數學證明給你看",
     "angle": "散戶最愛=最危險，精確第7次破產", "category": "風控心法", "format": "short"},
    {"title": "參數調到回測一片綠，上線就虧：這叫過擬合",
     "angle": "反直覺綠的是陷阱，平滑才穩健", "category": "回測數據", "format": "short"},
    {"title": "停損設2%還是5%？回測10年告訴你哪個能活著",
     "angle": "A/B 數字對比，回測背書", "category": "風控心法", "format": "short"},
    {"title": "派網網格年化標200%，扣掉這3項成本剩多少？",
     "angle": "暴利數字封面+誠實拆解+自然導流", "category": "工具派網", "format": "long"},
]

# ── 批次 B：賭新題材(3 新疆域，各 2 支；小注試水贏了加碼) ──
GAMBLE = [
    # ① AI×交易：競品已驗證爆(225K-237K)+你真用 Claude 做 bot=誠實切入
    {"title": "我叫AI幫我寫交易機器人，第一版就虧爆——但第三版…",
     "angle": "過程戲劇張力+誠實揭失敗的反推銷人設", "category": "工具派網", "format": "long"},
    {"title": "ChatGPT報的明牌準不準？我回測了它100個建議",
     "angle": "蹭最大熱詞+回測護城河，別人抄不出", "category": "回測數據", "format": "short"},
    # ② 台股量化：你有全市場回測引擎，繁中基數×10、crypto天花板低
    {"title": "我把這策略套全台1841檔股票，只有35%會賺——那怎麼選？",
     "angle": "反直覺只有35%+真實全市場回測發現", "category": "回測數據", "format": "short"},
    {"title": "台股除權息行情，用這招網格回測5年給你看",
     "angle": "台股專屬場景+回測背書、長尾穩", "category": "網格交易", "format": "long"},
    # ③ 行為/反直覺純觀念：完播率天生高、CPM高、可跨圈
    {"title": "賺30%要先賠50%才能回本？散戶最常死在這",
     "angle": "數學反直覺、不綁工具、跨圈傳播", "category": "市場觀念", "format": "short"},
    {"title": "每天賺1%，一年後幾倍？答案會嚇到你（但有陷阱）",
     "angle": "複利懸念+括號代價、可 loop", "category": "市場觀念", "format": "short"},
]

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD_JSON = os.path.join(os.path.dirname(HERE), "cloud.json")

import paramiko  # noqa: E402
c = json.load(open(CLOUD_JSON, encoding="utf-8"))
root = c.get("remote_root", "/root/yt")
cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(c["ip"], port=22, username=c.get("user", "root"), password=c["password"], timeout=30)


def run(cmd, t=120):
    i, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


print("① 上傳題目包(16 題：確定性10 + 賭新題材6)")
payload = {"confident": CONFIDENT, "gamble": GAMBLE}
sf = cli.open_sftp()
with sf.open(root + "/STUDIO/_hook_inject.json", "w") as fp:
    fp.write(json.dumps(payload, ensure_ascii=False, indent=2))
sf.close()
print(f"   uploaded：確定性 {len(CONFIDENT)} + 賭新 {len(GAMBLE)} 題")

print("② 雲端插隊進 topic_bank(front=True，下批優先產；去重內建)")
applier = (
    "import sys; sys.path.insert(0,'scripts'); import json, topic_bank; "
    "d=json.load(open('STUDIO/_hook_inject.json',encoding='utf-8')); "
    "a=topic_bank.add_topics(d['confident'], source='hook_bank', front=True); "
    "b=topic_bank.add_topics(d['gamble'], source='gamble', front=True); "
    "u=[t for t in topic_bank.load_bank() if not t.get('used')]; "
    "print('NEW_CONFIDENT='+str(a)); print('NEW_GAMBLE='+str(b)); print('UNUSED_TOTAL='+str(len(u)))"
)
out, err = run(f"cd {root} && .venv/bin/python -c \"{applier}\"")
print((out.strip() or err[-400:]))
cli.close()

print("\n完成。這 16 題已插到雲端題庫最前面，下批 produce_batch 優先抽。")
print("（NEW_*=0 代表先前已注入過，去重略過，正常）")
print("人類可讀版：STUDIO/會紅選題題庫_2026-06-28.md")
