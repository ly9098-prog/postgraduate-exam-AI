function buildSubjectMeta(tree) {
  const roots = Array.isArray(tree) ? tree : []
  const byId = {}
  const leafIds = []
  const normalizeId = value => {
    const n = Number(value)
    return Number.isFinite(n) && n > 0 ? n : null
  }
  const visit = (node, parentId) => {
    if (!node || node.is_active === false) return []
    const id = normalizeId(node.subject_id || node.id)
    const children = Array.isArray(node.children) ? node.children : []
    const childLeafIds = []
    children.forEach(child => {
      const descendants = visit(child, id)
      descendants.forEach(leafId => childLeafIds.push(leafId))
    })
    const label = String(node.subject_name || node.display_name || node.name || '').trim() || '未分类'
    const code = String(node.subject_code || node.product_code || node.code || '').trim()
    const isLeaf = childLeafIds.length === 0
    const descendantLeafIds = isLeaf && id != null ? [id] : childLeafIds.slice()
    if (id != null) {
      byId[id] = {
        id,
        parentId: normalizeId(parentId),
        name: label,
        code,
        isLeaf,
        descendantLeafIds,
      }
      if (isLeaf) leafIds.push(id)
    }
    return descendantLeafIds
  }
  roots.forEach(node => visit(node, null))
  return { byId, leafIds }
}

function distributeAggregateValue(total, leafIds, currentTotals) {
  const count = Array.isArray(leafIds) ? leafIds.length : 0
  const safeTotal = Math.max(0, Math.round(Number(total) || 0))
  if (!count || !safeTotal) return []
  const weights = leafIds.map(id => Math.max(0, Number(currentTotals[id]) || 0))
  const weightSum = weights.reduce((sum, value) => sum + value, 0)
  const base = []
  const remainders = []
  let assigned = 0
  leafIds.forEach((id, index) => {
    const share = weightSum > 0
      ? (safeTotal * weights[index]) / weightSum
      : safeTotal / count
    const value = Math.floor(share)
    base[index] = value
    remainders[index] = share - value
    assigned += value
  })
  let rest = safeTotal - assigned
  const order = leafIds.map((id, index) => ({ index, remainder: remainders[index], weight: weights[index] }))
    .sort((a, b) => {
      if (b.remainder !== a.remainder) return b.remainder - a.remainder
      if (b.weight !== a.weight) return b.weight - a.weight
      return a.index - b.index
    })
  let cursor = 0
  while (rest > 0 && order.length) {
    const target = order[cursor % order.length]
    base[target.index] += 1
    rest -= 1
    cursor += 1
  }
  return leafIds.map((id, index) => ({ id, value: base[index] }))
}

function normalizeDistributionSubjects(subjects, meta) {
  const subjArr = Array.isArray(subjects) ? subjects : []
  if (!meta || !meta.byId) return subjArr.slice()

  const bucketById = {}
  const passthrough = []
  const parentBuckets = []
  const upsertLeaf = (subjectId, fallbackItem) => {
    const metaNode = meta.byId[subjectId] || {}
    if (!bucketById[subjectId]) {
      bucketById[subjectId] = {
        subject_id: subjectId,
        subject_code: metaNode.code || String((fallbackItem && fallbackItem.subject_code) || ''),
        subject_name: metaNode.name || String((fallbackItem && fallbackItem.subject_name) || '未分类'),
        sessions: 0,
        participation_sessions: 0,
        duration_sec: 0,
      }
    }
    return bucketById[subjectId]
  }

  subjArr.forEach(item => {
    const subjectId = item && item.subject_id != null ? Number(item.subject_id) : null
    const durationSec = Math.max(0, Number(item && item.duration_sec) || 0)
    const sessions = Math.max(0, Number(item && item.sessions) || 0)
    const participationSessions = Math.max(
      0,
      Number(item && item.participation_sessions != null
        ? item.participation_sessions
        : sessions) || 0
    )
    if (subjectId == null || !meta.byId[subjectId]) {
      passthrough.push({
        subject_id: item && item.subject_id != null ? item.subject_id : null,
        subject_code: String((item && item.subject_code) || ''),
        subject_name: String((item && item.subject_name) || '未分类'),
        sessions,
        participation_sessions: participationSessions,
        duration_sec: durationSec,
      })
      return
    }
    const node = meta.byId[subjectId]
    if (node.isLeaf) {
      const bucket = upsertLeaf(subjectId, item)
      bucket.sessions += sessions
      bucket.participation_sessions += participationSessions
      bucket.duration_sec += durationSec
      return
    }
    const leafIds = Array.isArray(node.descendantLeafIds) ? node.descendantLeafIds.filter(id => meta.byId[id] && meta.byId[id].isLeaf) : []
    if (!leafIds.length) {
      passthrough.push({
        subject_id: subjectId,
        subject_code: node.code || String((item && item.subject_code) || ''),
        subject_name: node.name || String((item && item.subject_name) || '未分类'),
        sessions,
        participation_sessions: participationSessions,
        duration_sec: durationSec,
      })
      return
    }
    parentBuckets.push({ item, leafIds, durationSec, sessions, participationSessions })
  })

  parentBuckets.forEach(entry => {
    const currentDurations = {}
    const currentSessions = {}
    entry.leafIds.forEach(id => {
      currentDurations[id] = bucketById[id] ? bucketById[id].duration_sec : 0
      currentSessions[id] = bucketById[id] ? bucketById[id].sessions : 0
    })
    const durationShares = distributeAggregateValue(entry.durationSec, entry.leafIds, currentDurations)
    const sessionShares = distributeAggregateValue(entry.sessions, entry.leafIds, currentSessions)
    const participationShares = distributeAggregateValue(
      entry.participationSessions, entry.leafIds, currentSessions
    )
    durationShares.forEach(share => {
      const bucket = upsertLeaf(share.id, entry.item)
      bucket.duration_sec += share.value
    })
    sessionShares.forEach(share => {
      const bucket = upsertLeaf(share.id, entry.item)
      bucket.sessions += share.value
    })
    participationShares.forEach(share => {
      const bucket = upsertLeaf(share.id, entry.item)
      bucket.participation_sessions += share.value
    })
  })

  return Object.values(bucketById)
    .concat(passthrough)
    .filter(item => Number(item.duration_sec) > 0 || Number(item.sessions) > 0)
    .sort((a, b) => {
      const diff = Number(b.duration_sec || 0) - Number(a.duration_sec || 0)
      if (diff !== 0) return diff
      return String(a.subject_name || '').localeCompare(String(b.subject_name || ''), 'zh-Hans-CN')
    })
}

module.exports = {
  buildSubjectMeta,
  distributeAggregateValue,
  normalizeDistributionSubjects,
}
