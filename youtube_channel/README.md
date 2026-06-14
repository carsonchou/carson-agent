# 量化阿森｜Carson Quant — 自動化 YouTube 頻道專案

> Faceless（不出鏡）繁體中文量化交易內容頻道的總說明與操作手冊。
> 本專案用半自動 Pipeline 產出影片：**選題 → 產腳本 → 產配音 → 剪輯 → 上傳**，每月成本控制在 **US$30 以內**。

---

## 0. 頻道一句話定位

- **頻道名**：量化阿森｜Carson Quant
- **語言**：主力繁體中文（台灣 Mandarin），Pipeline 設計保留多語擴充
- **受眾**：25–45 歲、有資金、玩過股/幣但靠感覺賠過錢、想自動化又怕被割韭菜的上班族散戶
- **核心承諾**：每個策略都有**回測數據**、可複製、faceless 理性顧問調性，不喊單
- **完整定位文件**：見 [`01_頻道定位.md`](./01_頻道定位.md)（受眾、4 大內容支柱、影片格式、變現策略的完整版）

### 4 大內容支柱（每支影片選一個歸屬）
1. **策略拆解（Strategy Decode）** — 招牌，建立專業印象
2. **工具教學（Pionex 派網實操）** — 聯盟返佣主戰場
3. **市場觀念（倉位 / 風控 / 心理）** — CPM 友善、建立信任
4. **實測回測（Backtest Lab）** — 量化護城河、最難被複製

---

## 1. 專案目的與整體流水線

**目的**：用最低人力與成本，穩定產出「有數據佐證的量化交易教學影片」，靠聯盟返佣（先）＋ YPP 廣告（後）變現。

### 流水線圖（文字版）

```
┌────────────┐   ┌──────────────────────┐   ┌────────────────────┐   ┌────────────────────┐   ┌──────────┐
│  ① 選題     │ → │ ② generate_script.py │ → │ ③ tts_pipeline.py  │ → │ ④ 剪輯              │ → │ ⑤ 上傳    │
│ (人工/熱點) │   │  產腳本 + 配音稿      │   │  產配音 mp3        │   │ CapCut / DaVinci   │   │ YouTube  │
└────────────┘   └──────────────────────┘   └────────────────────┘   └────────────────────┘   └──────────┘
      │                    │                          │                         │                     │
   主題清單           scripts/*.md             output/audio/*.mp3        套用品牌模板          標題/縮圖/描述
   支柱歸屬           + 配音純文字稿            (固定 voice profile)      + 回測圖 + 字卡        + 派網聯盟連結
```

### 各階段說明

| 階段 | 做什麼 | 產出 | 工具 |
|------|--------|------|------|
| ① 選題 | 從 4 支柱挑題、對痛點 | 一個明確標題 + Hook | 人工（未來可自動找熱點） |
| ② 產腳本 | LLM 依模板產 Hook→正文→CTA | `output/{slug}.md` 腳本 + `output/{slug}.voice.txt` 純配音稿 | `scripts/generate_script.py`（Claude API） |
| ③ 產配音 | 把配音稿轉成冷靜顧問口吻 AI 語音 | `output/{slug}.mp3` | `scripts/tts_pipeline.py`（ElevenLabs API） |
| ④ 剪輯 | 配音對齊操作畫面 + 回測圖 + 動態字幕字卡 | 成片 mp4 | CapCut / DaVinci Resolve（免費版） |
| ⑤ 上傳 | 上標題、縮圖、描述、聯盟連結、預告下一集 | 已發佈影片 | YouTube Studio（未來可排程 API） |

> **腳本/配音稿分離設計**：`generate_script.py` 同時輸出「人看的完整腳本 `output/{slug}.md`（含視覺指示、字卡提示）」與「純配音文字稿 `output/{slug}.voice.txt`（給 TTS 吃的乾淨段落）」，避免把視覺指示唸出來。`tts_pipeline.py` 正好吃 `{slug}.voice.txt` 產出 `output/{slug}.mp3`，檔名約定兩端對齊。多語擴充時只需替換「翻譯節點 + TTS voice」即可重用同一份結構化腳本。

---

## 2. 資料夾結構

```
youtube_channel/
├── README.md              ← 本檔（總說明 + 操作手冊）
├── 00_審查報告.md          ← 專案審查報告（本次審查產出）
├── 01_頻道定位.md          ← 完整定位文件（受眾/支柱/格式/變現）
├── 02_選題清單.md          ← 前 20 支影片選題與排程
├── 03_第一支影片腳本.md     ← 第一支影片成品級腳本（人工精修範例）
├── channel_config.json    ← 頻道設定（兩支程式共用：名稱/CTA/聯盟/voice 等）
├── requirements.txt       ← Python 套件清單
│
├── scripts/               ← 程式碼
│   ├── generate_script.py ←   腳本產生器（呼叫 Claude API；claude-opus-4-8）
│   └── tts_pipeline.py    ←   配音產生器（呼叫 ElevenLabs API）
│
├── output/                ← 所有程式產出物（預設輸出位置）
│   ├── {slug}.md          ←   完整腳本：Hook / 正文 / CTA + 視覺指示 + 字卡
│   ├── {slug}.voice.txt   ←   純配音稿（餵給 TTS，無視覺指示）
│   └── {slug}.mp3         ←   tts_pipeline.py 產的配音 mp3
│
└── assets/                ← 可重複使用的品牌素材（需自行建立子資料夾）
    ├── brand/             ←   logo、品牌色票、片頭片尾、字型
    ├── templates/         ←   CapCut/DaVinci 模板、字卡模板、縮圖模板（Canva）
    ├── bgm/               ←   背景音樂（免版稅）
    └── stock/             ←   Pexels/Pixabay 下載的空鏡素材
```

> 規則：**程式碼進 `scripts/`、所有產出進 `output/`、可重用素材進 `assets/`**。每支影片用同一個 `slug`（由 `generate_script.py` 從題目自動轉成安全檔名，或自行命名）貫穿 `.md`→`.voice.txt`→`.mp3` 全流程，方便對齊與管理。

---

## 3. 環境設定（Windows + Python）

### 3.1 安裝 Python
- 安裝 Python 3.10+（[python.org](https://www.python.org/) 或 winget）。安裝時勾選「Add Python to PATH」。
- 驗證：

```powershell
python --version
```

### 3.2 建立虛擬環境並安裝套件

```powershell
# 進入專案
Set-Location D:\carson-agent\youtube_channel

# 建立並啟用虛擬環境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 若 PowerShell 擋執行政策，先放行（CLAUDE.md 已允許此指令）
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 安裝套件
pip install -r requirements.txt
```

專案已內附 `requirements.txt`，內容如下（注意：`tts_pipeline.py` 是用 `requests` 直打 ElevenLabs REST API，**不需要** elevenlabs SDK）：

```
anthropic>=0.40.0      # generate_script.py 用，呼叫 Claude API 產腳本（claude-opus-4-8）
requests>=2.31.0       # tts_pipeline.py 用，呼叫 ElevenLabs REST API
pydub>=0.25.1          # tts_pipeline.py 選用，合併多段 mp3（需另裝 ffmpeg；無則自動回退串接）
python-dotenv>=1.0.0   # 選用，從 .env 讀環境變數，方便管理金鑰
```

> `pydub` 與 `ffmpeg` 為選用：單支影片旁白通常一次合成即可（不需合併多段），即使不裝也能正常產出 mp3。只有當配音稿超過單段字元上限被切成多段時，才會用到合併；無 ffmpeg 時程式會自動回退為 binary 串接，對 YouTube 上傳無影響。

### 3.3 設定環境變數（API 金鑰）

需要兩把金鑰：
- `ANTHROPIC_API_KEY` — Claude API（產腳本）。到 [console.anthropic.com](https://console.anthropic.com/) 取得。
- `ELEVENLABS_API_KEY` — ElevenLabs（產配音）。到 [elevenlabs.io](https://elevenlabs.io/) 帳戶頁取得。

**方法 A：當前 PowerShell 工作階段（暫時，關掉視窗就失效）**

```powershell
$env:ANTHROPIC_API_KEY  = "sk-ant-你的金鑰"
$env:ELEVENLABS_API_KEY = "你的 elevenlabs 金鑰"
```

**方法 B：永久寫入使用者環境變數（推薦，重開機仍在）**

```powershell
setx ANTHROPIC_API_KEY  "sk-ant-你的金鑰"
setx ELEVENLABS_API_KEY "你的 elevenlabs 金鑰"
# 注意：setx 設定後，需「重開一個新的 PowerShell 視窗」才會生效
```

**方法 C：用 `.env` 檔（搭配 python-dotenv，金鑰不寫死在程式裡）**

在 `youtube_channel/` 建立 `.env`：

```
ANTHROPIC_API_KEY=sk-ant-你的金鑰
ELEVENLABS_API_KEY=你的 elevenlabs 金鑰
```

> 安全提醒：`.env` 與金鑰**絕不要**上傳到 GitHub。若用 git，請把 `.env` 加進 `.gitignore`。

驗證金鑰已載入：

```powershell
echo $env:ANTHROPIC_API_KEY
echo $env:ELEVENLABS_API_KEY
```

---

## 4. 每月成本表

| 項目 | 用途 | 方案 | 月費（USD） |
|------|------|------|------------|
| ElevenLabs | AI 配音（固定 voice profile） | Starter（~30,000 字元/月，足夠數支影片） | **~$5** |
| Anthropic Claude API | 產腳本 | 用量計費，腳本量小 | **~$1–3** |
| Pexels / Pixabay | 空鏡 / 素材影片圖片 | 免費（免版稅可商用） | $0 |
| CapCut / DaVinci Resolve | 影片剪輯 | 免費版 | $0 |
| Canva | 縮圖設計 | 免費版 | $0 |
| Mermaid / Chart.js | 數據圖 / 回測視覺化 | 開源免費 | $0 |
| 背景音樂 | BGM | YouTube Audio Library / 免版稅 | $0 |
| **合計** | | | **約 $6–8／月，遠低於 $30 上限** |

> 預算抓 $30 是留給：未來升級 ElevenLabs（更多字元 / Pro voice）、偶爾買付費素材或音樂、Canva Pro（縮圖批量）。初期 $10 內就能跑。

---

## 5. 從零到第一支影片（逐步操作）

> 目標：產出 `ep01`，主題假設為「派網網格機器人新手設定 + 回測驗證」（支柱②工具教學 ×④回測）。

### 步驟 1：環境就緒（只需做一次）
```powershell
Set-Location D:\carson-agent\youtube_channel
.\.venv\Scripts\Activate.ps1          # 啟用虛擬環境
echo $env:ANTHROPIC_API_KEY            # 確認金鑰在
```

### 步驟 2：選題
- 從 4 支柱挑一個明確、可數據化的題目（題庫見 `02_選題清單.md`）。
- 寫下一句反直覺 Hook（例：「90% 的人開網格機器人，第一步就設錯了」）。
- 題目本身會被自動轉成 `slug`（安全檔名）；中文會保留，非法字元會被移除。

### 步驟 3：產腳本 + 配音稿
> CLI 是「題目當位置參數」，不是 `--slug/--title`。題目用引號包起來。
```powershell
python scripts\generate_script.py "派網網格機器人新手設定＋回測驗證"
```
產出（預設到 `output/`，檔名取自題目）：
- `output\派網網格機器人新手設定＋回測驗證.md`（完整腳本，含視覺指示）
- `output\派網網格機器人新手設定＋回測驗證.voice.txt`（純配音稿，給 TTS）

沒設定 `ANTHROPIC_API_KEY`（或加 `--no-llm`）時，會改用內建模板產出「骨架腳本」讓你手動填。

**人工校稿**：打開 `.md` 檢查數據是否正確、Hook 夠不夠勾、CTA 有無放派網聯盟連結。改完同步修 `.voice.txt`（TTS 只吃 `.voice.txt`）。

### 步驟 4：產配音
> 輸入的是上一步產出的 `.voice.txt`（位置參數）。先用 `--dry-run` 看分段與成本估算，確認沒問題再正式跑。
```powershell
# 先試跑（不呼叫 API、不花錢，只看分段與字元數）
python scripts\tts_pipeline.py "output\派網網格機器人新手設定＋回測驗證.voice.txt" --dry-run

# 正式產配音（需先設好 ELEVENLABS_API_KEY）
python scripts\tts_pipeline.py "output\派網網格機器人新手設定＋回測驗證.voice.txt"
```
產出：`output\派網網格機器人新手設定＋回測驗證.mp3`（固定冷靜顧問 voice，voice_id 取自 `channel_config.json` 的 `tts` 區塊）。試聽，斷句不順就回去改 `.voice.txt` 重跑。

### 步驟 5：準備視覺素材
- 錄製 Pionex / TradingView 自有操作畫面（螢幕錄影）。
- 用 Mermaid / Chart.js 產回測圖，截圖存 `assets/stock/` 或 `output/`。
- 缺空鏡到 Pexels / Pixabay 下載。

### 步驟 6：剪輯（CapCut 或 DaVinci 免費版）
1. 套用 `assets/templates/` 的品牌模板（統一品牌色、字型、片頭片尾）。
2. 把 `output/audio/ep01-...mp3` 拉進時間軸當主軸。
3. 對齊操作畫面、回測圖、字卡（依 `.md` 的視覺指示）。
4. 加動態字幕字卡、BGM（壓低音量）。
5. 輸出成片到 `output/video/ep01-pionex-grid-basic.mp4`。

### 步驟 7：做縮圖與上傳文案
- Canva 用縮圖模板做 `ep01` 縮圖（大字痛點 + 品牌色）。
- 在 `output/upload/ep01.txt` 寫好：標題、描述、tags、**派網聯盟連結**、下一集預告。

### 步驟 8：上傳
- YouTube Studio 上傳 `mp4` + 縮圖 + 描述。
- 影片長度 8–12 分鐘可開「中插廣告」；同步剪一支 Shorts 導流。
- 發佈，完成第一支！

---

## 5.5 全自動上架（run_all.py 一鍵端到端）

> 上面第 5 節是「逐步手動」流程，方便理解每一階段。本節介紹**一鍵編排器** `scripts/run_all.py`，把整條產線串成**一行指令**：
>
> ```
> 題目 → ① generate_script.py → ② tts_pipeline.py → ③ make_video.py → ④ upload_youtube.py
>        產腳本/配音稿              產配音 mp3            剪輯成片 mp4          上傳 YouTube
> ```
>
> `run_all.py` 用 `subprocess` 依序呼叫各階段（同一個 Python 直譯器），**任何一階段失敗就立刻停止並印出清楚錯誤**，不會往下硬跑。全線以「題目→slug」推導各階段檔名（與 `generate_script.py` 的 `slugify()` 完全一致），對齊 `output/{slug}.md` / `.voice.txt` / `.mp3` / `.mp4`。

### 5.5.1 一行指令用法

```powershell
Set-Location D:\carson-agent\youtube_channel
.\.venv\Scripts\Activate.ps1

# 全自動串到「成片」就停（預設，不上傳）：依序產出 .md → .voice.txt → .mp3 → .mp4
python scripts\run_all.py "派網網格機器人新手設定＋回測驗證"
```

跑完會印出每一階段產物路徑與最後狀態摘要（哪個檔有產出、檔案大小）。

### 5.5.2 `--stop-after`：要停在哪一階段

`run_all.py` 用 `--stop-after` 控制「跑到哪一階段為止」，預設 `video`：

| `--stop-after` | 跑到 | 產物 | 用途 |
|----------------|------|------|------|
| `script` | ① 產腳本 | `{slug}.md` + `{slug}.voice.txt` | 最便宜，先看文案/校 Hook |
| `tts` | ② 產配音 | 上述 + `{slug}.mp3` | 試聽配音、調斷句 |
| `video`（**預設**） | ③ 剪輯成片 | 上述 + `{slug}.mp4` | 產出成片就停，**人工檢查後再決定上傳** |
| `upload` | ④ 上傳 | 上述 + 已上架 YouTube | 全自動到底 |

```powershell
# 只產腳本就停（最便宜，先看文案）
python scripts\run_all.py "馬丁格爾策略回測拆解" --stop-after script

# 產到配音就停（試聽 mp3）
python scripts\run_all.py "三重 SuperTrend 策略拆解" --stop-after tts
```

### 5.5.3 安全預設（重要）

- **預設不上傳**：`--stop-after` 預設 `video`，產出 `mp4` 就停，讓 Carson 先人工檢查成片，**不會自動把半成品丟上 YouTube**。
- **要上傳得明確開**：加 `--upload`（等同 `--stop-after upload`）才會真的上傳。
- **上傳預設 private（私人）**：`--privacy` 預設 `private`，即使上傳也是私人，確認沒問題再去 YouTube Studio 改公開。可選 `public` / `unlisted` / `private`。
- **`--dry-run` 全程不花錢**：每一階段都帶上各自的 dry-run（腳本用 `--no-llm` 改走內建模板、tts/video/upload 用 `--dry-run`），**不呼叫付費 API、不上傳**，純粹驗證整條流程接線是否正確。

```powershell
# 全程 dry-run：不花錢、不上傳，先驗證流程能不能跑通
python scripts\run_all.py "測試題目" --dry-run --stop-after upload

# 人工確認成片 OK 後，才真的上傳（預設 private 私人）
python scripts\run_all.py "派網網格機器人新手設定＋回測驗證" --upload

# 上傳並設為 unlisted（不公開、但有連結者可看，常用於排程前內審）
python scripts\run_all.py "派網網格機器人新手設定＋回測驗證" --upload --privacy unlisted
```

### 5.5.4 需要的全部金鑰／憑證清單

全自動到上傳，需要備齊以下 4 項（前 3 項是環境變數，第 4 項是憑證檔 + 一次性授權）：

| 項目 | 環境變數／檔案 | 用於哪一階段 | 去哪申請 |
|------|---------------|-------------|---------|
| Anthropic Claude API key | `ANTHROPIC_API_KEY` | ① 產腳本 | [console.anthropic.com](https://console.anthropic.com/) → API Keys → Create Key（`sk-ant-...`） |
| ElevenLabs API key | `ELEVENLABS_API_KEY` | ② 產配音 | [elevenlabs.io](https://elevenlabs.io/) → 帳戶頭像 → Profile + API Key |
| Pexels API key | `PEXELS_API_KEY` | ③ 剪輯成片（抓 B-roll 空鏡） | [pexels.com/api](https://www.pexels.com/api/) → 免費註冊 → Your API Key（免費、無限額） |
| YouTube OAuth 憑證 | `client_secrets.json` + 一次性 OAuth 授權 | ④ 上傳 | 見下方 5.5.5（Google Cloud Console） |

> 只跑到 `--stop-after script` 只需 `ANTHROPIC_API_KEY`；到 `tts` 再加 `ELEVENLABS_API_KEY`；到 `video` 再加 `PEXELS_API_KEY`；到 `upload` 才需要 YouTube 憑證。`--dry-run` 全部都不需要，可零金鑰先試跑流程。

設定環境變數（PowerShell，永久寫入見第 3.3 節 `setx`）：

```powershell
$env:ANTHROPIC_API_KEY  = "sk-ant-你的金鑰"
$env:ELEVENLABS_API_KEY = "你的 elevenlabs 金鑰"
$env:PEXELS_API_KEY     = "你的 pexels 金鑰"
```

### 5.5.5 YouTube 上傳憑證設定（一次性，最費工）

YouTube Data API 用 OAuth（不是單純 API key），需要做一次以下設定，之後會快取授權 token，後續上傳免再授權：

1. **建立 Google Cloud 專案**：到 [console.cloud.google.com](https://console.cloud.google.com/) → 建立新專案（例：`carson-quant-youtube`）。
2. **啟用 YouTube Data API v3**：左側「API 和服務 → 程式庫」搜尋「YouTube Data API v3」→ 啟用。
3. **設定 OAuth 同意畫面**：「API 和服務 → OAuth 同意畫面」→ User Type 選「外部」→ 填 App 名稱/支援信箱 → 在「測試使用者」加入**你自己上傳用的 Google 帳號**（測試模式下只有測試使用者能授權，足夠自用）。
4. **建立 OAuth 用戶端 ID**：「API 和服務 → 憑證 → 建立憑證 → OAuth 用戶端 ID」→ 應用程式類型選「**桌面應用程式**」→ 建立後**下載 JSON**。
5. **放置憑證檔**：把下載的 JSON 改名為 `client_secrets.json`，放到 `youtube_channel/` 根目錄（與 `channel_config.json` 同層）。
6. **一次性授權**：第一次跑到上傳階段時，`upload_youtube.py` 會開瀏覽器要你登入並授權，授權後會把 token 快取在本機（例如 `token.json`）。**之後就不用再授權**，除非 token 過期或刪除。

> 安全提醒：`client_secrets.json`、`token.json`、`.env` 與所有金鑰**絕不要**上傳到 GitHub。用 git 的話請把它們全部加進 `.gitignore`。配額提醒：YouTube Data API 每日有配額，一支影片上傳約耗 1600 點（每日預設 10000 點），自用足夠。

---

## 6. 每週工作節奏（可持續產出）

> 目標：**每週穩定 1 支長片 + 2–3 支 Shorts**，避免燃盡。

| 日 | 任務 | 產出 |
|----|------|------|
| **週一** | 選題 + 蒐集數據/回測（步驟 2、5 的資料面） | 1 個確定題目 + 回測圖 |
| **週二** | 跑 `generate_script.py` + 人工校稿 | 完成的腳本 + 配音稿 |
| **週三** | 跑 `tts_pipeline.py` + 錄操作畫面 | 配音 mp3 + 螢幕錄影 |
| **週四** | 剪輯成片 + 做縮圖 | `output/video/` 成片 + 縮圖 |
| **週五** | 上傳長片 + 切 2–3 支 Shorts | 已發佈 |
| **週末** | 回覆留言、看數據、囤下週題庫（2–3 個備用題） | 題庫 + 觀眾回饋 |

原則：
- **永遠領先 1 支**：手上隨時有一支「已選題、待製作」的備案，避免斷更。
- **批次化**：同一支柱的題目連做幾支，重用同一套字卡/回測模板，攤平製作時間。
- **模板優先**：第一次把 `assets/templates/` 做扎實，之後每支只換內容不換結構。

---

## 7. 後續可自動化方向

依「投報率 / 省時程度」排序，建議逐步導入：

1. **自動找熱點選題**
   - 抓 YouTube / Google Trends / 加密貨幣與台股新聞熱詞，比對 4 支柱，產出「本週候選題清單 + 建議 Hook」。
   - 可接 `WebSearch` / 既有 `morning-stock`、`ebc-monitor` 類流程，每天早上吐題庫。

2. **自動產縮圖**
   - 用模板 + Pillow / Canva API / HTML→截圖，把標題大字自動套進品牌縮圖模板，產 2–3 版本供 A/B。

3. **自動上傳排程**
   - 接 YouTube Data API：自動上傳 `output/video/` 成片、套用 `output/upload/` 的標題描述 tag、設定排程發佈時間，並自動帶入派網聯盟連結。

4. **腳本→字幕→剪輯半自動串接**
   - 由 `.voice.txt` 自動生成 SRT 字幕，剪輯時直接匯入，省手打字卡時間。
   - 進一步可用自動對齊（forced alignment）把字卡時間軸自動排好。

5. **多語擴充節點**
   - 在 Pipeline 末端加「翻譯 + 換 TTS voice」節點，同一份結構化腳本一鍵產英文 / 簡中版，開新語言頻道，不需重做內容。

6. **成效回饋迴圈**
   - 自動抓各影片觀看/留存/CTR/聯盟點擊，回寫成「哪種支柱/Hook 表現最好」的報表，反哺選題。

---

## 附錄：快速指令備忘

```powershell
# 啟用環境
Set-Location D:\carson-agent\youtube_channel
.\.venv\Scripts\Activate.ps1

# 產腳本（題目當位置參數；加 --no-llm 可不呼叫 API 先出骨架）
python scripts\generate_script.py "<影片題目>"

# 產配音（吃上一步的 .voice.txt；先 --dry-run 估成本）
python scripts\tts_pipeline.py "output\<slug>.voice.txt" --dry-run
python scripts\tts_pipeline.py "output\<slug>.voice.txt"

# 之後：剪輯(CapCut/DaVinci) → 縮圖(Canva) → 上傳(YouTube Studio)
```

---

*本專案隸屬 carson-agent。定位細節請參考 `01_頻道定位.md`。所有 API 金鑰請以環境變數或 `.env` 管理，切勿外洩。*
