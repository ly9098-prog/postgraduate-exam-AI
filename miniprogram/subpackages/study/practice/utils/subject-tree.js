function readSubjectId(node) {
  return node.subject_id != null ? node.subject_id : node.id
}

function readSubjectName(node) {
  return node.display_name != null ? node.display_name : (node.name != null ? node.name : '')
}

function readSubjectCode(node) {
  return node.subject_code != null ? node.subject_code : (node.code != null ? node.code : '')
}

function bySortOrder(a, b) {
  return (a.sort_order - b.sort_order) || (a.subject_id - b.subject_id)
}

function normalizeSubjectNode(node) {
  if (!node) return null
  if (node.is_active === false) return null
  return {
    subject_id: Number(readSubjectId(node)),
    display_name: readSubjectName(node),
    subject_code: readSubjectCode(node),
    parent_id: node.parent_id != null ? Number(node.parent_id) : null,
    level: node.level != null ? Number(node.level) : null,
    path: node.path || '',
    sort_order: node.sort_order != null ? Number(node.sort_order) : 0,
    is_active: true,
    children: Array.isArray(node.children)
      ? node.children.map(normalizeSubjectNode).filter(Boolean).sort(bySortOrder)
      : [],
  }
}

function buildFlatChildren(root) {
  const flatChildren = []
  const appendDescendants = (node, depth) => {
    const children = Array.isArray(node.children) ? node.children : []
    children.forEach((child) => {
      const hasChildren = Array.isArray(child.children) && child.children.length > 0
      flatChildren.push({
        subject_id: Number(child.subject_id),
        display_name: hasChildren ? `${child.display_name}（全部）` : child.display_name,
        raw_display_name: child.display_name,
        parent_id: child.parent_id,
        level: child.level,
        has_children: hasChildren,
        depth,
        indent_rpx: Math.max(0, depth - 1) * 28,
      })
      appendDescendants(child, depth + 1)
    })
  }
  appendDescendants(root, 1)
  return flatChildren
}

function normalizeSubjectTree(raw) {
  if (!Array.isArray(raw) || raw.length === 0) return []
  const nodes = {}
  const parentItems = []
  const childItems = []
  const items = raw.map(normalizeSubjectNode).filter(Boolean)
  if (items.length === 0) return []

  items.forEach((item) => {
    nodes[item.subject_id] = item
    const isParent = item.level === 1 || item.parent_id == null
    if (isParent) parentItems.push(item)
    else childItems.push(item)
  })

  childItems.forEach((child) => {
    const parent = child.parent_id != null ? nodes[child.parent_id] : null
    if (parent) {
      if (!parent.children.some(item => item.subject_id === child.subject_id)) {
        parent.children.push(child)
      }
      parent.children.sort(bySortOrder)
    } else {
      parentItems.push(child)
    }
  })

  parentItems.sort(bySortOrder)
  parentItems.forEach((root) => {
    root.flat_children = buildFlatChildren(root)
    root.descendant_count = root.flat_children.length
    const iconMeta = subjectIconMeta(root.display_name, root.subject_code)
    root.icon_type = iconMeta.type
    root.icon_mark = iconMeta.mark
    root.icon_src = iconMeta.src
  })
  return parentItems
}

function flattenSelectableSubjects(subjectTree) {
  const result = []
  const appendNode = (node, rootId) => {
    const children = Array.isArray(node.children) ? node.children : []
    children.forEach(child => appendNode(child, rootId))
    result.push({
      subject_id: Number(node.subject_id),
      display_name: children.length > 0 ? `${node.display_name}（全部）` : node.display_name,
      parent_subject_id: rootId,
      has_children: children.length > 0,
    })
  }

  ;(subjectTree || []).forEach((root) => {
    const rootId = Number(root.subject_id)
    const children = Array.isArray(root.children) ? root.children : []
    children.forEach(child => appendNode(child, rootId))
    result.push({
      subject_id: rootId,
      display_name: children.length > 0 ? `${root.display_name}（全部）` : root.display_name,
      parent_subject_id: rootId,
      has_children: children.length > 0,
    })
  })
  return result.filter(item => item.subject_id && item.display_name)
}

function subjectMark(name) {
  const text = String(name || '')
  if (/数据|计算机|程序|代码|网络|操作系统/.test(text)) return '</>'
  if (/数学|代数|高数|概率|统计/.test(text)) return 'Σ'
  if (/英语|外语/.test(text)) return 'A'
  if (/政治|思政/.test(text)) return '政'
  return text.slice(0, 1) || '·'
}

function subjectIconMeta(name, code) {
  const text = `${String(name || '')} ${String(code || '')}`
  const codeText = String(code || '').trim()
  if (/计算机|数据结构|程序|代码|网络|操作系统|computer/i.test(text) || /^cs(?:408)?$/i.test(codeText)) {
    return { type: 'computer', mark: '', src: '/assets/icons/practice-subject/monitor.svg' }
  }
  if (/数学|代数|高数|概率|统计|math/i.test(text)) {
    return { type: 'math', mark: '', src: '/assets/icons/practice-subject/code-xml.svg' }
  }
  if (/英语|外语|english/i.test(text)) {
    return { type: 'english', mark: '', src: '/assets/icons/practice-subject/languages.svg' }
  }
  if (/政治|思政|politic/i.test(text)) {
    return { type: 'politics', mark: '', src: '/assets/icons/practice-subject/landmark.svg' }
  }
  return { type: 'default', mark: String(name || '').slice(0, 1) || '·', src: '' }
}

function decorateRecentSubjects(subjects, subjectHasChildren) {
  return (subjects || []).map((item) => {
    const subjectId = Number(item.subject_id)
    const hasChildren = item.has_children != null
      ? Boolean(item.has_children)
      : subjectHasChildren(subjectId)
    const mark = subjectMark(item.display_name)
    return {
      subject_id: subjectId,
      display_name: item.display_name,
      parent_subject_id: Number(item.parent_subject_id || item.subject_id),
      has_children: hasChildren,
      mark,
      icon_src: mark === '</>'
        ? '/assets/icons/practice-subject/code-xml.svg'
        : subjectIconMeta(item.display_name).src,
      scope_label: hasChildren ? '全部范围' : '继续练习',
    }
  })
}

function findParentSubjectId(subjectId, subjectTree) {
  const id = Number(subjectId)
  const tree = subjectTree || []
  for (let i = 0; i < tree.length; i += 1) {
    const root = tree[i]
    if (Number(root.subject_id) === id) return Number(root.subject_id)
    const stack = (root.children || []).slice()
    while (stack.length) {
      const node = stack.pop()
      if (Number(node.subject_id) === id) return Number(root.subject_id)
      if (Array.isArray(node.children)) Array.prototype.push.apply(stack, node.children)
    }
  }
  return null
}

function subjectHasChildren(subjectId, subjectTree) {
  const id = Number(subjectId)
  const stack = (subjectTree || []).slice()
  while (stack.length) {
    const node = stack.pop()
    if (Number(node.subject_id) === id) {
      return Array.isArray(node.children) && node.children.length > 0
    }
    if (Array.isArray(node.children)) Array.prototype.push.apply(stack, node.children)
  }
  return false
}

function getPracticeSubjectScopeIds(subjectId, includeChildren, subjectTree) {
  const id = Number(subjectId)
  if (!id) return []
  if (!includeChildren) return [id]
  const stack = (subjectTree || []).slice()
  let target = null
  while (stack.length) {
    const node = stack.pop()
    if (Number(node.subject_id) === id) {
      target = node
      break
    }
    if (Array.isArray(node.children)) Array.prototype.push.apply(stack, node.children)
  }
  if (!target) return []

  const scope = []
  const descendants = [target]
  while (descendants.length) {
    const node = descendants.pop()
    const nodeId = Number(node && node.subject_id)
    if (nodeId) scope.push(nodeId)
    if (node && Array.isArray(node.children)) Array.prototype.push.apply(descendants, node.children)
  }
  return Array.from(new Set(scope.length ? scope : [id]))
}

module.exports = {
  normalizeSubjectTree,
  flattenSelectableSubjects,
  subjectMark,
  subjectIconMeta,
  decorateRecentSubjects,
  findParentSubjectId,
  subjectHasChildren,
  getPracticeSubjectScopeIds,
}
