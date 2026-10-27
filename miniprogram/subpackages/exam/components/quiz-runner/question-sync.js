var appendRenderPatch = require('./question-render-patch')
var appendAnswerPatch = require('./question-answer-patch')
var commitQuestionView = require('./question-view-commit')

function syncQuestion(q, answerState, questionAdapter) {
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
    appendRenderPatch(this, q, model, data)
  }
  appendAnswerPatch(data, q, answerState, questionId, questionAdapter)
  commitQuestionView(this, data, shouldResetViewport, questionChanged)
}

module.exports = syncQuestion
