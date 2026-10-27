
var codeBlockRender = require('../../utils/code-block-render')
var questionAdapter = null
try {
questionAdapter = require('../../utils/question-runner-adapter')
} catch (e) {
}
var syncQuestion = require('./question-sync')
var navigationMethods = require('./navigation-methods')
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
return syncQuestion.call(this, q, answerState, questionAdapter)
},
},
methods: Object.assign({
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
}, navigationMethods, {
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
onPrimaryNavigation: function () {
if (this.data._animating || this.data.submitted || this.data.submitting || this.data.totalCount <= 0) return
if (this.data.currentIndex >= this.data.totalCount - 1) {
this.onSubmit()
return
}
if (this.data.nextDisabled) return
this.goNext()
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
}),
})
