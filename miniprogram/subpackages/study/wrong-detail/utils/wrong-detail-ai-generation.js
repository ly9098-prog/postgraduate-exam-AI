async function loadAiAnalysis(page, wqId, { _generationMarker }) {
    if (!wqId || page.data.aiLoading) return
    const baselineGeneratedAt = String(page._aiGenerationMarker || _generationMarker(page.data.wq) || '')
    const requestId = ++page._aiRequestId
    page.setData({
      aiLoading: true, aiRequested: true, aiFallback: false,
      aiErrorText: '', aiRetryable: true, aiInlineNotice: '',
    })
    try {
      const result = await page._requestAiAnalysis(wqId, false)
      if (!page._isCurrentAiRequest(requestId, wqId)) return
      await page._applyAiAnalysisResult(result, wqId, requestId, baselineGeneratedAt)
    } catch (e) {
      await page._handleAiAnalysisError(e, wqId, requestId, baselineGeneratedAt)
    }
  }

async function _applyAiAnalysisResult(page, result, wqId, requestId, baselineGeneratedAt, { _normalizeAiPayload, _hasAiContent }) {
    if (!page._isCurrentAiRequest(requestId, wqId)) return
    const normalized = _normalizeAiPayload(result)
    if (result && result.availability && page._applyAiAvailability) {
      page._applyAiAvailability(result.availability)
    }
    const hasContent = _hasAiContent(normalized)
    const model = (result && result.model) || ''
    const fromFallback = !!(result && result.from_fallback)
    if (model === 'generating') {
      const recovered = await page._pollPersistedAiAnalysis(wqId, requestId, {
        requireNewGeneration: true, baselineGeneratedAt,
      })
      if (!page._isCurrentAiRequest(requestId, wqId)) return
      if (page._applyRecoveredAiResult(recovered)) return
      page._resetAiLoadingState()
      page.setData({ aiFallback: true, aiErrorText: 'AI 分析正在生成中，请稍后重试' })
      return
    }
    if (fromFallback) {
      page._resetAiLoadingState()
      page.setData(Object.assign({ aiFallback: true }, page._analysisFailureState(model, result)))
      _refreshAvailabilityAfterFailure(page, !!(result && result.availability))
      return
    }
    if (!hasContent) {
      page._resetAiLoadingState()
      page.setData({ aiFallback: true, aiErrorText: 'AI 分析结果为空，请稍后重试' })
      return
    }
    page._commitAiAnalysisSuccess(result, normalized, wqId)
  }

function _commitAiAnalysisSuccess(page, result, normalized, wqId, { _normalizeAiResult }) {
    page._resetAiLoadingState()
    page._aiResult = normalized
    page._aiGenerationMarker = String((result && result.generated_at) || page._aiGenerationMarker || '')
    page._syncWqCacheAi(wqId, normalized, page._aiGenerationMarker)
    page.setData({
      aiCards: _normalizeAiResult(normalized), aiFallback: false,
      aiFromCache: !!(result && result.from_cache), aiFromQuestionAnalysis: false,
      aiErrorText: '', aiRetryable: true,
    })
  }

async function _handleAiAnalysisError(page, e, wqId, requestId, baselineGeneratedAt, { _isTimeoutError, _shouldRecoverAiRequest }) {
    console.error('加载 AI 分析失败', e)
    if (!page._isCurrentAiRequest(requestId, wqId)) return
    const availability = _applyAvailabilityFromError(page, e)
    if (page._isCurrentAiRequest(requestId, wqId) && _shouldRecoverAiRequest(e)) {
      page.setData({ aiInlineNotice: 'AI 正在继续生成，完成后会自动显示' })
      page._enqueueAiRecovery(wqId, false, '')
      const recovered = await page._pollPersistedAiAnalysis(wqId, requestId, {
        requireNewGeneration: true, baselineGeneratedAt,
      })
      if (!page._isCurrentAiRequest(requestId, wqId)) return
      if (page._applyRecoveredAiResult(recovered)) return
    }
    if (page._isCurrentAiRequest(requestId, wqId)) {
      page._resetAiLoadingState()
      page.setData(Object.assign({ aiFallback: true },
        page._analysisFailureState(_isTimeoutError(e) ? 'timeout' : '', e)))
      _refreshAvailabilityAfterFailure(page, availability)
    }
  }

function _applyAvailabilityFromError(page, error) {
    if (!page._availabilityFromAiError) return null
    const availability = page._availabilityFromAiError(error)
    if (availability && page._applyAiAvailability) page._applyAiAvailability(availability)
    return availability
}

function _refreshAvailabilityAfterFailure(page, handled) {
    if (handled) return
    if (page._refreshAiAvailability) page._refreshAiAvailability({ force: true, silent: true })
}

module.exports = { loadAiAnalysis, _applyAiAnalysisResult, _commitAiAnalysisSuccess, _handleAiAnalysisError }
