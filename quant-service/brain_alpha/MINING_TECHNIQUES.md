# WorldQuant BRAIN Alpha 挖掘技術彙整(外部實作考察)

> 產出日期:2026-08-27。來源:5 個指定 GitHub repo 全部 clone 下來親手讀原始碼,外加 2 個搜尋到的 repo(`QuantML-Research/wq-alpha-research`、`dige04/WQ-Brainn`)與 CSDN/個人網站文章。
> 標示約定:**[原始碼]** = repo 裡實際存在的程式碼/資料;**[README宣稱]** = 文件宣稱、未見程式驗證;**[推論]** = 我的推論,非來源明說。
> 本機 clone 位置(暫存,session 結束會清):`C:\Users\User\AppData\Local\Temp\claude\D--carson-agent\60590d32-091f-4e7a-9837-215e939e0e68\scratchpad\`

---

## 0. 最重要的結論(先讀這段)

你的蹺蹺板(Sharpe 1.46 / fitness 0.90 vs Sharpe 0.77 / fitness 1.33)在外部實作裡有明確的、被反覆驗證的解法,而且**全部指向同一件事:離開 pv1,改用低自然換手的 fundamental / analyst / model 資料集**。

證據鏈:
1. `fitness = Sharpe × sqrt(|returns| / max(turnover, 0.125))`。turnover 有 12.5% 地板 → **把換手壓到 12.5% 以下後,再壓沒有任何 fitness 收益**;但從 50%+ 壓到 12.5%,fitness 乘數從 ~0.4 升到 ~0.75+。pv1 價量訊號天生高換手,所以你在 pv1 上永遠在蹺蹺板兩端跳。
2. `wq-alpha-research/SKILL.md`(USA TOP3000 實戰統計)**[原始碼]**:失敗占比 LOW_SHARPE 90.7%、LOW_FITNESS 66.2%;**按資料類型的通過率:基本面 40% > 混合 12.7% > 純技術 5.3% > 其他 0%**。基本面質量因子 decay=0 的預期換手只有 **2–8%**,分析師 9–16%——換手直接掉進 fitness 地板區,蹺蹺板消失,剩下的唯一問題就是把 Sharpe 拉上 1.25。
3. `worldquant-miner` 的 `alpha_tracking.json` 裡 725 條實測 green alpha(**[原始碼]**,該工具自動記錄的模擬結果)中,同時過 Sharpe≥1.25 / fitness≥1.0 / TO≤0.7 的 396 條,幾乎全部用 anl / fnd / mdl / rp / mws 字段,**換手集中在 0.02–0.27**,沒有一條是純 pv1 價量。

---

## 1. 可直接照抄的表達式(逐字,含宣稱指標)

### 1.1 有實測指標的完整 alpha

來源 A:`jglazar.github.io/projects/wq_project/`(WorldQuant 國際賽參賽者的公開 write-up,指標為其自報)**[README宣稱]**

```
(high + low)/2 - close
```
Sharpe 1.80 / fitness 1.03 / TO 51%。TOP3000,market neutralization。

```
rel_days_since_max = rank(ts_arg_max(close, 30));
decline_pct = (vwap - close) / close;
decline_pct / min(ts_decay_linear(rel_days_since_max, 1), 0.15)
```
Sharpe 1.58 / fitness 1.09 / TO 49%。TOP200,market。

```
-ts_zscore(enterprise_value/ebitda, 63)
```
Sharpe 2.00 / fitness 1.26 / TO 25%。TOP3000,industry。← 注意:一行基本面估值,TO 只有 25%,fitness 直接過。

```
avg_news = vec_avg(nws12_afterhsz_sl);
rank(ts_sum(avg_news, 60)) > 0.5 ? 1 : rank(-ts_delta(close, 2))
```
Sharpe 1.84 / fitness 1.08 / TO 9%。TOP3000,subindustry。← 新聞字段當 gate、技術反轉當訊號的混合。

```
buzz = ts_backfill(-vec_sum(scl12_alltype_buzzvec), 20);
ts_av_diff(buzz, 60)
```
Sharpe 1.94 / fitness 1.35 / TO 45%。TOP3000,subindustry。← 兩項同時高,用的是 social buzz 資料集。

來源 B:`worldquant-miner/generation_one/consultant-templates-ollama/alpha_tracking.json`(工具自動記錄的 BRAIN 模擬結果,green_alphas 區)**[原始碼]**。挑換手「真實」(<0.45)且同過雙門檻的:

```
trade_when(normalize(mdl26_forward_pe_mean_fy1 - current_ratio), mdl26_dsnc_bld_stmt_fq1_rnngs > 50, ts_decay_linear(mdl26_chng_frm_52wk_lw_prc, 30))
```
CHN,Sharpe 5.50 / fitness 20.28 / TO 0.268。

```
ts_backfill(add(ts_zscore(vec_avg(nws17_multiple_comp_d1_bee), 250), ts_zscore(vec_avg(mdl307_atlas_unit_name), 250)), lookback=60)
```
EUR,Sharpe 5.74 / fitness 7.02 / TO 0.048。

```
subtract(0, log(ts_max(mdl54_dma_monthly, 30) - ts_min(fn_allocated_share_based_compensation_expense_a, 30)) * fn_assets_fair_val_l2_q / abs(fn_avg_diluted_shares_q))
```
USA,Sharpe 1.74 / fitness 3.05 / TO 0.038。(檔案內表達式被截斷處我以 `fn_avg_diluted_shares_q` 補完欄位名——**[推論]**,原檔第 160 字元後截斷;其餘逐字。)

```
rank(multiply(abs(fnd23_1oscq), abs(cashflow_op), assets, mdl110_score))
```
ASI,Sharpe 2.11 / fitness 1.40 / TO 0.071。

```
ts_min(mdl110_score, 25)
```
ASI,Sharpe 1.58 / fitness 1.17 / TO 0.038。← 一個運算子 + 一個 model 字段就同時雙過,說明字段選擇 > 表達式複雜度。

```
rank(ts_sum(debt_st, 20), rate=0) * rank(star_sr_coverage, rate=0) * ts_target_tvr_decay(mdl110_score, lambda_min=0.5, lambda_max=1, target_tvr=0.05)
```
ASI,Sharpe 1.82 / fitness 1.34 / TO 0.067。← 注意 `ts_target_tvr_decay(..., target_tvr=0.05)`:直接指定目標換手率的運算子。

```
ts_zscore(vec_avg(mdl14_2_d1_target_price_space), 250)
```
CHN,Sharpe 1.52 / fitness 1.12 / TO 0.216。

⚠️ 同檔案裡 GLB 區有一批 Sharpe 9–18 / fitness 15–24 的 `anl11_*` 表達式(如 `max(anl11_cit_totalcor, anl11_2_gse) * ts_delay(anl11_citregsubsecrnk, 1) / fnd44_probability_restatement`)。指標是工具記錄的真實模擬輸出,但 **[推論]** 這種量級極可能是窄覆蓋率字段造成的 artifact(long/short count 少、sub-universe 會掛),照抄前先看 coverage。

來源 C:`alexisdpc/WorldQuant-alpha-trading/README.md` **[README宣稱]**(自稱 high Sharpe,未附數字):

```
SMA_30 = ts_mean(close,30);
rank(SMA_30 - close)
```
USA TOP3000 / Subindustry / Decay 4 / Truncation 0.08 / Pasteurization Off。

```
event = volume>adv20;
alpha = (-ts_delta(close,5));
trade_when(event,alpha,-1)
```
USA TOP3000 / Subindustry / Decay 2 / Truncation 0.01。

```
alpha = ts_rank(cashflow_op/cap,60);
group_rank(alpha, subindustry)
```
USA TOP3000 / Subindustry / Decay 4 / nanHandling On。

```
rank(-mdl175_volatility*log(volume))
    *(1+group_rank(mdl175_revenuettm, sector))
```
CHN TOP3000 / Delay 0 / Sector / Decay 3。

同 repo `ImprovingAlphas.md` 的完整「改良鏈」範例:

```
raw     = -ts_delta(close, 5) / close;
norm    = rank(winsorize(raw, 4));
neutral = group_neutralize(norm, sector);
smooth  = ts_decay_linear(neutral, 10);
event   = volume > adv20;
alpha   = trade_when(event, smooth, -1);
```

來源 D:`QuantML-Research/wq-alpha-research/SKILL.md` 模板庫(自稱「高胜率模板」,附實戰統計但無逐條指標)**[原始碼]**:

```
group_rank(ts_rank(operating_income / equity, 126), subindustry)
group_rank(ts_rank(est_eps / close, 126), industry)
group_rank(ts_rank(free_cash_flow_reported_value / equity, 126), industry)
0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry)
+ 0.5 * group_rank(ts_rank(est_eps / close, 126), industry)
0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))
rank(ts_rank(operating_income / sales * sales / assets, 126))
```
配套設定表(同檔):基本面質量 decay=0 / SUBINDUSTRY / trunc 0.08 / nanHandling ON → 預期 TO 2–8%;分析師 decay 0–4 → TO 9–16%;技術反轉 decay 10–30 → TO 15–35%。

來源 E:`worldquant-miner/.../templateRAW.txt`(顧問級種子模板,逐字)**[原始碼]**:

```
sentiment = ts_backfill(ts_delay( vec_avg(SENTIMENT FROM OTHER),1),20) ;
vhat=ts_regression(volume,sentiment,250);
ehat=-ts_regression(returns,vhat,750);
alpha=group_rank(ehat,bucket(rank(cap),range='0,0.1,0.1'))
```
(`SENTIMENT FROM OTHER` 是留給你代入 vector 情緒字段的槽位——**[推論]**。)

```
group_normalize(ts_zscore(winsorize(ts_backfill(anl4_afv4_eps_high, 120), std=4), 66),densify(industry))
```

來源 F:CSDN `worldquant操作笔记`(weixin_43249038,155161233)**[README宣稱]**:

```
zscore(rank(ts_rank(pretax_income, 250) * ts_rank(sales, 250)))
```

來源 G:`RussellDash332/WQ-Brain/arxiv.txt` = 101 Formulaic Alphas 全文(100 行,舊 WebSim 語法)**[原始碼]**。範例第 1 條:

```
(rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5
```
⚠️ 這批是 2015 年論文因子、全 pv1、且用舊語法(`correlation`→`ts_corr`、`delta`→`ts_delta`、`stddev`→`ts_std_dev`、`decay_linear`→`ts_decay_linear`、`adv20` 要自己定義)。**[推論]** 以你「pv1 已擁擠 206 萬條」的處境,這批的邊際價值最低,只當運算子組合的靈感庫用。

### 1.2 一階模板(拿來大量掃字段的)

`angel4angelov-glitch/wq-alpha-pipeline/src/wq_pipeline/runner.py` 的 8 條模板(含它自己第一批 222 次模擬的戰果註記)**[原始碼]**:

```python
Template(name="ts_mean_10",        expression="ts_mean({f}, 10)",        decay=4, truncation=0.01),
Template(name="ts_zscore_63_neg",  expression="-ts_zscore({f}, 63)",     decay=4, truncation=0.01),
Template(name="ts_rank_22_neg",    expression="-ts_rank({f}, 22)",       decay=4, truncation=0.01),
Template(name="ts_delta_5_rank",   expression="rank(ts_delta({f}, 5))",  decay=4, truncation=0.01),
Template(name="ts_zscore_22",      expression="ts_zscore({f}, 22)",      decay=4, truncation=0.01),
Template(name="ts_delta_5_rank_neg", expression="-rank(ts_delta({f}, 5))", decay=4, truncation=0.01),
Template(name="ts_delta_22_rank",  expression="rank(ts_delta({f}, 22))", decay=4, truncation=0.01),
Template(name="ts_zscore_252_neg", expression="-ts_zscore({f}, 252)",    decay=4, truncation=0.01),
```
原始註解:`rank_neg` 掃過一批後平均 Sharpe -0.27 被砍;`ts_delta_5_rank`(max 0.98)與 `ts_zscore_63_neg`(max 0.91)是頭兩名。字段來源限 `fnd6_`、`pv13_` 前綴,按 userCount 排序取熱門。

`dige04/WQ-Brainn/README.md` 的三階模板 **[原始碼+README]**:
- brain2:`group_rank(({field})/cap, subindustry)` 掃全部 MATRIX 字段
- brain3:`<group_op>(<ts_op>(<field>, <days>), <group>)`,group_op ∈ {group_rank, group_zscore, group_neutralize},ts_op ∈ {ts_rank, ts_zscore, ts_av_diff},days ∈ {60, 200},group ∈ {market, industry, subindustry, sector, densify(pv13_h_f1_sector)}

---

## 2. 表達式產生方法論(誰在用什麼)

### 2.1 中國社群「Alpha 工廠」三階流水線(最成熟、最值得照抄)

出處:`dige04/WQ-Brainn/Alpha_Factory/`(簡中註解原版)與 `zhutoutoutousan/worldquant-miner/stone_age/python/`(同一套碼的英文化擴充版,pre_consultant_non_ai + consultant 兩份)。**[原始碼]**

流程(notebook `Alpha Machine Factory.ipynb` 逐 cell 實作):

1. **選一個資料集**(範例用 `analyst4`,不是 pv1),`get_datafields()` 拉全部字段。
2. **字段預處理**:MATRIX 字段直接用;VECTOR 字段套 8 種 vec 運算子展開(`vec_avg/vec_sum/vec_ir/vec_max/vec_count/vec_skewness/vec_stddev/vec_choose(nth=-1|0)`);然後**每個字段一律包 `winsorize(ts_backfill(%s, 120), std=4)`**(補缺失值提 coverage + 去極值,一次解 CONCENTRATED_WEIGHT 和稀疏字段問題)。
3. **一階工廠** `first_order_factory(fields, ts_ops)`:每字段 × 每 ts 運算子 × days ∈ **[5, 22, 66, 120, 240]** 全展開。初始 decay=6。SUBINDUSTRY 中性化模擬。
4. **收割+剪枝**:`get_alphas()` 用 API 撈 sharpe>1、fitness>0.7 的一階倖存者(**負 Sharpe < -1.2 的也收,表達式前面加 `-` 翻正**);`prune(recs, 'anl4', 5)` 每個字段只留 top-5 Sharpe,避免同字段淹沒回測額度。
5. **decay 階梯**(`get_alphas` 內建,依換手自動加 decay 再回測)**[原始碼]**:
   - TO > 0.7 → decay×4;TO > 0.6 → decay×3+3;TO > 0.5 → decay×3;TO > 0.4 → decay×2;TO > 0.35 → decay+4;TO > 0.3 → decay+2;否則不動。
6. **二階工廠**:對一階倖存者套 `group_ops(ts_ops(field, days), group)`,group_op ∈ {group_neutralize, group_rank, group_zscore},group 除了 market/sector/industry/subindustry 外還有整卡車**分群字段**(見 §3.3)與三個 bucket 模板:
   ```
   bucket(rank(cap), range='0.1, 1, 0.1')
   bucket(group_rank(cap,sector),range='0,1,0.1')
   bucket(rank(ts_std_dev(ts_returns(close,1),20)),range = '0.1,1,0.1')
   bucket(rank(fnd28_value_05480/close), range='0.2, 1, 0.2')
   ```
   全部包 `densify()`。
7. **三階工廠 = trade_when 事件疊加**(專治換手/fitness):`trade_when(open_event, alpha, exit_event)`,open_event 從 22 條事件池挑(逐字,`machine_lib.py trade_when_factory`):
   ```
   ts_arg_max(volume, 5) == 0
   ts_corr(close, volume, 20) < 0
   ts_corr(close, volume, 5) < 0
   ts_mean(volume,10)>ts_mean(volume,60)
   group_rank(ts_std_dev(returns,60), sector) > 0.7
   ts_zscore(returns,60) > 2
   ts_skewness(returns,120)> 0.7
   ts_arg_min(volume, 5) > 3
   ts_std_dev(returns, 5) > ts_std_dev(returns, 20)
   ts_arg_max(close, 5) == 0
   ts_arg_max(close, 20) == 0
   ts_corr(close, volume, 5) > 0 / > 0.3 / > 0.5
   ts_corr(close, volume, 20) > 0 / > 0.3 / > 0.5
   ts_regression(returns, %s, 5, lag = 0, rettype = 2) > 0     # %s = 該 alpha 的字段
   ts_regression(returns, %s, 20, lag = 0, rettype = 2) > 0
   ts_regression(returns, ts_step(20), 20, lag = 0, rettype = 2) > 0
   ts_regression(returns, ts_step(5), 5, lag = 0, rettype = 2) > 0
   ```
   exit_event ∈ `["abs(returns) > 0.1", "-1", "days_from_last_change(ern3_pre_reptime) > 20"]`。
   另有 USA 專用情緒 gate 池:`rank(rp_css_business) > 0.8`、`ts_rank(vec_avg(mws82_sentiment),22) > 0.8`、`rank(vec_avg(nws48_ssc)) > 0.8`、`ts_rank(vec_sum(scl12_alltype_buzzvec),22) > 0.9`、`pcr_oi_270 < 1`、`pcr_oi_270 > 1` 等(TWN 池:`rank(vec_avg(mdl109_news_sent_1m)) > 0.8`、`rank(rp_ess_business) > 0.8`)。
8. **提交檢查**:撈 sharpe≥1.25 / fitness≥1 的,逐一打 `/alphas/{id}/check`,全 PASS 且拿到 PROD_CORRELATION 值的進 gold_bag,按 Sharpe 排序手動提交。

### 2.2 模板網格暴掃(wq-alpha-pipeline)

簡單模板 × 熱門字段 × universe × neutralization 全交叉 → SQLite 記錄 → `survivors.py` 篩(**Sharpe≥1.25、fitness≥1.3、|margin|≥50bp、TO 0.01–0.7**,加四個結構檢查 concentrated_weight / low_sub_universe_sharpe / matches_competition / units 不得 FAIL)→ `correlation.py` 拉每條 PnL、**diff 成日收益**算兩兩相關,**貪婪選籃:按 |Sharpe| 降序,只留與已選集合 max|corr| 低於門檻的**。負 Sharpe 反向利用(`allow_inverse`)。**[原始碼]**

### 2.3 LLM 生成(worldquant-miner gen1/gen2、Brainiac)

- worldquant-miner consultant-templates-ollama:Ollama 本地模型 + persona 輪替生成模板,multi-arm bandit 做 explore/exploit(exploit = 從 top 模板變異),operator blacklist 自動維護,模板 3 次零 PnL 即刪。green/yellow/red 三色記錄(green = sharpe>1.5)。**[原始碼]**
- Brainiac:研究論文 PDF → LlamaParse → LLM 抽策略 JSON → 第二個 prompt 拿著「你帳號有權限的 dataset 清單(含 coverage、userCount)+ 運算子速查表」把策略翻成 Fast Expression → 自動回測。它的 `Datasets/*.csv` 就是給 LLM 的字段選單。**[原始碼]**
- **[推論]** 這兩套的實際價值不在 LLM,在它們附帶的資料檔:operatorRAW.json(全運算子)、alpha_tracking.json(1.7 萬條含指標的實測記錄)、Datasets/*.csv。

### 2.4 進化演算法

worldquant-miner generation_two/evolution/ 有 `alpha_evolution_engine.py`(genetic evolution)、`advanced_bandits.py`、`self_optimizer.py`。**[README宣稱]** 自我優化;我沒逐行驗證其 GA 實際效果,無實測指標檔佐證。

---

## 3. 資料集/欄位情報(pv1 以外)

### 3.1 實測有效的字段家族(從 396 條雙過門檻 green alpha + 各 repo 彙總)**[原始碼]**

| 家族 | 例子 | 用法 | 出處 |
|------|------|------|------|
| analyst(anl4/anl11/anl69/anl81) | `anl4_afv4_eps_high`、`anl69_best_cur_fiscal_semi_year_period`、`anl81_probability_of_default_percent` | ts_zscore/group_rank,decay 0–4 | templateRAW、alpha_tracking |
| fundamental(fnd6/fnd23/fnd28/fnd44/fn_) | `fnd6_pnrsho`、`fnd23_1oscq`、`fnd44_probability_restatement`、`fnd44_jones_cf_accruals`、`fnd28_value_05480` | 一階掃 + /cap /equity 比值 | wq-alpha-pipeline、alpha_tracking |
| model(mdl10/mdl14/mdl26/mdl36/mdl54/mdl110/mdl175/mdl307/mdl109/mdl110) | `mdl110_score`(一個運算子就雙過)、`mdl26_forward_pe_mean_fy1`、`mdl175_volatility` | ts_min/ts_zscore/直接 rank | alpha_tracking、alexisdpc |
| RavenPack 情緒(rp_css_*/rp_ess_*) | `rp_css_business`、`rp_ess_mna`、`rp_ess_product` | 當 trade_when gate 或乘數 | machine_lib、alpha_tracking |
| earnings call(mws36/mws38/mws50/mws52/mws82/mws84/mws85) | `mws52_sentences_in_qa`、`mws82_sentiment` | gate + 分母 | machine_lib、alpha_tracking |
| news(nws3/nws12/nws17/nws20/nws48) | `nws12_afterhsz_sl`、`nws17_multiple_comp_d1_bee` | vec_avg 後 ts_zscore 250 | jglazar、alpha_tracking |
| social buzz(scl12) | `scl12_alltype_buzzvec` | vec_sum + ts_backfill | jglazar、machine_lib |
| option | `pcr_oi_270`(put/call OI 比) | 二值 gate | machine_lib |
| 事件 | `ern3_pre_reptime` + `days_from_last_change()` | exit event | machine_lib |
| 分群字段(當 group 用) | `pv13_*_sector`、`sta1_*`/`sta2_*`/`sta3_*`、`rsk69_*`、`anl52_*`、`oth455_*`(關係圖譜 n2v 聚類)、`oth171_*` | `group_rank(x, densify(pv13_r2_min2_3000_sector))` | machine_lib group_factory(每個 region 各有清單,USA 的逐字在 §2.1 出處檔) |

### 3.2 USA TOP3000 delay=1 字段普查 **[原始碼]**

`wq-alpha-research/references/wq_usa_top3000_delay1_data_fields.json` 收錄完整 4367 個字段(fundamental 1652、analyst 1324、news 996、pv 195、option 138、model 40、socialmedia 22)。這個檔可以直接抄回來當你的字段選單,省掉自己打 API。

### 3.3 pv13 的另一個用途

pv13 不只是價量——`pv13_*_sector` 系列是**現成的股票分群字段**,machine_lib 把它們全當 `group_rank`/`group_neutralize` 的 group 參數用(USA:`pv13_h_min2_3000_sector`、`pv13_r2_min20_3000_sector`、`pv13_r2_min2_3000_sector`、`pv13_h_min2_focused_pureplay_3000_sector`)。**[原始碼]** 你現有的 pv1 訊號換成這些非標準分群做中性化,是最便宜的差異化手段之一(**[推論]**:同時能降 SELF_CORRELATION,因為權重分配路徑不同)。

---

## 4. 蹺蹺板專章:同時拉高 Sharpe 和 fitness

外部實作裡明確處理過這件事的做法,按力度排序:

1. **換資料集(治本)**。fitness 卡住的根源是 `sqrt(|returns|/turnover)` 這一項。基本面/分析師字段 decay=0 換手就只有 2–16%(SKILL.md 設定表,實戰統計佐證),此時 fitness ≈ Sharpe × sqrt(|returns|/0.125),**蹺蹺板消失,兩個指標變成同向**。你的 206 萬條 pv1 競品同時也解釋了為什麼 pv1 上的殘存訊號又弱又擁擠。
2. **trade_when 三階(治標最有效)**。中國社群工廠把它列為專門一階(§2.1 第 7 步):訊號不變、只在事件日換倉 → returns 幾乎不動、turnover 大砍 → fitness 直接上去,Sharpe 通常還會微升(少交易 = 少噪音)。22 條 open_event 池逐字可抄。
3. **decay 階梯(機械化)**。§2.1 第 5 步的表:照換手區間直接乘/加 decay 再回測一次,不用猜。
4. **換手目標運算子(一步到位)**:`ts_target_tvr_decay(x, lambda_min=0.5, lambda_max=1, target_tvr=0.05)` 在 alpha_tracking 的雙過樣本裡實際出現;CSDN(Oo_Amy_oO,147725000)另外點名 `ts_target_tvr_hump`、`ts_target_tvr_delta_limit`、`ts_delta_limit`、`hump_decay`、`jump_decay`。這些是「把 turnover 當參數直接指定」的運算子,比手動 hump 調參快。
5. **混合慢訊號**。`0.5*rank(-(close/open-1)) + 0.5*rank(ts_rank(operating_income/equity,126))`(SKILL.md 模板 E):50/50 摻一個基本面慢因子,換手被拉低、Sharpe 靠兩腿分散,兩指標同升。SKILL.md 實戰註:「fitness failures are often turnover problems in disguise;decay 和 signal mixing 是第一批要檢查的槓桿」。
6. **注意 0.125 地板**:TO 壓到 12.5% 以下後繼續壓沒有 fitness 收益,只會犧牲訊號(ImprovingAlphas.md 明說)。所以最佳工作區是 TO 5–20% + 全力拉 Sharpe。
7. **returns 那一項別忘了**:fitness 分子是 |returns|。**[推論]** 你 Sharpe 1.46 / fitness 0.90 的組合,若 TO 已在 0.3 以下,那卡的是 returns 太小——解法不是再壓換手,而是加 booksize 利用率(避免大量 NaN 權重、用 ts_backfill 提 coverage)或選波動較大的字段。

---

## 5. SELF_CORRELATION 的做法

來源:`wq-alpha-research/SKILL.md` §8(對自己 ACTIVE alpha 池做過日收益相關普查)**[原始碼]**:

- **鐵律:相關性必須用日收益(daily PnL diff)算,不能用累計 PnL**。累計曲線自帶趨勢,兩兩相關普遍 >0.90,會誤判所有因子都一樣。(它的 `fetch_pnl` + `daily_returns` 程式碼逐字可抄,§7.2。)
- 實測數據:同信號簇內相關 0.74–0.84(兩個 open-close 反轉混合權重不同 → 0.84;兩個分析師 EPS → 0.74;兩個槓桿/質量因子 → 0.84);跨簇(scl12 buzz vs est_eps/close)也還有 0.59–0.67。
- **結論(原文)**:「換窗口、換權重、換 neutralization 不能創造真正的低相關。真正的低相關來自完全不同的資料來源或經濟邏輯。」在 USA TOP3000 常規池裡,日收益相關 0.3–0.6 就算「低」,不要追求 0。
- 豁免通道:與舊 alpha 相關 ≥0.7 時,新 alpha Sharpe ≥ 舊 × 1.1 仍可提交(和你從 API 抓到的規則一致;它的自動提交模板把這條寫進判斷式)。
- 提交後必須二次確認 `status == ACTIVE`:POST /submit 回 201 不代表上線,SELF_CORRELATION 未過會停在 UNSUBMITTED。
- wq-alpha-pipeline 的做法(§2.2):乾脆在自己這端先做**貪婪去相關選籃**(門檻自訂,PnL 有 .npz 磁碟快取),只提交籃內的。
- **[推論]** 綜合以上:你要避 SELF_CORRELATION,優先順序是「換資料集家族 > 換分群(pv13/sta/oth455 當 group)> 換 horizon > 調參」,最後一項基本無效。

---

## 6. 你目前清單以外、外部實作高頻使用的運算子

(你已用:rank / ts_rank / ts_delta / ts_mean / ts_std_dev / ts_max / ts_decay_linear / hump / trade_when / sign / group_neutralize / ts_backfill)

| 運算子 | 外部用法 | 出處 |
|--------|----------|------|
| `winsorize(x, std=4)` | 與 ts_backfill 焊死成標準前處理:`winsorize(ts_backfill(f,120), std=4)` | machine_lib(所有字段一律套) |
| `ts_zscore(x, d)` | 一階掃描主力(-ts_zscore(f,63) 是 wq-alpha-pipeline 冠軍模板之一) | 多處 |
| `group_rank(x, g)` / `group_zscore(x, g)` | 「group_rank + ts_rank 是黃金組合」 | SKILL.md 核心經驗 5 |
| `bucket(rank(x), range='0,1,0.1')` + `densify(g)` | 自製分組(市值分桶、波動分桶、板塊內市值分桶)餵給 group_* | machine_lib group_factory |
| `ts_regression(y, x, d, lag=0, rettype=2)` | rettype=2 取斜率當 gate;嵌套兩層做殘差 alpha(templateRAW 第 1 條) | machine_lib、templateRAW |
| `ts_av_diff(x, d)` | x 減 d 日均值(容 NaN),jglazar buzz alpha 主體 | jglazar |
| `vec_avg / vec_sum / vec_ir / vec_max / vec_count / vec_skewness / vec_stddev / vec_choose(f, nth=-1)` | VECTOR 字段唯一入口,不套就不能用整批新聞/情緒資料集 | machine_lib get_vec_fields |
| `ts_target_tvr_decay(x, lambda_min=, lambda_max=, target_tvr=)` | 直接指定目標換手 | alpha_tracking 實測雙過樣本 |
| `ts_target_tvr_hump` / `ts_target_tvr_delta_limit` / `ts_delta_limit` / `hump_decay` | 換手控制家族 | CSDN 147725000 |
| `jump_decay(x, d, sensitivity=0.5, force=0.1)` | 跳變平滑 | alpha_tracking(GLB 高分樣本) |
| `ts_decay_exp_window(x, d, factor=0.5)` | 指數衰減(比線性激進) | machine_lib arsenal |
| `ts_percentage(x, d, percentage=0.5)` / `ts_quantile` / `ts_moment(x,d,k=2..4)` / `ts_entropy(x,d,buckets=10)` / `ts_min_max_cps` / `ts_min_max_diff` / `inst_tvr` | 一階工廠的「冷門武器庫」(arsenal),原註解意圖就是避開擁擠組合 | machine_lib |
| `ts_corr / ts_covariance / ts_co_kurtosis / ts_co_skewness / ts_theilsen` | 雙字段工廠(field × 其他 field × day) | machine_lib twin_field_factory |
| `signed_power(x, 2)` | 保號平方,放大尾部 | machine_lib、101 alphas |
| `ts_arg_max / ts_arg_min(x, d)` | 事件 gate(`ts_arg_max(volume,5)==0` = 今天放量) | trade_when 事件池 |
| `ts_step(d)` | 造時間序列當回歸自變數(動量 gate) | trade_when 事件池 |
| `days_from_last_change(x)` | 財報後 N 天退出 | trade_when exit 池 |
| `ts_scale / normalize(x, useStd=true, limit=..) / scale_down` | 標準化家族 | alpha_tracking |
| `s_log_1p(x)` | 保號壓縮(注意:machine_lib 把它列在部分帳號拿不到權限的清單裡,先驗證) | machine_lib inaccessible_ops |
| `vector_neut(x, y) / vector_proj(x, y)` | 對 cap 等向量做正交化 | machine_lib arsenal |
| `group_backfill(x, g, d)` | 組內回填 | SKILL.md 運算子表 |
| `last_diff_value / ts_returns / ts_ir / ts_skewness / ts_kurtosis` | 一階工廠 ts_ops 全集成員 | machine_lib |

---

## 7. 各 repo 一句話評價與檔案索引

| Repo | 價值 | 關鍵檔案 |
|------|------|----------|
| zhutoutoutousan/worldquant-miner | ★★★ 本次最大礦:中國社群工廠完整移植 + 1.7 萬條實測記錄 | `stone_age/python/pre_consultant_non_ai/machine_lib.py`(895 行,工廠全集)、`generation_one/consultant-templates-ollama/alpha_tracking.json`(725 green)、`templateRAW.txt`、`operatorRAW.json` |
| dige04/WQ-Brainn(搜尋補入) | ★★★ 工廠簡中原版 + 三階 notebook(操作手冊等級) | `Alpha_Factory/Alpha Machine Factory.ipynb`、`Alpha_Factory/machine_lib.py`、`brain/brain3.py` |
| QuantML-Research/wq-alpha-research(搜尋補入) | ★★★ 唯一直面「失敗統計/相關性真相」的實戰 playbook(中文) | `SKILL.md`(623 行)、`references/wq_usa_top3000_delay1_data_fields.json`(4367 字段) |
| angel4angelov-glitch/wq-alpha-pipeline | ★★ 工程最乾淨的模板網格 + 去相關選籃 | `src/wq_pipeline/runner.py`、`survivors.py`、`correlation.py`、`expressions.py` |
| alexisdpc/WorldQuant-alpha-trading | ★★ 指標公式推導 + 改良運算子對照表(無宣稱指標的範例) | `ImprovingAlphas.md`、`README.md` |
| RussellDash332/WQ-Brain | ★ 101 Alphas 全文 + 批量模擬/scrape 腳本(IS 門檻同你已知) | `arxiv.txt`、`scrape_alphas.py` |
| jdhruv1503/Brainiac | ★ LLM 管線;附 dataset CSV 選單與運算子知識庫 | `AlphaGenerator/utils/program_alphas.py`(prompt)、`Datasets/*.csv`、`utils/BrainKnowledgebaseSyntax/syntax.md` |
| hr-23/Worldquant-Brain-Alpha- | **clone 失敗(空 repo),未取得內容** | — |

網頁來源:
- https://jglazar.github.io/projects/wq_project/ (5 條含指標 alpha)
- https://blog.csdn.net/Oo_Amy_oO/article/details/147725000 (提質量技巧、換手運算子家族)
- https://blog.csdn.net/weixin_43249038/article/details/155161233 (操作筆記)
- https://blog.csdn.net/Yanbang1/article/details/145809309 (顧問挑戰日記,sub-universe sharpe >0.26 說法;VIP 牆後內容未讀到)
- https://deepwiki.com/xiegengcai/world-quant-brain/4.1-self-correlation-analysis (SelfCorrelation 類;原 repo 已 404,只剩 DeepWiki 快取)

## 8. 找不到的東西(誠實申報)

- **沒有任何 repo 給出「已通過 SUBMIT 的表達式 + 完整 IS 指標」的成對公開資料**——最接近的是 alpha_tracking.json(模擬指標,非提交結果)與 jglazar 自報(參賽 write-up)。
- 沒找到明確的 LOW_SUB_UNIVERSE_SHARPE 數值公式第三方驗證(你從 API 抓的 `0.75*sqrt(sub/alpha)*sharpe` 比外部任何來源都精確;CSDN 只有「>0.26」的粗說法)。
- hr-23/Worldquant-Brain-Alpha- 抓不到內容。
- xiegengcai/world-quant-brain 原 repo 已消失,只剩 DeepWiki 摘要。
