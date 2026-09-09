// 参考“卡片 + 中心节点”图谱：固定世界坐标保证不同机型按同一比例缩放。
const WORLD = { width: 800, height: 920 }
const GROUPS_PER_PAGE = 8
const POINTS_PER_PAGE = 8
const CARD_POSITIONS = [
  [170, 132], [630, 132],
  [170, 340], [630, 340],
  [170, 580], [630, 580],
  [170, 788], [630, 788],
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
    id: `${from.id}>${to.id}`,
    from: from.id,
    to: to.id,
    kind,
    active,
    style: `left:${x}px;top:${y}px;width:${length}px;transform:rotate(${Math.atan2(dy, dx) * 180 / Math.PI}deg);`,
  }
}

function buildScene(groups, subject, options = {}) {
  const focused = options.groupKey ? groups.find(group => String(group.key) === String(options.groupKey)) : null
  const candidates = focused ? focused.nodes : groups.filter(group => group.nodes.length)
  const size = focused ? POINTS_PER_PAGE : GROUPS_PER_PAGE
  const pageCount = Math.max(1, Math.ceil(candidates.length / size))
  const page = Math.max(0, Math.min(pageCount - 1, Number(options.page) || 0))
  const slice = candidates.slice(page * size, (page + 1) * size)
  const selectedId = Number(options.selectedId) || 0
  const core = box('core', 'core', focused ? focused.name : subject.subject_name, 400, 460, 204, 204, {
    caption: focused ? `${focused.nodes.length} 个知识点` : '学科知识中心',
    groupKey: '',
    tone: 'core',
    iconSrc: '/assets/icons/knowledge-subject/layers.png',
  })

  const nodes = [core]
  const edges = []
  const pointIds = []

  slice.forEach((item, index) => {
    const position = CARD_POSITIONS[index]
    if (!position) return
    if (focused) {
      const pointId = Number(item.knowledge_point_id)
      const selected = pointId === selectedId
      const node = box(`point:${pointId}`, 'point', item.name, position[0], position[1], 226, 112, {
        pointId,
        groupKey: focused.key,
        tone: item.tone,
        selected,
        pathActive: selected,
        caption: item.statusText,
        iconSrc: item.iconSrc || focused.iconSrc || '/assets/icons/knowledge-subject/nodes.png',
      })
      nodes.push(node)
      pointIds.push(pointId)
      edges.push(edge(core, node, 'hierarchy', selected))
      return
    }

    const group = item
    const node = box(`group:${group.key}`, 'group', group.name, position[0], position[1], 226, 112, {
      groupKey: String(group.key),
      caption: `${group.nodes.length} 个知识点`,
      number: group.number,
      selected: false,
      pathActive: false,
      tone: group.tone,
      iconSrc: group.iconSrc || '/assets/icons/knowledge-subject/nodes.png',
    })
    nodes.push(node)
    edges.push(edge(core, node, 'membership', false))
  })

  nodes.forEach((node, index) => { node.motionDelay = Math.min(220, 30 + index * 20) })
  edges.forEach((item, index) => { item.motionDelay = Math.min(180, 25 + index * 14) })

  return {
    nodes: candidates.length ? nodes : [],
    edges,
    pointIds,
    page,
    pageCount,
    total: candidates.length,
    rangeText: candidates.length ? `${page * size + 1}-${Math.min((page + 1) * size, candidates.length)} / ${candidates.length}` : '0 / 0',
    focused: Boolean(focused),
    title: focused ? focused.name : '全科知识图谱',
    hint: focused ? '点击知识点查看掌握状态与专项练习' : '连接主题展开，定位到具体知识点',
  }
}

function fitCamera(frame) {
  const scale = Math.min(frame.width / WORLD.width, frame.height / WORLD.height) * .965
  return { scale, x: (frame.width - WORLD.width * scale) / 2, y: (frame.height - WORLD.height * scale) / 2 }
}

function cameraLimits(frame) {
  const fitScale = fitCamera(frame).scale
  return { min: fitScale, max: Math.max(1.6, fitScale * 2.1) }
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
  return `transform:translate3d(${camera.x.toFixed(2)}px,${camera.y.toFixed(2)}px,0) scale(${camera.scale.toFixed(4)});`
}

module.exports = { WORLD, POINTS_PER_PAGE, buildScene, fitCamera, cameraLimits, clampCamera, zoomCamera, cameraStyle }
