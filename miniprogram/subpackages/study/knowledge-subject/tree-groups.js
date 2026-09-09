const DEFAULT_GROUP_NAME = '其他知识点'

const toId = (value) => {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

const safeDepth = value => Math.max(0, Math.min(8, Math.floor(Number(value) || 0)))

function groupTone(nodes) {
  if (nodes.some(node => node.tone === 'weak')) return 'weak'
  if (nodes.some(node => node.tone === 'stable')) return 'stable'
  return 'unseen'
}

function normalizeNode(node, rootDepth) {
  const depth = Math.max(0, safeDepth(node.depth) - rootDepth - 1)
  return {
    ...node,
    parentId: toId(node.parent_id),
    depth,
    indent: Math.min(depth, 4) * 20,
  }
}

function buildFlatGroup(nodes, subject) {
  const name = String((subject && subject.subject_name) || DEFAULT_GROUP_NAME)
  const normalized = nodes.map(node => ({
    ...node,
    parentId: null,
    depth: 0,
    indent: 0,
  }))
  return [{ key: 'all', name, number: '01', tone: groupTone(normalized), nodes: normalized }]
}

/**
 * 把后端的前序树节点整理为“一级主题 + 内部知识点”。
 * 输入异常时也会稳定降级：孤儿节点成为自己的根，循环链按首个可见节点分组。
 */
function buildKnowledgeGroups(input, subject) {
  const source = Array.isArray(input) ? input.filter(Boolean) : []
  if (!source.length) return []

  const nodes = []
  const byId = new Map()
  source.forEach((item) => {
    const id = toId(item.knowledge_point_id)
    if (!id || byId.has(id)) return
    const node = { ...item, knowledge_point_id: id }
    nodes.push(node)
    byId.set(id, node)
  })
  if (!nodes.length) return []

  const hasHierarchy = nodes.some(node => {
    const parentId = toId(node.parent_id)
    return parentId && parentId !== node.knowledge_point_id && byId.has(parentId)
  })
  if (!hasHierarchy) return buildFlatGroup(nodes, subject)

  const rootCache = new Map()
  const resolveRoot = (node) => {
    if (rootCache.has(node.knowledge_point_id)) return rootCache.get(node.knowledge_point_id)
    const path = []
    const seen = new Set()
    let cursor = node
    while (cursor && !seen.has(cursor.knowledge_point_id)) {
      if (rootCache.has(cursor.knowledge_point_id)) {
        cursor = rootCache.get(cursor.knowledge_point_id)
        break
      }
      path.push(cursor)
      seen.add(cursor.knowledge_point_id)
      const parentId = toId(cursor.parent_id)
      const parent = parentId && parentId !== cursor.knowledge_point_id ? byId.get(parentId) : null
      if (!parent) break
      cursor = parent
    }
    const root = cursor || node
    path.forEach(item => rootCache.set(item.knowledge_point_id, root))
    return root
  }

  const groupsByRoot = new Map()
  nodes.forEach((node) => {
    const root = resolveRoot(node)
    if (!groupsByRoot.has(root.knowledge_point_id)) {
      groupsByRoot.set(root.knowledge_point_id, { root, descendants: [] })
    }
    if (node.knowledge_point_id !== root.knowledge_point_id) {
      groupsByRoot.get(root.knowledge_point_id).descendants.push(node)
    }
  })

  return Array.from(groupsByRoot.values()).map((entry, index) => {
    // 单节点主题仍保留一个可点选节点，避免丢失练习入口。
    const children = entry.descendants.length ? entry.descendants : [entry.root]
    const normalized = children.map(node => normalizeNode(node, safeDepth(entry.root.depth)))
    return {
      key: String(entry.root.knowledge_point_id),
      name: String(entry.root.name || `${DEFAULT_GROUP_NAME}${index + 1}`),
      number: String(index + 1).padStart(2, '0'),
      tone: groupTone(normalized),
      nodes: normalized,
    }
  })
}

module.exports = { buildKnowledgeGroups }
