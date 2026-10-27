const { get, setStrict, ownerFingerprint } = require('./storage-core')

const {
  STUDY_STRATEGY_STORAGE_KEY,
  SCHEMA_VERSION,
  SUBJECTS,
  SUBJECT_MAP,
  STAGE_MAP,
  clamp,
} = require('./study-strategy-meta')

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

module.exports = {
  createDefaultProfile,
  normalizeSubjectEntry,
  normalizeProfile,
  getProfile,
  validateProfile,
  saveProfile,
  getSubjectStrategy,
}
