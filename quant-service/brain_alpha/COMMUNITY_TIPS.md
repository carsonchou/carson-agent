# WorldQuant BRAIN 社群實戰經驗彙整(COMMUNITY_TIPS)

> 彙整日期:2026-08-27。搜遍中英文社群(知乎、CSDN、電鴨、Threads、GitHub、官方 IQC 規則頁)。
> 標註原則:**[作者實測宣稱]** = 原文照抄或摘錄、有出處;**[推論]** = 我根據多個來源推導,非原文。
> 時效警告:BRAIN 門檻與規則會變。各條目附資料日期,2025 之前的資料視為可能過時。

---

## 0. 無法讀取的來源(誠實聲明)

- 知乎問題頁「你了解世坤的 worldquant brain 平台吗?」(www.zhihu.com/question/6667015461)— 403,連 r.jina.ai 也被擋,只拿到搜尋摘要。
- 百度貼吧 worldquant 吧 — 403。搜尋摘要顯示吧內有「账号莫名其妙被封」的帖子標題,但**內文讀不到**,無法確認封號原因。
- B 站影片「WorldQuant Brain平台Alpha策略构建从入门到精通」(BV1DrjuzPEFt)— 影片未看,僅知存在。
- 小紅書 — 搜不到可直接讀取的實戰貼文。
- Reddit — 多組查詢都沒撈到 r/quant 上的 BRAIN 實戰討論串,**找不到就是找不到**。
- Scribd「Improving Alpha Fitness Strategies」PDF — 未讀取。
- 電鴨社區貼文(eleduck.com/posts/OGfRbB)— 內文要登入,只拿到搜尋摘要。
- 知乎「日赚 60 美金的 WorldQuant BRAIN顾问」(zhuanlan.zhihu.com/p/2011835143673910990)— 直連 403,**經 r.jina.ai 成功讀到全文**,下文引用。

---

## 1. 實戰者的具體表達式(逐字照抄)

### 1.1 GitHub「wq-alpha-research」skill(QuantML-Research,建於 2026-06-19,最後更新 2026-06-29)
出處:https://github.com/QuantML-Research/wq-alpha-research (SKILL.md,CC BY-NC 4.0)
作者宣稱這些模板來自「USA TOP3000 实证经验」。**注意:這是匿名 GitHub 倉庫的自我宣稱,通過率數字無法獨立驗證。**

```
-- 模板 A:ROE 趋势(通过率最高)
group_rank(ts_rank(operating_income / equity, 126), subindustry)

-- 模板 B:EPS 收益率修正
group_rank(ts_rank(est_eps / close, 126), industry)

-- 模板 C:FCF 收益率
group_rank(ts_rank(free_cash_flow_reported_value / equity, 126), industry)

-- 模板 D:多因子混合(高 Fitness)
0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry)
+ 0.5 * group_rank(ts_rank(est_eps / close, 126), industry)

-- 模板 E:低相关技术+基本面混合
0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))

-- 模板 F:资产周转 × 利润率
rank(ts_rank(operating_income / sales * sales / assets, 126))
```

搭配設定表(原文照抄):

| 因子類型 | Decay | Neutralization | Truncation | nanHandling | 預期 TO |
|----------|-------|----------------|------------|-------------|---------|
| 基本面质量 | 0 | SUBINDUSTRY | 0.08 | ON | 2–8% |
| 分析师预期 | 0–4 | INDUSTRY/SUBINDUSTRY | 0.08 | ON | 9–16% |
| 技术反转 | 10–30 | INDUSTRY | 0.08 | OFF | 15–35% |
| 混合因子 | 4–20 | INDUSTRY/SUBINDUSTRY | 0.08 | ON | 10–20% |
| 情绪 | 4–10 | INDUSTRY | 0.05–0.08 | ON | 8–30% |

原文金句:「**group_rank + ts_rank 是黄金组合**」「**SUBINDUSTRY 中性化通过率最高**」「**Decay 是控制换手的主杠杆:基本面 0,技术 10–30**」。

### 1.2 GitHub「WorldQuant-alpha-trading」(alexisdpc,英文,含官方教學例)
出處:https://github.com/alexisdpc/WorldQuant-alpha-trading

```
SMA_30 = ts_mean(close,30); rank(SMA_30 - close)          # Price Reversion (USA)
event = volume>adv20; alpha = (-ts_delta(close,5)); trade_when(event,alpha,-1)   # 事件觸發降換手
(vwap-close)/vwap                                          # Price Weighted Average (USA)
alpha = ts_rank(cashflow_op/cap,60); group_rank(alpha, subindustry)   # Operating Cashflow (USA)
rank(-mdl175_volatility*log(volume))*(1+group_rank(mdl175_revenuettm, sector))   # Volatility Turnover (China)
```

### 1.3 CSDN「使用trade_when构建event alphas和low turnover alphas」(Oo_Amy_oO,2025-05-06)
出處:https://blog.csdn.net/Oo_Amy_oO/article/details/147729641

```
Trade_When (volume >= ts_sum(volume,5)/5, rank(-returns), -1)
Trade_When (volume >= ts_sum(volume,5)/5, rank(-returns), abs(returns) > 0.1)
```
作者同時警告 trade_when 系:「難以獲得高夏普比率的阿爾法因子」「難以獲得高回報率的阿爾法因子」——**[推論]** 即 trade_when 是修 turnover 的工具,不是修 Sharpe 的工具。

### 1.4 CSDN「零基础通关 WorldQuant 竞赛」(Liiiks,2026-06-29)
出處:https://blog.csdn.net/Liiiks/article/details/151655098

```
rank(ts_sum(close, 5) - ts_sum(close, 10))
(high - low) / close
ts_delta(close, 3)
group_neutralize(your_factor, 'industry')
```
附帶建議(摘錄):「确保单日换手率<15%」「5个以内高质量因子足矣,过多易引入噪声」、線性因子比複雜模型友好、關注平台的「Spectacular」標籤。

### 1.5 知乎「日赚 60 美金的 WorldQuant BRAIN顾问…实战指南」(經 r.jina.ai 讀取,日期不明,約 2025)
出處:https://zhuanlan.zhihu.com/p/2011835143673910990

```
rank(ts_mean(close, 20))
rank(ts_mean(returns, 5)) / rank(volume)
group_neutralize(ts_rank(scale(zscore(returns)), 10), sector)
```

### 1.6 其他零散
- roger2389(繁中,日期不明):`rank(ts_zscore(mdf_gry, 15))`、`-(close - ts_mean(close, 5))`;建議「Truncation value = 0.01 for diversity」。出處:https://roger2389.github.io/WorldQuant-Introduction/

---

## 2. 積分與時間基準(真實數字)

### 2.1 [作者實測宣稱] CSDN「Python量化兼职初体验」(PearlOwl67,約 2025-11,文章 ID 154641045)
出處:https://blog.csdn.net/PearlOwl67/article/details/154641045
> 「注册后首先需要完成10,000分的初始任务,每个成功提交的因子可获得1,500-2,000分。……**我每天提交1个因子,仅用5天就达成了目标。**」
> 通過 **34 個 Alpha 因子**的提交,**兩個月後**收到第一筆顧問費。

**[推論]** 對照你的處境:此作者「每天 1 個因子、5 天達標」的前提是**每個提交都過**;你 200+ 模擬 0 過,卡的不是積分機制,是提交測試本身。

### 2.2 [作者實測宣稱] Threads @skyning823(台灣,2026-03-15 發文,講的是約 2024 年的事)
出處:https://www.threads.com/@skyning823/post/DV7BpGygTn3/
> 「比賽期間 可以很容易水到一個顧問的title 果不其然**不到一個月**就拿到了Quantitative Research Consultant……**第三個交的alpha一個就讓我賺了40多刀**」

**[推論]** 兩位實戰者的共同訊息:**IQC 比賽期間是拿顧問資格的最快窗口**(IQC 2026 Stage 1 為 3/17–5/18,已過;下屆通常在每年 3 月開)。

### 2.3 [作者宣稱] 收入階梯(知乎「日赚60美金」文,約 2025)
新人 $1.5–2/日 → 進階 $5–7/日 → 頂級 $120/日;季度獎金 $100–25,000;文中「現實預期」為月人民幣 3,000–5,000。另外多篇中文文章提到新顧問激勵:30 天內 10 個提交日領一次性 $100。

### 2.4 積分機制共識(多來源交叉:PearlOwl67、電鴨搜尋摘要、wq-guide)
- 10,000 分拿金牌認證 + 顧問邀請;**每日積分上限 2,000**;每個成功提交的因子 1,500–2,000 分。
- **[推論]** 理論下限 5 天,社群常見說法 1–2 週。瓶頸永遠是「能不能過提交測試」,不是分數計算。

---

## 3. 通過 self-correlation 的做法

### 3.1 規則本體(知乎「从头打造WorldQuant投研平台——Alpha提交前验证」,2025-05-30)
出處:https://zhuanlan.zhihu.com/p/1915099506304849861(經 r.jina.ai 讀取)
> 自相關「要求小于0.7,**或者要求Sharpe Ratio比其他自己提交的alpha高至少10%**」

作者的本地預檢程式(原文照抄):
```python
self_corr_max = os_alpha_rets[os_alpha_ids].corrwith(alpha_rets).max()
# 實測輸出範例:self_corr_max: 0.6091 < 0.7
```

### 3.2 計算細節(DeepWiki 對 xiegengcai/world-quant-brain 工具的解析)
出處:https://deepwiki.com/xiegengcai/world-quant-brain/4.1-self-correlation-analysis
- 用「**最近 4 年**」的 OS(已上線)alpha PnL。
- PnL 轉日收益:`alpha_pnls - alpha_pnls.ffill().shift(1)`。
- 只跟**同 region** 的已提交 alpha 比,取 max。
- **先本地算好再提交**,省 API 也省心。

### 3.3 什麼才真的能降相關(wq-alpha-research SKILL.md,2026-06,作者實證數據)
原文照抄:
> 「换窗口、换权重、换 neutralization **不能创造真正的低相关**。」
> 「两个 open-close 反转 + OI/Equity 混合(权重不同)日收益相关 **0.84**」「两个分析师 EPS 相关 **0.74**」
> 「基于 scl12_buzz 的情绪 alpha 与基于 est_eps/close 的分析师 alpha 相关仍达 **0.59–0.67**」
> 「真正的低相关来自**完全不同的数据来源或经济逻辑**(如:宏观事件、期权流、跨境、另类数据)」
> 「在常规 USA TOP3000 基本面/价量/分析师池子里,『低相关』往往是 **0.3–0.6 的日收益相关,不要追求 0**。」

另一個工程級大坑(同來源):
> 「**不要用累计 PnL 算相关**。累计曲线自带强趋势,会把不同信号的相关性严重夸大」(其實測:累計 PnL 兩兩相關普遍 > 0.90)。

### 3.4 提交狀態陷阱(同來源)
> 「`POST /alphas/{id}/submit` 返回 201 只表示请求被接受,**不代表 alpha 已变为 ACTIVE**」——必須回讀 `status == ACTIVE`,SELF_CORRELATION 沒過的會停在 UNSUBMITTED。
> **[推論]** 這跟我們 memory 裡「API 回 200 但靜默不改」是同型坑,務必二次確認。

---

## 4. 怎麼破 Sharpe/fitness 蹺蹺板(你最需要的)

### 4.1 先看數學:fitness 的分母有地板
`fitness = Sharpe × sqrt(|returns| / max(turnover, 0.125))`
- **turnover ≤ 12.5% 之後,分母被 0.125 夾住,再降換手對 fitness 零貢獻**。此時 fitness = Sharpe × sqrt(|returns|/0.125) = Sharpe × sqrt(8×|returns|)。
- **[推論,但由公式直接可證]** 當 TO 已觸地板,fitness ≥ 1.0 等價於 `Sharpe × sqrt(returns) ≥ 0.3536`,亦即 Sharpe 1.25 時只需年化 returns ≥ 8%;Sharpe 1.46 時只需 ≥ 5.9%。**你的蹺蹺板(Sharpe 1.46 → fitness 0.90)代數上只有兩種可能:TO 遠高於 12.5%,或 returns 太薄。**

### 4.2 社群給的解法方向(按出現頻率排序)

1. **換資料集,不要在高換手信號上硬壓**(wq-alpha-research,2026-06):
   > 「LOW_FITNESS……通常是 HIGH_TURNOVER 的软性版本」「基本面质量因子 decay=0 预期 TO 2–8%」
   **[推論]** 這是根治法:基本面/分析師字段的信號天生慢,TO 直接落在 0.125 地板附近,蹺蹺板結構性消失,剩下只要拚 Sharpe。你掛在 pv1(價量)上,價量信號天生快,decay 壓 TO 的同時必然鈍化信號、砍 Sharpe——蹺蹺板正是 pv 資料集的特產。
2. **Decay 是第一槓桿**(多來源一致):alexisdpc:「Increase Decay ⟹ Reduces the turnover」;wq-alpha-research 把 decay 列為 HIGH_TURNOVER 與 LOW_FITNESS 的首選修法。
3. **trade_when 事件閘門**(alexisdpc + CSDN Oo_Amy_oO):`trade_when(volume>adv20, alpha, -1)` 只在事件日更新持倉。但 CSDN 作者明言此法「難以獲得高夏普」——用它救 TO,別指望它救 Sharpe。
4. **50/50 混一支穩定基本面因子**(wq-alpha-research 模板 D/E):快信號提供 Sharpe,慢信號拉低整體 TO、撐 returns。同來源提醒:「50/50 正交混合能降低换手,但未必能降低相关」。
5. **拉 returns 的手段**(roger2389 + [推論]):returns 在 fitness 分子裡,和 Sharpe 同向。小 universe(TOP500/TOP1000)与更集中的權重(較小 truncation)会拉高 returns,但會撞 concentrated weight 與 sub-universe 測試,需權衡;roger2389 建議 truncation 0.01 是為分散,方向相反,證明這是一個要調參試的 trade-off。

### 4.3 失敗率基準(wq-alpha-research 作者實測統計,樣本為其自身批量模擬)
> LOW_SHARPE 90.7%、LOW_FITNESS 66.2%、LOW_SUB_UNIVERSE_SHARPE 51.0%
> 「按数据类型通过率:**基本面 40% > 混合 12.7% > 纯技术 5.3% > 其他 0%**」

**[推論]** 你 200+ 全掛在 pv1 ≈ 全在「纯技术 5.3%」桶裡,期望值 200×5.3% ≈ 10 支——0 支略低於期望但同一數量級;若换到基本面桶,同樣 200 次模擬的期望是 80 支。這是整份報告最重要的一條。

---

## 5. 哪些資料集/欄位最容易出成績

- **[作者實測宣稱]**(wq-alpha-research,2026-06)最穩起點三個字段:`operating_income/equity`、`est_eps/close`、`free_cash_flow_reported_value/equity`;中性化用 SUBINDUSTRY 通過率最高。
- 同來源的 USA TOP3000 delay=1 字段普查:fundamental 1652 欄、analyst 1324、news 996、**pv 只有 195**、option 138、model 40、socialmedia 22。**[推論]** pv 欄位最少、用的人最多,self-correlation 池最擠;fundamental+analyst 合計近 3000 欄,是藍海。
- **[作者實測宣稱]**(James T. Glazar,IQC 2021,https://jglazar.github.io/projects/wq_project/):測 1,103 支、提交 28 支,「Price reversion strategies proved most effective」;news/social buzz 類「performed especially well starting around March 2020」。**時效警告:2021 年資料,價量反轉如今是最擁擠賽道。**
- 中國市場模型字段(alexisdpc 範例):`mdl175_volatility`、`mdl175_revenuettm`——**[推論]** 換 region(CHN)本身就是降 self-correlation 的槓桿之一(相關只跟同 region 比,見 3.2)。
- 該 skill 倉庫的 references/ 目錄有現成的 4,367 欄字段清單(JSON/CSV)可直接下載離線查:https://github.com/QuantML-Research/wq-alpha-research/tree/main/references

---

## 6. 紅線:什麼會被判 gaming / 封號

### 6.1 官方白紙黑字(WorldQuant IQC Guidelines,2026 賽季,原文照抄)
出處:https://www.worldquant.com/brain/iqc-guidelines/
> 「if we detect any signs of **'gaming,' sharing, cheating** or any other unethical or dishonest behavior, we will **terminate the participant's and/or the team's account**」
> 「disqualify the alpha or terminate the participant's and/or the team's account **without any notice** if we find the **deliberate introduction of 'noise'** to subvert our scoring」
> 「**Duplicate accounts** for one individual are grounds for disqualification not only from the IQC but also from BRAIN and the WorldQuant Challenge.」
> 帳號不得共用;alpha 必須是「your original」work。

**[推論]** 界線解讀:
- 「deliberate noise injection」直接點名:**為了繞過 self-correlation 而往表達式裡摻雜訊,是官方明文的封號項**。同信號加 `+0.001*rank(vwap)` 這類擾動屬高風險。
- 「一人多帳號」是全平台(不只比賽)取消資格——想開小號重跑積分 = 紅線。
- 帳號共用、代寫共享 alpha = 紅線。

### 6.2 自動化/API 批量模擬的界線(社群現況,非官方保證)
- 公開的自動挖掘工具不少且長期存活:worldquant-miner(LLM+遺傳演算法,https://github.com/zhutoutoutousan/worldquant-miner)、WQ-Brain(https://github.com/RussellDash332/WQ-Brain)、wq-alpha-research、知乎公開的 QuantGPT 全自動提交文。這些 README **都沒有**記載因 API 自動化被封號的案例。
- 平台硬限制(worldquant-miner 記載):Pre-Consultant 最多 **5 併發模擬**;工具自律「Submits only once per day」。wq-alpha-research 建議:模擬間 sleep 2–5 秒、429 讀 Retry-After 退避、≤2 併發。
- **[推論]** 社群共識畫出的安全界線:**用 API 批量「模擬」沒人出事;出事的紅線在「提交端造假」**——噪音注入、多帳號、抄襲共享。另外百度貼吧有「账号莫名其妙被封」帖(內文讀不到,原因不明),自動化仍應保守限速。
- 誠信對照:BRAIN 官方 FAQ/文件未找到「每日提交上限」的明文數字(社群說法從 1 到 4 不等),此處**不要**拿本文件當授權依據。

---

## 7. 快速可抄的完整檢查清單(wq-alpha-research 原文,2026-06)

> - 新因子与已有 ACTIVE alpha **日收益**相关性 < 0.7(或新 Sharpe ≥ 旧 Sharpe × 1.1)
> - Sharpe ≥ 1.3(理想 ≥ 1.5);Fitness ≥ 1.1;Turnover 1%–20%(可放宽至 ≤ 35%);Drawdown < 15%
> - 提交后**再次确认 status == ACTIVE,201 不代表上线**

(其 delay-0 門檻另見知乎驗證文:Sharpe > 2、fitness > 1.3。你在 delay-1,照上面即可。)

---

## 8. 結論(給 Carson 的三句話)

1. **蹺蹺板不是要「破」,是要「繞」**:它是 pv1 高換手信號的結構性產物;換到 fundamental/analyst 字段(TO 2–16%),分母觸 0.125 地板,fitness 只剩 Sharpe×sqrt(8×returns),一個變數消失。
2. **200 支 0 過符合「纯技术 5.3% 通过率」的統計預期**,不是你手藝問題,是賽道選擇問題。
3. **紅線清楚**:噪音注入繞 self-correlation、多帳號、共用/抄襲 = 官方明文封號;API 批量模擬(限速 ≤2 併發、sleep 2–5s)= 社群長期實踐無事故記錄。
