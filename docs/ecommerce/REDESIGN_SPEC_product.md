# 量化阿森電商 v2 — 成品視覺 + 渲染管線規格(產品篇)

> 對應任務:v1「做不夠好、全部重做」中的**成品視覺系統 + 渲染管線選型**。
> 姊妹文件:`REDESIGN_SPEC_business.md`(商品線/定價/漏斗,由 spec-business 負責)。
> 本文所有 token 皆已在 mockup 實跑驗證:
> `quant-service/ecommerce/mockup/subscription_weekly_sample.html`(+ `.pdf` + `render.py`)。

---

## 0. v1 現況(baseline,要超越的對象)

| 面向 | v1 實況 | 問題 |
|---|---|---|
| 旗艦訂閱週報交付 | `subscription_report.py` **只吐純文字 `.md`**,email/telegram 純文字送出 | 旗艦商品沒有任何成品排版,像記事本,完全撐不起訂閱費 |
| 一次性 SKU 報告 | `product_factory.md_to_pdf` 用 **reportlab + STSong-Light**(淺灰底/office 排版) | 白底、無品牌、無圖表、無數據卡質感;與頻道暗色品牌完全脫節 |
| xlsx | `csv_to_xlsx` **裸傾印**:單一 `tracker` 工作表、只設欄寬 | 無凍結窗格/篩選/條件格式/表頭樣式,不像數據產品 |
| 圖表 | **完全沒有** | 純數字表格,無 sparkline / 位階 / 對照視覺 |
| 色彩 | 灰階 | 沒有台股漲紅跌綠、沒有暗金 accent |

**baseline 誠信面(要保留、不可退化)**:v1 的溯源守門(`fact_source_guard` fail-closed)、
「介紹≠推薦」、數字綁定來源欄位(`Provenance.num` / `_fact_ok`)是對的,v2 **只換視覺與渲染外殼,
誠信結構原封搬進來**(見 §7)。

---

## 1. 渲染管線選型(定案)

### 定案:HTML + CSS → headless Chromium(Playwright)→ `page.pdf()`

**已實跑驗證**:Chromium 148.0.7778.96 本機可啟動;`render.py` 產出 536 KB A4 PDF,
深色底真的印進去、繁中零缺字(見 mockup)。

### 為什麼不是別的

| 方案 | 判定 | 理由 |
|---|---|---|
| **reportlab(v1)** | ✗ 淘汰 | 手刻 flowable、無 CSS、深色底/圖表/數據卡幾乎不可能做到位;維護成本高 |
| **WeasyPrint** | ✗ 不用 | 純 CSS 引擎但不吃 flexbox/grid 的完整實作、SVG/漸層支援弱,做暗金質感會處處受限;還要另裝 GTK 依賴 |
| **matplotlib 直出整頁** | ✗ 不用 | 排版能力弱,做不出封面/數據卡/雙語版式 |
| **HTML→Chromium(定案)** | ✅ | 完整 CSS grid/flex、漸層、SVG、system 繁中字型;WYSIWYG(瀏覽器怎麼看就怎麼印);本機已裝 Playwright;和 web_center 前端同一套技術棧,可共用元件 |

### 管線關鍵參數(已驗證,見 `render.py`)

```python
pg.emulate_media(media="print")
pg.pdf(
    prefer_css_page_size=True,   # 尊重 .page 的 210mm×297mm,不被預設 A4 邊界干擾
    print_background=True,        # ★ 深色底真的印進 PDF(不設 → 白底)
    margin={"top":"0","bottom":"0","left":"0","right":"0"},  # 邊界改由 CSS .pad 管
)
```

CSS 端必配:
```css
html{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }  /* 強制印背景色 */
```

### 分頁策略(重要,決定「頁首頁尾/頁碼/分頁控制」怎麼做)

**定案:顯式 A4 頁面 div(`.page { width:210mm; height:297mm; page-break-after:always }`)。**
每頁是一個固定尺寸容器,背景/邊框/頁首/頁尾/頁碼**逐頁烘進 DOM**,得到像素級可控、
所見即所印。這是設計型 PDF 的專業做法,勝過「一長條讓 Chromium 自動分頁」。

- **頁首/頁尾**:每頁 div 內各放一個 `.runhead` / `.runfoot`(品牌 logo + 期號 + 頁碼)。
  不用 Playwright 的 `header_template/footer_template`(它在獨立白底 context 渲染、
  吃不到頁面 CSS、樣式受限,是已知痛點)。
- **頁碼**:寫死在每頁 `.runfoot`(顯式分頁下本就知道第幾頁),不靠不可靠的 CSS `counter(page)`。
- **動態長度內容的自動分頁**(真引擎需要,mockup 因內容固定是手排):
  在 Chromium 內用 JS 量測 `card.offsetHeight`,把資料卡依序塞進當前 `.page` 直到裝滿
  (超過可用高度就開新頁),再 `page.pdf()`。→ §5 演算法。

### 已知坑(實跑遇到 / 要留意)

1. `print_background` **一定要開**,否則深色底整片變白(v2 命脈)。
2. 深色底 PDF 檔案較大(mockup 3 頁 536 KB;滿版深色點陣紋理會加大)——可接受,
   若要壓可把 `.page::before` 點陣紋理 opacity 降低或改用更省的漸層。
3. 繁中**必須明確指定** `font-family`,不能靠 Chromium 預設 fallback:
   本機已確認有 `Microsoft JhengHei`(msjh/msjhbd/msjhl)、`Noto Sans TC`、`Noto Serif TC`。
4. `wait_until="networkidle"`:所有資產走 inline(SVG/漸層/data-uri),不依賴外網,離線可印。
5. 圖表用 **inline SVG**(sparkline/位階條/對照橫條)——向量清晰、主題一致、可套 CSS 變數;
   只有「多點權益曲線/價格走勢」這種點多的才退回 matplotlib 暗色 PNG 嵌 data-uri(§4)。

---

## 2. 視覺 token(色票 / 字級 / 間距)

### 2.1 色票(hex,已在 mockup 生效)

**深色基底**
| token | hex | 用途 |
|---|---|---|
| `--bg` | `#0B0E14` | 主背景(近黑帶藍) |
| `--bg2` | `#0D1017` | 頁面漸層底 |
| `--card` | `#141922` | 數據卡表面 |
| `--card2` | `#1A2029` | 抬升卡面 |
| `--pod` | `#10151D` | 內嵌 pod / KPI 底 |
| `--line` | `#242C38` | 髮絲線(弱) |
| `--line2` | `#2E3745` | 邊框(強) |

**文字**
| token | hex | 用途 |
|---|---|---|
| `--tx` | `#E6EAF0` | 主文(off-white,不用純白才高級) |
| `--tx2` | `#9AA5B5` | 次文 |
| `--tx3` | `#5D6675` | 說明/caption |

**暗金 accent(頻道品牌色)**
| token | hex | 用途 |
|---|---|---|
| `--gold` | `#C9A227` | 暗金主色(eyebrow/標題強調) |
| `--gold-hi` | `#E3B93E` | 亮金(高亮/marker/sparkline) |
| `--gold-deep` | `#8A6D1C` | 深金(漸層底/分隔線) |

**台股漲跌色(★ 慣例:漲/正=紅、跌/負=綠 —— 與西方相反,硬規)**
| token | hex | 用途 |
|---|---|---|
| `--up` | `#FF5C5C` | 漲/正報酬(紅) |
| `--dn` | `#33D69F` | 跌/負報酬(綠) |
| `--amber` | `#E3B93E` | 燈號中段 |

> **3 個關鍵 hex**:背景 `#0B0E14`、暗金 `#C9A227`、台股紅 `#FF5C5C` / 綠 `#33D69F`。

**燈號(估值位階,只標位置、非買賣)**:綠 `#33D69F`(≤P60)/ 琥珀 `#E3B93E`(P60–95)/ 紅 `#FF5C5C`(≥P95)。

### 2.2 字體與字級階層

**字族**
- 內文/數據:`"Microsoft JhengHei","Noto Sans TC","Segoe UI",-apple-system,sans-serif`
- 封面大標(magazine 質感):`"Noto Serif TC",serif`
- 全域 `font-variant-numeric:tabular-nums`(數字等寬,表格/KPI 對齊)

**字級(px,已驗證)**
| 角色 | size / weight / 其他 |
|---|---|
| 封面大標 masthead | 58 / 700 / Noto Serif TC,line-height 1.06 |
| eyebrow(小標籤) | 10–12 / letter-spacing .14–.34em / uppercase / 金色 |
| 區塊 H2 | 19 / 600 |
| 資料卡股名 | 18 / 700(code 11、mono、`--tx3`) |
| KPI 大數字 | 20–30 / 700 / tabular |
| 內文 | 11.5–12.5 / line-height 1.7 |
| 表格 cell | 11.5 / tabular |
| 說明/來源 | 9.5–10 / `--tx3` |

### 2.3 版式與間距

- 頁面:`.page` 210×297mm;`.frame` 內縮 9mm 髮絲金框;`.pad` 內距 11mm 12mm 14mm。
- 卡片圓角 8–11px、左緣 3px 金色漸層 bar(品牌記號)、`--line2` 邊框。
- 背景層次:雙 radial(右上暗金光暈 10% + 左下冷藍 14%)+ 垂直漸層 + 極淡點陣紋理
  (`radial-gradient` dot,22px 間距,opacity .5)——質感但不喧賓。bloom 一律克制
  (box-shadow 發光 ≤ 10px、opacity ≤ .3),符合 Carson「暗才高級、發光克制」。

---

## 3. 數據卡元件規格

### 3.1 本期總覽密表(封面後第一頁,Carson 要的「密、可排序」)

- 表頭:深色帶 `#0E141C`、金字 `--gold`、下緣 1.5px `--gold-deep`;每欄附排序提示符
  (`▼` / `A→Z`)標明**預設排序鍵**(視覺暗示可排序;真互動在 web_center,PDF 內是靜態快照)。
- 每列:股名(粗)+ 代號(mono、`--tx3`)、年化報酬(台股紅綠)、最大回撤(綠)、
  **估值位階 cell**、最長套牢、殖利率。
- 斑馬紋:偶數列 `rgba(255,255,255,.014)`(極淡)。
- 數字欄一律右對齊 + tabular-nums。

### 3.2 紅綠燈號 + 估值位階條(誠信核心元件)

**估值位階不用「買賣燈」,用「位置條」**——這是把「介紹≠推薦」做進視覺:
- 燈號 dot 只標**落在自身近 10 年區間的哪一段**(綠≤P60 / 琥珀 P60–95 / 紅≥P95),
  文字寫「P98 偏高」而非「貴/該賣」。
- 位階條:track(`--line`)+ 淡金 IQR 帶(P25–P75)+ 金色 marker(目前本益比)+
  中位刻度;下方標 `P25 / 中位 / P75` 實際倍數。純位置陳述。

### 3.3 sparkline(營收/EPS/毛利率趨勢)

- **inline SVG**:`viewBox` 正規化;`polyline` 金線(`--gold-hi`,1.6px,round join)+
  面積填充 `url(#gf)`(金 28%→0% 垂直漸層)+ 末點 2.6px 金點。
- 右側 meta:最新值(大字)、起點年/值、區間變化(台股紅綠)。
- 真引擎:series 取事實庫既有年度序列;若只有端點,mockup 用示意序列並在免責標「示意序列(端點為真實值)」。

### 3.4 三種買法對照(All-in vs 定投 vs 0050)

- 三條橫 bar,寬度 = 各自報酬 ÷ 該組最大值(同基準才可比):
  All-in 金漸層 / 定投 灰 / 0050 藍。右側數值台股紅綠。一眼看出「單筆 vs 定投 vs 大盤」差距。

### 3.5 崩盤韌性 pod(2008/2020/2022)

- 三個等寬 pod:年度標籤、跌幅(**綠**,因下跌)、「抱到今 +X%」(**紅**,因正報酬)。
  台股色規則貫徹到底。

### 3.6 KPI mini-tile

- `.kpi`:pod 底、上標(uppercase caption)+ 大數字(台股紅綠)。卡頭右側橫排 2–3 顆
  (年化 / 最大回撤 / 最長套牢 或 殖利率)。

---

## 4. 圖表路線(SVG 優先,matplotlib 備援)

| 圖種 | 做法 | 理由 |
|---|---|---|
| sparkline、位階條、對照橫條、KPI | **inline SVG / CSS** | 點少、向量清晰、吃 CSS 變數主題一致、檔案小、可印可縮放 |
| 多點權益曲線 / 還原價格走勢 / 相關熱圖 | **matplotlib 暗色 PNG → data-uri 嵌入** | 點多時手刻 SVG path 不划算;matplotlib 出 2x DPI 深色圖較省 |

**matplotlib 暗色輸出約定**(要與 token 對齊):
```python
plt.rcParams.update({
  "figure.facecolor":"#0B0E14","axes.facecolor":"#10151D",
  "text.color":"#9AA5B5","axes.edgecolor":"#242C38",
  "xtick.color":"#5D6675","ytick.color":"#5D6675","axes.grid":True,
  "grid.color":"#242C38","font.family":"Microsoft JhengHei",
})
# 漲紅跌綠:漲段 #FF5C5C、跌段 #33D69F、主線 #E3B93E;dpi=200 存 PNG → base64 → <img src="data:image/png;base64,...">
```

---

## 5. 動態分頁演算法(真引擎,mockup 因固定內容手排)

```
可用高度 H = 297mm − 上下 pad(≈ 259mm)− runhead − runfoot
current_page = 新 .page(含 runhead/runfoot)
for card in 資料卡序列:
    量測 card.offsetHeight(在同寬容器內先 render 於離屏)
    if 已用高度 + card 高 > H:
        current_page 收尾;開新 .page(頁碼+1,重畫 runhead/runfoot)
    append card 到 current_page;累加高度
封面、總覽、免責頁為固定模板,前後各佔整頁
```
> 在 Playwright 內 `page.evaluate()` 跑量測即可,不需外部排版引擎。

---

## 6. xlsx 儀表板規格(openpyxl)

**設計原則(誠實的人因取捨)**:PDF 是**成品展示** → 全深色高級感;
xlsx 是**使用者要編輯/篩選/列印的工作檔** → **深色表頭 + 淺色斑馬內文 + 台股紅綠條件格式**。
全深色試算表難編輯難列印,故 xlsx 不照抄 PDF 的全暗;此為 ergonomic 取捨,已載明。

**多工作表結構**
1. `總覽`(dashboard):覆蓋個股 × 關鍵欄(年化/回撤/估值位階/殖利率),條件格式儀表。
2. `個股體檢`:逐檔完整事實列(可篩選)。
3. `全市場排行`:1770 檔回測(接 product_factory 一次性 SKU)。
4. `定投對照`:All-in vs 定投 vs 0050 參考列。

**逐項規格(openpyxl 能力)**
| 項目 | 實作 |
|---|---|
| 深色表頭 | `PatternFill(start_color="0B0E14", fill_type="solid")` + `Font(color="E3B93E", bold=True)`;`row_dimensions[1].height=28` |
| 凍結窗格 | `ws.freeze_panes = "B2"`(凍表頭 + 首欄股名/代號) |
| 自動篩選 | `ws.auto_filter.ref = ws.dimensions` |
| 條件格式(台股色) | 報酬/勝率欄用 3 色階 `ColorScaleRule` **低=綠 `2FB877` → 中 `F2F2F2` → 高=紅 `E5484D`**(高報酬=紅,對齊台股);回撤欄反向 |
| 燈號 | 估值位階欄 `IconSetRule('3TrafficLights1')`(或自訂 dot 字元著色) |
| data bar | 淨報酬/成交量等量級欄 `DataBarRule(color="E3B93E")` |
| 數字格式 | 百分比 `0.0"%"`;金額 `#,##0`;代號**留字串**(前導零 0050/00878 不可被吃成數字) |
| 斑馬內文 | 偶數列淡灰 `PatternFill("F4F6F9")` |
| 欄寬 | 依內容量身(股名寬、數字欄窄),上限 40 |

---

## 7. 誠信結構原封搬進 v2(不可退化)

v1 的誠信是對的,v2 **只換皮不動骨**:
- `product_factory.Provenance.num()`:數字仍綁來源欄位、寫 `_provenance.json`;v2 渲染
  只是把同一批已綁定的數字排進 HTML,**不新增任何手打統計**。
- `fact_source_guard` fail-closed gate 保留;`subscription_report._fact_ok`(缺 source/claim/data 丟掉)保留。
- **視覺化元件不得製造新語意**:估值用「位置條」不用「買賣燈」;崩盤/報酬只呈現既有數字;
  sparkline series 來自事實庫,端點為真實值,插值一律標「示意」。
- 每頁 runfoot + 免責頁固定帶「介紹 ≠ 推薦」與資料來源(FinMind / Yahoo 含息還原)。

---

## 8. v1 → v2 升級對照(核心,≥5 點)

| # | v1 | v2 | 升級點 |
|---|---|---|---|
| 1 | 旗艦訂閱週報**只吐純文字 `.md`**(email/tg 純文字) | **品牌化深色 PDF**:封面 / 本期總覽密表 / 個股資料卡 / 免責 四段式 | 旗艦成品從「記事本」→「值得訂閱費的數據刊物」 |
| 2 | reportlab + STSong-Light 淺底 office 排版 | **HTML+CSS → Chromium**,全 token 化、深色印底、繁中 Microsoft JhengHei / Noto Serif TC 零缺字 | 渲染引擎換代,設計自由度與品牌一致性 |
| 3 | 灰階、無品牌 | **暗金鎖色 + 台股漲紅跌綠 + 燈號**,對齊頻道「暗色數據卡 + 金箭頭」 | 品牌識別落進成品 |
| 4 | 逐檔長條列點 | **本期總覽密表**(年化/回撤/估值位階可排序欄 + 燈號 + 位階條) | Carson 要的「密、可排序、資訊密度高」 |
| 5 | xlsx 裸傾印單表 | **多工作表儀表板**:凍結窗格 / 自動篩選 / 台股紅綠條件格式 / 深色表頭 / icon 燈號 / data bar | 從 CSV 傾印 → 專業級可用試算表 |
| 6 | **無任何圖表** | inline SVG **sparkline / 位階條 / 三種買法對照橫條**(+ matplotlib 暗色備援) | 從純數字 → 一眼可讀的視覺數據 |
| 7 | 誠信只在文字 | 誠信**視覺化**:估值用「位置條」非買賣燈、崩盤只呈現既有數字、插值標示意 | 「介紹≠推薦」紅線內建進設計元件 |

---

## 9. 交付物索引

- 規格(本文):`docs/ecommerce/REDESIGN_SPEC_product.md`
- mockup 樣張(HTML):`quant-service/ecommerce/mockup/subscription_weekly_sample.html`
- mockup 渲染 PDF(實跑產出,536 KB,深色底 + 繁中零缺字):
  `quant-service/ecommerce/mockup/subscription_weekly_sample.pdf`
- 渲染管線最小可行版(可直接被 v2 引擎 import 復用):
  `quant-service/ecommerce/mockup/render.py`

> Phase 2a(訂閱週報引擎 v2 實作)可直接把 `subscription_report.py` 的 `generate_weekly_report`
> 輸出改組成本規格的 HTML(用同一份 token + `render.py`),即完成旗艦成品升級。
