# 賈維斯 — LiveKit 專業版（即時語音管線）

這是影片那套：**LiveKit（WebRTC，<100ms 延遲）+ Claude Code**。比網頁 orb 版更順、更專業、可部署到雲端常駐。
管線：你說話 → VAD 偵測 → Deepgram 轉文字 → 大腦(Claude/GPT) → ElevenLabs 念回 → WebRTC 串回，全程低延遲。
還有三大超能力：**上網查、寄 Email、攝影機真視覺**。

> 做法跟影片一樣：**clone 官方 starter（已 80% 完成、SDK 一定對）**，把這資料夾的 `prompts.py / tools.py / .env`
> 丟進去，再用 `claude` 把模型換成我們要的、把工具和視覺接上。我不手寫整支 `agent.py`，避免 SDK 版本對不上。

---

## 一、先開帳號、拿金鑰（免費起步）

| 服務 | 用途 | 怎麼拿 | 費用 |
|---|---|---|---|
| **LiveKit** | 即時語音傳輸 | cloud.livekit.io 註冊 → Settings → Project 拿 URL；API Keys → Create 拿 key/secret | 免費 1000 agent 分/月 |
| **Deepgram** | 語音轉文字 | deepgram.com 註冊 → API Keys → Create | 新帳號送 $200 |
| **ElevenLabs** | 念回的嗓音 | elevenlabs.io 註冊 → 挑一個聲音複製 voice id；Profile → API key | 有免費額度 |
| **Firecrawl** | 上網查資料 | firecrawl.dev 註冊 → 拿 API key | 免費起步 |
| **Anthropic** | 大腦 | 你已經有 `ANTHROPIC_API_KEY` | 你已在用 |
| **Gmail App 密碼** | 寄信 | Google 帳號 → 安全性 → 開兩步驟驗證 → 應用程式密碼 → 產生 16 碼 | 免費 |

把這些填進 `.env`（先 `copy .env.example .env`）。

## 二、把專案搭起來（一鍵）

```bat
jarvis\livekit\setup.bat
```
它會：clone 官方 `agent-starter-python`、建虛擬環境、`pip install`、把我們的 `prompts.py / tools.py / .env` 複製進去。

## 三、用 Claude Code 完成接線

進到 clone 出來的資料夾，跑 `claude`，貼這段給它：

> 把 agent.py 的管線換成：STT 用 Deepgram nova-3、LLM 用 Anthropic Claude、TTS 用 ElevenLabs（讀 .env 的
> ELEVENLABS_VOICE_ID）、VAD 用 silero。系統提示改成 import 同目錄 prompts.py 的 AGENT_INSTRUCTION 與
> SESSION_INSTRUCTION。把 tools.py 的 search_web、scrape_url、send_email 掛成 agent 的 function tools。
> 再加視覺：每則使用者訊息附帶最新一張攝影機影格給多模態 LLM（attach video track），讓它看得到我。
> 改完跑起來，有錯就自己修到能在 LiveKit playground 對話。

## 四、跑起來測

```bat
:: 終端機 1（後端 agent）
python agent.py dev
:: 終端機 2（前端介面，starter 內附）
cd frontend && npm install && npm run dev
```
瀏覽器開 starter 給的網址（或 agentsplayground.livekit.io），點 talk，授權麥克風/攝影機就能對話。

## 五、部署常駐（出國也在跑）

```bat
lk agent create        :: 或照 starter 的部署指令
```
部署到 LiveKit cloud 後，關掉本機後端它仍在跑。前端可丟 Vercel。

---

### 這資料夾各檔
- `prompts.py` — 賈維斯人設（跟本機語音版同一個口吻）
- `tools.py` — 上網查 / 抓網頁 / 寄信 三工具（標準 Python，金鑰填了就動）
- `.env.example` — 所有金鑰範本
- `setup.bat` — clone starter + 裝環境 + 複製我們的檔

兩版差別：**網頁 orb 版**（`jarvis/web/`）零帳號、現在就能用、接本機電腦操控；**LiveKit 版**（這裡）即時低延遲、可雲端常駐、有寄信/上網/視覺。
