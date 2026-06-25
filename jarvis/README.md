# 賈維斯（語音版）🗣

喊「**Hey Jarvis**」→ 講話 → 她聽懂、做事、出聲回你。電影那種。

她的大腦直接接你電腦上的 **Claude Code**，所以**全能**：開程式、查資料、改檔案、
上網搜、跑你的交易機器人 / YouTube 工作室、回答任何問題——能做的事 = Claude Code 能做的事。

## 一次性安裝
```bash
uv pip install -r jarvis/requirements.txt
```
首次執行會自動下載 Whisper 與喚醒詞模型（約數百 MB，之後就快）。
需要：麥克風 + 喇叭、`claude` 指令已安裝在 PATH（你已有）。

## 跑起來
```bash
python jarvis/jarvis.py            # 完整語音模式：待命，喊「Hey Jarvis」叫醒
```
講法：先說「**Hey Jarvis**」→ 她回「在」→ 接著用中文講你要幹嘛（講完停一下她就開始做）。

### 開發 / 測試用（不用一直喊）
```bash
python jarvis/jarvis.py --text "現在 BTC 多少、我的交易機器人今天還好嗎"   # 只測大腦
python jarvis/jarvis.py --say  "賈維斯測試"                              # 只測念字
python jarvis/jarvis.py --listen                                       # 只測喚醒+聽寫
```

## ⚠️ 安全（重要，先讀）
**預設是「安全模式」**：她能回答、查資料、讀檔、上網，但**破壞性動作會被擋**，
不會在沒人看著時擅自跑刪檔/改設定那類指令。先玩這個最安心。

要真正「**全能、免確認**」（喊一聲就跑你的腳本、改檔、開程式，全都直接做），
是**你自己明確打開**——理解風險後再開（語音聽錯/誤觸可能執行你不想要的動作）：
```bash
set JARVIS_FULL_POWER=1
python jarvis/jarvis.py
```
建議：先用安全模式熟悉，覺得可靠了再開全能。日後可再加「危險指令口頭二次確認」的護欄。

## 可調（環境變數）
| 變數 | 預設 | 說明 |
|---|---|---|
| `JARVIS_FULL_POWER` | （未開）| 設 `1` 開啟全能模式（免確認跑任何動作）|
| `JARVIS_PERMISSION_MODE` | `default`（安全）| Claude 權限模式；全能模式自動切 `bypassPermissions` |
| `JARVIS_WHISPER` | `small` | 聽寫模型大小 tiny/base/small/medium（越大越準越慢）|
| `JARVIS_WAKE_THRESHOLD` | `0.5` | 喚醒靈敏度（誤醒就調高、叫不醒就調低）|
| `JARVIS_BRAIN_TIMEOUT` | `300` | 大腦單次處理上限秒數 |
| `JARVIS_CLAUDE_BIN` | `claude` | claude 執行檔路徑 |

## 之後可以加
- ElevenLabs 磁性嗓音（取代免費機器音）
- 多輪對話記憶（記得上一句）
- 危險指令口頭二次確認的安全護欄
- 開機自動常駐
