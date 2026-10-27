const { get, set, ownerFingerprint } = require('./storage-core')

const KNOWLEDGE_PRACTICE_SYNC_STORAGE_KEY = 'knowledge_practice_sync_receipts_v1'
const KNOWLEDGE_PRACTICE_SYNC_BASELINE_STORAGE_KEY = 'knowledge_practice_sync_baselines_v1'
const KNOWLEDGE_PRACTICE_SYNC_MAX_RECEIPTS = 120

function loadKnowledgePracticeSyncData() {
  const raw = get(KNOWLEDGE_PRACTICE_SYNC_STORAGE_KEY)
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { version: 1, owner: '', receipts: [] }
  const receipts = Array.isArray(raw.receipts) ? raw.receipts : []
  return {
    version: Number(raw.version) || 1,
    owner: String(raw.owner || ''),
    receipts,
  }
}

function knowledgeOwnerFingerprint() {
  return ownerFingerprint()
}

function saveKnowledgePracticeSyncData(data) {
  set(KNOWLEDGE_PRACTICE_SYNC_STORAGE_KEY, data)
}

function knowledgePracticeReceiptKey(subjectId, knowledgePointId) {
  return `${Math.max(0, Number(subjectId) || 0)}:${Math.max(0, Number(knowledgePointId) || 0)}`
}

function nonNegativeCount(value) {
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? Math.max(0, Math.floor(n)) : 0
}

function normalizeKnowledgePracticeReceipt(input) {
  const source = input && typeof input === 'object' ? input : {}
  const subjectId = Math.max(0, nonNegativeCount(source.subjectId))
  const knowledgePointId = Math.max(0, nonNegativeCount(source.knowledgePointId))
  const answeredCount = nonNegativeCount(source.answeredCount)
  const correctCount = Math.min(answeredCount, Math.max(0, nonNegativeCount(source.correctCount)))
  const wrongCount = Math.min(answeredCount - correctCount, Math.max(0, nonNegativeCount(source.wrongCount)))
  const baselineAttemptCount = Math.max(0, nonNegativeCount(source.baselineAttemptCount))
  return {
    subjectId,
    knowledgePointId,
    includeDescendants: source.includeDescendants === true,
    answeredCount,
    correctCount,
    wrongCount,
    baselineAttemptCount,
    expectedMinAttemptCount: baselineAttemptCount + answeredCount,
    requestId: String(source.requestId || '').slice(0, 128),
    rootName: String(source.rootName || '').slice(0, 80),
    createdAt: Number(source.createdAt) || Date.now(),
  }
}

function knowledgeReceiptMap(receipts) {
  const byKey = new Map()
  receipts.forEach((item) => {
    const normalized = normalizeKnowledgePracticeReceipt(item)
    const key = knowledgePracticeReceiptKey(normalized.subjectId, normalized.knowledgePointId)
    byKey.set(key, normalized)
  })
  return byKey
}

function mergeKnowledgeReceipt(current, existing) {
  // The latest launch wins, but a lower baseline is kept so a receipt can only
  // resolve after every absorbed expected session has reached the map endpoint.
  return {
    ...current,
    baselineAttemptCount: Math.min(
      current.baselineAttemptCount,
      existing.baselineAttemptCount
    ),
    expectedMinAttemptCount: Math.max(
      current.expectedMinAttemptCount,
      existing.expectedMinAttemptCount
    ),
    createdAt: Math.max(current.createdAt, existing.createdAt || 0),
    requestId: current.requestId || existing.requestId || '',
  }
}

function trimKnowledgeReceipts(data) {
  if (data.receipts.length > KNOWLEDGE_PRACTICE_SYNC_MAX_RECEIPTS) {
    data.receipts.sort((a, b) => Number(b.createdAt || 0) - Number(a.createdAt || 0))
    data.receipts = data.receipts.slice(0, KNOWLEDGE_PRACTICE_SYNC_MAX_RECEIPTS)
  }
}

function saveMergedKnowledgeReceipt(receipt) {
  const data = loadKnowledgePracticeSyncData()
  const owner = knowledgeOwnerFingerprint()
  const currentOwner = data.owner || owner
  if (currentOwner !== owner) {
    data.owner = owner
    data.receipts = []
  }
  data.version = 1
  data.owner = owner
  const byKey = knowledgeReceiptMap(data.receipts)
  const normalizedCurrent = normalizeKnowledgePracticeReceipt(receipt)
  const currentKey = knowledgePracticeReceiptKey(
    normalizedCurrent.subjectId,
    normalizedCurrent.knowledgePointId
  )
  const existingCurrent = byKey.get(currentKey)
  byKey.set(currentKey, existingCurrent
    ? mergeKnowledgeReceipt(normalizedCurrent, existingCurrent)
    : normalizedCurrent)
  data.receipts = Array.from(byKey.values())
  trimKnowledgeReceipts(data)
  saveKnowledgePracticeSyncData(data)
  return byKey.get(knowledgePracticeReceiptKey(receipt.subjectId, receipt.knowledgePointId))
}

const knowledgePracticeSync = {
  STORAGE_KEY: KNOWLEDGE_PRACTICE_SYNC_STORAGE_KEY,
  BASELINE_STORAGE_KEY: KNOWLEDGE_PRACTICE_SYNC_BASELINE_STORAGE_KEY,
  setBaseline(subjectId, knowledgePointId, attemptCount) {
    const key = knowledgePracticeReceiptKey(subjectId, knowledgePointId)
    if (key === '0:0') return
    const owner = knowledgeOwnerFingerprint()
    const raw = get(KNOWLEDGE_PRACTICE_SYNC_BASELINE_STORAGE_KEY)
    const data = raw && typeof raw === 'object' && !Array.isArray(raw) && String(raw.owner || '') === owner
      ? raw
      : { version: 1, owner, baselines: {} }
    data.version = 1
    data.owner = owner
    data.baselines = data.baselines && typeof data.baselines === 'object' && !Array.isArray(data.baselines)
      ? data.baselines
      : {}
    data.baselines[key] = Math.max(0, nonNegativeCount(attemptCount))
    set(KNOWLEDGE_PRACTICE_SYNC_BASELINE_STORAGE_KEY, data)
  },
  consumeBaseline(subjectId, knowledgePointId) {
    const key = knowledgePracticeReceiptKey(subjectId, knowledgePointId)
    if (key === '0:0') return 0
    const owner = knowledgeOwnerFingerprint()
    const raw = get(KNOWLEDGE_PRACTICE_SYNC_BASELINE_STORAGE_KEY)
    if (!raw || typeof raw !== 'object' || Array.isArray(raw) || String(raw.owner || '') !== owner) return 0
    const baselines = raw.baselines && typeof raw.baselines === 'object' && !Array.isArray(raw.baselines)
      ? raw.baselines
      : {}
    const baseline = nonNegativeCount(baselines[key])
    delete baselines[key]
    set(KNOWLEDGE_PRACTICE_SYNC_BASELINE_STORAGE_KEY, raw)
    return baseline
  },
  record(input) {
    const receipt = normalizeKnowledgePracticeReceipt(input)
    if (!receipt.subjectId || !receipt.knowledgePointId || !receipt.answeredCount) return null
    return saveMergedKnowledgeReceipt(receipt) || receipt
  },
  getForSubject(subjectId) {
    const wanted = Math.max(0, Number(subjectId) || 0)
    if (!wanted) return []
    const data = loadKnowledgePracticeSyncData()
    const owner = knowledgeOwnerFingerprint()
    if (!data.owner || data.owner !== owner) return []
    return data.receipts
      .map(normalizeKnowledgePracticeReceipt)
      .filter(item => item.subjectId === wanted && item.knowledgePointId > 0 && item.answeredCount > 0)
  },
  hasPending(subjectId) {
    return this.getForSubject(subjectId).length > 0
  },
  remove(receipts) {
    const list = Array.isArray(receipts) ? receipts : []
    if (!list.length) return
    const data = loadKnowledgePracticeSyncData()
    const owner = knowledgeOwnerFingerprint()
    if (!data.owner || data.owner !== owner) return
    const removed = new Set(list.map(item => {
      const receipt = item && typeof item === 'object' ? item : {}
      return knowledgePracticeReceiptKey(receipt.subjectId, receipt.knowledgePointId)
    }))
    data.receipts = data.receipts.filter((item) => {
      const normalized = normalizeKnowledgePracticeReceipt(item)
      return !removed.has(knowledgePracticeReceiptKey(normalized.subjectId, normalized.knowledgePointId))
    })
    saveKnowledgePracticeSyncData(data)
  },
  resolveReceipt(receipt, backendAttemptCount) {
    const normalized = normalizeKnowledgePracticeReceipt(receipt)
    if (!normalized.knowledgePointId || !normalized.answeredCount) return false
    return nonNegativeCount(backendAttemptCount) >= normalized.expectedMinAttemptCount
  },
}

module.exports = { knowledgePracticeSync }
