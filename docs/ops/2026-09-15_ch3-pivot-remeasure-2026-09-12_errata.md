# errata:`docs/ch3-pivot-remeasure-2026-09-12.md` §6(僅補充,不改動原檔)

原檔(commit `07505427`)已經 Phase B 指紋驗證凍結,本檔不碰原檔本體,僅補充一個原檔本身指不到的落差。

**①哪一段不完整**:§6「兩處爭議的答案」裡「英語教材片混進記憶類結果……4支勝出裡1支,不是2支」這句,算的是 top-10 排名窗、單一查詢(`how to remember what i read`)。原檔沒有註明這是 top-10 窗下的數字。

**②完整數字(同一查詢,三輪r1/r2/r3一致)**:top10=1、top20=2、top50=3。top-50窗下三個教材頻道(English With Ethan、VUS - Learning English Podcast、Daily English Flow)三輪都在勝出名單裡,分別落在約第6–7名、16–20名、30–36名。窗口拉大,污染比原句字面讀起來更明顯,但結論方向(拿掉教材片不影響主結論)不變。

**③佐證**:數字經 wF:p8 獨立重算三份raw JSON(`r1_20260911T1830Z.json`/`r2_20260914T0111Z.json`/`r3_20260915T0734Z.json`)複核,與 Phase C fresh-context 獨立驗證(`docs/ops/2026-09-15_ch3_remeasure_phaseC_content_verification.md`,commit `f58f6190804fe947e6e9ab43e2b6e55d6a468905`)一致。

**④commit**:本檔commit hash見送出後回報(`never-guess-identifiers-in-reports`,待git回傳補上,不用記憶填)。
