const HOME_MASTERY_SUBJECTS = [
  { key: 'data', code: 'data_structure', name: '数据结构' },
  { key: 'chip', code: 'computer_organization', name: '计算机组成原理' },
  { key: 'code', code: 'operating_system', name: '操作系统' },
  { key: 'network', code: 'computer_network', name: '计算机网络' },
]

function getMasteryMark(name, code) {
  const text = `${String(name || '')} ${String(code || '')}`.toLowerCase()
  if (text.includes('数据结构') || text.includes('data_structure')) return '数'
  if (text.includes('组成') || text.includes('organization')) return '组'
  if (text.includes('操作系统') || text.includes('operating')) return '系'
  if (text.includes('网络') || text.includes('network')) return '网'
  if (text.includes('高等数学') || text.includes('calculus')) return '高'
  if (text.includes('线性代数') || text.includes('linear')) return '线'
  if (text.includes('英语') || text.includes('english')) return '英'
  if (text.includes('政治') || text.includes('politic')) return '政'
  const clean = String(name || '').trim()
  return clean ? clean.slice(0, 1) : '科'
}

function getMasteryIconClass(name, code) {
  const text = `${String(name || '')} ${String(code || '')}`.toLowerCase()
  if (text.includes('数据结构') || text.includes('data_structure')) return 'data'
  if (text.includes('组成') || text.includes('organization')) return 'chip'
  if (text.includes('操作系统') || text.includes('operating')) return 'code'
  if (text.includes('网络') || text.includes('network')) return 'network'
  if (text.includes('高等数学') || text.includes('calculus')) return 'math'
  if (text.includes('线性代数') || text.includes('linear')) return 'matrix'
  if (text.includes('英语') || text.includes('english')) return 'language'
  if (text.includes('政治') || text.includes('politic')) return 'civic'
  return 'generic'
}

function getMasteryIconSrc(iconClass) {
  const icons = {
    data: '/assets/icons/home-mastery/data-structure.png',
    chip: '/assets/icons/home-mastery/computer-organization.png',
    code: '/assets/icons/home-mastery/operating-system.png',
    network: '/assets/icons/home-mastery/computer-network.png',
  }
  return icons[String(iconClass || '')] || ''
}

function getMasterySubjectKey(name, code) {
  const rawCode = String(code || '').trim().toLowerCase()
  const rawName = String(name || '').trim().toLowerCase()
  const text = `${rawName} ${rawCode}`
  if (rawCode === 'data_structure' || text.includes('数据结构')) return 'data'
  if (rawCode === 'computer_organization' || text.includes('组成原理') || text.includes('计组')) return 'chip'
  if (rawCode === 'operating_system' || text.includes('操作系统')) return 'code'
  if (rawCode === 'computer_network' || text.includes('计算机网络') || text.includes('计网')) return 'network'
  return getMasteryIconClass(name, code)
}

function toNonNegativeInt(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return 0
  return Math.round(n)
}

function indexSubjectMastery(list) {
  const byKey = {}
  ;(Array.isArray(list) ? list : []).forEach((item) => {
    if (!item) return
    const key = getMasterySubjectKey(item.subject_name, item.subject_code)
    const supported = HOME_MASTERY_SUBJECTS.some(meta => meta.key === key)
    if (supported && !byKey[key]) byKey[key] = item
  })
  return byKey
}

function resolveSubjectMastery(values) {
  const {
    hubItem,
    statsItem,
    hubHasData,
    statsHasData,
    hubAttempts,
    statsAttempts,
    hubScoreNumber,
    statsAccuracy,
  } = values
  let score = 0
  let attemptCount = 0
  let correctCount = 0
  let hasData = false
  if (hubHasData) {
    hasData = true
    score = Math.max(0, Math.min(100, Math.round(hubScoreNumber)))
    attemptCount = hubAttempts || statsAttempts
    const hubAccuracy = Number(hubItem && hubItem.accuracy)
    if (attemptCount > 0 && Number.isFinite(hubAccuracy)) {
      correctCount = Math.max(0, Math.min(attemptCount, Math.round(attemptCount * hubAccuracy)))
    } else if (statsItem && statsAttempts === attemptCount) {
      correctCount = Math.max(0, Math.min(attemptCount, toNonNegativeInt(statsItem.correct_count)))
    }
  } else if (statsHasData) {
    // Study Hub has no score yet; preserve the real dashboard practice fallback.
    hasData = true
    score = Math.max(0, Math.min(100, Math.round(statsAccuracy * 100)))
    attemptCount = statsAttempts
    correctCount = Math.max(0, Math.min(attemptCount, toNonNegativeInt(statsItem.correct_count)))
  }
  return { score, attemptCount, correctCount, hasData }
}

function buildSubjectMasteryItem(meta, index, hubByKey, statsByKey) {
  const hubItem = hubByKey[meta.key] || null
  const statsItem = statsByKey[meta.key] || null
  const hubAttempts = toNonNegativeInt(hubItem && hubItem.attempt_count)
  const statsAttempts = toNonNegativeInt(statsItem && statsItem.total_questions)
  const rawHubScore = hubItem && hubItem.mastery_score
  const hubScoreNumber = rawHubScore == null ? NaN : Number(rawHubScore)
  const hubHasData = !!(
    hubItem &&
    Number.isFinite(hubScoreNumber) &&
    (hubItem.data_available !== false || hubAttempts > 0)
  )
  const statsAccuracy = Number(statsItem && statsItem.accuracy)
  const statsHasData = !!(statsItem && statsAttempts > 0 && Number.isFinite(statsAccuracy))
  const mastery = resolveSubjectMastery({
    hubItem,
    statsItem,
    hubHasData,
    statsHasData,
    hubAttempts,
    statsAttempts,
    hubScoreNumber,
    statsAccuracy,
  })
  const sourceItem = hubItem || statsItem || {}
  const subjectName = String(sourceItem.subject_name || meta.name)
  const subjectCode = String(sourceItem.subject_code || meta.code)
  const subjectId = Number(sourceItem.subject_id) || 0
  const iconClass = meta.key
  const { score, attemptCount, correctCount, hasData } = mastery
  return {
    subjectId,
    subjectCode,
    subjectName,
    orderText: String(index + 1).padStart(2, '0'),
    mark: getMasteryMark(subjectName, subjectCode),
    iconClass,
    iconSrc: getMasteryIconSrc(iconClass),
    hasData,
    score,
    scoreText: hasData ? `${score}%` : '--',
    barWidth: hasData ? score : 0,
    attemptCount,
    correctCount,
    questionStatText: hasData ? `${correctCount}/${attemptCount} 题` : '0/0 题',
    statusText: hasData ? (score >= 85 ? '已掌握' : '掌握不足') : '数据不足',
  }
}

function buildSubjectMastery(options = {}) {
  const hubByKey = indexSubjectMastery(options.hubSubjectMastery)
  const statsByKey = indexSubjectMastery(options.dashboardSubjectStats)
  return HOME_MASTERY_SUBJECTS.map((meta, index) => (
    buildSubjectMasteryItem(meta, index, hubByKey, statsByKey)
  ))
}

module.exports = {
  HOME_MASTERY_SUBJECTS,
  buildSubjectMastery,
  toNonNegativeInt,
}
