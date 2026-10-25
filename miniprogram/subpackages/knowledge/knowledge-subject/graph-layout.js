
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
function directChildren(group, parentId) {
if (!group || !Array.isArray(group.nodes)) return []
return group.nodes.filter(node => Number(node.parentId || node.parent_id) === Number(parentId))
}
function nodeMap(group) {
return new Map((group && Array.isArray(group.nodes) ? group.nodes : []).map(node => [Number(node.knowledge_point_id), node]))
}
function breadcrumbItems(subject, group, focusNode) {
const items = [{ key: 'subject', label: String(subject.subject_name || '全科'), groupKey: '', focusNodeId: 0, current: !focusNode }]
if (!group || !focusNode) return items
const byId = nodeMap(group)
const pathIds = Array.isArray(focusNode.pathIds) && focusNode.pathIds.length
? focusNode.pathIds
: [focusNode.knowledge_point_id]
pathIds.forEach((id) => {
const node = byId.get(Number(id))
if (!node) return
items.push({
key: `node:${node.knowledge_point_id}`,
label: String(node.name || '未命名知识点'),
groupKey: String(group.key),
focusNodeId: Number(node.knowledge_point_id),
current: Number(node.knowledge_point_id) === Number(focusNode.knowledge_point_id),
})
})
return items
}
function buildScene(groups, subject, options = {}) {
  var ctx = resolveSceneContext(groups, subject, options)
  var nodes = [ctx.core], edges = [], pointIds = []
  buildSceneCards(ctx, nodes, edges, pointIds)
  assignMotionDelays(nodes, edges)
  return buildSceneResult(ctx, nodes, edges, pointIds, groups)
}

function resolveSceneContext(groups, subject, options) {
  var groupKey = String(options.groupKey || "")
  var focusedGroup = groupKey ? groups.find(function(group) { return String(group.key) === groupKey }) : null
  var focusNode = resolveFocusNode(focusedGroup, options)
  var candidates = focusNode ? directChildren(focusedGroup, focusNode.knowledge_point_id) : groups.filter(function(group) { return group.nodes.length })
  var size = focusNode ? POINTS_PER_PAGE : GROUPS_PER_PAGE
  var pageCount = Math.max(1, Math.ceil(candidates.length / size))
  var page = Math.max(0, Math.min(pageCount - 1, Number(options.page) || 0))
  var slice = candidates.slice(page * size, (page + 1) * size)
  var core = box("core", "core", focusNode ? focusNode.name : subject.subject_name, 400, 460, 204, 204, {
    caption: focusNode ? (focusNode.parentId ? "返回上一级" : "返回全科") : "Knowledge Map",
    groupKey: focusNode ? String(focusedGroup.key) : "", pointId: focusNode ? Number(focusNode.knowledge_point_id) : 0,
    tone: "core", iconSrc: "/assets/icons/knowledge-subject/layers.png",
  })
  return { focusNode: focusNode, focusedGroup: focusedGroup, candidates: candidates, size: size, pageCount: pageCount, page: page, slice: slice, core: core, selectedId: Number(options.selectedId) || 0, subject: subject }
}

function resolveFocusNode(focusedGroup, options) {
  if (!focusedGroup) return null
  var byId = nodeMap(focusedGroup)
  var requestedId = Number(options.focusNodeId) || Number(focusedGroup.rootId) || 0
  return byId.get(requestedId) || byId.get(Number(focusedGroup.rootId)) || focusedGroup.rootNode || focusedGroup.nodes[0] || null
}

function buildSceneCards(ctx, nodes, edges, pointIds) {
  ctx.slice.forEach(function(entry, index) {
    var position = CARD_POSITIONS[index]
    if (!position) return
    var item = entry, group = ctx.focusedGroup, edgeKind = "hierarchy"
    if (!ctx.focusNode) { group = entry; item = entry.rootNode || entry.nodes[0]; edgeKind = "membership" }
    if (!item) return
    var pointId = Number(item.knowledge_point_id)
    var visibleChildren = directChildren(group, pointId)
    var expandable = Boolean(item.hasChildren)
    var selected = !expandable && pointId === ctx.selectedId
    var kind = expandable ? "group" : "point"
    var node = box(kind + ":" + pointId, kind, item.name, position[0], position[1], 226, 112, {
      pointId: pointId, groupKey: String(group.key), tone: item.tone, selected: selected,
      pathActive: expandable || selected, expandable: expandable,
      caption: expandable ? visibleChildren.length + (visibleChildren.length === Number(item.childCount || 0) ? "" : " / " + Number(item.childCount || 0)) + " 个直接子节点" + (item.contextOnly ? " · 路径" : "") : (item.contextOnly ? "路径 · " : "") + (item.statusText || "未开始") + (Number(item.trainable_question_count) > 0 ? " · " + Number(item.trainable_question_count) + "题" : ""),
      iconSrc: item.iconSrc || group.iconSrc || "/assets/icons/knowledge-subject/nodes.png",
    })
    nodes.push(node)
    if (!expandable) pointIds.push(pointId)
    edges.push(edge(ctx.core, node, edgeKind, selected))
  })
}

function assignMotionDelays(nodes, edges) {
  nodes.forEach(function(node, index) { node.motionDelay = Math.min(220, 30 + index * 20) })
  edges.forEach(function(item, index) { item.motionDelay = Math.min(180, 25 + index * 14) })
}

function buildSceneResult(ctx, nodes, edges, pointIds, groups) {
  var matchTotal = groups.reduce(function(total, group) { return total + Number(group.matchCount == null ? group.nodes.length : group.matchCount) }, 0)
  var visibleDirectChildren = ctx.focusNode ? ctx.candidates.length : 0
  var rangeText = ctx.candidates.length ? (ctx.pageCount > 1 ? (ctx.page * ctx.size + 1) + "-" + Math.min((ctx.page + 1) * ctx.size, ctx.candidates.length) + " / " + ctx.candidates.length : ctx.candidates.length + (ctx.focusNode ? " 个子节点" : " 个主题")) : "0 " + (ctx.focusNode ? "个子节点" : "个主题")
  return { nodes: ctx.candidates.length || ctx.focusNode ? nodes : [], edges: edges, pointIds: pointIds, page: ctx.page, pageCount: ctx.pageCount, total: ctx.candidates.length, matchTotal: matchTotal, rangeText: rangeText, focused: Boolean(ctx.focusNode), focusNodeId: ctx.focusNode ? Number(ctx.focusNode.knowledge_point_id) : 0, parentFocusId: ctx.focusNode ? Number(ctx.focusNode.parentId) || 0 : 0, groupKey: ctx.focusNode ? String(ctx.focusedGroup.key) : "", title: ctx.focusNode ? ctx.focusNode.name : "全科知识图谱", hint: ctx.focusNode ? visibleDirectChildren + " 个直接子节点 · 逐层展开知识结构" : "从一级主题进入，再逐层定位具体知识点", countText: ctx.focusNode ? visibleDirectChildren + " 个直接子节点" : "共 " + matchTotal + " 个知识点", scopeText: ctx.focusNode ? ctx.focusNode.name + " · 当前层级" : "全科知识图谱", breadcrumbs: breadcrumbItems(ctx.subject, ctx.focusedGroup, ctx.focusNode) }
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
