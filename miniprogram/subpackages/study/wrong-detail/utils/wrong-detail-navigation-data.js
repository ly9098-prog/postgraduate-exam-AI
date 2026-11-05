async function _prepareNavigationData(page, idx, navigationSeq, { fetchWrongQuestion, _processWqData, _resolvePreferredAnalysis, _normalizeAiResult }) {
    var questionIds = page.data.questionIds || []
    var wqId = Number(questionIds[idx])
    if (!wqId || idx < 0 || idx >= questionIds.length) return null
    var entry = page._wqCache && page._wqCache[wqId]
    var cached = entry && Date.now() - entry.ts < 300000 ? entry : null
    var wq = cached ? cached.data : await fetchWrongQuestion(wqId)
    if (!page._alive || navigationSeq !== page._navigationSeq) return null
    if (!wq) throw new Error('not found')
    if (!cached && page._wqCache) page._wqCache[wqId] = { data: wq, ts: Date.now() }
    const raw = _processWqData(wq, page.data.safeModeActive)
    const nextData = page._buildNavigateDataPatch(wq, raw, idx)
    var nextAiResult = null
    var preferredAnalysis = _resolvePreferredAnalysis(wq)
    if (preferredAnalysis) {
      nextAiResult = preferredAnalysis.normalized
      nextData.aiCards = _normalizeAiResult(nextAiResult)
      nextData.aiRequested = true
      nextData.aiFromCache = preferredAnalysis.source === 'ai'
      nextData.aiFromQuestionAnalysis = preferredAnalysis.source === 'question'
      nextData.aiFallback = false
      nextData.aiErrorText = ''
    }
    return { wqId, wq, raw, nextData, nextAiResult, navigationSeq }
  }

function _buildNavigateDataPatch(page, wq, raw, idx, { _isWqMastered, errorDiagnosis }) {
    const currentQuestion = Object.assign({}, wq, {
      _optionList: raw._optionList, _optionKeys: raw._optionKeys,
      _opts: raw._opts, _blankOptionGroups: raw._blankOptionGroups,
      _hasBlankOptionGroups: raw._hasBlankOptionGroups, _renderModel: raw._renderModel,
    })
    var totalQ = page.data.totalQuestions || 1
    var wrongQuestions = []
    for (var wi = 0; wi < totalQ; wi++) wrongQuestions.push({ _answered: true })
    return {
      wq, currentQuestion, wrongQuestions, currentIdx: idx,
      runnerProgressPercent: totalQ > 0 ? Math.round((idx + 1) / totalQ * 100) : 0,
      subjectLabelText: raw.subjectLabelText, aiLoading: false, aiRegenerating: false,
      aiCards: null, aiRequested: false, aiFromCache: false, aiFromQuestionAnalysis: false,
      aiFallback: false, aiErrorText: '', aiRetryable: true,
      aiSkeletonVisible: false, aiInlineNotice: '',
      isCurrentMastered: _isWqMastered(wq), masterSubmitting: false, removeSubmitting: false,
      errorDiagnosis: errorDiagnosis.normalizeDiagnosis(wq.error_diagnosis),
      nextErrorAction: errorDiagnosis.buildNextAction(wq, errorDiagnosis.normalizeDiagnosis(wq.error_diagnosis)),
      diagnosisSheetVisible: false, diagnosisSaving: false, diagnosisSyncing: false,
      teacherLoadingAction: '', teacherLastAction: '', teacherResult: null,
      teacherSheetVisible: false, teacherErrorText: '', teacherFeedbackSent: '',
      teacherActionsExpanded: false,
    }
  }

module.exports = { _prepareNavigationData, _buildNavigateDataPatch }
