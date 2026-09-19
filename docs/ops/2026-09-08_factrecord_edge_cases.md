# `_fact_record_key` 的兩個銳角 —— 給主頻道線(基建線 2026-09-08 驗證所得)

> **這不是 bug 報告,是兩個「現在碰不到、但條件變了就會碰到」的角落。**
> 對象:`youtube_channel/scripts/produce_batch.py` 的事實溯源 sidecar(`cb52ae03`)。
> 🔴 **不建議現在改** —— 理由寫在第四節,改 key 會讓已驗過的東西要重驗。
>
> 走總督導轉達,不直接對線。理由是 09-05 那次的形狀(memory `yt-quota-is-per-cloud-project`):
> 兩個 session 各自算了一遍、各自去改,結果一起修了一個不存在的問題。**跨線的事實只走一條路才對得起來。**

---

## 一、那段程式在做什麼(獨立看懂用)

`cb52ae03` 讓每支產出的片落一份 `output/{slug}.facts.json`,記「這支片是從哪幾條 fact 寫出來的」。

鏈路四段:

| # | 位置 | 動作 |
|---|---|---|
| 1 | `produce_batch.py:2148` `_record_fact_keys()` | 把記錄塞進模組層 dict `_LAST_FACT_KEYS`,鍵 = `_fact_record_key(topic)` |
| 2 | `:2842` `call_claude` | `_LAST_FACT_KEYS.pop(_fact_record_key(topic), None)` 取出 |
| 3 | `:3026` | 掛上 `result["_fact_record"]` |
| 4 | `:6465-6487` `make_one` | 寫 `{slug}.facts.json`(`tmp → os.replace`,整段 fail-open) |

鍵怎麼算(`:2137-2146`):

```python
_id = topic.get("id")
if _id not in (None, ""):
    return f"id:{_id}"
return "title:" + str(topic.get("title", ""))[:160]
```

---

## 二、銳角 A:沒有 `id` 時,鍵退回標題 ⇒ 可能撞號

**怎麼觸發**:兩個 topic **都沒有 `id`** 且**標題相同**(或都沒有標題)。

實測(基建線跑的,不是推論):

| 輸入 topic | 算出的鍵 | |
|---|---|---|
| `{'id':'a1','fact_key':'k__1','title':'甲'}` | `'id:a1'` | |
| `{'fact_key':'k__1','title':'甲'}` | `'title:甲'` | |
| `{'title':'甲'}` | `'title:甲'` | 🔴 **與上一列同鍵** |
| `{'fact_key':'k__2','title':'乙'}` | `'title:乙'` | |
| `{'title':'乙'}` | `'title:乙'` | 🔴 **與上一列同鍵** |
| `{}`(空 topic) | `'title:'` | 🔴 **所有空 topic 全部同鍵** |

⚠️ 注意 `fact_key` **不參與**鍵的計算,所以兩個標題相同、事實不同的 topic 分不開。

**影響哪個路徑**:第 2 段的 `pop`。撞號時後寫的會蓋掉先寫的
⇒ **一支片的 sidecar 可能記到另一支片的 fact_keys**。
🔴 **那比「沒有 sidecar」更糟** —— 沒有的話會被發現,記錯的會被當成憑據用。

## 三、銳角 B:`len > 64` 時 `clear()` 清掉全部

`:2165`:

```python
if len(_LAST_FACT_KEYS) > 64:
    _LAST_FACT_KEYS.clear()
```

**怎麼觸發**:同一個 process 內累積超過 64 筆未被 pop 的殘渣。
**影響**:`clear()` 清的是**整個 dict**,理論上能清掉一筆**正在飛**(已 record、還沒 pop)的記錄
⇒ 那支片靜默沒有 sidecar。

---

## 四、🔴 為什麼**現在不是活 bug**,以及不建議現在改

兩個銳角都需要**同一個 process 內交錯**才會發生,而目前結構上不會:

1. **record → pop 是連續的**:`_record_fact_keys` 在 `call_claude` 內部呼叫,
   而同一次 `call_claude` 在 `:2842` 就把它 pop 走。中間沒有第二支片插進來的縫。
2. **平行跑是不同 process**:`produce_batch` 平行執行是多個獨立行程
   (memory `herdr-parallel-work-preference` 提到要帶 `--stock` 免得互搶題庫),
   **模組層的 `_LAST_FACT_KEYS` 不共用**。
3. 銳角 B 還多一個保護:`clear()` 發生在**塞入新記錄之前**,所以當下這一筆一定活著。

⇒ 要讓它變成活 bug,得先有「同 process 內交錯產製」這個新條件出現。

**若將來真要防**,最小改法是把 `fact_key` 併進鍵(它是每支片唯一的):
```python
return f"id:{_id}" if _id else "fk:%s|title:%s" % (topic.get("fact_key",""), str(topic.get("title",""))[:120])
```
⚠️ **但改鍵就要重驗第 1、2 段的來回** —— 那是這條鏈最脆的地方,不是改完就算。

---

## 五、基建線驗到什麼(給你們判斷可信度用)

全部是**執行期**驗的,不是讀碼;第 4 段跑的是**原始碼本身**(從檔案抓那 23 行 compile 後執行),不是抄本。

| 檢查 | 結果 |
|---|---|
| 同一個 topic 兩次算出同一把鍵 | ✅ |
| 記進去 pop 得回來,六個欄位完整 | ✅ |
| **陰性對照**:別的 topic 拿不到這一筆 | ✅(沒有這條,「拿得回來」和「對誰都回同一筆」分不開) |
| 第 4 段正常路徑:寫得出 `.facts.json`、8 個欄位、**無殘留 `.tmp`** | ✅ `os.replace` 生效 |
| **陰性對照**:`_fact_record` 不是 dict 時**不寫檔** | ✅ |
| **陰性對照**:寫檔失敗時**不拋例外**且留下一行 ops | ✅ `補產·事實溯源 ⚠️ … sidecar 寫入失敗(不影響產線)` |

⇒ **四段鏈路每一段都被實際執行過了**,唯一還沒發生的是「一次真實產製把四段連起來跑」。

📌 對答案用:**下一輪產製後 `output/*.facts.json` 的數量應等於該輪個股體檢片數。**
查法零成本:`ls youtube_channel/output/*.facts.json | wc -l`
若產了片而數量是 0 ⇒ 去看 `ops_log` 的「補產·事實溯源」那行(它 fail-open,**不會有別的訊號**)。
