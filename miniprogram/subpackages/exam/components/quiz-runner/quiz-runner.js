
var questionAdapter = null
try {
questionAdapter = require('../../utils/question-runner-adapter')
} catch (e) {
}
Component({
properties: {
mode: { type: String, value: 'practice' },
theme: { type: String, value: 'default' },
title: { type: String, value: '' },
subtitle: { type: String, value: '' },
subjectName: { type: String, value: '' },
questions: { type: Array, value: [] },
currentQuestion: { type: Object, value: null },
answerState: { type: Object, value: null },
currentIndex: { type: Number, value: 0 },
totalCount: { type: Number, value: 0 },
answeredCount: { type: Number, value: 0 },
progressPercent: { type: Number, value: 0 },
elapsedText: { type: String, value: '00:00' },
readonly: { type: Boolean, value: false },
submitted: { type: Boolean, value: false },
submitting: { type: Boolean, value: false },
showAnswer: { type: Boolean, value: false },
showFeedback: { type: Boolean, value: false },
submitText: { type: String, value: '提交' },
submitDisabled: { type: Boolean, value: false },
prevDisabled: { type: Boolean, value: false },
nextDisabled: { type: Boolean, value: false },
showMasterButton: { type: Boolean, value: false },
showMarkButton: { type: Boolean, value: false },
markedForReview: { type: Boolean, value: false },
showSubmitButton: { type: Boolean, value: true },
showNavigation: { type: Boolean, value: true },
showBackButton: { type: Boolean, value: false },
customNavigation: { type: Boolean, value: false },
swipeEnabled: { type: Boolean, value: true },
swipeThroughOptions: { type: Boolean, value: false },
allowSwipeInReadonly: { type: Boolean, value: false },
compactReviewMode: { type: Boolean, value: false },
externalSwitchAnimation: { type: Boolean, value: false },
flowLayout: { type: Boolean, value: false },
compactBottom: { type: Boolean, value: false },
heroCollapseEnabled: { type: Boolean, value: true },
loading: { type: Boolean, value: false },
errorText: { type: String, value: '' },
emptyText: { type: String, value: '' },
renderErrorText: { type: String, value: '' },
},
data: {
showSheet: false,
heroCollapsed: false,
questionScrollIntoView: '',
animClass: '',
_animating: false,
_touchX: undefined,
_touchY: undefined,
_touchTime: 0,
_swipeTapLockUntil: 0,
_qTypeLabel: '',
_codeLines: [],
_mixedBlocks: [],
_questionImages: [],
_optionList: [],
_blankOptionGroups: [],
_hasBlankOptionGroups: false,
_renderUnknownMode: false,
_renderFallbackText: '',
},
created: function () {
this._lastRenderModel = null
this._lastQuestionId = null
this._hasRenderedQuestion = false
this._questionResetPending = false
this._lastQuestionScrollTop = 0
this._heroCollapseLockUntil = 0
},
observers: {
'currentQuestion, answerState': function (q, answerState) {
if (!q) {
this.setData({ _qTypeLabel: '', _codeLines: [], _mixedBlocks: [], _questionImages: [], _optionList: [], _blankOptionGroups: [], _hasBlankOptionGroups: false, _renderUnknownMode: false, _renderFallbackText: '' })
this._lastRenderModel = null
this._lastQuestionId = null
this._hasRenderedQuestion = false
return
}
var questionId = q.id == null ? '' : String(q.id)
var questionIdentity = questionId
? 'id:' + questionId
: 'index:' + String(this.data.currentIndex)
var questionChanged = questionIdentity !== this._lastQuestionId
var wasRendered = this._hasRenderedQuestion
this._lastQuestionId = questionIdentity
var model = q._renderModel || {}
var renderModelChanged = this._lastRenderModel !== model
var shouldResetViewport = wasRendered && questionChanged
this._hasRenderedQuestion = true
this._lastRenderModel = model
var data = {}
if (renderModelChanged) {
var label = q._typeLabel || this._typeLabel(q)
var codeLines = model.mode === 'CODE' ? this._splitCodeLines(model.rawText) : []
var mixedBlocks = model.mode === 'MIXED' ? this._decorateMixedBlocks(model.blocks) : []
var images = []
var adapter
try { adapter = require('../../utils/question-runner-adapter') } catch (e) {}
if (adapter && typeof adapter.computeExtraImages === 'function') {
images = adapter.computeExtraImages(q)
} else if (adapter && typeof adapter.getQuestionImages === 'function') {
images = adapter.getQuestionImages(q)
} else if (Array.isArray(q.image_url)) {
images = q.image_url.filter(function (u) { return u && typeof u === 'string' })
} else if (q.content && Array.isArray(q.content.image_url)) {
images = q.content.image_url.filter(function (u) { return u && typeof u === 'string' })
}
var knownModes = { SEGMENTS: true, RICH_TEXT: true, CODE: true, LATEX: true, MIXED: true }
var unknownMode = !model.mode || !knownModes[model.mode]
var fallbackText = ''
if (unknownMode) {
fallbackText = q.content && (q.content.text || q.content.stem) || ''
if (!fallbackText) fallbackText = '该题内容暂时无法显示'
}
data._qTypeLabel = label
data._codeLines = codeLines
data._mixedBlocks = mixedBlocks
data._questionImages = images
data._renderUnknownMode = unknownMode
data._renderFallbackText = fallbackText
}
var answerStateMatches = !!(
answerState &&
String(answerState.questionId == null ? '' : answerState.questionId) === questionId
)
var blankOptionGroups = answerStateMatches && Array.isArray(answerState.blankOptionGroups)
? answerState.blankOptionGroups
: (Array.isArray(q._blankOptionGroups) ? q._blankOptionGroups : [])
if (questionAdapter && typeof questionAdapter.getBlankOptionGroups === 'function') {
try {
var rawGroups = blankOptionGroups
if (!rawGroups.length) rawGroups = questionAdapter.getBlankOptionGroups(q)
var firstGroup = rawGroups[0]
var firstOption = firstGroup && Array.isArray(firstGroup.options)
? firstGroup.options[0]
: null
var needsEnrich = !!(rawGroups.length && (!firstOption || !firstOption._text))
if (needsEnrich && typeof questionAdapter.enrichBlankOptionGroups === 'function') {
rawGroups = questionAdapter.enrichBlankOptionGroups(
rawGroups,
q._blankAnswer || q.user_answer || ''
)
}
if (rawGroups.length) blankOptionGroups = rawGroups
} catch (e) {
}
}
data._blankOptionGroups = blankOptionGroups
data._hasBlankOptionGroups = blankOptionGroups.length > 0
var optionList = answerStateMatches && Array.isArray(answerState.optionList)
? answerState.optionList
: (Array.isArray(q._optionList) ? q._optionList : [])
if (!optionList.length && !blankOptionGroups.length &&
questionAdapter && typeof questionAdapter.buildOptionListFromFlags === 'function') {
try {
var optionSource = q._opts && Object.keys(q._opts).length > 0
? q._opts
: (typeof questionAdapter.getQuestionOptions === 'function'
? questionAdapter.getQuestionOptions(q)
: q.options)
if (optionSource && typeof optionSource === 'object') {
var optionKeys = Array.isArray(q._optionKeys)
? q._optionKeys
: Object.keys(optionSource)
optionList = questionAdapter.buildOptionListFromFlags(
optionSource,
optionKeys,
q._selectedFlags || {}
)
}
} catch (e) {
}
}
data._optionList = optionList
if (shouldResetViewport) data.heroCollapsed = false
this.setData(data)
if (shouldResetViewport) this._requestQuestionViewportReset()
},
},
methods: {
_requestQuestionViewportReset: function () {
var self = this
if (this._questionResetPending) return
this._questionResetPending = true
this._lastQuestionScrollTop = 0
this._heroCollapseLockUntil = 0
setTimeout(function () {
self._questionResetPending = false
self.setData({
heroCollapsed: false,
questionScrollIntoView: 'runner-scroll-top-anchor',
}, function () {
self.setData({ questionScrollIntoView: '' })
})
}, 0)
},
_typeLabel: function (q) {
if (!q) return ''
if (q._hasBlankOptionGroups || q.question_type === 'multi_blank_choice') return '多空选择题'
if (q.question_type === 'multiple_choice') return '多选题'
if (q.question_type === 'true_false' || q.question_type === 'judgement') return '判断题'
return '单选题'
},
_splitCodeLines: function (value) {
var raw = String(value == null ? '' : value)
.replace(/\r\n/g, '\n')
.replace(/\r/g, '\n')
var parts = raw.split('\n')
if (!parts.length) parts = ['']
return parts.map(function (text, index) {
return { no: index + 1, text: text || ' ' }
})
},
_decorateMixedBlocks: function (blocks) {
var self = this
return (Array.isArray(blocks) ? blocks : []).map(function (block) {
if (!block || block.type !== 'CODE') return block
return Object.assign({}, block, {
_codeLines: self._splitCodeLines(block.rawText),
})
})
},
selectOption: function (e) {
if (this.data._animating || this.data.readonly || this.data.submitted) return
if (this.data._swipeTapLockUntil && Date.now() < this.data._swipeTapLockUntil) return
this.triggerEvent('selectoption', {
option: e.currentTarget.dataset.option,
question: this.data.currentQuestion,
index: this.data.currentIndex,
})
},
selectBlankOption: function (e) {
if (this.data._animating || this.data.readonly || this.data.submitted) return
if (this.data._swipeTapLockUntil && Date.now() < this.data._swipeTapLockUntil) return
this.triggerEvent('selectblankoption', {
blankId: e.currentTarget.dataset.blankId,
option: e.currentTarget.dataset.option,
question: this.data.currentQuestion,
index: this.data.currentIndex,
})
},
requestExit: function () {
this.triggerEvent('exit', {
answeredCount: this.data.answeredCount,
totalCount: this.data.totalCount,
currentIndex: this.data.currentIndex,
})
},
goPrev: function () {
if (this.data._animating || this.data.currentIndex <= 0 || this.data.prevDisabled) return
this._slideTo(this.data.currentIndex - 1, 'right')
},
goNext: function () {
if (this.data._animating || this.data.nextDisabled) return
if (this.data.currentIndex >= this.data.totalCount - 1) return
this._slideTo(this.data.currentIndex + 1, 'left')
},
goQuestion: function (e) {
var idx = parseInt(e.currentTarget.dataset.index, 10)
if (isNaN(idx) || idx < 0 || idx >= this.data.totalCount) return
if (idx === this.data.currentIndex) {
this.setData({ showSheet: false })
return
}
this.setData({ showSheet: false })
this.triggerEvent('jump', { index: idx })
},
_slideTo: function (nextIdx, dir) {
var self = this
if (this.data.externalSwitchAnimation) {
this.triggerEvent(dir === 'left' ? 'next' : 'prev', { index: nextIdx })
return
}
this.data._animating = true
this.setData({ animClass: dir === 'left' ? 'slide-out-left' : 'slide-out-right' })
setTimeout(function () {
self.triggerEvent(dir === 'left' ? 'next' : 'prev', { index: nextIdx })
self.setData({ animClass: 'slide-in' }, function () {
self.data._animating = false
})
setTimeout(function () {
self.setData({ animClass: '' })
}, 150)
}, 110)
},
onTouchStart: function (e) {
if (!this.data.swipeEnabled || this.data._animating) return
if (this.data.submitted) return
if (this.data.readonly && !this.data.allowSwipeInReadonly) return
var target = e && e.target ? e.target : {}
var dataset = target.dataset || {}
if (dataset.swipeBlock === true || dataset.swipeBlock === 'true' || dataset.swipeBlock === '1') {
this.data._swipeTapLockUntil = 0
this.data._touchX = undefined
this.data._touchY = undefined
return
}
var t = e.touches && e.touches[0]
if (!t) return
this.data._touchX = t.clientX
this.data._touchY = t.clientY
this.data._touchTime = Date.now()
},
onTouchEnd: function (e) {
if (!this.data.swipeEnabled || this.data._animating) return
if (this.data.submitted) return
if (this.data.readonly && !this.data.allowSwipeInReadonly) return
if (this.data._touchX === undefined) return
var t = e.changedTouches && e.changedTouches[0]
if (!t) return
var dx = t.clientX - this.data._touchX
var dy = t.clientY - this.data._touchY
var absDx = Math.abs(dx)
var absDy = Math.abs(dy)
if (absDx < 44 || absDx <= absDy * 1.10) {
this.data._touchX = undefined
this.data._touchY = undefined
return
}
this.data._touchX = undefined
this.data._touchY = undefined
this.data._swipeTapLockUntil = Date.now() + 100
if (dx < 0) this.goNext()
else this.goPrev()
},
onTouchCancel: function () {
this.data._touchX = undefined
this.data._touchY = undefined
},
onQuestionScroll: function (e) {
if (this.data.flowLayout || this.data.compactReviewMode) return
var top = e && e.detail ? Number(e.detail.scrollTop || 0) : 0
if (!isFinite(top) || top < 0) top = 0
this._lastQuestionScrollTop = top
if (this.data.heroCollapseEnabled === false) {
if (this.data.heroCollapsed) this.setData({ heroCollapsed: false })
return
}
var now = Date.now()
if (this.data.heroCollapsed) return
if (top > 34 && now >= this._heroCollapseLockUntil) {
this._heroCollapseLockUntil = now + 260
this.setData({ heroCollapsed: true })
}
},
_expandHero: function () {
if (!this.data.heroCollapsed) return
var self = this
this._heroCollapseLockUntil = Date.now() + 420
this._lastQuestionScrollTop = 0
this.setData({
heroCollapsed: false,
questionScrollIntoView: 'runner-scroll-top-anchor',
}, function () {
setTimeout(function () {
self.setData({ questionScrollIntoView: '' })
}, 0)
})
},
expandHero: function () {
this._expandHero()
},
toggleSheet: function () {
this.setData({ showSheet: !this.data.showSheet })
this.triggerEvent('toggleanswercard')
},
closeSheet: function () {
this.setData({ showSheet: false })
},
toggleMark: function () {
if (this.data.readonly || this.data.submitted) return
this.triggerEvent('togglemark', {
marked: !this.data.markedForReview,
question: this.data.currentQuestion,
index: this.data.currentIndex,
})
},
onMaster: function () {
if (this.data.readonly) return
this.triggerEvent('master', {
question: this.data.currentQuestion,
index: this.data.currentIndex,
})
},
onSubmit: function () {
if (this.data.submitting || this.data.submitDisabled) return
this.triggerEvent('submit', {
questions: this.data.questions,
currentIndex: this.data.currentIndex,
})
},
onRetry: function () {
this.triggerEvent('retry', {})
},
previewQuestionImage: function (e) {
var urls = this.data._questionImages
var src = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.src
if (!urls || !urls.length) return
wx.previewImage({ current: src || urls[0], urls: urls })
},
previewOptionImage: function (e) {
var src = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.src
if (!src) return
var cq = this.data.currentQuestion
var list = (cq && cq._optionList) || this.data._optionList
if (!Array.isArray(list)) { wx.previewImage({ current: src, urls: [src] }); return }
var seen = {}
var urls = []
for (var i = 0; i < list.length; i++) {
var segs = list[i]._segments
if (!Array.isArray(segs)) continue
for (var j = 0; j < segs.length; j++) {
var url = segs[j] && segs[j].url
if (url && !seen[url]) { seen[url] = true; urls.push(url) }
}
}
if (!urls.length) urls = [src]
wx.previewImage({ current: src, urls: urls })
},
noop: function () {},
},
})
