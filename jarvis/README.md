# 賈維斯（語音版）🗣🦾

喊「**Hey Jarvis**」→ 講話 → 她聽懂、**動手操控整台電腦**、出聲回你。電影那種。

她有兩層大腦＋一雙手腳：

- **手腳（本機秒做）** — 開程式、切視窗、控制媒體與音量、打字、點滑鼠、截圖、**看著螢幕**回答你。
  這類常用指令直接在本機執行，不繞雲端，**秒回**。
- **快腦（直連 API，1–2 秒）** — 聊天、問答、意見、常識。語音互動九成走這條，所以反應飛快。
- **全能腦（Claude Code，較慢但無所不能）** — 要碰你的專案、讀寫檔、跑腳本、查即時外部資料時才升級，
  能做的事 = Claude Code 能做的事。

## 一次性安裝
```bash
uv pip install -r jarvis/requirements.txt
```
首次執行會自動下載 Whisper 與喚醒詞模型（約數百 MB，之後就快）。
需要：麥克風 + 喇叭、`claude` 指令在 PATH。電腦操控用到 `pyautogui / pygetwindow / pillow / pyperclip`（已含）。

## 跑起來
雙擊 `啟動賈維斯.bat`（安全模式）或 `啟動賈維斯-全能.bat`（全能模式），或：
```bash
python jarvis/jarvis.py            # 待命，喊「Hey Jarvis」叫醒
```
講法：說「**Hey Jarvis**」→ 一聲短嗶 → 直接用中文講你要幹嘛（講完停一下她就動作）。
喚醒後會進**對話模式**，五分鐘內可以連續講、不用每句重喊。

## 她聽得懂的操控指令（直接做，秒回）
| 你說 | 她做 |
|---|---|
| 「打開記事本 / 開 YouTube / 打開派網」 | 開程式或網站 |
| 「音量大一點 / 調到三十趴 / 靜音」 | 控制系統音量 |
| 「暫停 / 下一首 / 上一首」 | 控制正在播的媒體 |
| 「**看一下螢幕 / 螢幕上是什麼**」 | 截圖→用視覺認出畫面、口語回你 |
| 「截個圖」 | 全螢幕截圖存檔 |
| 「打字 你好世界 / 輸入：…」 | 把字打進目前游標處（支援中文） |
| 「切到 Chrome 視窗 / 關掉記事本視窗 / 回到桌面」 | 視窗管理 |
| 「鎖電腦 / 讓電腦睡覺」 | 系統控制 |
| 「在 YouTube 找告五人 / 搜尋 比特幣價格」 | 開搜尋結果 |

其餘（「今天交易賺多少」「幫我把昨天影片發布」「為什麼比特幣跌」…）會自動交給對應的腦處理。

### 開發 / 測試用
```bash
python jarvis/jarvis.py --do   "打開記事本"      # 只測電腦操控（命中就真的做）
python jarvis/jarvis.py --text "現在幾點"        # 只測大腦（不用音訊）
python jarvis/jarvis.py --say  "賈維斯測試"      # 只測念字
python jarvis/jarvis.py --listen                # 只測喚醒+聽寫
python jarvis/jarvis.py --selftest              # 逐項自我診斷
```

## ⚠️ 安全（重要）
**預設安全模式**：本機操控（開程式/音量/截圖/看螢幕/打字…）照常能用，因為都是**有界限的固定動作**；
但「無界限、要動破壞性指令」的全能腦動作**會被擋**，不會在沒人看著時擅自刪改。

要真正「**全能、免確認**」（喊一聲就跑腳本、改檔、做任何事），是**你自己明確打開**：
```bash
set JARVIS_FULL_POWER=1 && python jarvis/jarvis.py     # 或直接雙擊 啟動賈維斯-全能.bat
```
全能模式下，聽起來像刪檔/格式化/關機那類**危險指令她會先開口問你確認**。

## 可調（環境變數）
| 變數 | 預設 | 說明 |
|---|---|---|
| `JARVIS_FULL_POWER` | （未開）| 設 `1` 開全能模式（免確認跑任何動作；危險動作仍會口頭確認）|
| `JARVIS_MODEL` | `sonnet` | 全能腦模型；要更聰明設 `opus`、更快設 `haiku` |
| `JARVIS_FAST_MODEL` | `claude-sonnet-4-6` | 快腦/看螢幕用的直連模型 |
| `JARVIS_WHISPER` | `large-v3-turbo` | 聽寫模型（GPU 跑得動最強的，沒 GPU 自動退 CPU）|
| `JARVIS_WAKE_THRESHOLD` | `0.45` | 喚醒靈敏度（誤醒調高、叫不醒調低）|
| `JARVIS_CONVO_SEC` | `300` | 喚醒後對話模式維持秒數 |
| `JARVIS_VOICE` / `JARVIS_PITCH` / `JARVIS_RATE` | 雲健 / -13Hz / -8% | 嗓音、音調、語速 |
| `JARVIS_NOCOLOR` | （未設）| 設任意值關掉終端彩色 |

## 架構
- `jarvis.py` — 耳朵（openWakeWord 喚醒 + faster-whisper 聽寫）、嘴巴（edge-tts 串流分句念）、分流大腦。
- `computer.py` — 手腳：本機操控工具 + 中文語音意圖路由（`route()` 命中→秒做，沒命中→交給大腦）。
- `dashboard/` — 鋼鐵人風全息儀表板，即時跟賈維斯情緒同步（idle/listening/thinking/speaking）。

## 之後可以加
- 講話中途插話打斷（barge-in）
- ElevenLabs 更擬真嗓音
- 開機自動常駐
