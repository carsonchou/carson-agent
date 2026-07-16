# VERIFY_REPORT_runbook — GO_LIVE_RUNBOOK 找碴驗證

> 驗證人:verifier-sku2(fresh-context,未參與手冊撰寫)｜日期:2026-07-16
> 對象:`docs/ecommerce/GO_LIVE_RUNBOOK.md`(Carson 本人照抄執行的上線手冊)
> 立場:**一律以 repo 程式碼實況為準,不以手冊自稱為準**。行號逐一 Read 該檔該行;機制類宣稱用實跑驗證。
> 唯讀:未改手冊、未開帳號、未打外部網路、未讀任何 .env 密鑰值(只掃程式碼的 getenv 讀取點)。

## 總結

| 檢查面 | 結論 |
|---|---|
| 1 env 變數總表 | **FAIL** — 變數名/行號 20/20 全對,但 `quant-service/.env` **沒有任何程式讀它**,且 §2.3 漏一個讀取點 |
| 2 行號/符號引用 | **FAIL** — `app.py` **6/7 個行號全部腐爛(整體 +14)**;其餘 30+ 個引用全對 |
| 3 webhook URL 路徑 | **PASS** — 四路徑 + `?token=` + `/health` 全部正確 |
| 4 placeholder 替換點 | **FAIL** — 落點 6/7 正確且無漏列,但 §4 的**替換機制本身失效**,且有 1 個假條目 |
| 5 SKU 上架對照表 | **PASS** — 8/8 目錄 + 點名檔名 + 定價 + 4 份 checklist 全部存在 |
| 6 依賴順序 | **PASS** — 無死結;1 個過時註記 |
| 7 有無腦補 | **PASS** — 不確定處全標「以官方為準/待確認」,且與程式碼註解一致 |

**4 PASS / 3 FAIL。2 個 BLOCKER 都是「照做會靜默失敗」型:照手冊設完密鑰,webhook 收不到任何一筆錢;照手冊換完 placeholder,landing 買鈕仍是死連結。**

值得先講:**這份手冊的誠信面做得好**——Whop/Portaly 欄位未經證實處全標「待校準」、PayPal/玉山標「待確認」、平台後台一律「以官方為準」,且 §3.4 的「官方無第一手 spec」與 `normalize.py:153` 的程式碼註解**完全一致**,沒有對 Carson 講死不確定的事。壞的是**機制驗證**(.env 到底有沒有人載)與**行號時效**。

---

## BLOCKER(照做會失敗 / 收不到錢)

### B1 `quant-service/.env` 沒有任何程式讀它 → 四平台 webhook 全回 503,一毛收不到

手冊 §0 / §2.1 / §2.2 / §2.3 叫 Carson 把 `GUMROAD_PING_TOKEN`、`PORTALY_WEBHOOK_SECRET`、`SMTP_USER/PASS`、`ECOMMERCE_DL_*` 全部填進 `quant-service/.env`。

**實況:整個 `quant-service/webhook/` 樹零個 .env 載入器。**
- 證據:`Grep path=quant-service/webhook pattern=dotenv|environ.setdefault|\.env` → **0 occurrences across 0 files**。
- 證據:全 repo 掃「誰讀 quant-service/.env」→ **零命中**(`load_dotenv()` 只出現在 **v1 舊檔** `quant-service/webhook_server.py:28-30`、`notify.py:12-14` 等,v2 的 `webhook/` 套件從不呼叫)。
- 實跑證明(清空環境變數後):
  ```
  Settings.from_env() → gumroad_ping_token='' / portaly_secret='' / dry_run=True
  ```
  `config.py:124-131` 只 `os.getenv`,檔案裡有值也進不了 process 環境。

**後果**:`verify.py:59/63` fail-closed → 每個平台 webhook 回 **503** → Gumroad/Portaly 重試數次後放棄 → **成交事件全丟、名冊不動、記帳不動**;且 `dry_run=True` → **交付信永遠不寄**。全部靜默(Carson 只會看到「沒人買」)。

**手冊自己標了 `(待確認:以你本機 webhook 啟動器實際載入方式為準)`——但 repo 裡根本沒有 webhook 啟動器**:掃 `*.bat/*.vbs/*.ps1/*.sh` 提及 uvicorn/webhook.app → 只命中 `quant-service/requirements.txt`(其餘全是 jarvis venv 的 site-packages 雜訊)。這個 hedge 指向一個不存在的東西。

**修法建議(擇一,交給實作者)**:(a) 在 `webhook/app.py` 或 `config.py` 頂端加 `_load_env()`(照 `local_cron.py:70-76` 同款逐行 `KEY=VALUE` 解析,讀 `quant-service/.env`);(b) 提供一支 `啟動webhook.bat` 先 set 再起 uvicorn;(c) 手冊改成明寫 `set KEY=VALUE` 逐條指令。**在修好之前,§2 的整張表對 Carson 是無效操作。**

### B2 §4「設 `.env` 的 `PRODUCT_STORE_URL` 後重跑 `make_landing.py`」不會生效 → landing 買鈕留死連結

§4 表格第 157/158 列明寫:設 `.env` 的 `PRODUCT_STORE_URL`/`GUMROAD_STORE_URL` 後**重跑** `make_landing.py`。

**實況:`make_landing.py` 拿不到 `youtube_channel/.env` 的值。**
- `make_landing.py` 零 .env 載入器(`Grep environ.setdefault|load_dotenv` → **0**),import 只有 `json/os/sys/pathlib`(line 27-31),且在 **module 層**就讀掉:
  - `make_landing.py:40` `PORTALY = os.environ.get("PRODUCT_STORE_URL", "[PORTALY_URL_PLACEHOLDER]")`
  - `make_landing.py:41` `GUMROAD = os.environ.get("GUMROAD_STORE_URL", "[GUMROAD_URL_PLACEHOLDER]")`
- **唯一會載 `youtube_channel/.env` 的是排程器** `local_cron.py:70-76`(`ROOT = Path(__file__).resolve().parent.parent` → `ROOT/.env` = `youtube_channel/.env`,line 29 已驗),它只把 env 餵給**自己排的 job**。
- **`make_landing.py` 不在 `deploy/crontab.txt` 裡**(grep 該檔只有 `tg_magnet.py`@94/96/163、`ecommerce_weekly.py`@176)→ 它**只會被手動執行** → 手動 `python make_landing.py` 的 shell 沒有那些變數 → 落回 placeholder。

**後果**:重跑後 `assets/landing/index.html:115/142/148/154` 仍是 `[PORTALY_URL_PLACEHOLDER]`/`[GUMROAD_URL_PLACEHOLDER]`,**四個購買按鈕全是死連結**,而腳本會正常結束、不報錯 → **靜默**。這正是 §4 這一節要防的事,照做卻會發生。

> 對照:`tg_magnet.py`(crontab:94/96/163)、`ecommerce_weekly.py`(crontab:176)跑在排程下,**會**吃到 `youtube_channel/.env` ✓。所以 §2.4 的變數對這兩支有效,對 `make_landing.py` 無效。**手冊沒有區分這件事**。

**修法建議**:`make_landing.py` 加 `_load_env()`,或手冊改成 `set PRODUCT_STORE_URL=... && python make_landing.py`。

---

## MAJOR(會浪費時間)

### M1 `app.py` 6 個行號全部腐爛(整體 +14)

| 手冊處 | 手冊寫 | 實際 | 該行現在是什麼 |
|---|---|---|---|
| §3.4 驗證 | `app.py:47` | **61** | `@api.get("/health")` |
| §3.1 路由 | `app.py:53` | **67** | `@api.post("/sale-ping/gumroad")` |
| §3.1 token 驗 | `app.py:58` | **72** | `token = request.query_params.get("token","") or x_ping_token` |
| §3.2 路由 | `app.py:63` | **77** | `@api.post("/sale-ping/lemonsqueezy")` |
| §3.3 路由 | `app.py:71` | **85** | `@api.post("/sale-ping/whop")` |
| §3.4 路由 | `app.py:81` | **95** | `@api.post("/sale-ping/portaly")` |

**根因**:phase3a 的 B1 修把 `_json_or_400()` 插進 `app.py:29-40`(+ 空行共 14 行),其後所有行號整體下移 14。手冊是在該修之前寫的。
**唯一沒壞的**:§3 的 `app.py:8`(uvicorn 指令)✓ 仍正確——因為它在插入點**之前**。這個 +14 的一致性反過來證明其餘引用當初是真的掃過的。

### M2 §2.3 SMTP 漏列讀取點,且指向的 .env 檔會讓**旗艦週報永遠寄不出去**

§2.3「誰在讀」只列 `webhook/delivery.py:28/29` + `config.py:131`(**兩者行號皆正確** ✓),但漏了:
- **`quant-service/ecommerce/subscription_report.py:301-304`** 也讀 `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS`——這是**訂閱週報的寄送路徑**(旗艦商品!)。缺憑證時回 `{"sent": False, "reason": "SMTP 未設定(SMTP_USER/SMTP_PASS)"}`。

**為什麼是 MAJOR 不是 MINOR**:§2.3 叫 Carson 把 SMTP 填 `quant-service/.env`;但這支是被 `ecommerce_weekly.py` 用的,而 `ecommerce_weekly.py` 跑在 **youtube_channel 排程**下(`crontab.txt:176`),吃的是 **`youtube_channel/.env`**。→ 只填 `quant-service/.env` 的話,**旗艦訂閱週報寄送永遠 skipped**,而 §7.4 只教他驗「交付信」有沒有寄達,驗不到週報這條。

### M3 §3 uvicorn 指令沒說要在哪個目錄跑(只有 repo root 能跑)

手冊 §3:`uvicorn quant-service.webhook.app:app --host 0.0.0.0 --port 8021`。

實測(`uvicorn.importer.import_from_string` 逐一驗):
```
cwd = D:\carson-agent (repo root) → ✓ 成功
cwd = D:\carson-agent\quant-service → ✗ ModuleNotFoundError: No module named 'quant-service'
cwd = C:\Users\User                 → ✗ ModuleNotFoundError: No module named 'quant-service'
```
手冊緊接著寫的是路徑 `quant-service/webhook/app.py`,Carson 很自然會 `cd quant-service` 再跑 → 直接失敗。
> 附帶澄清(我原本以為是 bug,實測推翻):`quant-service` 含連字號**不影響**——PEP 420 namespace package + uvicorn/importlib 走字串式 import,連字號合法。指令本身**是對的**,只差沒寫執行目錄。

---

## MINOR(可上線後改)

- **N1 §4 line 161 `gen_media_kit.py` 是假條目**:該表宣稱它「(含 placeholder,媒體包用)」、「換成→對應連結」。實況:全檔**零個** `[PORTALY_URL_PLACEHOLDER]`/`[GUMROAD_URL_PLACEHOLDER]`;它的 `PLACEHOLDER = "〔待補：Carson 從 YouTube Studio 後台填〕"`(`gen_media_kit.py:41`)是**YT 後台數據佔位**(訂閱總數/聯絡窗口),跟商店連結無關,也不走 env。Carson 會去找一個不存在的連結 placeholder。
- **N2 §3.4「`config.py:51 SUBSCRIPTION_TIERS`」未加前綴**:實際是 `quant-service/webhook/config.py:51` ✓(行號正確),但 repo 有**兩個** config.py,且 `quant-service/ecommerce/config.py` 在 §2 脈絡也出現過 → 建議寫全路徑免走錯檔。
- **N3 §5 註記過時**:「Task #4(product_factory v2)標記 in_progress」——Task #4 已 completed(現由 fixer-sku 修 SKU BLOCKER)。§5 所有路徑/檔名**現在全部存在且正確**(見下),但檔名仍可能隨 fixer-sku 收尾微調 → 維持「以最終產物為準」的但書是對的。
- **N4 §6 具體數字無官方出處**:30% 終身 / 「多為秒過」/ ClickBank cookie 60 天 / 蝦皮 NT$500·cookie 7 天 / 通路王「近 2 個月」——這些**忠實轉述自** `affiliate_checklists/*.md`(`tradingview_..:3,22`、`ichannels_..:3,10,25`),手冊沒捏造;但**checklists 自身也沒標官方出處**。建議 §6 補「方案條款以官方最新公告為準」。

---

## 各檢查面證據明細

### ✅ 檢查面 3:webhook URL 路徑 — PASS
四條路徑對 `app.py` 實際註冊全部正確:`/sale-ping/gumroad`(67)、`/sale-ping/lemonsqueezy`(77)、`/sale-ping/whop`(85)、`/sale-ping/portaly`(95)、`/health`(61)。
Gumroad 的 `?token=` 寫法**正確**:`app.py:72` `request.query_params.get("token","") or x_ping_token` → query 或 `x-ping-token` header 皆可,與手冊 §3.1 描述一致。§2.1「密鑰未設 → 503」亦屬實(`verify.py:59/63`)。

### ✅ 檢查面 5:SKU 上架對照表 — PASS
8/8 目錄存在;點名檔名全中(`台積電體檢報告.pdf`、`台股定投追蹤模板.xlsx`+`_導引.pdf`、`台股全市場回測_1770檔.xlsx`+`台股全市場回測數據包_摘要.pdf`);`listings_copy/portaly/{C1_fullmarket_backtest,C2_bluechip_checkup,subscription_weekly}.md` 全在;4 份 affiliate checklist 全在。
定價與 `ecommerce/config.py` 逐項相符:T1 99 / T2 149 / C1 990·US$35 / C2 1280·US$39(`ONE_OFF`)、訂閱 99/149/1290(`SUBSCRIPTION`)✓。§2.2「訂閱 SUB_weekly 無 dl_env」亦屬實(`webhook/config.py:46` `"dl_env": ""`)。

### ✅ 檢查面 6:依賴順序 — PASS
無 A 需要 B 產物但 B 排在 A 後的死結。「先上架拿下載連結 → 回填 `ECOMMERCE_DL_*`」(§5→§2.2)順序正確且兩處互相呼應。§8 依賴速查與各節一致。

### ✅ 檢查面 7:有無腦補 — PASS
§1.1/1.2/1.3/1.4「以官方為準」、§1.5「(待確認)」、§3.3「欄位待真實 webhook 校準」、§3.4「官方無第一手 spec,全為暫定」、§6「送件入口以官方為準」、§0「(待確認:webhook 啟動器載入方式)」——**不確定處全部標示**。
且 §3.3/§3.4 的校準說明與程式碼註解**逐字對得上**(`normalize.py:7-11` 校準註記、`:153` 「官方無第一手 webhook spec(僅 n8n 教學證實 webhook 存在且含 姓名/email)」)→ 不是腦補,是忠實轉述。
(唯一可再收緊:§1.1「自動續訂+自動發票」、§1.2「蝦皮數位交付走買家下單→你發下載連結」是平台機制宣稱,同段雖有「以後台實際欄位為準」但未直接涵蓋這兩句 → 建議補一句但書。)

### ✅ 行號正確的部分(對照組,證明手冊當初真的掃過)
- `webhook/config.py`:35 / 38 / 41 / 44(`ECOMMERCE_DL_*` dl_env)、51(`SUBSCRIPTION_TIERS`)、124–131(六把密鑰 + SMTP dry_run)——**11/11 全對**
- `normalize.py`:7-11(校準註記)、46(`parse_gumroad`)、82(`_LS_KIND`)、118(`_WHOP_KIND`)、140-146(Whop 候選鍵)、152-154(Portaly 暫定註記)、155(`_PORTALY_STATUS_KIND`)、181-187(Portaly 候選鍵)——**8/8 全對**
- `delivery.py`:26 / 27 / 28 / 29(SMTP_HOST/PORT/USER/PASS)——**4/4 全對**
- `tg_magnet.py`:46 / 82 / 96 / 98、`autopost.py`:43 / 44 / 54 / 145、`make_landing.py`:40 / 41、`assets/landing/index.html`:115 / 142 / 148 / 154——**14/14 全對**
- §2.9「`weekly_report_v2.py` 本身不讀任何 env」——**實查 0 個 getenv/environ,宣稱屬實** ✓

---

## 回報用清單

### 「程式碼在讀、但手冊沒列」的漏網 env
**變數名層級:零漏、零多餘。** 手冊列的 20 個變數(6 把密鑰 + NTFY_TOPIC + SMTP×4 + ECOMMERCE_DL×4 + 漏斗 8 個)**全部真的有人讀,且行號全對**;無任何已從程式碼消失的殭屍變數。§2.5 的自我盤點屬實。

**讀取點層級:漏 1 個(見 M2)**
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` @ **`quant-service/ecommerce/subscription_report.py:301-304`** — §2.3「誰在讀」未列;且該路徑吃的是 `youtube_channel/.env`,與 §2.3 指定的 `quant-service/.env` 不同 → 旗艦週報寄送會靜默 skipped。
- (`TELEGRAM_BOT_TOKEN` @ `subscription_report.py:325` 退回別名 —— §2.5 已註明,**不算漏** ✓)

### 行號腐爛清單
| 手冊 | 實際 | 位置 |
|---|---|---|
| `app.py:47` | **61** | `/health` |
| `app.py:53` | **67** | `/sale-ping/gumroad` |
| `app.py:58` | **72** | Gumroad token 驗 |
| `app.py:63` | **77** | `/sale-ping/lemonsqueezy` |
| `app.py:71` | **85** | `/sale-ping/whop` |
| `app.py:81` | **95** | `/sale-ping/portaly` |

全部 **+14**,單一根因 = phase3a B1 修新增 `_json_or_400`(`app.py:29-40`)。`app.py:8` 未受影響仍正確。**其餘 37 個行號引用(normalize/config/delivery/tg_magnet/autopost/make_landing/index.html)全部準確。**
