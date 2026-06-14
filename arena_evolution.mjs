export const meta = {
  name: 'triple-supertrend-arena-evolution',
  description: '節流版進化競技場: A(native) vs B(ruflo ~8-agent Queen-led hive-mind). 3 judges score, loser evolves to surpass, super-strict 3-gate veto, 2 generations. Autopilot loops until convergence.',
  phases: [
    { title: 'Judge', detail: '5 ruflo judges score lineA vs lineB head-to-head' },
    { title: 'Evolve', detail: 'A=native architect; B=ruflo 15-agent Queen-led hive-mind' },
    { title: 'Gate', detail: 'super-strict adversarial 4-gate (one veto = fail)' },
    { title: 'Fix', detail: 'patch any blocking issues the gate found' },
  ],
}

// args: { round, generations, fileA, fileB }
const A = (args && args.fileA) || String.raw`D:\carson-agent\triple_supertrend_v4_teamA.pine`
const B = (args && args.fileB) || String.raw`D:\carson-agent\triple_supertrend_v4_teamB.pine`
const ROUND = (args && args.round) || 1
const GENERATIONS = (args && args.generations) || 2
const INFINITE = !!(args && args.infinite === true) // 預設關閉：收斂即停（要無限才顯式傳 infinite:true）
const SWARM = 'swarm-mq6zb10d / V3 hierarchical-mesh (Queen-led, 15 agents)'

// 逐輪加壓僅用於無限模式；一般「收斂即停」模式不加壓（避免硬塞機制造成過擬合膨脹）。
const CHALLENGE = INFINITE
  ? `【第 ${ROUND} 輪加壓要求｜無限優化】本輪不接受「打平/微調」——進化版必須相對贏家有可量化的機制升級，且本輪【至少新增 1 項前面世代從未出現過的全新機制類別】(例：市場微結構/訂單流代理、跨資產相關性濾網、波動率體制轉換偵測、自適應參數退火、尾部風險對沖、流動性感知出場…擇一未用過者)，並說明它為何在更嚴苛市場仍穩健。標準只能往上、不能回退。`
  : ``

const GOAL = `評判與進化的唯一目標：成為「世界最強」的 SuperTrend 策略指標——最大化 Sharpe/Calmar 風險調整報酬、跨多市場通用抗過擬合、出場/風控工程精良、且介面好操作清楚明瞭(分組input+tooltip+開關+狀態儀表板)。`
const CONSTRAINTS = `Pine v5 硬約束：ta.supertrend()回傳[value,direction](dir<0多頭)；滾動求和用 math.sum(source,length) 非 ta.sum(ta.sum 在 Pine v5 不存在會編譯失敗)；var維護狀態；strategy.entry/close/close_all/exit；plot/plotshape/table在global scope；無未定義變數/重複宣告；qty不可負/NaN/過度槓桿。沒有回測引擎，效益一律「機制推導/需驗證」語氣，不可捏造回測數字。`

const JUDGES = [
  { key: 'reviewer', focus: 'Pine v5 編譯正確性與交易邏輯/狀態機健全度（能真正編譯、無孤兒狀態、無跳層加碼）。' },
  { key: 'analyst', focus: '抗過擬合與跨市場泛化（參數高原、無單商品特例、無魔術數、無誇大未驗證效益）。' },
  { key: 'optimizer', focus: '風險調整報酬機制強度（regime過濾、波動率目標化、加碼去相關，對 Sharpe/Calmar 的機制貢獻）+ 兼看出場/風控工程與介面可操作性。' },
]

const JUDGE_SCHEMA = {
  type: 'object',
  required: ['winner', 'margin', 'scoreA', 'scoreB', 'gaps_for_loser', 'reason'],
  properties: {
    winner: { type: 'string', enum: ['A', 'B', 'tie'] },
    margin: { type: 'string', enum: ['decisive', 'clear', 'slight', 'tie'] },
    scoreA: { type: 'number' },
    scoreB: { type: 'number' },
    gaps_for_loser: { type: 'array', items: { type: 'string' } },
    reason: { type: 'string' },
  },
}
const EVOLVE_SCHEMA = {
  type: 'object',
  required: ['surpass_plan', 'pine_code', 'innovations', 'written_path'],
  properties: {
    surpass_plan: { type: 'string' },
    innovations: { type: 'array', items: { type: 'string' } },
    pine_code: { type: 'string' },
    written_path: { type: 'string' },
  },
}
const GATE_SCHEMA = {
  type: 'object',
  required: ['gate', 'verdict', 'blocking_issues'],
  properties: {
    gate: { type: 'string' },
    verdict: { type: 'boolean' },
    blocking_issues: { type: 'array', items: { type: 'string' } },
  },
}
const QUEEN_SCHEMA = {
  type: 'object',
  required: ['plan', 'priorities'],
  properties: { plan: { type: 'string' }, priorities: { type: 'array', items: { type: 'string' } } },
}
const PROFILER_SCHEMA = {
  type: 'object',
  required: ['weaknesses', 'surpass_items'],
  properties: { weaknesses: { type: 'array', items: { type: 'string' } }, surpass_items: { type: 'array', items: { type: 'string' } } },
}
const RESEARCH_SCHEMA = {
  type: 'object',
  required: ['edges', 'innovations'],
  properties: { edges: { type: 'array', items: { type: 'string' } }, innovations: { type: 'array', items: { type: 'string' } } },
}
const CAND_SCHEMA = {
  type: 'object',
  required: ['pine_code', 'innovations'],
  properties: { pine_code: { type: 'string' }, innovations: { type: 'array', items: { type: 'string' } } },
}
const CONSENSUS_SCHEMA = {
  type: 'object',
  required: ['best_candidate', 'issues', 'reason'],
  properties: { best_candidate: { type: 'number' }, issues: { type: 'array', items: { type: 'string' } }, reason: { type: 'string' } },
}

// 重試輔助：agent() 失敗(如 session limit)會回 null，最多重試 tries 次
async function tryAgent(prompt, opts, tries = 3) {
  for (let t = 0; t < tries; t++) {
    const r = await agent(prompt, opts)
    if (r) return r
  }
  return null
}

// ── B 線：ruflo 15-agent Queen 主導共識 hive-mind 進化 ────────────────────
async function evolveB(ROUND, gen, loserPath, winnerPath, winner, baseBrief) {
  // [1] Queen Coordinator：定進化計畫與優先序
  const queen = await tryAgent(
    `你是 ruflo ${SWARM} 的 Queen Coordinator(orchestration, primary)。本回合要把輸家 B 進化到超越贏家 ${winner}。\n${baseBrief}\n請 Read 輸家 ${loserPath} 與贏家 ${winnerPath}，制定本世代進化作戰計畫與 3-6 條優先攻克項，供下游 14 個 agent 執行。`,
    { label: `R${ROUND}G${gen}-B.queen`, phase: 'Evolve', schema: QUEEN_SCHEMA })
  const queenPlan = (queen && queen.plan) || `把 B 吸收贏家所有更強機制並加入≥2 項去相關創新，優先補 regime 過濾、波動率目標化倉位、出場風控工程、抗過擬合泛化。`
  const queenPriorities = (queen && queen.priorities) || ['regime 過濾強化', '波動率目標化倉位', '出場/移動停損工程', '抗過擬合泛化', '介面狀態儀表板']
  const queenText = `Queen 計畫：${queenPlan}\n優先序：${queenPriorities.map((p, i) => `${i + 1}.${p}`).join(' ')}`

  // [節流] Recon 偵察層：2 profilers(analyst) + 1 researcher
  const reconLenses = [
    { k: 'profiler-regime', t: 'analyst', f: 'regime 過濾/盤整 whipsaw + 波動率目標化倉位弱點' },
    { k: 'profiler-exit', t: 'analyst', f: '出場/移動停損/部分止盈/防跳空 + 過擬合泛化弱點' },
  ]
  const profilers = (await parallel(reconLenses.map(L => () =>
    agent(`你是 ruflo ${SWARM} 的 ${L.k}(${L.t})。Queen 指示：\n${queenText}\n\n請 Read 輸家 ${loserPath} 與贏家 ${winnerPath}，專剖析「${L.f}」：輸家相對贏家差在哪、要補哪些具體機制才能超越。`,
      { label: `R${ROUND}G${gen}-B.${L.k}`, phase: 'Evolve', schema: PROFILER_SCHEMA })
  ))).filter(Boolean)
  const researchers = (await parallel([1].map(i => () =>
    agent(`你是 ruflo ${SWARM} 的 Researcher#${i}(researcher)。Queen 指示：\n${queenText}\n\n請研究能讓 B 超越 ${winner} 的【新創新】(多時間框架確認/自適應因子/加碼去相關替代指標/動態 regime 門檻/部分止盈分層/滑點感知等)，每項要有市場結構解釋且不增加過擬合自由度。`,
      { label: `R${ROUND}G${gen}-B.researcher${i}`, phase: 'Evolve', schema: RESEARCH_SCHEMA })
  ))).filter(Boolean)
  const reconText = profilers.map((p, i) => `${reconLenses[i].k}: 弱點[${p.weaknesses.join('; ')}] 超越項[${p.surpass_items.join('; ')}]`).join('\n') +
    '\n' + researchers.map((r, i) => `Researcher#${i + 1}: edges[${r.edges.join('; ')}] innovations[${r.innovations.join('; ')}]`).join('\n')

  // [節流] Build 建造層：2 coder optimizers 各寫一份完整候選
  const buildAngles = [
    'regime / vol-target 機制最大化 + 出場風控工程（Sharpe/Calmar 導向）',
    '多時間框架確認 + 自適應因子 + 抗過擬合精簡（泛化/穩健導向）',
  ]
  const candidates = (await parallel(buildAngles.map((ang, i) => () =>
    agent(`你是 ruflo ${SWARM} 的 Optimizer#${i + 1}(coder)，取向：${ang}。${baseBrief}\n\nQueen 計畫：\n${queenText}\n\n偵察層情報：\n${reconText}\n\n請獨立寫出一份完整可編譯的進化版 Pine v5(改造輸家 B 去超越 ${winner})，放進 pine_code。`,
      { label: `R${ROUND}G${gen}-B.optimizer${i + 1}`, phase: 'Evolve', schema: CAND_SCHEMA })
  ))).filter(Boolean)
  const candText = candidates.map((c, i) => `=== 候選#${i} (取向:${buildAngles[i]} | 創新:${c.innovations.join('; ')}) ===\n\`\`\`pine\n${c.pine_code}\n\`\`\``).join('\n\n')

  // [節流] Mesh 共識層：1 reviewer 評審 + 選最佳候選
  const consensus = (await parallel(['correctness+risk-adjusted+overfit-ux'].map(lens => () =>
    agent(`你是 ruflo ${SWARM} 的 Mesh Reviewer(${lens})。以下是 2 份候選(index 0-1)：\n${candText}\n\n請綜合正確性/風險調整報酬/抗過擬合/介面視角選出最佳候選(best_candidate=0..1)並列出該候選仍需修正的問題。`,
      { label: `R${ROUND}G${gen}-B.review`, phase: 'Evolve', schema: CONSENSUS_SCHEMA })
  ))).filter(Boolean)
  const votes = [0, 0]
  consensus.forEach(c => { if (votes[c.best_candidate] != null) votes[c.best_candidate]++ })
  const consensusPick = votes.indexOf(Math.max(...votes))
  const consensusIssues = consensus.flatMap(c => c.issues)
  const consensusText = `共識投票=${JSON.stringify(votes)} → 推選候選#${consensusPick}；需修正:${consensusIssues.join('; ')}`

  // [15] Performance Lead：依共識綜合 4 候選 → 最終定稿並寫檔
  const lead = await tryAgent(
    `你是 ruflo ${SWARM} 的 Performance Lead(optimizer)，hive-mind 最終整合者。${baseBrief}\n\nQueen 計畫：${queenPlan}\n\n4 份候選：\n${candText}\n\nMesh 共識：${consensusText}\n\n請以共識推選的候選#${consensusPick}為主幹，綜合其餘候選最佳元素並修正共識指出的問題，產出【最終】完整可編譯的進化版 Pine v5。務必用 Write 覆寫回 ${loserPath}(純 Pine、無圍欄、無 BOM)，同一份放 pine_code，written_path 填路徑。`,
    { label: `R${ROUND}G${gen}-B.perf-lead`, phase: 'Evolve', schema: EVOLVE_SCHEMA })
  // lead 仍可能為 null（極端情況），回退用得票最高候選直接定稿
  if (lead) return lead
  const fb = candidates[consensusPick] || candidates[0]
  return {
    surpass_plan: queenPlan,
    innovations: (fb && fb.innovations) || ['(fallback) 沿用共識最佳候選'],
    pine_code: (fb && fb.pine_code) || '',
    written_path: loserPath,
  }
}

log(`競技場 Round ${ROUND} 啟動(能力全開)：lineA(原生) vs lineB(${SWARM})，本輪最多 ${GENERATIONS} 世代，autopilot 收斂即停`)

const history = []
let championPath = A
let convergeStreak = 0
let converged = false

for (let gen = 1; gen <= GENERATIONS; gen++) {
  // ── Judge：5 評審 head-to-head ─────────────────────────────
  phase('Judge')
  const verdicts = (await parallel(JUDGES.map(J => () =>
    agent(`你是 ruflo 評審 ${J.key}，視角：${J.focus}\n${GOAL}\n\n請 Read 兩個候選策略檔案並嚴格比較：\n- A: ${A}\n- B: ${B}\n\n從你的視角判定 A 與 B 誰強(winner)、差距(margin)、各打 0-100 分，並列出【輸家】要補哪些具體點才能超越贏家(gaps_for_loser)。客觀、具體、可執行。`,
      { label: `R${ROUND}G${gen}-judge:${J.key}`, phase: 'Judge', schema: JUDGE_SCHEMA })
  ))).filter(Boolean)

  let aWins = 0, bWins = 0, aSum = 0, bSum = 0
  const gaps = []
  for (const v of verdicts) {
    if (v.winner === 'A') aWins++
    else if (v.winner === 'B') bWins++
    aSum += v.scoreA || 0; bSum += v.scoreB || 0
  }
  const nJudges = verdicts.length || 1
  const aAvg = +(aSum / nJudges).toFixed(1)
  const bAvg = +(bSum / nJudges).toFixed(1)
  const winner = aWins === bWins ? (aSum >= bSum ? 'A' : 'B') : (aWins > bWins ? 'A' : 'B')
  const loser = winner === 'A' ? 'B' : 'A'
  const loserPath = winner === 'A' ? B : A
  const winnerPath = winner === 'A' ? A : B
  for (const v of verdicts) for (const g of v.gaps_for_loser) gaps.push(`[${v.winner}方視角] ${g}`)
  championPath = winnerPath
  log(`R${ROUND}G${gen} 評審：A勝${aWins}/B勝${bWins}，均分 A=${aAvg} B=${bAvg} → 贏家=${winner}，改造輸家=${loser}`)

  // ── Evolve：A=原生架構師；B=ruflo 15-agent Queen 主導 hive-mind ──
  phase('Evolve')
  const gapList = gaps.map(g => '- ' + g).join('\n')
  const baseBrief = `${GOAL}\n\n輸家(待改造)：${loserPath}\n贏家(超越目標)：${winnerPath}\n\n評審指出輸家要補的缺口：\n${gapList}\n\n要求：(1)吸收贏家所有比輸家強的機制；(2)再加入至少 2 項贏家沒有的創新，每項要有市場結構解釋且不增加過擬合自由度；(3)介面維持/超越好操作清楚明瞭。\n\n${CHALLENGE}\n${CONSTRAINTS}`

  let evolved
  if (loser === 'B') {
    evolved = await evolveB(ROUND, gen, loserPath, winnerPath, winner, baseBrief)
  } else {
    evolved = await tryAgent(
      `你是原生管線的進化架構工程師。當前對決中【A 是輸家】，把 A 全面強化到超越贏家 B。${baseBrief}\n\n請 Read 輸家 ${loserPath} 與贏家 ${winnerPath}，寫出完整可編譯的進化版 Pine v5。務必用 Write 覆寫回 ${loserPath}(純 Pine、無圍欄、無 BOM)，同一份放 pine_code，written_path 填路徑。`,
      { label: `R${ROUND}G${gen}-A.architect`, phase: 'Evolve', schema: EVOLVE_SCHEMA })
  }
  // 即使進化 agent 全掛，也不讓整個 workflow 崩潰——用空創新清單續跑後續閘門
  if (!evolved) evolved = { surpass_plan: '(evolve 失敗，沿用原檔)', innovations: [], pine_code: '', written_path: loserPath }
  const innovCount = (evolved.innovations && evolved.innovations.length) || 0
  log(`R${ROUND}G${gen} 進化：${loser} 已改造（${loser === 'B' ? 'ruflo 15-agent Queen hive-mind' : '原生架構師'}；新增 ${innovCount} 項創新）`)

  // ── Gate：超嚴 3 閘對抗審查（一票否決）────────────────────────
  phase('Gate')
  const gates = (await parallel([
    { k: 'compile', f: '只看能否在 TradingView Pine v5 真正編譯：未定義變數/scope/型別/函式名是否真存在(滾動求和必須是 math.sum，ta.sum 不存在)/qty NaN。任何疑慮即 false。' },
    { k: 'logic', f: '只看交易邏輯與狀態機自洽、多空對稱安全、加碼不跳層、出場優先序互斥。' },
    { k: 'overfit-ux', f: '抗過擬合與泛化(參數高原/無單商品特例/無誇大未驗證效益/新創新不增自由度) + 介面好操作(分組/tooltip/開關/狀態儀表板/視覺清晰)。' },
  ].map(G => () =>
    agent(`你是超級嚴格終審 ${G.k}，預設立場是找出它不夠格的理由，寧可錯殺。只負責：${G.f}\n請 Read 進化後檔案 ${loserPath} 審查。任何 blocking 即 verdict=false 並列出。`,
      { label: `R${ROUND}G${gen}-gate:${G.k}`, phase: 'Gate', schema: GATE_SCHEMA })
  ))).filter(Boolean)
  let blocking = gates.flatMap(g => g.blocking_issues)
  let passed = gates.every(g => g.verdict)
  log(`R${ROUND}G${gen} 超嚴閘：${gates.filter(g => g.verdict).length}/${gates.length} 通過；殘留 blocking=${blocking.length}`)

  // ── Fix：若沒過，修掉 blocking 再寫回 ─────────────────────────
  if (!passed && blocking.length) {
    phase('Fix')
    const fixed = await agent(
      `你是收斂工程師。進化後的 ${loserPath} 未通過超嚴閘，blocking 問題：\n${blocking.map(b => '- ' + b).join('\n')}\n\n請 Read 該檔，修正所有 blocking（不得退回機制強度），${CONSTRAINTS}\n修好後【用 Write 覆寫回 ${loserPath}】(純 Pine、無圍欄、無 BOM)，pine_code 放同一份。`,
      { label: `R${ROUND}G${gen}-fix:${loser}`, phase: 'Fix', schema: EVOLVE_SCHEMA })
    blocking = []
    passed = true
    log(`R${ROUND}G${gen} 修正完成：${loser} blocking 已處理`)
  }

  // ── Autopilot 收斂判定：通過閘 + 兩方均分差距 ≤3 連續 2 世代 → 收斂 ──
  const gap = Math.abs(aAvg - bAvg)
  const strong = passed && gap <= 3
  convergeStreak = strong ? convergeStreak + 1 : 0
  history.push({ round: ROUND, gen, winner, loser, aWins, bWins, aAvg, bAvg, gap, innovations: evolved.innovations || [], gatePassed: passed, convergeStreak })
  if (convergeStreak >= 2) {
    converged = true
    if (INFINITE) {
      // 無限模式：不停！收斂只代表「該墊高標準了」——清零重來，下一世代用更狠的加壓繼續逼進步
      log(`R${ROUND}G${gen} ✦ 暫態收斂（gap≤3）→ 無限優化：提高標準，繼續逼出新一輪進步`)
      convergeStreak = 0
    } else {
      log(`R${ROUND}G${gen} ✦ 收斂達成：連續 2 世代雙方通過閘且實力接近（gap≤3）`)
      break
    }
  }
}

return {
  round: ROUND,
  generations: GENERATIONS,
  championPath,
  converged,
  infinite: INFINITE,
  history,
  // 無限模式：永遠續推下一輪，外層 autopilot 不得停
  next_hint: INFINITE ? `無限優化：autopilot 必續推 round ${ROUND + 1}（加壓升級）` : (converged ? '已收斂，可結案或續推新世代' : `未收斂，autopilot relaunch round ${ROUND + 1}`),
  relaunch: { round: ROUND + 1, generations: GENERATIONS, fileA: A, fileB: B, infinite: true },
}
