const { SUBJECTS, CHOICE_TOTAL_POINTS, CHOICE_LOSS_BUDGET_POINTS, CHOICE_TARGET_POINTS,
  SUBJECT_MAP, clamp, stageLabel, subjectCodeFromItem } = require('./study-strategy-meta')
const { normalizeProfile, getProfile, normalizeSubjectEntry } = require('./study-strategy-profile')

// ``accuracyPct`` is explicitly percent-scaled (1 means 1%).  Legacy ``accuracy``
// stays fraction-based (0.8 means 80%) but still tolerates 0-100 percent values.
function normalizeAccuracy(value, isPct) {
  if (value == null) return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  if (isPct) return clamp(n, 0, 100) / 100
  if (n > 1) return clamp(n / 100, 0, 1)
  return clamp(n, 0, 1)
}

function choiceLossSources(subjectItems) {
  const items = Array.isArray(subjectItems) ? subjectItems : []
  const byCode = {}
  items.forEach(item => {
    const code = subjectCodeFromItem(item)
    if (code && !byCode[code]) byCode[code] = item
  })
  return byCode
}

function choiceLossEntry(meta, source) {
  const attempts = Number(source && (source.totalQuestions != null ? source.totalQuestions : source.total_questions)) || 0
  const hasPctAccuracy = Boolean(source) && source.accuracyPct != null
  const rawAccuracy = hasPctAccuracy
    ? { value: source.accuracyPct, isPct: true }
    : { value: source && source.accuracy, isPct: false }
  const acc = normalizeAccuracy(rawAccuracy.value, rawAccuracy.isPct)
  const hasData = attempts > 0 && acc != null
  const fullPoints = meta.choiceQuestions * 2
  const expectedLoss = hasData ? Math.round(fullPoints * (1 - acc) * 10) / 10 : null
  const expectedScore = hasData ? Math.round((fullPoints - expectedLoss) * 10) / 10 : null
  return {
    hasData,
    coveredQuestions: hasData ? meta.choiceQuestions : 0,
    expectedLoss: hasData ? expectedLoss : 0,
    entry: {
      code: meta.code,
      name: meta.shortName,
      choiceQuestions: meta.choiceQuestions,
      fullPoints,
      hasData,
      attempts,
      accuracyPct: hasData ? Math.round(acc * 100) : null,
      expectedLoss,
      expectedScore,
      lossText: hasData ? `预计失 ${expectedLoss} 分` : '待建立数据',
    },
  }
}

function choiceLossStatus(coveredQuestions, projectedLoss) {
  const fullCoverage = coveredQuestions === 40
  const remainingBudget = Math.round((CHOICE_LOSS_BUDGET_POINTS - projectedLoss) * 10) / 10
  if (!fullCoverage) {
    return {
      fullCoverage,
      remainingBudget,
      status: 'building',
      statusText: `已覆盖 ${coveredQuestions}/40 道选择题配额`,
    }
  }
  if (projectedLoss <= CHOICE_LOSS_BUDGET_POINTS) {
    return {
      fullCoverage,
      remainingBudget,
      status: 'on_track',
      statusText: `预计失分 ${projectedLoss}，在预算内`,
    }
  }
  return {
    fullCoverage,
    remainingBudget,
    status: 'over_budget',
    statusText: `预计超预算 ${Math.abs(remainingBudget)} 分`,
  }
}

function buildChoiceLossBudget(subjectItems) {
  const byCode = choiceLossSources(subjectItems)
  let coveredQuestions = 0
  let projectedLoss = 0
  const subjects = SUBJECTS.map(meta => {
    const result = choiceLossEntry(meta, byCode[meta.code] || null)
    coveredQuestions += result.coveredQuestions
    projectedLoss += result.expectedLoss
    return result.entry
  })
  projectedLoss = Math.round(projectedLoss * 10) / 10
  const summary = choiceLossStatus(coveredQuestions, projectedLoss)
  return {
    totalPoints: CHOICE_TOTAL_POINTS,
    targetPoints: CHOICE_TARGET_POINTS,
    lossBudgetPoints: CHOICE_LOSS_BUDGET_POINTS,
    maxWrongQuestions: CHOICE_LOSS_BUDGET_POINTS / 2,
    coveredQuestions,
    coveredSubjects: subjects.filter(item => item.hasData).length,
    coveragePct: Math.round(coveredQuestions / 40 * 100),
    fullCoverage: summary.fullCoverage,
    projectedLoss,
    projectedScore: Math.round((coveredQuestions * 2 - projectedLoss) * 10) / 10,
    remainingBudget: summary.remainingBudget,
    status: summary.status,
    statusText: summary.statusText,
    subjects,
  }
}

function taskSubjectCode(task, subjectMastery) {
  const params = task && task.route_params && typeof task.route_params === 'object' ? task.route_params : {}
  const code = String(params.subject_code || task && task.subject_code || '').toLowerCase()
  if (SUBJECT_MAP[code]) return code
  const id = Number(params.subject_id || task && task.subject_id) || 0
  if (id) {
    const match = (Array.isArray(subjectMastery) ? subjectMastery : []).find(item => Number(item.subjectId || item.subject_id) === id)
    const inferred = subjectCodeFromItem(match)
    if (inferred) return inferred
  }
  return subjectCodeFromItem(task)
}

function subjectMasteryMap(subjectMastery) {
  const map = {}
  ;(Array.isArray(subjectMastery) ? subjectMastery : []).forEach(item => {
    const code = subjectCodeFromItem(item)
    if (code && !map[code]) map[code] = item
  })
  return map
}

function strategyScore(meta, strategy, mastery) {
  const weight = Number(strategy.weight || 0)
  const hasData = Boolean(mastery && (mastery.hasData || Number(mastery.attemptCount || mastery.attempt_count) > 0))
  const scoreValue = Number(mastery && (mastery.score != null ? mastery.score : mastery.mastery_score))
  const masteryScore = hasData && Number.isFinite(scoreValue) ? clamp(scoreValue, 0, 100) : null
  const stageBonus = { not_started: 30, strengthening: 26, second_round: 21, exam: 17, maintenance: 6 }[strategy.stage] || 0
  const noDataBonus = !hasData && strategy.stage !== 'maintenance' ? 10 : 0
  const weaknessBonus = masteryScore == null ? 0 : Math.max(0, (85 - masteryScore) * 0.3)
  const score = weight + stageBonus + noDataBonus + weaknessBonus
  const subjectId = Number(mastery && (mastery.subjectId || mastery.subject_id)) || 0
  const baseParams = subjectId ? { subject_id: subjectId } : { subject_code: meta.code }
  return { score, masteryScore, baseParams, weight }
}

function strategyProgressCandidate(meta, strategy, weight, score, baseParams) {
  const verb = strategy.stage === 'not_started' ? '启动' : '推进'
  return {
    key: `nba:${meta.code}:${strategy.stage}`,
    task_type: 'strategy_progress',
    title: `${verb}${meta.shortName}强化`,
    reason: `手动权重 ${weight}% · 当前${stageLabel(strategy.stage)}，先推进主线再用选择题验证。`,
    action_label: '开始专注',
    route: 'pomodoro',
    route_params: { ...baseParams, task_type: 'lecture' },
    estimated_minutes: 50,
    estimated_question_count: 0,
    _nbaScore: score,
    _subjectCode: meta.code,
  }
}

function strategyPracticeCandidate(meta, strategy, weight, score, masteryScore, baseParams) {
  const count = strategy.stage === 'maintenance' ? 10 : 20
  // `exam_list` is only wired on the study-plan allocation route today.  The Home
  // primary-task handler would silently ignore it, so keep exam detection on the
  // stable smart-practice route until that navigation path is unified.
  const mode = 'smart'
  const title = strategy.stage === 'maintenance'
    ? `${meta.shortName}保温 ${count} 题`
    : (strategy.stage === 'exam' ? `${meta.shortName}选择题检测` : `${meta.shortName}二轮专项 ${count} 题`)
  const reason = `手动权重 ${weight}% · 当前${stageLabel(strategy.stage)}${masteryScore == null ? ' · 尚缺稳定检测数据' : ` · 掌握度约 ${Math.round(masteryScore)}%`}。`
  return {
    key: `nba:${meta.code}:${strategy.stage}`,
    task_type: strategy.stage === 'maintenance' ? 'maintenance' : 'smart_practice',
    title,
    reason,
    action_label: '开始练习',
    route: 'practice',
    route_params: { ...baseParams, mode, count, source: 'nba' },
    estimated_minutes: Math.max(12, Math.round(count * 1.2)),
    estimated_question_count: count,
    _nbaScore: score,
    _subjectCode: meta.code,
  }
}

function strategyCandidate(meta, strategy, mastery) {
  const scored = strategyScore(meta, strategy, mastery)
  if (strategy.stage === 'not_started' || strategy.stage === 'strengthening') {
    return strategyProgressCandidate(meta, strategy, scored.weight, scored.score, scored.baseParams)
  }
  return strategyPracticeCandidate(meta, strategy, scored.weight, scored.score, scored.masteryScore,
    scored.baseParams)
}

function dueReviewCandidate(due) {
  return {
    key: 'nba:review:due',
    task_type: 'review',
    title: `先复习 ${due} 道到期错题`,
    reason: '到期错题已经进入记忆复习窗口；数量较多时优先处理，避免遗忘继续累积。',
    action_label: '开始今日复习',
    route: 'review_today',
    route_params: {},
    estimated_minutes: Math.max(8, Math.min(40, due * 2)),
    estimated_question_count: due,
    _nbaScore: 43 + Math.min(34, due * 1.7),
    _subjectCode: '',
  }
}

function hubTaskCandidate(task, backendTasks, profile, opts) {
  if (!task || !task.route) return null
  const code = taskSubjectCode(task, opts.subjectMastery)
  const strategy = profile.subjects.find(item => item.code === code)
  const weightBonus = strategy ? strategy.weight * 0.35 : 0
  return {
    ...task,
    key: task.key || `nba:backend:${backendTasks.indexOf(task)}`,
    _nbaScore: 42 + weightBonus + (task.completed_today ? -18 : 0),
    _subjectCode: code,
  }
}

function hubTaskCandidates(hub, profile, opts) {
  const backendTasks = []
  if (hub && hub.primary_task) backendTasks.push(hub.primary_task)
  if (hub && Array.isArray(hub.tasks)) Array.prototype.push.apply(backendTasks, hub.tasks)
  return backendTasks
    .map(task => hubTaskCandidate(task, backendTasks, profile, opts))
    .filter(candidate => candidate !== null)
}

function strategyCandidates(profile, opts) {
  const masteryMap = subjectMasteryMap(opts.subjectMastery)
  const candidates = []
  SUBJECTS.forEach(meta => {
    const strategy = profile.subjects.find(item => item.code === meta.code) || normalizeSubjectEntry(null, meta)
    // A manual weight of 0 explicitly pauses this subject in strategy-driven NBA.
    if (Number(strategy.weight || 0) <= 0) return
    candidates.push(strategyCandidate(meta, strategy, masteryMap[meta.code]))
  })
  const due = Math.max(0, Number(opts.dueReviewCount) || 0)
  if (due > 0) candidates.push(dueReviewCandidate(due))
  hubTaskCandidates(opts.hub || null, profile, opts)
    .forEach(candidate => candidates.push(candidate))
  return candidates
}

function pickBestCandidate(candidates) {
  candidates.sort((a, b) => Number(b._nbaScore || 0) - Number(a._nbaScore || 0))
  const winner = candidates[0] || null
  if (!winner) return null
  const clean = { ...winner }
  delete clean._nbaScore
  delete clean._subjectCode
  return clean
}

function buildNextBestAction(options) {
  const opts = options || {}
  const profile = normalizeProfile(opts.profile || getProfile())
  return pickBestCandidate(strategyCandidates(profile, opts))
}

module.exports = {
  normalizeAccuracy,
  buildChoiceLossBudget,
  taskSubjectCode,
  subjectMasteryMap,
  strategyCandidate,
  buildNextBestAction,
}
