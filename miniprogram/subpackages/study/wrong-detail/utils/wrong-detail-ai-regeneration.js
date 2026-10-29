async function regenerateAiAnalysis(page, { _generationMarker }) {
    const wqId = page._currentWqId || (page.data.wq && page.data.wq.id)
    if (!wqId || page.data.aiLoading || page.data.aiRegenerating) return
    const oldCards = page.data.aiCards
    const oldResult = page._aiResult
    const baselineGeneratedAt = String(page._aiGenerationMarker || _generationMarker(page.data.wq) || '')
    const requestId = ++page._aiRequestId
    page.setData({
      aiRegenerating: true, aiSkeletonVisible: true, aiErrorText: '',
      aiRetryable: true, aiFallback: false, aiInlineNotice: '',
    })
    try {
      const result = await page._requestAiAnalysis(wqId, true)
      if (!page._isCurrentAiRequest(requestId, wqId)) { page._resetAiLoadingState(); return }
      await page._applyRegenerateResult(result, wqId, requestId, baselineGeneratedAt, oldCards, oldResult)
    } catch (e) {
      page._handleRegenerateError(e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult)
    }
  }

async function _applyRegenerateResult(page, result, wqId, requestId, baselineGeneratedAt, oldCards, oldResult, { _normalizeAiPayload, _hasAiContent }) {
    const normalized = _normalizeAiPayload(result)
    const hasContent = _hasAiContent(normalized)
    const model = (result && result.model) || ''
    const fromFallback = !!(result && result.from_fallback)
    const cachePreserved = !!(result && result.cache_preserved)
    if (model === 'generating') {
      await page._handleRegeneratingModel(wqId, requestId, baselineGeneratedAt)
      return
    }
    if (cachePreserved && hasContent) {
      page._commitRegenerateCachePreserved(result, normalized, wqId, baselineGeneratedAt)
      return
    }
    if (fromFallback) {
      page._handleRegenerateFallback(model, result, oldCards)
      return
    }
    if (!hasContent) {
      page._handleRegenerateEmpty(oldCards)
      return
    }
    page._commitRegenerateSuccess(result, normalized, wqId)
  }

async function _handleRegeneratingModel(page, wqId, requestId, baselineGeneratedAt, { showToast }) {
    page.setData({ aiInlineNotice: 'AI 正在生成中，完成后会自动更新' })
    const recovered = await page._pollPersistedAiAnalysis(wqId, requestId, {
      requireNewGeneration: true, baselineGeneratedAt,
    })
    if (page._applyRecoveredAiResult(recovered, { fromRegeneration: true })) {
      showToast({ title: '已重新生成', icon: 'success' })
      return
    }
    if (!page._isCurrentAiRequest(requestId, wqId)) return
    page._resetAiLoadingState()
    page.setData({ aiInlineNotice: 'AI 正在生成中，请稍后重试' })
  }

function _commitRegenerateCachePreserved(page, result, normalized, wqId, baselineGeneratedAt, { _normalizeAiResult, showToast }) {
    page._resetAiLoadingState()
    page._aiResult = normalized
    page._aiGenerationMarker = String((result && result.generated_at) || baselineGeneratedAt || '')
    page._syncWqCacheAi(wqId, normalized, page._aiGenerationMarker)
    page.setData({
      aiCards: _normalizeAiResult(normalized), aiFallback: false, aiFromCache: true,
      aiFromQuestionAnalysis: false, aiInlineNotice: '重新生成失败，已保留历史解析',
    })
    showToast({ title: '重新生成失败，已保留历史解析', icon: 'none' })
  }

function _handleRegenerateFallback(page, model, result, oldCards, { showToast }) {
    page._resetAiLoadingState()
    var failure = page._analysisFailureState(model, result)
    if (oldCards) {
      page.setData({ aiFallback: false, aiInlineNotice: failure.aiErrorText || '重新生成失败，已保留当前解析' })
      showToast({ title: '重新生成失败，已保留当前解析', icon: 'none' })
    } else {
      page.setData(Object.assign({ aiFallback: true }, failure))
    }
  }

function _handleRegenerateEmpty(page, oldCards, { showToast }) {
    if (oldCards) {
      page._resetAiLoadingState()
      page.setData({ aiFallback: false, aiInlineNotice: '返回内容为空，已保留当前解析' })
      showToast({ title: '返回内容为空，已保留当前解析', icon: 'none' })
    } else {
      page._resetAiLoadingState()
      page.setData({ aiFallback: true, aiErrorText: 'AI 返回内容为空，请稍后重试' })
    }
  }

function _commitRegenerateSuccess(page, result, normalized, wqId, { _normalizeAiResult, showToast }) {
    page._resetAiLoadingState()
    page._aiResult = normalized
    page._aiGenerationMarker = String((result && result.generated_at) || page._aiGenerationMarker || '')
    page._syncWqCacheAi(wqId, normalized, page._aiGenerationMarker)
    page.setData({
      aiCards: _normalizeAiResult(normalized), aiFallback: false,
      aiFromCache: !!(result && result.from_cache), aiFromQuestionAnalysis: false,
      aiErrorText: '', aiRetryable: true,
    })
    showToast({ title: '已重新生成', icon: 'success' })
  }

function _handleRegenerateError(page, e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult) {
    console.error('重新生成 AI 分析失败', e)
    if (page._isCurrentAiRequest(requestId, wqId)) {
      page._handleRegenerateRecovery(e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult)
      return
    }
  }

async function _handleRegenerateRecovery(page, e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult, { showToast }) {
    page.setData({ aiInlineNotice: 'AI 正在继续重新生成，完成后会自动更新' })
    page._enqueueAiRecovery(wqId, true, baselineGeneratedAt)
    const recovered = await page._pollPersistedAiAnalysis(wqId, requestId, {
      requireNewGeneration: true, baselineGeneratedAt,
    })
    if (page._applyRecoveredAiResult(recovered, { fromRegeneration: true })) {
      showToast({ title: '已重新生成', icon: 'success' })
      return
    }
    if (page._isCurrentAiRequest(requestId, wqId)) {
      page._handleRegenerateTimeout(e, oldCards, oldResult)
    }
  }

function _handleRegenerateTimeout(page, e, oldCards, oldResult, { _isTimeoutError, showToast }) {
    const timeoutText = _isTimeoutError(e) ? '重新生成超时' : '重新生成失败'
    if (oldCards) {
      page._resetAiLoadingState()
      page._aiResult = oldResult
      page.setData({ aiCards: oldCards, aiFallback: false, aiInlineNotice: `${timeoutText}，已保留历史解析` })
      showToast({ title: `${timeoutText}，已保留历史解析`, icon: 'none' })
    } else {
      page._resetAiLoadingState()
      page.setData({ aiErrorText: `${timeoutText}，请稍后重试` })
      showToast({ title: timeoutText, icon: 'none' })
    }
  }

module.exports = { regenerateAiAnalysis, _applyRegenerateResult, _handleRegeneratingModel, _commitRegenerateCachePreserved, _handleRegenerateFallback, _handleRegenerateEmpty, _commitRegenerateSuccess, _handleRegenerateError, _handleRegenerateRecovery, _handleRegenerateTimeout }
