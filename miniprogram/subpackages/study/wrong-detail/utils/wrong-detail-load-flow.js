async function loadData(page, wqId, { requestClient }) {
    var loadSeq = ++page._aiRequestId
    page._resetAiLoadingState()
    page._aiResult = null
    page.setData(page._loadDataInitialPatch())
    page._diagnosisRequestSeq++
    page._teacherRequestSeq++
    try {
      const wq = await requestClient.get(`/wrong-questions/${wqId}`)
      if (loadSeq !== page._aiRequestId || !page._alive) return
      if (!wq) throw new Error('not found')
      if (page._wqCache) page._wqCache[wqId] = { data: wq, ts: Date.now() }
      const data = page._buildLoadedDataPatch(wq, wqId, loadSeq)
      if (!data) return
      page.setData(data)
      page._refreshDiagnosisFromServer(wqId, wq.error_diagnosis)
      if (page._refreshAiAvailability) page._refreshAiAvailability({ force: true })
      page._checkLoadedRenderInvariant(data)
    } catch (e) {
      page._handleLoadDataError(e, loadSeq)
    }
  }

function _loadDataInitialPatch() {
    return {
      loading: true, errorText: '', aiFallback: false, aiErrorText: '',
      aiRetryable: true, aiRequested: false, aiFromCache: false,
      aiFromQuestionAnalysis: false, masterConfirmVisible: false,
      unmasterConfirmVisible: false, moreMenuVisible: false,
      removeConfirmVisible: false, masterSubmitting: false,
      removeSubmitting: false, diagnosisSheetVisible: false,
      diagnosisSaving: false, diagnosisSyncing: false,
    }
  }

function _buildLoadedDataPatch(page, wq, wqId, loadSeq, { _processWqData, _generationMarker }) {
    const raw = _processWqData(wq, page.data.safeModeActive)
    const currentQuestion = Object.assign({}, wq, {
      _optionList: raw._optionList, _optionKeys: raw._optionKeys,
      _opts: raw._opts, _blankOptionGroups: raw._blankOptionGroups,
      _hasBlankOptionGroups: raw._hasBlankOptionGroups, _renderModel: raw._renderModel,
    })
    var totalQ = page.data.totalQuestions || 1
    var wrongQuestions = []
    for (var wi = 0; wi < totalQ; wi++) wrongQuestions.push({ _answered: true })
    page._currentWqId = wqId
    page._diagnosisRequestSeq++
    page._teacherRequestSeq++
    page._errorTypeLabelText = raw.errorTypeLabelText
    page._aiGenerationMarker = _generationMarker(wq)
    page._aiResult = null
    var data = page._buildLoadedDataFields(wq, currentQuestion, wrongQuestions, raw, totalQ)
    page._applyPreferredAnalysisToData(data, wq)
    if (loadSeq !== page._aiRequestId || !page._alive) return null
    return data
  }

function _buildLoadedDataFields(page, wq, currentQuestion, wrongQuestions, raw, totalQ, { _isWqMastered, errorDiagnosis }) {
    return {
      wq, currentQuestion, wrongQuestions,
      runnerProgressPercent: totalQ > 0 ? Math.round((page.data.currentIdx + 1) / totalQ * 100) : 0,
      subjectLabelText: raw.subjectLabelText, loading: false, aiLoading: false,
      errorText: '', aiCards: null, aiRequested: false, aiFromCache: false,
      aiFromQuestionAnalysis: false, aiFallback: false, aiErrorText: '', aiRetryable: true,
      isCurrentMastered: _isWqMastered(wq), masterSubmitting: false, removeSubmitting: false,
      errorDiagnosis: errorDiagnosis.normalizeDiagnosis(wq.error_diagnosis),
      nextErrorAction: errorDiagnosis.buildNextAction(wq, errorDiagnosis.normalizeDiagnosis(wq.error_diagnosis)),
      diagnosisSyncing: false, teacherLoadingAction: '', teacherLastAction: '',
      teacherResult: null, teacherSheetVisible: false, teacherErrorText: '',
      teacherFeedbackSent: '', teacherActionsExpanded: false,
      aiAvailabilityChecking: true, aiAvailabilityEnabled: false,
      aiAvailabilityStatus: 'checking', aiAvailabilityReason: 'checking',
      aiAvailabilityMessage: '正在检查 AI 服务',
    }
  }

function _applyPreferredAnalysisToData(page, data, wq, { _resolvePreferredAnalysis, _hasAiContent, _normalizeAiResult }) {
    var preferredAnalysis = _resolvePreferredAnalysis(wq)
    if (!preferredAnalysis) return
    var preferredNormalized = preferredAnalysis.normalized
    data.aiRequested = true
    if (_hasAiContent(preferredNormalized)) {
      page._aiResult = preferredNormalized
      data.aiCards = _normalizeAiResult(page._aiResult)
      data.aiFromCache = preferredAnalysis.source === 'ai'
      data.aiFromQuestionAnalysis = preferredAnalysis.source === 'question'
      data.aiFallback = false
      data.aiErrorText = ''
    } else {
      page._aiResult = null
      data.aiCards = null
      data.aiFromCache = false
      data.aiFromQuestionAnalysis = false
      data.aiFallback = true
      data.aiErrorText = preferredNormalized && preferredNormalized.formatError
        ? 'AI 返回格式异常，请重新生成' : 'AI 分析结果为空，请重新生成'
    }
  }

function _checkLoadedRenderInvariant(page, data) {
    const checkModel = data.currentQuestion && data.currentQuestion._renderModel
    if (checkModel) {
      page._checkRenderInvariant(checkModel)
      page._recordRenderTrace(checkModel.renderTrace)
    }
  }

function _handleLoadDataError(page, e, loadSeq) {
    if (loadSeq !== page._aiRequestId || !page._alive) return
    console.error('加载错题详情失败', e)
    page._aiResult = null
    page.setData({
      loading: false, errorText: '错题不存在或已被移除', wq: null,
      aiLoading: false, aiFallback: false,
    })
  }

function _prefetchWrongQuestion(page, idx, { requestClient }) {
if (idx < 0 || idx >= page.data.questionIds.length) return
var wqId = page.data.questionIds[idx]
if (!wqId) return
var cached = page._wqCache[wqId]
if (cached && Date.now() - cached.ts < 300000) return
var requestStartedAt = Date.now()
var self = page
requestClient.get(`/wrong-questions/${wqId}`).then(function(wq) {
if (!wq || !self._alive || !self._wqCache) return
var latest = self._wqCache[wqId]
if (latest && Number(latest.ts || 0) >= requestStartedAt) return
self._wqCache[wqId] = { data: wq, ts: Date.now() }
}).catch(function() {})
}

module.exports = { loadData, _loadDataInitialPatch, _buildLoadedDataPatch, _buildLoadedDataFields, _applyPreferredAnalysisToData, _checkLoadedRenderInvariant, _handleLoadDataError, _prefetchWrongQuestion }
