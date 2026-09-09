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

  // 后端异常数据可能出现循环 parent。这里确定性地断开循环中最早出现节点的父边，
  // 保证索引和图谱始终能生成一棵可遍历的树/森林。
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
  const source = Array.isArray(input) ? input.filter(Boolean) : []
  if (!source.length) return []

  const nodes = []
  const byId = new Map()
  const orderById = new Map()
  source.forEach((item, index) => {
    const id = toId(item.knowledge_point_id)
    if (!id || byId.has(id)) return
    const node = { ...item, knowledge_point_id: id }
    nodes.push(node)
    byId.set(id, node)
    orderById.set(id, index)
  })
  if (!nodes.length) return []

  const parentById = buildParentMap(nodes, byId, orderById)
  const childrenById = new Map(nodes.map(node => [node.knowledge_point_id, []]))
  nodes.forEach((node) => {
    const parentId = parentById.get(node.knowledge_point_id)
    if (parentId && childrenById.has(parentId)) childrenById.get(parentId).push(node.knowledge_point_id)
  })
  childrenById.forEach(children => children.sort((a, b) => orderById.get(a) - orderById.get(b)))

  const descendantCountCache = new Map()
  const descendantCount = (id) => {
    if (descendantCountCache.has(id)) return descendantCountCache.get(id)
    const count = (childrenById.get(id) || []).reduce((total, childId) => total + 1 + descendantCount(childId), 0)
    descendantCountCache.set(id, count)
    return count
  }

  const roots = nodes
    .filter(node => !parentById.get(node.knowledge_point_id))
    .sort((a, b) => orderById.get(a.knowledge_point_id) - orderById.get(b.knowledge_point_id))

  const decorateSubtree = (root) => {
    const result = []
    const walk = (id, depth, pathIds) => {
      const raw = byId.get(id)
      if (!raw) return
      const children = childrenById.get(id) || []
      const parentId = parentById.get(id)
      const nextPath = pathIds.concat(id)
      result.push({
        ...raw,
        parent_id: parentId,
        parentId,
        rootId: root.knowledge_point_id,
        depth,
        indent: Math.min(depth, 5) * 20,
        childCount: children.length,
        descendantCount: descendantCount(id),
        hasChildren: children.length > 0,
        isLeaf: children.length === 0,
        pathIds: nextPath,
      })
      children.forEach(childId => walk(childId, depth + 1, nextPath))
    }
    walk(root.knowledge_point_id, 0, [])
    return result
  }

  const groups = roots.map((root, sourceIndex) => {
    const normalized = decorateSubtree(root)
    const rootNode = normalized[0]
    return {
      key: String(root.knowledge_point_id),
      rootId: root.knowledge_point_id,
      rootNode,
      name: String(root.name || `${DEFAULT_GROUP_NAME}${sourceIndex + 1}`),
      tone: groupTone(normalized),
      nodeCount: normalized.length,
      descendantCount: Math.max(0, normalized.length - 1),
      directChildCount: rootNode ? rootNode.childCount : 0,
      sourceIndex,
      nodes: normalized,
    }
  })

  // 数据尚未完全补齐 parent 时，优先把真正拥有层级的根主题放到前面，
  // 避免首页被大量孤立叶节点占满；同类主题仍保持原始大纲顺序。
  groups.sort((a, b) => {
    const aStructured = a.descendantCount > 0 ? 1 : 0
    const bStructured = b.descendantCount > 0 ? 1 : 0
    if (aStructured !== bStructured) return bStructured - aStructured
    if (aStructured && a.nodeCount !== b.nodeCount) return b.nodeCount - a.nodeCount
    return a.sourceIndex - b.sourceIndex
  })

  return groups.map((group, index) => ({
    ...group,
    number: String(index + 1).padStart(2, '0'),
  }))
}

module.exports = { buildKnowledgeGroups }
