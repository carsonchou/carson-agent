# 配額提額申請書 —— 第五輪獨立驗證(2026-09-04,總督導派)

> 目標檔:`youtube_channel/docs/yt_quota_increase_2026-09.md`
> 驗證員 fresh context,找碴視角,不繼承任何人的推論;未改 repo、未 commit,只回報。
> 本檔由總督導落檔。**與前四輪的差別:前四輪問「這句會不會被 Google 抓」,這輪問「這句是不是真的」。**

## 給正在改這份包的人:先讀這五條,它們會改變你怎麼寫

1. **三個常數互相對齊成同一個 11** —— `produce_catchup --target 11`(產,且 `:100` 是 `gap = target - done`,是**地板不是天花板**,實測做到過 29)、`daily_publish --max 10 + --series 1`(發)、`YT_QUOTA_RESERVE=23650 ÷ 2150 = 11.0`(保留)。**「產出 > 上傳能力」這個不等式兩邊都是我們自己的 cron 參數。** 任一個不動,提額不會讓發布量多一支。
2. **`daily_publish` 從來沒有因為配額中止過** —— `ops_log` 全檔「配額用罄」13 次,**全部是維運部門,上架部門 0 次**。長片線 11 進 11 出、一支不欠。
3. 🔴 **`quota exhausted:videos.post 需 1600,今日剩 0` 全部是我們自己的客戶端閘門丟的,不是 Google。** `quota_meter.json` 的 `rejected_calls` 在 09-01~09-04 **連續四天 = 0**。Google 最後一次真的拒絕我們是 08-31(31 次)。⇒ **英文絕對不可以寫沒有主詞的 `were refused` / `blocked by insufficient quota`** ——那是在告訴一個手上有真 403 記錄的審核者「你們拒絕了我們 N 次」。要寫 `our meter declined to attempt`。v3 的 M1 修正做對過一次,09-04 有兩個獨立來源又各犯一次。
4. **`backlog of 81 finished videos awaiting publication` 把三種解方相反的積壓混成一個數**:A 27 支過不了自家品質關(提額完全沒用)/ B 21 支短片排序到不了(要改 `--max` 與 5:1 配比)/ C 33 支長片真排隊(提額有用)。**24 支「老片」全部在 A 和 B,一支都不在真排隊列裡。** 用 81 論證配額不足 = 把自家閘門擋下的 59% 算進 Google 的帳上,而且審核者索取清單就會看到那 27 支標著「我們自己判定不可發布」。
5. **§4 的 `Expected upload volume` 欄寫 `capped by our scheduler`,而 Justification 寫 `the quota supports publishing only ~11`** —— 同一個 11,兩種歸因,**相鄰兩欄都送出去**。(同一節上面兩行才剛為了「表單自相矛盾」加過警告。)

## 真正有 Google 端證據的損害(建議當承重點)

- **時事線**:09-01~09-04 共 12 支,發成功 1 支;其餘卡在上傳(**我方閘門**,措辭見第 3 條)。
- **維運線**:`deploy/crontab.txt:217 / :233 / :542 / :615` 四條排程 08-30 被註解掉,理由欄原文「**暫停·換發布額度**」。這比英文段現用的「39 支標題回填延後」(一次未執行的計畫)強得多。
- **backlog 走平本身就是最強論點**:產 11 = 發 11,存量結構性清不掉,不需要靠「backlog 在成長」(近四天實際只有 +2)。

## 順手發現的產線缺陷(與提額無關,現在就在流血)

`daily_publish.py:752` 排成 5 長 : 1 短 ⇒ 短片只出現在第 6、12、18 名。第 6 名是分數最高的短片 `S_CPI降溫…`,它 audit **確定性失敗**(旁白 73 字,靜態屬性,每晚重算同結果),而隔離**不會**把它移出候選池;`--max 10` 湊滿就 `break`,**永遠走不到第 12 名**。⇒ 一支片永久堵住其餘 32 支的唯一入口,**自 2026-08-25 起連續 10 天發布 0 支短片**。每晚報表那句「隔離 1 支」四天都是同一支。

---

以下為驗證員原文。

# 配額提額申請書驗證 —— 尚未交付的四項

> 目標檔:`D:\carson-agent\youtube_channel\docs\yt_quota_increase_2026-09.md`
> 本檔**只含**下列四項。已交付的內容(A 段、第 1 句裁決、backlog 逐日表、(a)、(b)、`finished` 理由①)一律不重覆。
> 未修改任何檔案、未 commit。

---

# 1. `finished` 不成立的理由 ② 與 ③

## 理由 ②:81 支裡有 69 支**從來沒有被檢查過**,所以「待發」沒有根據

`daily_publish.py:1205-1244` 的審核迴圈:

```python
    todo, quarantined = [], []
    for slug in cands:
        ok, reasons = audit_video.audit(slug)
        if not ok:
            quarantined.append((slug, reasons));  continue
        sc = qmap.get(slug)
        if sc is None: ...          # fail-closed ①
        if scv < floor: ...         # fail-closed ③ 硬地板 60
        if qmin and scv < qmin and not _is_ep0_title(slug): ...   # 門檻 75
        todo.append(slug)
        if len(todo) >= args.max:
            break                   # ← 湊滿 10 支就停
```

`--max 10` ⇒ 每晚只走到序列第 11~12 名。**其餘 69 支從未被 audit 或品質關碰過。**

而且每晚報表寫的「隔離 1 支」不是抽樣殘餘 —— **四天都是同一支**:

```
STUDIO/REPORTS/2026-09-01_自動上架.md  ⚠️ 審核部門攔下 1 支
  S_CPI降溫臺股會漲你以為抄底反而多賠306臺股崩盤回:旁白過短(73字)疑似空殼——內容被剝除後只剩骨架
STUDIO/REPORTS/2026-09-02_自動上架.md  同一支,同一理由
STUDIO/REPORTS/2026-09-03_自動上架.md  同一支,同一理由
STUDIO/REPORTS/2026-09-04_自動上架.md  同一支,同一理由
```

**不是每天新犧牲一支,是同一支每晚重試重敗。而隔離不是出口** —— `find_candidates()` 只排除
「已在 ledger / 在 publish_skip / 被 factguard 擋」三者,隔離不在其中,所以它明天照樣在池子裡。

⇒ `awaiting publication` 描述的是一個**沒有人查證過的狀態**。那 69 支我們自己都不知道能不能發。

---

## 理由 ③:30% 是躺了 2~5 週的死庫存,而且有**確定性機制**保證它們永遠出不去

### ③-a 年齡分佈

81 支的 mtime(台北日):

```
07-29:1  08-05:1  08-06:3  08-08:1  08-09:2  08-11:1  08-12:1  08-13:1
08-14:2  08-15:2  08-16:4  08-17:2  08-18:1  08-22:2        ← 小計 24 支(≥13 天)
08-30:24  08-31:2  09-01:10  09-02:4  09-03:10  09-04:7     ← 小計 57 支
```

格式分佈:短片 33 / 長片 48。**24 支老片裡有 24 支是短片**(老片 100% 是短片)。

### ③-b 為什麼老片不會被消化 —— 短片線的確定性死鎖

**候選序列的產生規則**,`daily_publish.py:752`:

```python
    LONG_PER_CYCLE, SHORT_PER_CYCLE = 5, 1
    merged = []
    li = si = 0
    while li < len(longs) or si < len(shorts):
        for _ in range(LONG_PER_CYCLE):
            if li < len(longs):
                merged.append(longs[li]); li += 1
        for _ in range(SHORT_PER_CYCLE):
            if si < len(shorts):
                merged.append(shorts[si]); si += 1
```

⇒ **短片只會出現在第 6、12、18… 名。**

**今天實跑 `find_candidates()` 的前 16 名:**

```
 # 1 長 分82 L_個股體檢日月光投控37113711抱20年賺4014
 # 2 長 分82 L_個股體檢采鈺6789採鈺6789持股53年總報酬竟是
 # 3 長 分82 L_個股體檢環宇-KY49914991暴賺1899卻套牢
 # 4 長 分82 L_個股體檢訊芯-KY6451抱十年賺388這近七成回撤
 # 5 長 分82 L_個股體檢大毅2478長抱大毅159年報酬率只有242
 # 6 短 分84 S_CPI降溫臺股會漲你以為抄底反而多賠306臺股崩盤回  ← 每晚被 audit 擋的就是它
 # 7 長 分82 L_個股體檢中美晶548318年含息總報酬58長抱竟等1
 # 8 長 分81 L_個股體檢世紀鋼9958抱18年賺692但為何你可能套
 # 9 長 分81 L_個股體檢東捷80648064上市186年總報酬500
 #10 長 分81 L_個股體檢大同2371抱15年報酬率只有722年化報酬
 #11 長 分80 L_個股體檢亞航26302630抱95年賺142最大回撤
 #12 短 分80 S_幣價暴跌63萬你的投資慘賠竟只因為這步驟做錯      ← 永遠走不到這裡
 #13 長 分80 L_個股體檢致伸49154915抱139年賺3424為何
```

**死鎖的完整機制:**

1. 短片依品質分 desc 排,最高分的短片(84 分)是 `S_CPI降溫…`,固定佔住第 **6** 名。
2. 它的 audit 失敗原因「旁白過短(73 字)疑似空殼」是檔案的**靜態屬性** ⇒ 每晚重算結果相同,**確定性失敗**。
3. `--max 10` 的迴圈為湊滿 10 支,走 #1~#5(5 長)、#6(短,隔離)、#7~#11(5 長)= todo 滿 10 ⇒ **break**。
4. **第 12 名(第二支短片)永遠不會被檢查到。**
5. 隔離不會把它移出池子 ⇒ 明天它還在第 6 名。

**⇒ 一支確定性失敗的影片,永久堵住了通往其餘 32 支短片的唯一入口。**

**外部驗證(兩個獨立觀測同時被解釋):**

- 每晚「隔離 1 支」= 剛好那一支,不多不少,四天同一支。
- **daily_publish 自 2026-08-25 起連續 10 天發布 0 支短片**(`STUDIO/REPORTS/*_自動上架.md` 逐檔數 `| L_` / `| S_` 列數):

```
08-22 長 2 短 0     08-27 長 2 短 0     09-01 長10 短 0
08-23 長 1 短 1     08-28 長 4 短 0     09-02 長10 短 0
08-24 長 2 短 1     08-29 長 5 短 0     09-03 長10 短 0
08-25 長 0 短 1 ←最後一支短片            09-04 長10 短 0
08-26 長 5 短 0     08-30 長 7 短 0
                    08-31 長 1 短 0
```

**公平補充(對申請有利,必須說):** 死鎖是「`--max` 太小」+「第 6 名確定性失敗」兩者疊加。
若 `--max` 從 10 提到 11,迴圈就會走到 #12,第二支短片(80 分)會被審。
**所以配額變多確實會鬆開這個死鎖的一部分** —— 但現行文件完全沒描述這件事,而且直接解方是**改 `--max` 或修掉那一支**,不是等配額。

---

## ③-c 由此得到的分堆 —— 81 支裡多少是配額問題

實跑分堆(依 FLOOR=60 / qmin=75 / EP0 豁免 / 格式):

| 堆 | 支數 | 佔比 | 卡在什麼 | 配額變多有沒有用 |
|---|---:|---:|---|---|
| **A** 過不了品質關 | **27**(短12/長15) | 33% | 我們自己的品質閘門 | **完全沒用** |
| **B** 短片,過得了品質關但排序到不了 | **21** | 26% | 5:1 配比 + `--max 10` + 第 6 名死鎖 | 部分有用(須同時提 `--max`) |
| **C** 長片,過得了品質關,真正在排隊 | **33** | 41% | 每日發布名額 | **有用** |

產於 08-23 之前的老片:A 有 **11** 支、B 有 **13** 支、**C 有 0 支**。
⇒ 24 支老片**全部**落在 A 與 B,一支都不在真正的排隊列裡。

長片隊列週轉:C = 33 支,而每日產 11 發 11 ⇒ **淨 0,清償速度 0**。

## ③-d 對送 Google 的文件的意義

`backlog of 81 finished videos awaiting publication` 把三種**解方相反**的積壓混成一個數:

- A(27 支)要的是**修片或降門檻**,給再多配額也不會發出去。
- B(21 支)要的是**改 `--max` / 改 5:1 配比 / 修掉第 6 名那支**。
- C(33 支)才是「配額不夠所以積壓」真正指向的東西。

**用 81 論證「配額不夠」,等於把我們自己閘門擋下的 48 支(59%)算進 Google 的帳上。**
而且可被反證:審核者若索取 backlog 清單,那 27 支低於自家門檻的片會直接顯示為「我們自己判定不可發布」。

**誠實且仍有力的寫法:** `81 unpublished videos, 54 of which pass our quality gate`,或更嚴格地只講 C 的 33 支。
**「產出與上傳恰好打平,存量結構性清不掉」這個論點不需要 81 就成立,而且更難被反駁。**

---

# 2. 第 3 句 —— 六個配額日 `18,760 / 19,645 / 23,341 / 21,858 / 22,910 / 26,001`

## 2.1 我實際跑了什麼

```bash
cd D:/carson-agent/youtube_channel && python -c "
import json,sys; sys.stdout.reconfigure(encoding='utf-8',errors='replace')
d=json.load(open('STUDIO/quota_meter.json',encoding='utf-8'))['days']
for k in sorted(d):
    v=d[k]; b=v.get('by_op',{})
    tot=sum(x['units'] for x in b.values())        # by_op 逐項 units 加總
    ..."                                            # 對 spent、videos.post、rejected_*
python -c "import datetime as dt; from zoneinfo import ZoneInfo;
           print(dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo('America/Los_Angeles')))"
```

## 2.2 原始輸出(逐日,不只平均)

```
現在:UTC 2026-09-04 14:24 / 太平洋 2026-09-04 07:24 / 台北 2026-09-04 22:24
⇒ 最後一個「已關帳」配額日 = 太平洋 2026-09-03

太平洋日     spent   by_op合計  一致  calls  videos.post  =支  上傳鏈   維運   Google真403
2026-08-24    5504     5504   OK     63       4800     3    5350    154      0
2026-08-25   18914    18914   OK    305       8000     5    9250   9664      0   ← 自標 unreliable,文件已排除
2026-08-26   18760    18760   OK    211      14400     9   17300   1460      0   ← 文件第 1 個
2026-08-27   19645    19645   OK    287       9600     6   11050   8595    935
2026-08-28   23341    23341   OK    334      12800     8   15850   7491      2
2026-08-29   21858    21858   OK    440      11200     7   14200   7658     16
2026-08-30   22910    22910   OK    234      16000    10   20400   2510      0
2026-08-31   26001    26001   OK    182      16000    10   20550   5451     31   ← 文件第 6 個
2026-09-01   25206    25206   OK    337      17600    11   23050   2156      0
2026-09-02   24673    24673   OK    245      17600    11   23100   1573      0
2026-09-03   26001    26001   OK    348      17600    11   23100   2901      0
2026-09-04   24931    24931   OK    160      17600    11   23100   1831      0   ← 未關帳
```
(「上傳鏈」= `videos.post + captions.post + thumbnails/set.post`;「維運」= spent − 上傳鏈)

## 2.3 裁決:能復現,對應**太平洋 08-26 ~ 08-31**

**在它自己那個窗裡:成立。**

- 六個數字逐一對上 `STUDIO/quota_meter.json` 的太平洋 08-26~08-31,**一字不差**。
- `by_op` 逐項 units 加總 **12/12 天 = spent,零誤差**(不是抽樣,是全部十二天)。
- 配額日確實是太平洋制:`quota_meter.py` 的 `_pacific_date()`,docstring 明寫
  「配額在太平洋時間午夜重置,換算台北是 15:00~16:00」「帳本以太平洋日期分桶」。
- 「client 端記帳、失敗呼叫照價目計價所以是上界」與程式行為一致:`_execute` 中一般失敗
  照扣進 spent,只有 `_is_quota_rejected(exc)` 為真才改記進 rejected 桶。
- 08-25(18,914)排除的理由(源頭自標 `"unreliable": true`)確實存在於檔案。
- 同段落兩個佐證也對:08-31 桶 `rejected_calls = 31`(> 25 ✔);
  ops_log `[09-01 10:02:26]` / `[09-01 11:38:16]` 兩次上傳被擋,
  台北 09-01 10:02/11:38 = **太平洋 08-31 19:02/20:38**,落在同一配額日 ✔。

**今天(09-04)讀:數字沒錯,但限定詞 `the last six closed quota days` 不成立。**

最近六個已關帳日是 **08-29 ~ 09-03 = 21,858 / 22,910 / 26,001 / 25,206 / 24,673 / 26,001**。
文件那六個是**倒數第 4~9 個**。文件最後一次修訂是 09-03,那時就已經過期兩天。

**英文原文有沒有任何字告訴讀者是哪天量的:沒有。** 只有 `the last six closed quota days` 這個相對表述。

## 2.4 換窗時**必須連動**修改的地方

新窗(08-29~09-03)裡 09-01/09-02/09-03 的 **Google 真 403 都是 0**。
所以同段落的 `more than 25 API calls were rejected by the API with quotaExceeded errors`
在新窗裡只有 08-29(16 次)與 08-31(31 次)撐得住 —— **不改就會從「過期但真」變成「假」。**

附帶:新序列對申請**更有利**(六天全在 21.8k~26k,不是 18.7k 起跳)。

## 2.5 唯一的結構性保留

全機只有 `quota_meter.json` 這一本帳,repo 內沒有第二來源可對。
`by_op` 加總一致只證明它**內部自洽**。**可復現 ≠ 獨立驗證。**

---

# 3. 45,000 的算式有沒有任何一步依賴自家觀測的天花板

## 3.1 算式本身:**沒有。四步全部不碰天花板**

| 步驟 | 數值 | 來源 | 依賴天花板? |
|---|---|---|---|
| 上傳能力需求 | 18 支/日 = 15(穩態良率)+ 2.7(81 ÷ 30 清償) | 毛產出序列、backlog 計數 | ✗ |
| 單支成本 | 2,150 units = 1,600 + 400 + 50 + ~100 | 官方 Quota Calculator 價目表 | ✗ |
| 維運編列 | 4,000~6,000 | `spent − 上傳鏈`,六日中位 5,796 | ✗(只用 spent,不用 limit) |
| headroom | 6,300 = 45,000 − 38,700 | 前兩項相減 | ✗ |

**維運序列我重算過:** 用 `videos.post + captions.post + thumbnails/set.post` 得
`1,460 / 8,595 / 7,491 / 7,658 / 2,510 / 5,451`;
文件的 `860 / 7,845 / 6,991 / 7,058 / 1,710 / 4,601` 每日恰好低 600~850,
差在文件的「上傳鏈」還含 `playlistItems.post` / `commentThreads.post` 那類同批呼叫。
**是口徑定義差異,不是算錯;序列可復現,中位 5,796 也算得出來。**

## 3.2 但有**一步支撐論證**依賴它

**「低值日(860 / 1,710)是被上傳餓出來的,不是需求低」→ 這一步依賴 `effective_limit()`。**

那兩天是太平洋 **08-26** 與 **08-30**,而 §2.2 的表顯示:**那兩天 Google 真 403 = 0,一次都沒拒絕我們。**

讓維運停下來的是我們自己:

- `quota_meter.py:659` 與 `:697` 的 `QuotaExhausted` 是**客戶端在呼叫送出前自己丟的**,
  判準是 `remaining() = effective_limit() − spent(day)`(`:568`),
  而 `effective_limit()`(`:478`)是從帳本自我校準出來的 **26,001**。
- `deploy/crontab.txt` 有 20+ 行維運排程掛 `YT_QUOTA_RESERVE=23650`,`_reserve_guard` 把它們擋在保留線外。

**影響評估:** 這一步是「無餓日需求 4,601~7,845、中位 7,025,所以編列 4,000~6,000 是刻意保守」的地基。
**地基動搖只會讓那一段變得更保守,不會讓 45,000 變大 ⇒ 對請求量本身無害。**

## 3.3 順手查到、比 3.2 更要緊的一件

**09-01 起連續四個配額日,Google 真 403 = 0。**
ops_log 裡那些 `quota exhausted:videos.post 需 1600,今日剩 0`(09-01~09-04 共 9 次)
**全部是我們自己的閘門**,不是 Google。

而 09-03 的 spent 恰好也是 **26,001** —— 因為 `remaining()` 的定義讓 spent 在結構上**不可能**超過
`effective_limit()`。**「08-31 和 09-03 兩天都打到 26,001」不是兩次獨立觀測,是同一條規則觸發兩次。**

外部確認過那道牆的只有 **08-31 一天**(31 次真 403 @ spent 26,001);再往前是 08-27 @ 19,645(935 次)。

**這對現在的文件沒有造成錯誤陳述** —— 英文原文把
`our meter reported 1,600 units required for videos.insert with 0 remaining`(客戶端)與
`more than 25 API calls were rejected by the API with quotaExceeded errors`(08-31 的真 403)
分得很乾淨,v3 驗證員的 M1 修正做對了。

但它讓 §3 那個勾選項變成**承重**:**console 的官方數字是唯一能證明 26,001 不是我們自己畫的線的東西。**

---

# 4. 哪一句我會拒絕在切結書上簽名

## 4.1 三句總表

| 句子 | 在它自己的窗裡? | 今天(09-04)? | 英文有標日期? | 簽? |
|---|---|---|---|---|
| 六個配額日 18,760…26,001 | ✔ 數字與口徑全對 | 數字對、**限定詞錯** | 沒有 | **會**,但送出當天必須換窗,並同步改「>25 次 API 拒絕」那句 |
| backlog 81 / +35 / finished | 前二項 ✔;**`finished` 在窗內也 ✗** | 81 ✔、+35 ✗、finished ✗ | 沒有 | **改了才簽** |
| completes 15–20(13–29)/ quota supports ~11 | ✔ | ✗ | 沒有 | **不簽** |

## 4.2 我拒簽的是第 1 句,理由兩條

### 理由一:它是三句裡唯一**沒有任何一個誠實的窗**能讓它成立的

- backlog 的 `81` 今天仍精準,只要改掉 `+35` 與 `finished` 就能簽。
- 六個配額日換窗即可修好,而且換完**對申請更有利**。
- 只有 `15–20 (13–29)`:
  - 換到今天的窗(09-02~09-04)是 **14 / 14 / 14**;
  - 換到六天窗(08-30~09-04)是均值 19,但**中位 14、全距 11–32**。
  - **沒有一個窗能同時產出「15–20 平均」與「13–29 全距」。**

這已經不是老化 —— 是那個窗不會再回來。而且**全距不像均值,它宣稱的是邊界,對窗長極度敏感**:
文件自己的方法算 09-03 是 9,下界 13 在文件定稿隔天就被自己的算法打破。

### 理由二:它跟時事線的缺席綁在一起,是**實質誤導**不是時效問題

原文:
> `our pipeline (rendering, scripting, quality gates) currently completes 15–20 videos per day on average (daily output varies, 13–29), while the quota supports publishing only ~11.`

讀者會理解成:主線每天有 4~9 支發不出去。

實際上:

- **主線 11 進 11 出、一支不欠**(`grep 配額用罄` 全檔 13 次全是維運部門,上架部門 **0 次** —— daily_publish 從未因配額中止)。
- 被配額擋住的是**英文段完全沒提到的時事線**,而且是 1~2 支/天(另 1~2 支被我們自己的 factguard 擋掉)。
- 「~11」同時是三個設定常數:`produce_catchup --target 11`(產)、`--max 10 + --series 1`(發)、`YT_QUOTA_RESERVE=23650 ÷ 2150 = 11`(配額保留)。

**這一段就算補上 “as of 2026-09-02” 也還是誤導的。**

## 4.3 我願意簽的版本

> Our pipeline currently completes 14 videos per day (11 long-form plus up to 3
> breaking-news shorts), measured over the last three complete days. Our scheduler
> publishes 11 of them; the breaking-news shorts are blocked at upload — over
> 2026-09-01 to 09-04, 9 of 12 such uploads were refused for insufficient remaining
> quota for videos.insert (1,600 units). Maintenance competes for the same budget:
> four scheduled back-catalogue jobs (chapter backfill, caption re-sync, engagement
> fixes, playlist chaining) were suspended on 2026-08-30 to free quota for uploads.
> We separately hold 81 unpublished videos, 54 of which pass our quality gate; that
> stock has been flat since 2026-09-01 because long-form production and publishing
> are exactly matched at 11 per day, so the backlog cannot be worked down.

特性:每個數字有兩個以上獨立來源(檔案系統 mtime + ops_log 去重 + 逐日上架報表);
不宣稱全距;爆量日不參與;時事線與維運線都寫進去 —— 那才是真正被配額擋住的兩條;
而且 **backlog 走平本身就是最強的論點**(產出與上傳恰好打平 ⇒ 存量結構性清不掉),不必靠「backlog 在成長」。

## 4.4 另外兩件強烈建議一併修

1. **§4 的 `Expected upload volume` 欄** —— 與 Justification 對同一個 11 給了兩種歸因,兩句都會被 Google 看到。
2. **backlog 的措辭** —— 見本檔 §1 的 ③-d:81 混了三種解方相反的積壓,拿去論證配額不足,等於把我們自己閘門擋下的 59% 算進 Google 的帳上。

---

# 附:本四項用到的檔案(絕對路徑)

- `D:\carson-agent\youtube_channel\STUDIO\quota_meter.json`(12 天逐日 spent / by_op / rejected)
- `D:\carson-agent\youtube_channel\STUDIO\ops_log.txt`
- `D:\carson-agent\youtube_channel\STUDIO\quality_scores.json`(min_score 75)
- `D:\carson-agent\youtube_channel\STUDIO\uploaded_ledger.json`(1,066 筆)
- `D:\carson-agent\youtube_channel\STUDIO\publish_skip.json`(93 筆)
- `D:\carson-agent\youtube_channel\STUDIO\REPORTS\2026-08-22 ~ 2026-09-04_自動上架.md`
- `D:\carson-agent\youtube_channel\output\`(1,244 個 S_/L_ mp4 的 mtime)
- `D:\carson-agent\youtube_channel\scripts\daily_publish.py`(`find_candidates` 613 / 5:1 配比 752 / 隔離判準 1205–1240 / `break` 1244 / 上架 log 1306)
- `D:\carson-agent\youtube_channel\scripts\quota_meter.py`(`_pacific_date` 118 / `_scan` 440 / `effective_limit` 478 / `remaining` 568 / `QuotaExhausted` 659,697)
- `D:\carson-agent\youtube_channel\deploy\crontab.txt`(:58 時事上限 3 / :186,187 catchup target 11 / :217,233,542,615 暫停·換發布額度 / :349,367 daily_publish --max)
