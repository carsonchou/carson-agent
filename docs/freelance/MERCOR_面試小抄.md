# Mercor AI 面試小抄

> 2026-08-30 建。**這不是背稿，是提醒你講什麼。**
> 每一句都指得回 `PORTFOLIO.md` 的真實檔案與實測數字 —— 被追問時你答得出來，
> 因為那些事是你做的。

---

## 一、先知道你在面對什麼

```
形式    AI 面試官,即時對話,語音(或語音+視訊),全程錄影
時長    約 20 分鐘
題數    8~12 題,**根據你的履歷即時生成**,每題還會追問一層
評分    具體度 · 主導性(ownership) · 技術深度 · 表達精簡
重考    沒過要等 30 天
```

**它評的四項裡有三項不是「你多會寫程式」**，是「你講不講得清楚、是不是你自己做的、細節記不記得」。

所以核心策略只有一句：**講數字、講你當時怎麼想、講你錯在哪。**

---

## 二、開場題：Tell me about yourself（幾乎必考）

不要背履歷。給三句：**你做什麼 → 你的特點 → 一個證據。**

> I build automation systems that run themselves — data comes in, gets processed,
> ships out, and pages me when something breaks.
>
> What I focus on is correctness under **silent failure**. The dangerous bug in
> these systems is not a crash. It's a wrong number that nobody notices for
> three months.
>
> I have 431 automated tests passing across my own data pipeline and payment
> webhook systems, and I design them to fail loudly rather than guess.

**追問預測**：*What do you mean by silent failure?* → 直接接第五節那三個例子。

---

## 三、主打案例：影片管線 294s → 22.5s

**這是你最強的一題。** 它同時證明「會量測」「不亂花錢」「工程紀律」。

> My video pipeline took 294 seconds to render one clip. Too slow to scale.
> The obvious fix was a better GPU.
>
> I measured first. And the measurement contradicted the assumption —
> **CPU time across the entire render was about 0.2 seconds.** The processor was
> idle for five minutes. So the bottleneck was not compute at all.
>
> It was I/O. moviepy was piping raw frames **one at a time** into ffmpeg over
> stdin. I rewrote that layer as a pure ffmpeg architecture — concat demuxer,
> a single filtergraph, one encode pass.
>
> **294 seconds to 22.5 seconds. Same machine. Zero hardware spend.**

**追問預測與答法：**

| 它可能問 | 你答 |
|---|---|
| How did you measure? | 量 user CPU time,不是只看牆鐘時間。牆鐘慢但 CPU 閒置 = I/O bound |
| Did you compare hardware? | 有。**雲端 2vCPU 170s / 本機 CPU 308s / 本機 RTX 4050 GPU 294s** —— GPU 跟 CPU 幾乎沒差,那就是硬體不是答案的證據 |
| What if the new path breaks? | 舊路徑保留為自動備案,`MV_FORCE_MOVIEPY=1` 可強制切回。**上線不賭單一路徑** |

⚠️ **那三個硬體數字要記住**（170 / 308 / 294）。這種細節是「真的做過」最強的證明。

---

## 四、第二案例：台股資料管線（如果它問資料工程）

> I built a service that consolidates Taiwanese stock market data from several
> official government sources into one queryable system — eight independent
> domains: institutional flows, margin trading, shareholder distribution,
> fundamentals, valuation, quotes, news, technical indicators.
>
> **Every external parser has its own test.** Government sites redesign their
> pages without notice. With tests, you find out the day it breaks. Without them,
> you find out three months later — and by then all your data was wrong.

**追問**：*How many tests?* → 365 in that service. Valuation module alone has 49.

---

## 五、殺手鐧：三個你真的修過的靜默失敗

**如果它問「講一個你解過的難 bug」或「什麼是 silent failure」——講這三個。**
這是整份小抄裡最有價值的東西，因為**編不出來**。

**1. `.get(key, 0)` 回傳 None**

> A dictionary lookup with a default of zero still returned None — because the
> key existed, with a null value. The default never fired. Every downstream
> calculation silently became garbage.

**2. 閘門被改「寬鬆一點」**

> A validation gate was quietly letting bad data through, because at some point
> someone made it "more tolerant". Worse — there were two implementations of the
> same gate, and the fix had been applied to the one nothing actually called.

**3.「超時 = 死掉」殺掉健康的長任務**

> A watchdog killed healthy long-running jobs. It decided a job was dead by
> checking the file's mtime — but never checked whether the process was alive.
> Long jobs legitimately take a long time. The heuristic guaranteed it would kill
> exactly the jobs that mattered most.
>
> The lesson: **any "timeout means dead" rule needs a liveness proof, not just a
> timestamp.**

第 3 個特別好 —— 它同時展示了 debug 能力**和**你從中抽出的通則。

---

## 六、行為題（8~12 題裡通常有 2~3 題）

它評的是 **ownership**：你是主導者還是旁觀者。一律用「我」不用「我們」。

**Tell me about a time you were wrong.**

> I assumed a rendering bottleneck was hardware. I was wrong, and the measurement
> proved it in about ten minutes. Now I measure before I spend — that one habit
> has saved me from buying hardware I didn't need.

**Why do you want this work?**

誠實講就好：想把已經在做的自動化和測試能力用在真實案子上，接觸自己專案碰不到的問題。**不要編對 AI 訓練的熱情。**

---

## 七、實戰注意

```
✓ 講數字:294 / 22.5 / 0.2 秒 / 431 / 365 / 66
✓ 用「我」不用「我們」
✓ 每題 60~90 秒。講完就停,讓它追問 —— 追問是好事,代表它有興趣
✓ 不知道就說不知道,然後說你會怎麼查。**編造是最扣分的**
✗ 不要背稿的語氣。它評「表達」,不是評「流暢」
✗ 不要提 ecommerce 的測試數(623/637/639)—— 那裡有 16 個真失敗,被追問你沒有答案
```

**環境**：安靜房間、耳機麥克風、網路穩、瀏覽器只開這一個分頁。錄影會錄到你，穿正常衣服。

**沒過要等 30 天** —— 準備好再點。看熟這份 + 把那三個硬體數字記起來，大概 30 分鐘。

---

## 八、如果英文口說沒把握

這是真的門檻，不用假裝沒有。三個做法：

1. **先練那三段主答案念出聲**（開場、影片管線、三個 silent failure）。其他題可以慢、可以想，但這三段要順。
2. **允許自己停頓**。AI 面試官不會不耐煩,慢慢講比講錯好。
3. **句子拆短**。`The bottleneck was not compute. It was I/O.` 比長句好講也好懂 ——
   而且它評的其中一項就叫 **communication compression**（表達精簡）。
