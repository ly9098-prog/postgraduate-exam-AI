const DEFAULT_GROUP_NAME = '其他知识点'
const toId = (value) => {
const id = Number(value)
return Number.isInteger(id) && id > 0 ? id : null
}
function groupTone(nodes) {
if (nodes.some(node => node.tone === 'weak')) return 'weak'
if (nodes.some(node => node.tone === 'stable')) return 'stable'
return 'unseen'
}
function buildParentMap(nodes, byId, orderById) {
const parentById = new Map()
nodes.forEach((node) => {
const id = node.knowledge_point_id
const parentId = toId(node.parent_id)
parentById.set(id, parentId && parentId !== id && byId.has(parentId) ? parentId : null)
})
const completed = new Set()
nodes.forEach((start) => {
const startId = start.knowledge_point_id
if (completed.has(startId)) return
const path = []
const pathIndex = new Map()
let cursorId = startId
while (cursorId && !completed.has(cursorId)) {
if (pathIndex.has(cursorId)) {
const cycle = path.slice(pathIndex.get(cursorId))
const breakId = cycle.reduce((best, id) => (
orderById.get(id) < orderById.get(best) ? id : best
), cycle[0])
parentById.set(breakId, null)
break
}
pathIndex.set(cursorId, path.length)
path.push(cursorId)
cursorId = parentById.get(cursorId)
}
path.forEach(id => completed.add(id))
})
return parentById
}
function buildKnowledgeGroups(input, subject) {
  var source = Array.isArray(input) ? input.filter(Boolean) : []
  if (!source.length) return []
  var ctx = buildGroupContext(source)
  if (!ctx.nodes.length) return []
  var groups = buildRootGroups(ctx)
  sortGroups(groups)
  return groups.map(function(group, index) { return Object.assign({}, group, { number: String(index + 1).padStart(2, "0") }) })
}

function buildGroupContext(source) {
  var nodes = [], byId = new Map(), orderById = new Map()
  source.forEach(function(item, index) {
    var id = toId(item.knowledge_point_id)
    if (!id || byId.has(id)) return
    var node = Object.assign({}, item, { knowledge_point_id: id })
    nodes.push(node); byId.set(id, node); orderById.set(id, index)
  })
  var parentById = buildParentMap(nodes, byId, orderById)
  var childrenById = new Map(nodes.map(function(node) { return [node.knowledge_point_id, []] }))
  nodes.forEach(function(node) {
    var parentId = parentById.get(node.knowledge_point_id)
    if (parentId && childrenById.has(parentId)) childrenById.get(parentId).push(node.knowledge_point_id)
  })
  childrenById.forEach(function(children) { children.sort(function(a, b) { return orderById.get(a) - orderById.get(b) }) })
  return { nodes: nodes, byId: byId, orderById: orderById, parentById: parentById, childrenById: childrenById }
}

function buildRootGroups(ctx) {
  var descendantCountCache = new Map()
  var descendantCount = function(id) {
    if (descendantCountCache.has(id)) return descendantCountCache.get(id)
    var count = (ctx.childrenById.get(id) || []).reduce(function(total, childId) { return total + 1 + descendantCount(childId) }, 0)
    descendantCountCache.set(id, count); return count
  }
  var roots = ctx.nodes.filter(function(node) { return !ctx.parentById.get(node.knowledge_point_id) }).sort(function(a, b) { return ctx.orderById.get(a.knowledge_point_id) - ctx.orderById.get(b.knowledge_point_id) })
  return roots.map(function(root, sourceIndex) { return buildRootGroup(ctx, root, sourceIndex, descendantCount) })
}

function buildRootGroup(ctx, root, sourceIndex, descendantCount) {
  var normalized = decorateSubtree(ctx, root)
  var rootNode = normalized[0]
  return {
    key: String(root.knowledge_point_id), rootId: root.knowledge_point_id, rootNode: rootNode,
    name: String(root.name || (DEFAULT_GROUP_NAME + (sourceIndex + 1))), tone: groupTone(normalized),
    nodeCount: normalized.length, descendantCount: Math.max(0, normalized.length - 1),
    directChildCount: rootNode ? rootNode.childCount : 0, sourceIndex: sourceIndex, nodes: normalized,
  }
}

function decorateSubtree(ctx, root) {
  var result = []
  var walk = function(id, depth, pathIds) {
    var raw = ctx.byId.get(id)
    if (!raw) return
    var children = ctx.childrenById.get(id) || []
    var parentId = ctx.parentById.get(id)
    var nextPath = pathIds.concat(id)
    result.push(Object.assign({}, raw, { parent_id: parentId, parentId: parentId, rootId: root.knowledge_point_id, depth: depth, indent: Math.min(depth, 5) * 20, childCount: children.length, descendantCount: descendantCountFor(ctx, id), hasChildren: children.length > 0, isLeaf: children.length === 0, pathIds: nextPath }))
    children.forEach(function(childId) { walk(childId, depth + 1, nextPath) })
  }
  walk(root.knowledge_point_id, 0, [])
  return result
}

function descendantCountFor(ctx, id) {
  var cache = ctx._descCache || (ctx._descCache = new Map())
  if (cache.has(id)) return cache.get(id)
  var count = (ctx.childrenById.get(id) || []).reduce(function(total, childId) { return total + 1 + descendantCountFor(ctx, childId) }, 0)
  cache.set(id, count); return count
}

function sortGroups(groups) {
  groups.sort(function(a, b) {
    var aStructured = a.descendantCount > 0 ? 1 : 0
    var bStructured = b.descendantCount > 0 ? 1 : 0
    if (aStructured !== bStructured) return bStructured - aStructured
    if (aStructured && a.nodeCount !== b.nodeCount) return b.nodeCount - a.nodeCount
    return a.sourceIndex - b.sourceIndex
  })
}
// Chapter graduation is evaluated next to tree grouping so the subject map can
// label whole chapters without importing page-level strategy modules.
const GRADUATION_CRITERIA = {
  evidenceCoveragePct: 80,
  accuracyPct: 85,
  stableCoveragePct: 80,
  weakCount: 0,
}

function safeGraduationPct(value) {
  if (value == null) return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return Math.max(0, Math.min(100, Math.abs(n) <= 1 ? n * 100 : n))
}

function collectChapterNodes(group) {
  const source = Array.isArray(group && group.nodes) ? group.nodes : []
  const nodes = source.filter(node => Number(node && node.trainable_question_count) > 0)
  return nodes
}

function computeChapterAccuracy(established) {
  let weightedCorrect = 0
  let weightedAttempts = 0
  let hasMissingAccuracy = false
  established.forEach(node => {
    const attempts = Math.max(0, Number(node.attempt_count) || 0)
    const acc = safeGraduationPct(node.accuracy)
    if (acc == null) {
      // A missing reading on any established node means the chapter accuracy is
      // still unknown; averaging over only the measured nodes would hide it.
      hasMissingAccuracy = true
      return
    }
    if (attempts > 0) {
      weightedAttempts += attempts
      weightedCorrect += attempts * acc / 100
    }
  })
  return !hasMissingAccuracy && weightedAttempts > 0
    ? Math.round(weightedCorrect / weightedAttempts * 100)
    : null
}

function buildGraduationChecks(evidenceCoveragePct, accuracyPct, stableCoveragePct, weakCount) {
  return {
    evidence: evidenceCoveragePct >= GRADUATION_CRITERIA.evidenceCoveragePct,
    accuracy: accuracyPct != null && accuracyPct >= GRADUATION_CRITERIA.accuracyPct,
    stable: stableCoveragePct >= GRADUATION_CRITERIA.stableCoveragePct,
    weak: weakCount <= GRADUATION_CRITERIA.weakCount,
  }
}

function resolveChapterState(checks, evidenceCoveragePct, accuracyPct, stableCoveragePct, weakCount) {
  const graduated = checks.evidence && checks.accuracy && checks.stable && checks.weak
  let state = graduated ? 'graduated' : 'building'
  let reason = graduated ? '已达到章节毕业标准' : ''
  if (!graduated) {
    if (!checks.evidence) reason = `检测覆盖 ${evidenceCoveragePct}% / ${GRADUATION_CRITERIA.evidenceCoveragePct}%`
    else if (!checks.accuracy) reason = `正确率 ${accuracyPct == null ? '--' : accuracyPct + '%'} / ${GRADUATION_CRITERIA.accuracyPct}%`
    else if (!checks.weak) reason = `仍有 ${weakCount} 个薄弱知识点`
    else if (!checks.stable) reason = `稳定节点 ${stableCoveragePct}% / ${GRADUATION_CRITERIA.stableCoveragePct}%`
    if (checks.evidence && checks.accuracy && weakCount <= 1) state = 'ready'
  }
  return { graduated, state, reason }
}

function evaluateChapter(group) {
  const nodes = collectChapterNodes(group)
  const total = nodes.length
  if (!total) {
    return {
      graduated: false,
      state: 'unavailable',
      label: '暂无可练',
      total: 0,
      evidenceCoveragePct: 0,
      accuracyPct: null,
      stableCoveragePct: 0,
      weakCount: 0,
      reason: '当前章节暂无可练知识点',
    }
  }
  const established = nodes.filter(node => Number(node.attempt_count || 0) > 0 && node.status !== 'no_data')
  const stable = nodes.filter(node => node.status === 'good' || node.status === 'mastered')
  const weak = nodes.filter(node => node.status === 'weak')
  const evidenceCoveragePct = Math.round(established.length / total * 100)
  const stableCoveragePct = Math.round(stable.length / total * 100)
  const accuracyPct = computeChapterAccuracy(established)
  const checks = buildGraduationChecks(evidenceCoveragePct, accuracyPct, stableCoveragePct, weak.length)
  const { graduated, state, reason } = resolveChapterState(checks, evidenceCoveragePct, accuracyPct, stableCoveragePct, weak.length)
  return {
    graduated,
    state,
    label: graduated ? '已毕业' : (state === 'ready' ? '接近毕业' : '待毕业'),
    total,
    evidenceCoveragePct,
    accuracyPct,
    stableCoveragePct,
    weakCount: weak.length,
    reason,
    checks,
  }
}

function summarizeGroups(groups) {
  const items = (Array.isArray(groups) ? groups : []).map(group => ({ ...group, graduation: evaluateChapter(group) }))
  const eligible = items.filter(group => group.graduation.state !== 'unavailable')
  const graduated = eligible.filter(group => group.graduation.graduated).length
  return {
    items,
    summary: {
      graduated,
      total: eligible.length,
      text: `${graduated}/${eligible.length} 章节毕业`,
      criteriaText: `覆盖≥${GRADUATION_CRITERIA.evidenceCoveragePct}% · 正确率≥${GRADUATION_CRITERIA.accuracyPct}% · 稳定节点≥${GRADUATION_CRITERIA.stableCoveragePct}% · 无薄弱节点`,
    },
  }
}

module.exports = { CRITERIA: GRADUATION_CRITERIA, buildKnowledgeGroups, evaluateChapter, summarizeGroups }
