
var codeBlockRender = require('../../utils/code-block-render')
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
navigationBarHeight: { type: Number, value: 44 },
swipeEnabled: { type: Boolean, value: true },
swipeThroughOptions: { type: Boolean, value: false },
allowSwipeInReadonly: { type: Boolean, value: false },
compactReviewMode: { type: Boolean, value: false },
externalSwitchAnimation: { type: Boolean, value: false },
flowLayout: { type: Boolean, value: false },
compactBottom: { type: Boolean, value: false },
loading: { type: Boolean, value: false },
errorText: { type: String, value: '' },
emptyText: { type: String, value: '' },
renderErrorText: { type: String, value: '' },
},
data: {
showSheet: false,
questionScrollIntoView: '',
animClass: '',
questionDirection: 'left',
_displayQuestion: null,
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
_isMultiBlankMultiple: false,
_renderUnknownMode: false,
_renderFallbackText: '',
},
created: function () {
this._lastRenderModel = null
this._lastQuestionId = null
this._hasRenderedQuestion = false
this._lastQuestionScrollTop = 0
this._switchTargetIndex = null
this._switchDirection = 'left'
this._switchPhase = ''
this._switchTimer = null
this._viewportResetTimer = null
this._switchFallbackTimer = null
this._detached = false
},
lifetimes: {
detached: function () {
this._detached = true
clearTimeout(this._switchTimer)
clearTimeout(this._switchFallbackTimer)
clearTimeout(this._viewportResetTimer)
},
},
observers: {
'currentQuestion, answerState': function (q, answerState) {
if (!q) {
this.setData({ _displayQuestion: null, _qTypeLabel: '', _codeLines: [], _mixedBlocks: [], _questionImages: [], _optionList: [], _blankOptionGroups: [], _hasBlankOptionGroups: false, _isMultiBlankMultiple: false, _renderUnknownMode: false, _renderFallbackText: '' })
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
var data = { _displayQuestion: q }
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
data._isMultiBlankMultiple = q.question_type === 'multi_blank_multiple_choice'
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
// Render from a local snapshot, never directly from the incoming property.
// This keeps the stem, options and motion in the same view-layer commit.
var resetViewport = shouldResetViewport && !this.data.flowLayout && !this.data.compactReviewMode && Number(this._lastQuestionScrollTop || 0) > 1
if (resetViewport) {
this._lastQuestionScrollTop = 0
data.questionScrollIntoView = 'runner-scroll-top-anchor'
}
var switching = questionChanged && this._switchTargetIndex !== null
if (switching) {
clearTimeout(this._switchFallbackTimer)
this._switchTargetIndex = null
this._switchPhase = 'enter'
data.animClass = this._switchDirection === 'left' ? 'slide-in-left' : 'slide-in-right'
}
var self = this
this.setData(data, function () {
if (self._detached) return
if (resetViewport) {
clearTimeout(self._viewportResetTimer)
self._viewportResetTimer = setTimeout(function () {
if (!self._detached) self.setData({ questionScrollIntoView: '' })
}, 0)
}
if (switching && self._switchPhase === 'enter') {
self._switchTimer = setTimeout(function () { self._finishQuestionSwitch() }, 300)
}
})
},
},
methods: {
_typeLabel: function (q) {
if (!q) return ''
if (q._hasBlankOptionGroups || q.question_type === 'multi_blank_choice') return '多空（单选）选择题'
if (q.question_type === 'multi_blank_multiple_choice') return '多空（多选）选择题'
if (q.question_type === 'multiple_choice') return '多选题'
if (q.question_type === 'true_false' || q.question_type === 'judgement') return '判断题'
return '单选题'
},
_splitCodeLines: function (value) {
return codeBlockRender.splitCodeLines(value)
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
if (this.data._animating) return
var idx = parseInt(e.currentTarget.dataset.index, 10)
if (isNaN(idx) || idx < 0 || idx >= this.data.totalCount) return
if (idx === this.data.currentIndex) {
this.setData({ showSheet: false })
return
}
this.setData({ showSheet: false })
this._slideTo(idx, idx > this.data.currentIndex ? 'left' : 'right', 'jump')
},
onQuestionAnimationEnd: function (e) {
var name = e && e.detail && e.detail.animationName
if (this._switchPhase === 'enter' && (name === 'runnerQuestionInLeft' || name === 'runnerQuestionInRight')) {
this._finishQuestionSwitch()
}
},
_finishQuestionSwitch: function () {
this._switchPhase = ''
clearTimeout(this._switchTimer)
clearTimeout(this._switchFallbackTimer)
this._switchTargetIndex = null
if (this._detached) return
this.setData({ animClass: '', _animating: false })
},
_slideTo: function (nextIdx, dir, eventName) {
if (this.data._animating) return
var event = eventName || (dir === 'left' ? 'next' : 'prev')
// Compact review and parents with their own animation keep their existing flow.
if (this.data.externalSwitchAnimation || this.data.compactReviewMode ||
(this.data.mode !== 'practice' && this.data.mode !== 'review' && this.data.mode !== 'exam')) {
this.triggerEvent(event, { index: nextIdx })
return
}
var self = this
this._switchTargetIndex = nextIdx
this._switchDirection = dir
this._switchPhase = 'exit'
this.setData({ _animating: true, animClass: 'question-fade-out', questionDirection: dir }, function () {
if (self._detached) return
self._switchTimer = setTimeout(function () {
if (self._detached) return
// Recover visibility and unlock input if a parent rejects the switch.
self._switchFallbackTimer = setTimeout(function () { self._finishQuestionSwitch() }, 800)
self.triggerEvent(event, { index: nextIdx })
}, 100)
})
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
},
toggleSheet: function () {
this.setData({ showSheet: !this.data.showSheet })
this.triggerEvent('toggleanswercard')
},
closeSheet: function () {
this.setData({ showSheet: false })
},
toggleMark: function () {
if (this.data._animating || this.data.readonly || this.data.submitted) return
this.triggerEvent('togglemark', {
marked: !this.data.markedForReview,
question: this.data.currentQuestion,
index: this.data.currentIndex,
})
},
onMaster: function () {
if (this.data._animating || this.data.readonly || this.data.submitted) return
this.triggerEvent('master', {
question: this.data.currentQuestion,
index: this.data.currentIndex,
})
},
onSubmit: function () {
if (this.data._animating || this.data.submitted || this.data.submitting || this.data.submitDisabled || this.data.totalCount <= 0) return
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
