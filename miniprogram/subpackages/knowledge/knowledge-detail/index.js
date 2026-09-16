const api = require('../../../utils/api')
const { knowledgePracticeSync } = require('../../../utils/storage')
const RELATION_META = {
prerequisite: {
label: '前置知识',
icon: '/assets/icons/knowledge-subject/tree.png',
},
next: {
label: '后续知识',
icon: '/assets/icons/knowledge-subject/nodes.png',
},
related: {
label: '相关知识',
icon: '/assets/icons/knowledge-subject/relation.png',
},
}
Page({
data: {
loading: true,
error: '',
detail: null,
syllabusVersion: null,
recent: [],
relationItems: [],
relationCount: 0,
scoreText: '--',
confidenceText: '--',
accuracyText: '--',
practiceDisabled: true,
practiceLaunching: false,
contentPhase: 'settled',
relationSwitching: false,
relationSwitchingId: 0,
},
onLoad(options) {
this._detailCache = Object.create(null)
this._detailRequests = Object.create(null)
this._switchToken = 0
this._phaseTimer = null
this._settleTimer = null
this._returnRefreshTimer = null
this._practiceLaunchFeedbackTimer = null
this._practiceNavigationPending = false
this.knowledgePointId = Number(options && options.knowledge_point_id)
if (!this.knowledgePointId) {
this.setData({ loading: false, error: '知识点参数无效' })
return
}
this.loadDetail()
},
onShow() {
this._practiceNavigationPending = false
if (this._practiceLaunchFeedbackTimer) {
clearTimeout(this._practiceLaunchFeedbackTimer)
this._practiceLaunchFeedbackTimer = null
}
if (this.data.practiceLaunching) this.setData({ practiceLaunching: false })
if (!this._loadedOnce) return
clearTimeout(this._returnRefreshTimer)
this._returnRefreshTimer = setTimeout(() => {
this._returnRefreshTimer = null
if (!this._unloaded) this.loadDetail(false, true)
}, 240)
},
onUnload() {
this._unloaded = true
this._switchToken += 1
if (this._phaseTimer) clearTimeout(this._phaseTimer)
if (this._settleTimer) clearTimeout(this._settleTimer)
if (this._returnRefreshTimer) clearTimeout(this._returnRefreshTimer)
if (this._practiceLaunchFeedbackTimer) clearTimeout(this._practiceLaunchFeedbackTimer)
this._practiceLaunchFeedbackTimer = null
this._practiceNavigationPending = false
},
_fetchDetail(id, force = false) {
const key = String(id)
if (!force && this._detailCache[key]) return Promise.resolve(this._detailCache[key])
if (!force && this._detailRequests[key]) return this._detailRequests[key]
const request = api.get(`/knowledge-map/points/${id}`).then(
detail => {
this._detailCache[key] = detail
delete this._detailRequests[key]
return detail
},
error => {
delete this._detailRequests[key]
throw error
}
)
this._detailRequests[key] = request
return request
},
_normalizeDetail(rawDetail) {
const source = rawDetail || {}
const directChildren = Array.isArray(source.direct_children) ? source.direct_children : []
const descendantCount = Math.max(0, Number(source.descendant_count) || 0)
const isParentNode = directChildren.length > 0 || descendantCount > 0
const detail = {
...source,
prerequisites: Array.isArray(source.prerequisites) ? source.prerequisites : [],
next_nodes: Array.isArray(source.next_nodes) ? source.next_nodes : [],
related_nodes: Array.isArray(source.related_nodes) ? source.related_nodes : [],
ancestors: Array.isArray(source.ancestors) ? source.ancestors : [],
direct_children: directChildren,
recent_answers: Array.isArray(source.recent_answers) ? source.recent_answers : [],
practice_route_params: source.practice_route_params || {},
correct_count: Number(source.correct_count) || 0,
wrong_count: Number(source.wrong_count) || 0,
recent_wrong_count: Number(source.recent_wrong_count) || 0,
attempt_count: Number(source.attempt_count) || 0,
trainable_question_count: Number(source.trainable_question_count) || 0,
descendant_count: descendantCount,
subtree_trainable_knowledge_points: Math.max(0, Number(source.subtree_trainable_knowledge_points) || 0),
subtree_reliable_knowledge_points: Math.max(0, Number(source.subtree_reliable_knowledge_points) || 0),
subtree_weak_knowledge_points: Math.max(0, Number(source.subtree_weak_knowledge_points) || 0),
subtree_coverage_ratio: Math.max(0, Number(source.subtree_coverage_ratio) || 0),
is_parent_node: isParentNode,
}
const recent = detail.recent_answers.map(item => ({
...item,
mark: item.is_correct ? '✓' : '×',
cls: item.is_correct ? 'correct' : 'wrong',
}))
const relationItems = this._buildRelationItems(detail)
const relationCount = detail.prerequisites.length + detail.next_nodes.length + detail.related_nodes.length
const displayMastery = isParentNode ? source.subtree_mastery_score : source.mastery_score
const displayConfidence = isParentNode ? source.subtree_confidence : source.confidence
const displayStatus = isParentNode ? (source.subtree_status || source.status) : source.status
const coverageText = isParentNode
? `${Math.round(Math.min(1, detail.subtree_coverage_ratio) * 100)}%`
: (detail.accuracy == null ? '--' : `${Math.round((Number(detail.accuracy) || 0) * 100)}%`)
detail.display_status = displayStatus || 'no_data'
const practiceTrainable = isParentNode
? detail.subtree_trainable_knowledge_points
: detail.trainable_question_count
const practiceDisabled = !detail.practice_route_params.subject_id ||
!detail.practice_route_params.knowledge_point_id ||
practiceTrainable <= 0
return {
detail,
syllabusVersion: detail.syllabus_version || null,
recent,
relationItems,
relationCount,
scoreText: displayMastery == null ? '--' : `${Math.round(Number(displayMastery) || 0)}%`,
confidenceText: `${Math.round((Number(displayConfidence) || 0) * 100)}%`,
accuracyText: coverageText,
practiceDisabled,
}
},
_buildRelationItems(detail) {
const groups = [
{ key: 'prerequisites', type: 'prerequisite' },
{ key: 'next_nodes', type: 'next' },
{ key: 'related_nodes', type: 'related' },
]
const seen = Object.create(null)
const items = []
groups.forEach(group => {
const meta = RELATION_META[group.type]
detail[group.key].forEach(item => {
const id = Number(item.knowledge_point_id)
if (!id || id === this.knowledgePointId || seen[id]) return
seen[id] = true
items.push({
...item,
knowledge_point_id: id,
relation_type: group.type,
relation_label: meta.label,
relation_icon: meta.icon,
})
})
})
return items
},
_applyDetail(rawDetail, extraData) {
const viewData = this._normalizeDetail(rawDetail)
wx.setNavigationBarTitle({ title: viewData.detail.name || '知识点详情' })
this._loadedOnce = true
this.setData({
loading: false,
error: '',
...viewData,
...(extraData || {}),
})
},
async loadDetail(showLoading = true, force = false) {
if (showLoading) this.setData({ loading: true, error: '' })
try {
const detail = await this._fetchDetail(this.knowledgePointId, force)
this._applyDetail(detail)
} catch (error) {
if (showLoading) {
this.setData({ loading: false, error: api.getErrorMessage(error) })
}
}
},
startPractice() {
const d = this.data.detail
const p = d && d.practice_route_params
if (this._practiceNavigationPending || this.data.practiceLaunching) return
const trainableCount = d && d.is_parent_node
? Number(d.subtree_trainable_knowledge_points)
: Number(d && d.trainable_question_count)
if (!p || !p.subject_id || !p.knowledge_point_id || trainableCount <= 0) {
wx.showToast({ title: d && d.is_parent_node ? '当前章节暂无可练题目' : '当前知识点暂无可练题目', icon: 'none' })
return
}
const returnTo = encodeURIComponent(`/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=${this.knowledgePointId}`)
const subjectName = encodeURIComponent(String(d.subject_name || '专项练习'))
const includeDescendants = Number(p.include_descendants || 0) === 1 || Boolean(d.is_parent_node)
knowledgePracticeSync.setBaseline(Number(p.subject_id) || 0, Number(p.knowledge_point_id) || 0, Number(d.attempt_count) || 0)
const url = `/subpackages/study/practice/practice?subject_id=${p.subject_id}&subject_name=${subjectName}&mode=random&count=${p.count || 10}&knowledge_point_id=${p.knowledge_point_id}&include_descendants=${includeDescendants ? 1 : 0}&include_children=1&allow_repeat=1&autostart=1&source=knowledge_map&return_to=${returnTo}`
this._practiceNavigationPending = true
if (this._practiceLaunchFeedbackTimer) clearTimeout(this._practiceLaunchFeedbackTimer)
this._practiceLaunchFeedbackTimer = setTimeout(() => {
this._practiceLaunchFeedbackTimer = null
if (!this._unloaded && this._practiceNavigationPending) this.setData({ practiceLaunching: true })
}, 140)
wx.navigateTo({
url,
success: () => {
if (this._practiceLaunchFeedbackTimer) {
clearTimeout(this._practiceLaunchFeedbackTimer)
this._practiceLaunchFeedbackTimer = null
}
},
fail: () => {
if (this._practiceLaunchFeedbackTimer) {
clearTimeout(this._practiceLaunchFeedbackTimer)
this._practiceLaunchFeedbackTimer = null
}
this._practiceNavigationPending = false
if (!this._unloaded && this.data.practiceLaunching) this.setData({ practiceLaunching: false })
wx.showToast({ title: '练习页打开失败，请重试', icon: 'none' })
},
})
},
prefetchRelation(event) {
const id = Number(event.currentTarget.dataset.id)
if (!id || id === this.knowledgePointId) return
this._fetchDetail(id).catch(() => {})
},
openRelation(event) {
const id = Number(event.currentTarget.dataset.id)
if (!id || id === this.knowledgePointId || this.data.relationSwitching) return
const token = ++this._switchToken
const startedAt = Date.now()
if (this._phaseTimer) clearTimeout(this._phaseTimer)
if (this._settleTimer) clearTimeout(this._settleTimer)
this.setData({
relationSwitching: true,
relationSwitchingId: id,
contentPhase: 'leaving',
})
wx.pageScrollTo({ scrollTop: 0, duration: 220 })
this._fetchDetail(id).then(detail => {
if (token !== this._switchToken) return
const remaining = Math.max(0, 110 - (Date.now() - startedAt))
this._phaseTimer = setTimeout(() => {
if (token !== this._switchToken) return
this.knowledgePointId = id
this._applyDetail(detail, {
contentPhase: 'entering',
relationSwitching: true,
relationSwitchingId: id,
})
wx.nextTick(() => {
this._settleTimer = setTimeout(() => {
if (token !== this._switchToken) return
this.setData({
contentPhase: 'settled',
relationSwitching: false,
relationSwitchingId: 0,
})
}, 24)
})
}, remaining)
}).catch(error => {
if (token !== this._switchToken) return
this.setData({
contentPhase: 'settled',
relationSwitching: false,
relationSwitchingId: 0,
})
wx.showToast({ title: api.getErrorMessage(error) || '知识点加载失败', icon: 'none' })
})
},
retry() {
this.loadDetail(true, true)
},
})
