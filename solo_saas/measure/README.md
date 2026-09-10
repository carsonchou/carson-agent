# `solo_saas/measure/` —— 量測儀器(不是產品的一部分)

這裡的東西**不參與偵測**,只負責產生 `docs/solo-saas/2026-09-10_selfcontra_findings.md`
裡的每一個數字。放進 repo 的理由只有一個:
**那份文件的數字是承重的,而承重的數字必須有人能重跑。**
(memory `only-what-lands-on-disk-exists`:講在對話裡的等於沒做。)

跑法一律用產線那個直譯器的**絕對路徑**(工作目錄會在 `D:\carson-agent` 和
`D:\carson-agent\solo_saas` 之間跳):

```
D:\carson-agent\youtube_channel\.venv\Scripts\python.exe solo_saas\measure\<檔名>
```

| 檔案 | 產生文件裡的哪一段 | 自我驗證 |
|------|--------------------|----------|
| `tp_by_month.py` | §2.1 家族×分類、§2.2 按月表、§2.3 家族組成 | 標籤必須正好綁到 12/1/12 支**精確路徑**,且被標記的 25 支全部有標籤,否則 assert 死 |
| `tp_stats.py` | §2.2 的 Wilson 95% 區間、12 支真陽性的日期與目錄 | —(讀同一份標籤) |
| `cmp_predicates.py` | §2.5 我的判準 vs 產線**現行**判準(交集 0) | 跑前後對 STUDIO 做 mtime 快照;已知排程雜訊分開印不靜音 |
| `cmp_old_vs_new_gate.py` | §2.6 08-20 版 vs 現行版的按月命中率 | 🔴 重建的 08-20 判準在他們當時的母體必須命中 **77** 支,對不上直接 assert 死 |
| `arith_eval.py` | §8.1~§8.4 算術期間訊號的可用性與準度 | — |
| `window_cluster.py` | §8.3 分群鍵的循環性 | — |
| `total_pop.py` | §8.4 換成 `total` 指標的母體 | — |
| `reaudit_out.txt` | **標籤來源**:25 支被標記稿的排名清單 | — |

## 🔴 標籤是怎麼綁的(踩過一次坑)

`tp_by_month.py` / `tp_stats.py` 把三分類(a/b/c)綁在 `reaudit_out.txt` 的**排名**上,
再由排名對到**精確相對路徑**。第一版是用檔名關鍵字比對,結果同一檔股票的多支副本
(堡達3537 有三支、廣閎科6693 兩支…)被一次全部命中,真陽性被灌成 19 支
(memory `flattened-key-hides-evidence`)。所以現在有兩道 assert:
標到的支數必須正好 12 / 1 / 12,而且被標記的 25 支不能有任何一支對不到標籤。

## ⚠️ 這裡沒有的東西

- **召回率**。沒有獨立標註集,所有數字都是精確率側的。
- **產線那 36 支的精確率**。那 36 支的原檔沒有人開過,不能假設它們都是真的錯。
