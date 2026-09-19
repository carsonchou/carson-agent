# OmniRoute 收線紀錄(2026-09-09)

**裁決**:Carson —「那算了」,**不走 omniroute**。
**理由(收斂後,以後不用再問一次)**:
OmniRoute **不產生額度**,它只把「你自己帳號的連線」收斂到一個端點。

- 本機那條 Claude provider 綁 **crayray86**,而 Claude Code 登入的是 **moneycometomywallet**
  ⇒ 走它 = 開始花第二個訂閱。那是資源分配決定,Carson 決定不花。
- 改綁成同一個帳號 ⇒ 同一個池子、同一個上限,只剩約 15% 溢流到非 Anthropic provider,
  而 antigravity 帶自己的 system prompt **不等價**
  ⇒ 兩邊的好處都拿不到。

## 收線前的現場(動手前擷取,2026-09-09 15:4x)

### 程序樹 —— 這不是「四支各自的程序」,是一棵樹

```
51568  cmd.exe    "cmd /c omniroute.cmd"                     start 09-03 11:05:55  CPU 0.06s   4.7MB
 └ 50616 node.exe  omniroute\bin\omniroute.mjs (無參數)       start 09-03 11:05:55  CPU 86.7s   123.9MB
    ├ 45640 esbuild.exe  --service=0.28.2 --ping              start 09-03 11:05:57  CPU 138.1s  53.2MB
    └ 29156 node.exe  dist\server-ws.mjs (--max-old-space-size=4096)
                                                             start 09-03 11:14:17  CPU 1039.8s 818.6MB
```

**更正一項先前的描述**:51568/50616 先前被我描述成「卡了 6 天的 CLI」。
父子關係顯示 **29156 gateway 是 50616 生出來的**,50616 是由 `start-omniroute.vbs`
以無參數啟動、**不會回傳的前景 CLI**(thread wait = UserRequest),不是當掉。
⇒ 以後重裝再看到這兩支不要當異常,那是這個啟動方式的正常形狀。

### 卡在什麼狀態(給未來重裝時比對)

- 51568:單執行緒、`UserRequest` 等待、CPU 0.06 秒 ⇒ 就是 `cmd /c` 在等子程序結束。
- 50616:15 執行緒(EventPairLow×5 / UserRequest×2 / Unknown×8),CPU 86.7 秒。
- 45640 esbuild `--ping`:CPU 138 秒,是 50616 的子程序,**跟著父程序一起走**。
- 29156:6 天累積 CPU 1040 秒、私有記憶體 818MB。

### 監聽與對外連線(這是停掉的真正理由)

| 項目 | 值 |
|---|---|
| 監聽 | **`0.0.0.0:20128`**(對整個網段可達,本機裝了 Tailscale)、`127.0.0.1:20131`、`127.0.0.1:20132` |
| 對外已建立連線 | `192.168.0.206:54015 → 104.18.32.47:443`、`:54016 → 35.186.247.105:443`(閒置狀態下仍常駐兩條 TLS) |
| 進來的連線 | 只有 `127.0.0.1` 的 TimeWait(它自己每 2 小時的探針) |

⇒ **帶著 crayray86 OAuth 憑證、常駐在 0.0.0.0、而沒有任何人要用它**。
沒有用途的曝險就是純曝險 ⇒ 收回 127.0.0.1 是把窗開小,停掉是把窗關上;既然不走,關上比開小好。

### 呼叫紀錄(`~/.omniroute/call_logs/`)

- **09-04 之後沒有任何一次 `/v1/messages` 推論**。09-04 當天 270 次:
  claude 200×223、antigravity 200×21、github 400×16、cline 401×11、claude 429×10、codex 401×3。
- 09-07/08/09 全部是同一支每 2 小時的 `POST /api/providers/test`
  → provider `cline` / 帳號「庭睿 周」/ **401 `Local CLI runtime is not installed`**。
- ⚠️ **`cline` 這條連線登記在第三方帳號「庭睿 周」名下,不是 Carson 的**;`antigravity` 在 09-04 服務過 21 次成功呼叫。兩者都不在核可 provider 清單內。

## ① 收線前確認(查完才動)

| 檢查 | 結果 |
|---|---|
| 有沒有 session/程序在打 :20128 | **沒有**。除了 LISTEN 只有它自己探針的 TimeWait |
| 有沒有程序 cmdline 帶 `carson-opus` / `20128` | **沒有**(命中的只有 omniroute 自己那棵樹) |
| `ANTHROPIC_BASE_URL`(User/Machine/shell) | **三處皆空** |
| `D:\claude\settings.json` 的 `env` | **`{}`**(mtime 09-05 02:05,早於本次所有動作) |
| repo / `D:\claude` 內有沒有腳本依賴 | **沒有**。全部命中都是文件敘述,唯一程式碼命中是 `WATCHDOG.md` 的交叉引用 |
| `usage_watch.py` 會不會壞掉 | **不會**。它不呼叫 gateway;只有第 613 行印一句「建議切換到本機 OmniRoute gateway」的**文字建議**(現已過期,見下) |
| 其他排程依賴 | 只有 `OmniRoute AutoStart` 一支;crontab 無命中 |

## ② 處置

- 停掉常駐 gateway 程序(整棵樹)
- 停用登入觸發排程 `OmniRoute AutoStart`

## ③ 保留(**不要卸載**)

- 安裝本體 `C:\Users\User\AppData\Roaming\npm\node_modules\omniroute`(3.8.50)
- `D:\omniroute-run\`(`usage_watch.py`、`usage-cache.json`、`usage-calibration.json`、`auto-switch.log`、`patch_allow_rule.py`、`start-omniroute.vbs`)
- `~/.omniroute/`(含 `call_logs/`、`storage.sqlite`)= 稽核 log
- `OMNIROUTE_API_KEY`(使用者層)—— 只是憑證,不造成路由

⇒ Carson 之後改主意時,一句話就能重開(見文末)。

## 驗收怎麼驗

1. **停完當下**:`Get-NetTCPConnection -LocalPort 20128` 要**查不到 Listen**(不是只看「我下了停止指令」)。
2. **開機/登入後不會自己起來**:🔴 **這一項現在驗不到**,它要**下一次登入或重開機**才觸發得到。
   驗法寫在這裡:下次登入後跑
   `Get-NetTCPConnection -LocalPort 20128` 和
   `Get-ScheduledTask -TaskName 'OmniRoute AutoStart' | Select State`
   —— 前者要空、後者要 `Disabled`。**在那之前不得宣稱「已驗證開機不會起來」**。

## 要重開時怎麼做

```powershell
Enable-ScheduledTask -TaskName 'OmniRoute AutoStart'   # 或直接:
wscript "D:\omniroute-run\start-omniroute.vbs"
```
🔴 重開前先讀:memory `omniroute-usage-failover`。唯一正確的接法是 process-scoped 的
`omniroute run claude --model carson-opus`;**絕不**寫 `D:\claude\settings.json` 的 `env`
(09-05 事故本體:新增鍵即時傳播、刪除鍵不傳播,只能重啟才回得來),
**絕不**用 `--profile` / `setup-claude`(預設寫到 `C:\Users\User\.claude`,
而該路徑是 `D:\.claude` 的 symlink = CLAUDE.md 明令禁寫的殭屍目錄)。
🔴 重開前也要先解決:綁的是哪個帳號 —— 這正是本次收線的理由。

---

## 執行結果(2026-09-09,本次)

| 動作 | 結果 |
|---|---|
| 停程序(由葉往根 29156 → 45640 → 50616 → 51568) | 四支**全部已結束**(逐支回讀確認) |
| `:20128` | ✅ **回讀查不到任何 Listen 或連線** |
| `:20131` / `:20132` | ✅ 一併消失 |
| 殘留 omniroute 程序 | ✅ 無(唯一命中是我自己的 grep / pwsh 指令列文字) |
| 排程 `OmniRoute AutoStart` | `Enabled/Ready` → **`Disabled`**(`schtasks /change /disable`,`Get-ScheduledTask` 回讀為 `Disabled`) |
| 全機其他 Omni 排程 | 無 |
| 安裝本體 / `D:\omniroute-run` / `~/.omniroute` | **原封保留,未卸載** |
| `D:\claude\settings.json` | **未動**(`env` 仍為 `{}`) |

### 順手改的一處(會誤導未來的人)

`D:\omniroute-run\usage_watch.py:613` 原本在額度告警時印
「**建議切換到本機 OmniRoute gateway 繼續工作**」——那個出口今天已收線,
留著會把未來的 session 導向已被否決的路。已改成告警 + 指回本檔,並註明裁決日期。
`py_compile` 通過;寫法是 tmp → 回讀比對 → `os.replace`。

### 🔴 尚未驗、且今天驗不到的一項

**「登入/開機後不會自己起來」** —— 排程狀態顯示 `Disabled`,但那是**設定**不是**行為**。
要下一次登入或重開機才驗得到。驗法見上節「驗收怎麼驗」第 2 點。
**在那之前不得宣稱已驗證。**
