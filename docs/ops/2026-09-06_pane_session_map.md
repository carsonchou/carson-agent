# herdr 窗格 <-> session id(2026-09-06 08:0x,關閉 wF:p2 之前記錄)

⚠️ 關窗格可逆的前提是 id 有記下來:`claude --resume <sid>`。見 memory `herdr-pane-session-map`。

| 窗格 | session id | 狀態 | 標題 |
|---|---|---|---|
| `w1:p1` | `cd3867ec-5e86-4846-8be4-79cae508fd63` | done | WorldQuant Brain 結算量測 |
| `w9:p1` | `efac2502-3b49-4fd4-9824-cdd4412f74f3` | done | Main ch 程序重啟與交接檔讀取 |
| `wB:p1` | `cda0ca12-c657-48a7-a311-7752a7c041a8` | idle | non. |
| `wE:p1` | `8ae57f4b-2990-4015-87b9-0eb686669b9d` | idle | Herdr優化員 |
| `wF:p1` | `730dd55f-5ec0-45e0-bf23-f9b2ad13cc58` | idle | 主頻道督導交接：fail-closed 閘門 |
| `wF:p2` | `818543e1-d51c-4902-b6ed-bcbcf3d20af1` | idle | Sec ch. supervisor |
| `wF:p3` | `752726ea-0cce-4ad0-bfc2-09b114942eb0` | working | 主頻道旁白改動的對照觀測 |
| `wF:p4` | `054492e4-ec29-4188-bafa-27e9a6ab4821` | idle | WorldQuant Brain 線督導交接 |
| `wF:p5` | `ee3f1512-e494-4633-bf37-7315958220ae` | idle | Carson 總督導系統角色與四條線管理 |
| `wG:p4` | `c04d599f-16c0-4fdc-9a39-a33f0a967b4d` | idle | Install and run omniroute globally |

- 本 session = `wF:p3`(752726ea…),**不要關**。
- 本次只關 `wF:p2`(Sec ch. supervisor;副頻道線已收,交接檔 docs/subchannel-verdict)。
- 總督導指定**先別關**:`wF:p4`(BRAIN)、`wF:p1`(主頻道)、`wB:p1`、`w9:p1`。
- **未經授權、我不動**:`wE:p1`(Herdr優化員)、`wG:p4`(omniroute)、`w1:p1`(BRAIN 結算量測)、`wF:p5`(總督導自己)。
