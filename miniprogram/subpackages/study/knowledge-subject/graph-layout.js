// 图谱坐标使用独立逻辑像素；屏幕尺寸与相机缩放负责适配设备。
const WORLD = { width: 800, height: 760 }
const GROUPS_PER_PAGE = 4
const POINTS_PER_PAGE = 8
const SLOT_CENTERS = [[230, 220], [570, 220], [570, 540], [230, 540]]
const SLOT_POINTS = [
  [[118, 112], [286, 72]], [[514, 72], [682, 112]],
  [[682, 648], [514, 688]], [[286, 688], [118, 648]],
]

function box(id, kind, label, cx, cy, width, height, extra = {}) {
  return {
    id, kind, label, cx, cy, width, height, ...extra,
    style: `left:${cx - width / 2}px;top:${cy - height / 2}px;width:${width}px;height:${height}px;`,
  }
}

function clip(node, dx, dy) {
  if (node.kind === 'core') return (node.width / 2) / (Math.hypot(dx, dy) || 1)
  return Math.min((node.width / 2) / (Math.abs(dx) || .001), (node.height / 2) / (Math.abs(dy) || .001))
}

function edge(from, to, kind, active) {
  const dx = to.cx - from.cx
  const dy = to.cy - from.cy
  const start = clip(from, dx, dy)
  const end = clip(to, dx, dy)
  const x = from.cx + dx * start
  const y = from.cy + dy * start
  const length = Math.max(0, Math.hypot(dx, dy) * (1 - start - end))
  return {
    id: `${from.id}>${to.id}`, from: from.id, to: to.id, kind, active,
    style: `left:${x}px;top:${y}px;width:${length}px;transform:rotate(${Math.atan2(dy, dx) * 180 / Math.PI}deg);`,
  }
}

function buildScene(groups, subject, options = {}) {
  const focused = options.groupKey ? groups.find(group => group.key === options.groupKey) : null
  const candidates = focused ? focused.nodes : groups.filter(group => group.nodes.length)
  const size = focused ? POINTS_PER_PAGE : GROUPS_PER_PAGE
  const pageCount = Math.max(1, Math.ceil(candidates.length / size))
  const page = Math.max(0, Math.min(pageCount - 1, Number(options.page) || 0))
  const slice = candidates.slice(page * size, (page + 1) * size)
  const selectedId = Number(options.selectedId) || 0
  const activePointIds = new Set()
  if (focused && selectedId) {
    const pointById = new Map(focused.nodes.map(point => [Number(point.knowledge_point_id), point]))
    let cursor = pointById.get(selectedId)
    while (cursor && !activePointIds.has(Number(cursor.knowledge_point_id))) {
      activePointIds.add(Number(cursor.knowledge_point_id))
      cursor = pointById.get(Number(cursor.parentId))
    }
  }
  const core = box('core', 'core', focused ? focused.name : subject.subject_name, 400, 380, 124, 124, {
    caption: focused ? `${focused.nodes.length} 个知识点` : '知识图谱', groupKey: '', tone: 'core',
  })
  const nodes = [core]
  const edges = []
  const points = []
  if (focused) {
    slice.forEach((point, index) => {
      const angle = -Math.PI / 2 + index * 2 * Math.PI / Math.max(slice.length, 1)
      // 单节点置于正上方，其余节点沿轨道均匀排布。
      const x = 400 + Math.cos(angle) * 290
      const y = 380 + Math.sin(angle) * 278
      points.push(box(`point:${point.knowledge_point_id}`, 'point', point.name, x, y, 164, 82, {
        pointId: point.knowledge_point_id, groupKey: focused.key,
        tone: point.tone, selected: Number(point.knowledge_point_id) === selectedId,
        pathActive: activePointIds.has(Number(point.knowledge_point_id)),
        parentId: point.parentId, depth: point.depth, caption: point.statusText,
      }))
    })
  } else {
    slice.forEach((group, index) => {
      const center = SLOT_CENTERS[index]
      const selectedInGroup = group.nodes.some(point => Number(point.knowledge_point_id) === selectedId)
      const hub = box(`group:${group.key}`, 'group', group.name, center[0], center[1], 184, 108, {
        groupKey: group.key, caption: `${group.nodes.length} 个知识点`, number: group.number,
        selected: selectedInGroup, pathActive: selectedInGroup, tone: group.tone,
      })
      nodes.push(hub)
      edges.push(edge(core, hub, 'membership', selectedInGroup))
      const preview = group.nodes.slice(0, 2)
      // 点选后仍将该节点保留在总览中，不用无意义的随机节点替换它。
      const selected = group.nodes.find(point => Number(point.knowledge_point_id) === selectedId)
      if (selected && !preview.includes(selected)) preview[preview.length - 1] = selected
      preview.forEach((point, pointIndex) => {
        const position = SLOT_POINTS[index][pointIndex]
        points.push(box(`point:${point.knowledge_point_id}`, 'point', point.name, position[0], position[1], 156, 78, {
          pointId: point.knowledge_point_id, groupKey: group.key, parentId: point.parentId,
          tone: point.tone, selected: Number(point.knowledge_point_id) === selectedId,
          pathActive: Number(point.knowledge_point_id) === selectedId, depth: point.depth, caption: point.statusText,
        }))
      })
    })
  }
  nodes.push(...points)
  const byId = new Map(nodes.map(node => [node.id, node]))
  points.forEach((point) => {
    const parent = byId.get(`point:${point.parentId}`)
    const from = parent && parent !== point ? parent : (byId.get(`group:${point.groupKey}`) || core)
    edges.push(edge(from, point, parent && parent !== point ? 'hierarchy' : 'membership', point.pathActive))
  })
  nodes.forEach((node, index) => { node.motionDelay = Math.min(300, 55 + index * 32) })
  edges.forEach((item, index) => { item.motionDelay = Math.min(220, 35 + index * 18) })
  return {
    nodes: candidates.length ? nodes : [], edges, pointIds: points.map(point => point.pointId),
    page, pageCount, total: candidates.length,
    rangeText: candidates.length ? `${page * size + 1}-${Math.min((page + 1) * size, candidates.length)} / ${candidates.length}` : '0 / 0',
    focused: Boolean(focused), title: focused ? focused.name : '全科知识图谱',
    hint: focused ? '选择节点查看状态，拖动画布探索关系' : '选择主题展开，再定位具体知识点',
  }
}

function fitCamera(frame) {
  const scale = Math.min(frame.width / WORLD.width, frame.height / WORLD.height) * .93
  return { scale, x: (frame.width - WORLD.width * scale) / 2, y: (frame.height - WORLD.height * scale) / 2 }
}

function cameraLimits(frame) {
  const fitScale = fitCamera(frame).scale
  return { min: fitScale * .8, max: Math.max(1.8, fitScale * 2.4) }
}

function clampCamera(camera, frame) {
  const limits = cameraLimits(frame)
  const scale = Math.max(limits.min, Math.min(limits.max, camera.scale))
  const width = WORLD.width * scale
  const height = WORLD.height * scale
  const x = width <= frame.width ? (frame.width - width) / 2 : Math.max(frame.width - width - 28, Math.min(28, camera.x))
  const y = height <= frame.height ? (frame.height - height) / 2 : Math.max(frame.height - height - 28, Math.min(28, camera.y))
  return { x, y, scale }
}

function zoomCamera(camera, factor, anchor, frame) {
  const limits = cameraLimits(frame)
  const scale = Math.max(limits.min, Math.min(limits.max, camera.scale * factor))
  return clampCamera({ scale, x: anchor.x - (anchor.x - camera.x) * scale / camera.scale, y: anchor.y - (anchor.y - camera.y) * scale / camera.scale }, frame)
}

function cameraStyle(camera) {
  // 舞台尺寸交给 WXSS，拖动帧只跨线程传输最小的 transform 字符串。
  return `transform:translate3d(${camera.x.toFixed(2)}px,${camera.y.toFixed(2)}px,0) scale(${camera.scale.toFixed(4)});`
}

module.exports = { WORLD, POINTS_PER_PAGE, buildScene, fitCamera, cameraLimits, clampCamera, zoomCamera, cameraStyle }
