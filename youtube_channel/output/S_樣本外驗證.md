# 🎬 回測一定要做這一步

## ⚡ HOOK（0-5 秒）

**旁白：** 沒做這步的回測都是自欺欺人。很多人把參數調到歷史曲線超漂亮，就以為找到聖盃，一上線卻馬上賠錢。

**建議畫面：** beautiful backtest equity curve zooming in, then crashing red after "live" label

## 📦 主體

### 段落 1：你只是在背答案

**旁白：** 在同一段歷史資料上反覆調參，本質上是把答案背起來，當然怎麼測都漂亮。這叫過度擬合，它對「沒看過的市場」完全沒有預測力。要破解，得先把資料切兩段：前段拿來開發與調參，後段完全鎖起來、開發過程一眼都不准看。

**建議畫面 / B-roll：** dataset split timeline graphic, in-sample vs out-of-sample, lock icon over second segment

### 段落 2：用樣本外資料做最後驗收

**旁白：** 等策略定稿、參數固定，再把它丟進那段全新的樣本外資料測一次。表現能維持，才比較可能是真的有效；一測就崩，代表你只是調出一條漂亮卻沒用的曲線。能在沒看過的資料上活下來，策略才算通過第一關。

**建議畫面 / B-roll：** out-of-sample test running, two equity curves side by side, pass vs fail stamp

## 🏁 結尾（OUTRO）

**旁白：** 這只是真正穩健回測的第一步。想看完整版？追蹤量化阿森，帶你把策略驗到真的能上線。

## 📝 YouTube 影片描述

回測曲線漂亮不代表策略有效，可能只是過度擬合在背答案。留一段沒調過參的樣本外資料做最後驗收，才知道是真本事還是運氣。本影片為教學與觀念分享，非投資建議，市場有風險，請自行評估並做好風控。

**Hashtags：** #Shorts #量化交易 #回測 #樣本外驗證 #過度擬合 #策略開發 #風控 #派網 #Pionex #量化阿森