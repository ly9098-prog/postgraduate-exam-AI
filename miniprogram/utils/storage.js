const KEYS = {
  TOKEN: 'token',
  USER: 'user',
  TOKEN_EXPIRES_AT: 'token_expires_at',
  REFRESH_TOKEN: 'refresh_token',
}

/** 业务缓存键列表 — 会话切换或注销时需清除 */
const BUSINESS_CACHE_KEYS = [
  'lastPracticeResult',
  'practice_recent_subjects_v1',
  'wrong_detail_nav',
  'pomodoro_running_state',
  'pomodoro_pause',
  'pomodoro_free_pause',
  'pomodoro_completion',
  'pomodoro_break',
  'pomodoro_confirm_pause',
  'pomodoro_pause_adjustment',
  'pomodoro_pending_sync',
  'pomodoro_unknown_start',
  'pomodoro_terminal_conflict',
  'pomodoro_font_size',
  'pomodoro_anim_idx',
  'home_today_goal_total',
]

/** 始终保留的键（会话清理时不受影响） */
const PROTECTED_KEYS = [
  'privacy_acceptance',
]

function get(key) {
  try {
    return wx.getStorageSync(key)
  } catch {
    return null
  }
}

function set(key, value) {
  try {
    wx.setStorageSync(key, value)
  } catch (e) {
    console.error('Storage set error:', e)
  }
}

/** 严格写入：失败时抛出错误，用于认证信息和协议记录等关键数据 */
function setStrict(key, value) {
  wx.setStorageSync(key, value)
}

function remove(key) {
  try {
    wx.removeStorageSync(key)
  } catch {
    // ignore
  }
}

/**
 * 统一会话清理：清除认证信息 + 业务缓存，可选保留协议同意记录。
 *
 * @param {object} [options]
 * @param {boolean} [options.preservePrivacyAcceptance=false] 为 true 时不清除协议同意记录
 * @param {boolean} [options.includeDebugSnapshots=true] 是否清除调试快照
 *
 * 调用场景：
 * - 手动退出（preservePrivacyAcceptance=false）
 * - Token 失效/401 自动清理（preservePrivacyAcceptance=true）
 * - 切换账号（preservePrivacyAcceptance=true）
 * - 账号注销（preservePrivacyAcceptance=false）
 */
function clearSession(options) {
  var opts = options || {}
  var preservePrivacy = opts.preservePrivacyAcceptance === true

  // 1. 清除认证信息
  remove(KEYS.TOKEN)
  remove(KEYS.TOKEN_EXPIRES_AT)
  remove(KEYS.REFRESH_TOKEN)
  remove(KEYS.USER)

  // 2. 清除业务缓存
  for (var bi = 0; bi < BUSINESS_CACHE_KEYS.length; bi++) {
    remove(BUSINESS_CACHE_KEYS[bi])
  }

  // 3. 清除动态会话缓存（AI 诊断 + 待确认刷题提交）
  try {
    var allKeys = wx.getStorageInfoSync().keys || []
    for (var ki = 0; ki < allKeys.length; ki++) {
      var key = allKeys[ki]
      // 跳过受保护的键
      if (preservePrivacy && PROTECTED_KEYS.indexOf(key) >= 0) continue
      if (
        key.indexOf('ai_') === 0 ||
        key.indexOf('aiCache') === 0 ||
        key.indexOf('ai_diagnosis') === 0 ||
        key.indexOf('practice_pending_submission_v1:') === 0
      ) {
        remove(key)
      }
    }
  } catch (_) {}

  // 4. 清除调试快照
  if (opts.includeDebugSnapshots !== false) {
    try {
      var keys2 = wx.getStorageInfoSync().keys || []
      for (var ki2 = 0; ki2 < keys2.length; ki2++) {
        if (keys2[ki2].indexOf('debug_snapshot:') === 0) {
          remove(keys2[ki2])
        }
      }
    } catch (_) {}
  }
}

// ---------------------------------------------------------------------------
// 408 strategy + pomodoro task typing live next to the storage primitives so
// pages can consume one aggregated namespace without circular imports.
// ---------------------------------------------------------------------------

const STUDY_STRATEGY_STORAGE_KEY = 'study_strategy_v1'
const SCHEMA_VERSION = 1
const CHOICE_TOTAL_POINTS = 80
const CHOICE_LOSS_BUDGET_POINTS = 8
const CHOICE_TARGET_POINTS = CHOICE_TOTAL_POINTS - CHOICE_LOSS_BUDGET_POINTS

const SUBJECTS = [
  { code: 'data_structure', name: '数据结构', shortName: '数据结构', choiceQuestions: 11, defaultStage: 'maintenance', defaultWeight: 15 },
  { code: 'computer_organization', name: '计算机组成原理', shortName: '计组', choiceQuestions: 12, defaultStage: 'second_round', defaultWeight: 35 },
  { code: 'operating_system', name: '操作系统', shortName: '操作系统', choiceQuestions: 10, defaultStage: 'not_started', defaultWeight: 35 },
  { code: 'computer_network', name: '计算机网络', shortName: '计网', choiceQuestions: 7, defaultStage: 'not_started', defaultWeight: 15 },
]

const STAGES = [
  { value: 'not_started', label: '未开始', hint: '优先建立课程/教材进度' },
  { value: 'strengthening', label: '强化中', hint: '输入与章节检测并行' },
  { value: 'second_round', label: '二轮刷题', hint: '以选择题专项和错题为主' },
  { value: 'exam', label: '真题检测', hint: '以选择题套卷暴露漏洞' },
  { value: 'maintenance', label: '保温', hint: '低频复习，避免挤占短板时间' },
]

const STAGE_MAP = STAGES.reduce((map, item, index) => {
  map[item.value] = { ...item, index }
  return map
}, {})
const SUBJECT_MAP = SUBJECTS.reduce((map, item) => {
  map[item.code] = item
  return map
}, {})

function clamp(value, min, max) {
  const n = Number(value)
  if (!Number.isFinite(n)) return min
  return Math.max(min, Math.min(max, n))
}

function ownerFingerprint() {
  const user = get(KEYS.USER) || {}
  const raw = user.id || user.user_id || user.uid || user.openid || user.username || user.nickname || user.nickName || ''
  return raw ? String(raw) : 'anonymous'
}

function createDefaultProfile() {
  return {
    version: SCHEMA_VERSION,
    owner: ownerFingerprint(),
    updatedAt: Date.now(),
    subjects: SUBJECTS.map(item => ({
      code: item.code,
      stage: item.defaultStage,
      weight: item.defaultWeight,
    })),
  }
}

function normalizeSubjectEntry(raw, meta) {
  const source = raw && typeof raw === 'object' ? raw : {}
  const stage = STAGE_MAP[source.stage] ? source.stage : meta.defaultStage
  let weight = Math.round(clamp(source.weight == null ? meta.defaultWeight : source.weight, 0, 100) / 5) * 5
  weight = clamp(weight, 0, 100)
  return { code: meta.code, stage, weight }
}

function normalizeProfile(raw) {
  const defaults = createDefaultProfile()
  if (!raw || typeof raw !== 'object') return defaults
  const currentOwner = ownerFingerprint()
  if (raw.owner && String(raw.owner) !== currentOwner) return defaults
  const rawSubjects = Array.isArray(raw.subjects) ? raw.subjects : []
  const byCode = {}
  rawSubjects.forEach(item => {
    if (item && SUBJECT_MAP[item.code]) byCode[item.code] = item
  })
  return {
    version: SCHEMA_VERSION,
    owner: currentOwner,
    updatedAt: Number(raw.updatedAt) || Date.now(),
    subjects: SUBJECTS.map(meta => normalizeSubjectEntry(byCode[meta.code], meta)),
  }
}

function getProfile() {
  return normalizeProfile(get(STUDY_STRATEGY_STORAGE_KEY))
}

function validateProfile(profile) {
  const normalized = normalizeProfile(profile)
  const totalWeight = normalized.subjects.reduce((sum, item) => sum + Number(item.weight || 0), 0)
  const invalidStage = normalized.subjects.some(item => !STAGE_MAP[item.stage])
  return {
    valid: !invalidStage && totalWeight === 100,
    totalWeight,
    message: invalidStage ? '存在无效学习阶段' : (totalWeight === 100 ? '' : `四科权重合计需为 100%，当前为 ${totalWeight}%`),
    profile: normalized,
  }
}

function saveProfile(profile) {
  const validation = validateProfile(profile)
  if (!validation.valid) {
    const error = new Error(validation.message || '学习策略无效')
    error.code = 'invalid_study_strategy'
    throw error
  }
  const next = { ...validation.profile, updatedAt: Date.now() }
  setStrict(STUDY_STRATEGY_STORAGE_KEY, next)
  return next
}

function getSubjectStrategy(profile, code) {
  const normalized = normalizeProfile(profile || getProfile())
  return normalized.subjects.find(item => item.code === code) || null
}

function stageLabel(stage) {
  return STAGE_MAP[stage] ? STAGE_MAP[stage].label : '未开始'
}

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

function subjectCodeFromItem(item) {
  const code = String(item && (item.subjectCode || item.subject_code || item.code || item.subject) || '').toLowerCase()
  if (SUBJECT_MAP[code]) return code
  const name = String(item && (item.subjectName || item.subject_name || item.name || item.label) || '')
  if (name.includes('数据结构')) return 'data_structure'
  if (name.includes('组成') || name.includes('计组')) return 'computer_organization'
  if (name.includes('操作系统')) return 'operating_system'
  if (name.includes('网络') || name.includes('计网')) return 'computer_network'
  return ''
}

function buildChoiceLossBudget(subjectItems) {
  const items = Array.isArray(subjectItems) ? subjectItems : []
  const byCode = {}
  items.forEach(item => {
    const code = subjectCodeFromItem(item)
    if (code && !byCode[code]) byCode[code] = item
  })
  let coveredQuestions = 0
  let projectedLoss = 0
  const subjects = SUBJECTS.map(meta => {
    const source = byCode[meta.code] || null
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
    if (hasData) {
      coveredQuestions += meta.choiceQuestions
      projectedLoss += expectedLoss
    }
    return {
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
    }
  })
  projectedLoss = Math.round(projectedLoss * 10) / 10
  const fullCoverage = coveredQuestions === 40
  const remainingBudget = Math.round((CHOICE_LOSS_BUDGET_POINTS - projectedLoss) * 10) / 10
  let status = 'building'
  let statusText = `已覆盖 ${coveredQuestions}/40 道选择题配额`
  if (fullCoverage) {
    if (projectedLoss <= CHOICE_LOSS_BUDGET_POINTS) {
      status = 'on_track'
      statusText = `预计失分 ${projectedLoss}，在预算内`
    } else {
      status = 'over_budget'
      statusText = `预计超预算 ${Math.abs(remainingBudget)} 分`
    }
  }
  return {
    totalPoints: CHOICE_TOTAL_POINTS,
    targetPoints: CHOICE_TARGET_POINTS,
    lossBudgetPoints: CHOICE_LOSS_BUDGET_POINTS,
    maxWrongQuestions: CHOICE_LOSS_BUDGET_POINTS / 2,
    coveredQuestions,
    coveredSubjects: subjects.filter(item => item.hasData).length,
    coveragePct: Math.round(coveredQuestions / 40 * 100),
    fullCoverage,
    projectedLoss,
    projectedScore: Math.round((coveredQuestions * 2 - projectedLoss) * 10) / 10,
    remainingBudget,
    status,
    statusText,
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

function strategyCandidate(meta, strategy, mastery) {
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

  if (strategy.stage === 'not_started' || strategy.stage === 'strengthening') {
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

  const count = strategy.stage === 'maintenance' ? 10 : 20
  const mode = strategy.stage === 'exam' ? 'smart' : 'smart'
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

function buildNextBestAction(options) {
  const opts = options || {}
  const profile = normalizeProfile(opts.profile || getProfile())
  const masteryMap = subjectMasteryMap(opts.subjectMastery)
  const candidates = []
  SUBJECTS.forEach(meta => {
    const strategy = profile.subjects.find(item => item.code === meta.code) || normalizeSubjectEntry(null, meta)
    // A manual weight of 0 explicitly pauses this subject in strategy-driven NBA.
    if (Number(strategy.weight || 0) <= 0) return
    candidates.push(strategyCandidate(meta, strategy, masteryMap[meta.code]))
  })

  const due = Math.max(0, Number(opts.dueReviewCount) || 0)
  if (due > 0) {
    candidates.push({
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
    })
  }

  const backendTasks = []
  const hub = opts.hub || null
  if (hub && hub.primary_task) backendTasks.push(hub.primary_task)
  if (hub && Array.isArray(hub.tasks)) Array.prototype.push.apply(backendTasks, hub.tasks)
  backendTasks.forEach(task => {
    if (!task || !task.route) return
    const code = taskSubjectCode(task, opts.subjectMastery)
    const strategy = profile.subjects.find(item => item.code === code)
    const weightBonus = strategy ? strategy.weight * 0.35 : 0
    candidates.push({
      ...task,
      key: task.key || `nba:backend:${backendTasks.indexOf(task)}`,
      _nbaScore: 42 + weightBonus + (task.completed_today ? -18 : 0),
      _subjectCode: code,
    })
  })

  candidates.sort((a, b) => Number(b._nbaScore || 0) - Number(a._nbaScore || 0))
  const winner = candidates[0] || null
  if (!winner) return null
  const clean = { ...winner }
  delete clean._nbaScore
  delete clean._subjectCode
  return clean
}

// eslint-disable-next-line no-use-before-define
const studyStrategy = {
  STORAGE_KEY: STUDY_STRATEGY_STORAGE_KEY,
  SCHEMA_VERSION,
  SUBJECTS,
  STAGES,
  STAGE_MAP,
  CHOICE_TOTAL_POINTS,
  CHOICE_LOSS_BUDGET_POINTS,
  CHOICE_TARGET_POINTS,
  createDefaultProfile,
  normalizeProfile,
  getProfile,
  saveProfile,
  validateProfile,
  getSubjectStrategy,
  stageLabel,
  subjectCodeFromItem,
  buildChoiceLossBudget,
  buildNextBestAction,
}

const POMODORO_TASK_RECORDS_STORAGE_KEY = 'pomodoro_task_type_records_v1'
const SELECTION_KEY = 'pomodoro_task_type_selection_v1'
const MAX_RECORDS = 600
const DEFAULT_TYPE = 'new_questions'
const TYPES = [
  { value: 'lecture', label: '听课', shortLabel: '听课' },
  { value: 'textbook', label: '教材', shortLabel: '教材' },
  { value: 'new_questions', label: '新题', shortLabel: '新题' },
  { value: 'wrong_questions', label: '错题', shortLabel: '错题' },
  { value: 'review', label: '复习', shortLabel: '复习' },
  { value: 'exam', label: '真题', shortLabel: '真题' },
]
const TYPE_MAP = TYPES.reduce((map, item) => { map[item.value] = item; return map }, {})

function normalize(type) {
  return TYPE_MAP[type] ? type : DEFAULT_TYPE
}
function label(type) {
  return TYPE_MAP[normalize(type)].label
}
function getSelected() {
  return normalize(get(SELECTION_KEY))
}
function setSelected(type) {
  const normalized = normalize(type)
  set(SELECTION_KEY, normalized)
  return normalized
}
function loadRecords() {
  const raw = get(POMODORO_TASK_RECORDS_STORAGE_KEY)
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { version: 1, records: {} }
  return { version: 1, records: raw.records && typeof raw.records === 'object' ? raw.records : {} }
}
function saveRecords(payload) {
  set(POMODORO_TASK_RECORDS_STORAGE_KEY, payload)
}
function recordSession(session, type) {
  if (!session) return
  // An invalid/empty type never overwrites an existing attribution and never
  // creates a new default-classified record.
  if (!TYPE_MAP[type]) return
  const id = session.id != null ? String(session.id) : ''
  const clientId = String(session.client_start_id || session.clientStartId || '')
  if (!id && !clientId) return
  const data = loadRecords()
  const key = id ? `id:${id}` : `client:${clientId}`
  data.records[key] = { type: normalize(type), savedAt: Date.now(), clientId }
  if (id && clientId) data.records[`client:${clientId}`] = { type: normalize(type), savedAt: Date.now(), sessionId: id }
  const entries = Object.keys(data.records).map(keyName => ({ key: keyName, ...data.records[keyName] }))
  entries.sort((a, b) => Number(b.savedAt || 0) - Number(a.savedAt || 0))
  if (entries.length > MAX_RECORDS) {
    const keep = new Set(entries.slice(0, MAX_RECORDS).map(item => item.key))
    Object.keys(data.records).forEach(keyName => { if (!keep.has(keyName)) delete data.records[keyName] })
  }
  saveRecords(data)
}
function typeForSession(session) {
  if (!session) return ''
  // Only a valid type is classified. Invalid/legacy sessions stay unclassified
  // instead of inheriting whatever the current default happens to be.
  if (TYPE_MAP[session.task_type]) return session.task_type
  const data = loadRecords()
  const id = session.id != null ? String(session.id) : ''
  const clientId = String(session.client_start_id || session.clientStartId || '')
  const byId = id && data.records[`id:${id}`]
  const byClient = clientId && data.records[`client:${clientId}`]
  const found = byId || byClient
  const foundType = found && found.type
  return TYPE_MAP[foundType] ? foundType : ''
}
function labelForSession(session) {
  const type = typeForSession(session)
  return type ? label(type) : ''
}

// eslint-disable-next-line no-use-before-define
const pomodoroTaskTypes = { STORAGE_KEY: POMODORO_TASK_RECORDS_STORAGE_KEY, SELECTION_KEY, TYPES, TYPE_MAP, DEFAULT_TYPE, normalize, label, getSelected, setSelected, recordSession, typeForSession, labelForSession }

module.exports = {
  KEYS,
  get,
  set,
  setStrict,
  remove,
  clearSession,
  BUSINESS_CACHE_KEYS,
  PROTECTED_KEYS,
  studyStrategy,
  pomodoroTaskTypes,
}