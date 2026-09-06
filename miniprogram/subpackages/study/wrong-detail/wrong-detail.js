const api = require('../../../utils/api')
const config = require('../../../config')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage
} = require('../utils/stem-render')
const { isTrueFalseType } = require('../utils/answer')
const adapter = require('../utils/question-runner-adapter')
const { normalizeAiAnalysisPayload, hasAiAnalysisContent } = require('../utils/ai-analysis-normalizer')
const { buildAiRichText } = require('../utils/ai-math-render')

// wx.request cannot hold one request open for the backend's full 150s AI
// provider budget. Keep each transport attempt safely below the platform's
// ~60s ceiling, then recover through persisted-result polling. The backend may
// continue the original generation and a recovery task is queued as a backup.
const AI_REQUEST_TIMEOUT_MS = 55000
const AI_CACHE_POLL_INTERVAL_MS = 3000
const AI_CACHE_POLL_ATTEMPTS = 60
const QUESTION_SWITCH_OUT_MS = 150
const QUESTION_SWITCH_IN_MS = 170
const QUESTION_SWITCH_WATCHDOG_MS = 35000
const QUESTION_SWITCH_ANIM_WATCHDOG_MS = 5000

function _sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function _isTimeoutError(err) {
  const message = [
    err && err.message,
    err && err.raw && err.raw.errMsg,
  ].filter(Boolean).join(' ').toLowerCase()
  return message.includes('timeout') || message.includes('timed out')
}

function _generationMarker(wq) {
  return String((wq && wq.ai_analysis_generated_at) || '')
}

function _fallbackMessage(model, errorCode, retryable) {
  if (errorCode === 'ai_provider_auth_failed') return 'AI 分析服务鉴权失败，请联系管理员检查模型 API Key'
  if (errorCode === 'ai_model_unconfigured') return 'AI 分析模型尚未正确配置，请联系管理员检查模型设置'
  if (errorCode === 'ai_provider_rate_limited') return 'AI 服务当前繁忙，请稍后重试'
  if (errorCode === 'ai_provider_timeout') return 'AI 分析生成超时，请稍后重试'
  if (errorCode === 'ai_provider_transient') return 'AI 服务暂时不可用，请稍后重试'
  if (errorCode === 'ai_response_parse_failed') return 'AI 返回格式异常，请重新生成'
  if (model === 'timeout') return 'AI 分析生成超时，请稍后重试'
  if (model === 'parse_failed') return 'AI 返回格式异常，请重新生成'
  if (model === 'vision_input_missing') return '题目图片缺失或无法读取，AI 解析失败'
  if (model === 'vision_unavailable') return '当前 AI 分析模型暂不支持图片理解，请稍后重试或联系管理员检查分析模型配置'
  if (model === 'vision_parse_failed') return 'AI 未能正确读取题目图片，解析失败，请稍后重试'
  if (retryable === false) return 'AI 服务配置异常，请联系管理员检查模型设置'
  return 'AI 服务暂时不可用，请稍后重试'
}

function _subjectLabel(s) {
  const { getSubjectName } = require('../../../utils/subject-meta')
  return getSubjectName(s)
}

function _errorTypeLabel(t) {
  const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
  return map[t] || t
}

function _processWqData(wq, safeMode) {
  const questionType = wq.question_type || wq.type || ''
  let opts = wq.options || null
  if ((!opts || Object.keys(opts).length === 0) && isTrueFalseType(questionType)) {
    opts = { A: '正确', B: '错误' }
  }
  const optionKeys = opts ? Object.keys(opts) : []
  var renderCfg = { enableMathImage: false, DEV: config.DEV }
  if (safeMode) renderCfg.SAFE_MODE = true
  const _renderModel = buildRenderModel(wq, opts, renderCfg)

  // Build readonly option list with correct/wrong highlighting
  const _optionList = adapter.buildOptionListReadonly(wq, opts, optionKeys, wq.answer, wq.wrong_answer)
  const blankOptionGroups = adapter.enrichBlankOptionGroupsReadonly(
    adapter.getBlankOptionGroups(wq), wq.answer, wq.wrong_answer
  )

  return {
    wq,
    _optionList,
    _optionKeys: optionKeys,
    _opts: opts,
    _blankOptionGroups: blankOptionGroups,
    _hasBlankOptionGroups: blankOptionGroups.length > 0,
    _renderModel,
    subjectLabelText: wq.subject_name || _subjectLabel(wq.subject_code),
    errorTypeLabelText: _errorTypeLabel(wq.error_type),
  }
}

function _buildAiRichText(value) {
  return buildAiRichText(value)
}

function _normalizeAiResult(content) {
  const diagnosis = content.mistake_diagnosis || content.error_analysis || ''
  const knowledge = content.knowledge_patch || content.knowledge_weakness || ''
  const task = content.review_task || content.suggestion || ''
  return {
    mistakeDiagnosis: _buildAiRichText(String(diagnosis).replace(/^错因诊断[：:]\s*/, '')),
    knowledgePatch: _buildAiRichText(String(knowledge).replace(/^补漏重点[：:]\s*/, '')),
    reviewTask: _buildAiRichText(String(task).replace(/^复练任务[：:]\s*/, '')),
    formatError: !!(content && content.formatError),
  }
}

function _normalizeAiPayload(result) {
  if (!result) return null
  return normalizeAiAnalysisPayload(result)
}

function _hasAiContent(content) {
  return hasAiAnalysisContent(content)
}

function _hasStoredAnalysisValue(raw) {
  if (raw === null || raw === undefined) return false
  if (typeof raw === 'string') {
    const t = raw.trim()
    if (!t) return false
    // 拒绝 JSON 字面量/空结构残留，避免 "null"/"false"/"0"/"[]"/"{}" 被当作已存储分析
    if (/^(null|true|false|undefined|\[\]|\{\}|-?\d+(?:\.\d+)?)$/i.test(t)) return false
    return true
  }
  if (Array.isArray(raw)) return raw.length > 0
  if (typeof raw === 'object') {
    if (Object.keys(raw).length === 0) return false
    // 对象必须有可消费的 AI 分析内容，避免 {error:...} 等包装被误判为已存储
    return hasAiAnalysisContent(normalizeAiAnalysisPayload(raw))
  }
  return true
}

function _detectAiCache(wq) {
  if (!wq) return false
  // New backend versions explicitly mark stale AI caches. Never recover or
  // render one merely because the historical JSON column is non-empty.
  if (wq.ai_analysis_status && wq.ai_analysis_status !== 'ready') return false
  return _hasStoredAnalysisValue(wq.ai_analysis)
}

function _resolvePreferredAnalysis(wq) {
  if (!wq) return null

  // 同一区域只选择一个来源：wrong_questions.ai_analysis 非空时优先，
  // 否则回退到 questions.analysis。两个来源都走同一套标准化/富文本渲染。
  if ((!wq.ai_analysis_status || wq.ai_analysis_status === 'ready') && _hasStoredAnalysisValue(wq.ai_analysis)) {
    return {
      normalized: _normalizeAiPayload(wq.ai_analysis),
      source: 'ai',
    }
  }
  if (_hasStoredAnalysisValue(wq.analysis)) {
    return {
      normalized: _normalizeAiPayload(wq.analysis),
      source: 'question',
    }
  }
  return null
}

function _isWqMastered(wq) {
  if (!wq) return false
  return wq.is_mastered === true ||
    wq.mastered === true ||
    wq.review_status === 'mastered' ||
    wq.status === 'mastered'
}


Page({
  data: {
    wq: null,
    aiLoading: false,
    aiFallback: false,
    aiErrorText: '',
    aiRetryable: true,
    aiRequested: false,
    aiFromCache: false,
    loading: true,
    errorText: '',
    questionIds: [],
    currentIdx: 0,
    totalQuestions: 0,
    safeModeActive: false,
    aiCards: null,
    aiFromQuestionAnalysis: false,
    aiRegenerating: false,
    aiSkeletonVisible: false,
    aiInlineNotice: '',
    contentTransitionClass: '',
    showSwitchMask: false,
    renderTraces: [],

    masterConfirmVisible: false,
    unmasterConfirmVisible: false,
    masterSubmitting: false,
    isCurrentMastered: false,
    masterUndoVisible: false,
    moreMenuVisible: false,
    removeConfirmVisible: false,
    removeSubmitting: false,

    // quiz-runner data
    currentQuestion: null,
    wrongQuestions: [],
    runnerProgressPercent: 0,
    skeletonOptions: [1, 2, 3, 4],
    aiSkeletonSections: [1, 2, 3],
  },

  _alive: false,
  _aiRequestId: 0,
  _currentWqId: null,
  _switching: false,
  _navigationSeq: 0,
  _aiResult: null,
  _errorTypeLabelText: '',
  _aiSwipeStart: null,
  _contentTransitionStartedAt: 0,
  _contentTransitionDirection: '',

  onLoad(options) {
    setRenderGuardPage('wrong-detail')
    this._alive = true
    this._aiRequestId = 0
    this._currentWqId = null
    this._aiGenerationMarker = ''
    this._switching = false
    this._navigationSeq = 0
    this._aiSwipeStart = null
    this._contentTransitionStartedAt = 0
    this._contentTransitionDirection = ''
    // 页面实例级缓存仅用于状态同步/弱网兜底；前台切题始终向服务端校验最新题库内容
    this._wqCache = {}
    this._switchMaskTimer = null
    this._contentTransitionTimer = null
    this._switchWatchdogTimer = null
    this._masterUndoTimer = null
    this._masterAdvanceTimer = null
    this._removeBackTimer = null
    this._masterUndoInFlight = false
    this._pendingMasterUndo = null
    const currentId = Number(options.id)
    if (!Number.isFinite(currentId) || currentId <= 0) {
      this.setData({ loading: false, errorText: '错题ID无效', wq: null })
      return
    }
    let questionIds = []
    try {
      if (options.source === 'wrong-book' || options.source === 'practice-result') {
        const nav = wx.getStorageSync('wrong_detail_nav')
        if (nav && Array.isArray(nav.ids) && Date.now() - Number(nav.ts || 0) < 30 * 60 * 1000) {
          const normalized = nav.ids.map(Number).filter(Number.isFinite)
          // New navigation contexts carry their source to avoid accidentally
          // reusing a stale group from another entry point. Legacy wrong-book
          // contexts have no source and remain backward compatible.
          const sourceMatches = !nav.source || nav.source === options.source
          if (sourceMatches && normalized.includes(currentId)) questionIds = normalized
        }
      }
    } catch (_) {}
    if (!questionIds.length) questionIds = [currentId]
    const currentIdx = questionIds.indexOf(currentId)
    this.setData({
      questionIds,
      currentIdx: currentIdx >= 0 ? currentIdx : 0,
      totalQuestions: questionIds.length,
    })
    this.loadData(currentId)
  },

  onUnload() {
    this._alive = false
    this._aiRequestId++
    if (this._switchMaskTimer) {
      clearTimeout(this._switchMaskTimer)
      this._switchMaskTimer = null
    }
    if (this._contentTransitionTimer) {
      clearTimeout(this._contentTransitionTimer)
      this._contentTransitionTimer = null
    }
    if (this._switchWatchdogTimer) {
      clearTimeout(this._switchWatchdogTimer)
      this._switchWatchdogTimer = null
    }
    if (this._removeBackTimer) {
      clearTimeout(this._removeBackTimer)
      this._removeBackTimer = null
    }
    this._clearMasterUndo()
    // 清空页面实例缓存，防止跨页面串用
    this._wqCache = null
    this._aiGenerationMarker = ''
    resetRenderGuard()
  },

  async loadData(wqId) {
    var loadSeq = ++this._aiRequestId
    this._resetAiLoadingState()
    this._aiResult = null
    this.setData({
      loading: true,
      errorText: '',
      aiFallback: false,
      aiErrorText: '',
      aiRetryable: true,
      aiRequested: false,
      aiFromCache: false,
      aiFromQuestionAnalysis: false,
      masterConfirmVisible: false,
      unmasterConfirmVisible: false,
      moreMenuVisible: false,
      removeConfirmVisible: false,
      masterSubmitting: false,
      removeSubmitting: false,
    })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (loadSeq !== this._aiRequestId || !this._alive) return
      if (!wq) throw new Error('not found')
      if (this._wqCache) this._wqCache[wqId] = { data: wq, ts: Date.now() }
      const raw = _processWqData(wq, this.data.safeModeActive)

      // Build quiz-runner compatible currentQuestion
      const currentQuestion = Object.assign({}, wq, {
        _optionList: raw._optionList,
        _optionKeys: raw._optionKeys,
        _opts: raw._opts,
        _blankOptionGroups: raw._blankOptionGroups,
        _hasBlankOptionGroups: raw._hasBlankOptionGroups,
        _renderModel: raw._renderModel,
      })
      var totalQ = this.data.totalQuestions || 1
      // Build wrongQuestions array for quiz-runner answer sheet
      var wrongQuestions = []
      for (var wi = 0; wi < totalQ; wi++) {
        wrongQuestions.push({ _answered: true })
      }

      this._currentWqId = wqId
      this._errorTypeLabelText = raw.errorTypeLabelText
      this._aiGenerationMarker = _generationMarker(wq)
      this._aiResult = null

      var data = {
        wq,
        currentQuestion,
        wrongQuestions,
        runnerProgressPercent: totalQ > 0 ? Math.round((this.data.currentIdx + 1) / totalQ * 100) : 0,
        subjectLabelText: raw.subjectLabelText,
        loading: false,
        aiLoading: false,
        errorText: '',
        aiCards: null,
        aiRequested: false,
        aiFromCache: false,
        aiFromQuestionAnalysis: false,
        aiFallback: false,
        aiErrorText: '',
        aiRetryable: true,
        isCurrentMastered: _isWqMastered(wq),
        masterSubmitting: false,
        removeSubmitting: false,
      }

      // 仅使用一个“AI 学习建议”区域：AI 分析优先，否则回退题库解析。
      var preferredAnalysis = _resolvePreferredAnalysis(wq)
      if (preferredAnalysis) {
        var preferredNormalized = preferredAnalysis.normalized
        data.aiRequested = true
        if (_hasAiContent(preferredNormalized)) {
          this._aiResult = preferredNormalized
          data.aiCards = _normalizeAiResult(this._aiResult)
          data.aiFromCache = preferredAnalysis.source === 'ai'
          data.aiFromQuestionAnalysis = preferredAnalysis.source === 'question'
          data.aiFallback = false
          data.aiErrorText = ''
        } else {
          // 历史缓存/题库解析若是截断或嵌套失败的 JSON，不渲染源码，
          // 直接进入可重试的降级态。
          this._aiResult = null
          data.aiCards = null
          data.aiFromCache = false
          data.aiFromQuestionAnalysis = false
          data.aiFallback = true
          data.aiErrorText = preferredNormalized && preferredNormalized.formatError
            ? 'AI 返回格式异常，请重新生成'
            : 'AI 分析结果为空，请重新生成'
        }
      }
      // Stale response guard
      if (loadSeq !== this._aiRequestId || !this._alive) return
      this.setData(data)
      // Render invariant check + trace
      const checkModel = data.currentQuestion && data.currentQuestion._renderModel
      if (checkModel) {
        this._checkRenderInvariant(checkModel)
        this._recordRenderTrace(checkModel.renderTrace)
      }
      // 不再自动调用 AI 分析，用户点击按钮后手动触发
    } catch (e) {
      if (loadSeq !== this._aiRequestId || !this._alive) return
      console.error('加载错题详情失败', e)
      this._aiResult = null
      this.setData({
        loading: false,
        errorText: '错题不存在或已被移除',
        wq: null,
        aiLoading: false,
        aiFallback: false,
        aiErrorText: '',
        aiRequested: false,
        aiFromCache: false,
        aiFromQuestionAnalysis: false,
      })
    }
  },

  /** 统一复位 AI 加载状态 */
  _resetAiLoadingState() {
    this.setData({
      aiLoading: false,
      aiRegenerating: false,
      aiSkeletonVisible: false,
      aiInlineNotice: '',
    })
  },

  /** 将最新 AI 结果回写页面实例缓存，避免切题回来后旧缓存丢弃刚生成的分析 */
  _syncWqCacheAi(wqId, normalized, generatedAt) {
    if (!this._wqCache || !wqId || !normalized) return
    const entry = this._wqCache[wqId]
    if (!entry) return
    const patch = { ai_analysis: normalized }
    if (generatedAt !== undefined) patch.ai_analysis_generated_at = String(generatedAt || '')
    entry.data = Object.assign({}, entry.data, patch)
  },

  async _requestAiAnalysis(wqId, forceRegenerate) {
    return api.post('/ai/error-analysis', {
      wrong_question_id: wqId,
      force_regenerate: !!forceRegenerate,
    }, {
      timeout: AI_REQUEST_TIMEOUT_MS,
      suppressNetworkToast: true,
    })
  },

  async _enqueueAiRecovery(wqId, forceRegenerate, baselineGeneratedAt) {
    try {
      const payload = {
        wrong_question_id: wqId,
        force_regenerate: !!forceRegenerate,
      }
      if (forceRegenerate) payload.baseline_generated_at = String(baselineGeneratedAt || '')
      const result = await api.post('/ai/error-analysis/recover', payload, {
        timeout: 10000,
        suppressNetworkToast: true,
      })
      return !!(result && result.queued)
    } catch (e) {
      console.warn('AI 恢复任务入队失败，将继续轮询原请求结果', e)
      return false
    }
  },

  _analysisFailureState(model, result) {
    return {
      aiErrorText: _fallbackMessage(
        model,
        result && result.error_code,
        result && result.retryable
      ),
      aiRetryable: !(result && result.retryable === false),
    }
  },

  onTapAiAnalysis() {
    if (this.data.aiLoading || this.data.aiRegenerating) return
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId) {
      wx.showToast({ title: '缺少错题ID', icon: 'none' })
      return
    }
    this.loadAiAnalysis(wqId)
  },

  _isCurrentAiRequest(requestId, wqId) {
    return requestId === this._aiRequestId &&
      this._alive &&
      this.data.wq &&
      String(this.data.wq.id) === String(wqId)
  },

  async _pollPersistedAiAnalysis(wqId, requestId, options) {
    const pollOptions = options || {}
    const baselineGeneratedAt = String(pollOptions.baselineGeneratedAt || '')
    const requireNewGeneration = !!pollOptions.requireNewGeneration
    for (var attempt = 0; attempt < AI_CACHE_POLL_ATTEMPTS; attempt++) {
      if (!this._isCurrentAiRequest(requestId, wqId)) return null
      if (attempt > 0) await _sleep(AI_CACHE_POLL_INTERVAL_MS)
      if (!this._isCurrentAiRequest(requestId, wqId)) return null

      try {
        const status = await api.get(`/ai/error-analysis/status/${wqId}`, {}, {
          timeout: 10000,
          suppressNetworkToast: true,
        })
        if (!this._isCurrentAiRequest(requestId, wqId)) return null
        if (!status || !status.ready) continue
        const generatedAt = String(status.generated_at || '')
        // A timed-out request must not mistake the old preserved/stale cache for
        // the new result it is waiting for.
        if (requireNewGeneration && generatedAt === baselineGeneratedAt) continue
        const normalized = _normalizeAiPayload(status.content)
        if (_hasAiContent(normalized)) {
          const latestWq = Object.assign({}, this.data.wq || {}, {
            ai_analysis: normalized,
            ai_analysis_status: 'ready',
            ai_analysis_generated_at: generatedAt,
          })
          return { normalized, latestWq, generatedAt }
        }
      } catch (_) {
        // Polling is a recovery path; one transient network failure must not
        // replace the original request error or stop later checks.
      }
    }
    return null
  },

  _applyRecoveredAiResult(recovered, options) {
    if (!recovered) return false
    const applyOptions = options || {}
    this._resetAiLoadingState()
    this._aiResult = recovered.normalized
    this._aiGenerationMarker = String(recovered.generatedAt || _generationMarker(recovered.latestWq) || '')
    if (recovered.latestWq) {
      this._syncWqCacheAi(
        recovered.latestWq.id,
        recovered.normalized,
        this._aiGenerationMarker
      )
    }
    const latestWq = recovered.latestWq || this.data.wq
    this.setData({
      wq: latestWq,
      aiCards: _normalizeAiResult(recovered.normalized),
      aiFallback: false,
      aiFromCache: !applyOptions.fromRegeneration,
      aiFromQuestionAnalysis: false,
      aiErrorText: '',
      aiRetryable: true,
      aiInlineNotice: '',
      })
    return true
  },

  async loadAiAnalysis(wqId) {
    if (!wqId) return
    if (this.data.aiLoading) return
    const baselineGeneratedAt = String(this._aiGenerationMarker || _generationMarker(this.data.wq) || '')
    const requestId = ++this._aiRequestId
    this.setData({
      aiLoading: true,
      aiRequested: true,
      aiFallback: false,
      aiErrorText: '',
      aiRetryable: true,
      aiInlineNotice: '',
      })
    try {
      const result = await this._requestAiAnalysis(wqId, false)
      // Stale response guard
      if (!this._isCurrentAiRequest(requestId, wqId)) {
        this._resetAiLoadingState()
        return
      }
      const normalized = _normalizeAiPayload(result)
      const hasContent = _hasAiContent(normalized)
      const model = (result && result.model) || ''
      const fromFallback = !!(result && result.from_fallback)

      if (model === 'generating') {
        const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
          requireNewGeneration: true,
          baselineGeneratedAt,
        })
        if (this._applyRecoveredAiResult(recovered)) return
        if (!this._isCurrentAiRequest(requestId, wqId)) return
        this._resetAiLoadingState()
        this.setData({ aiFallback: true, aiErrorText: 'AI 分析正在生成中，请稍后重试' })
        return
      }
      // fallback 本身带有三段通用文案，不能仅凭“有内容”判定为成功。
      if (fromFallback) {
        this._resetAiLoadingState()
        this.setData(Object.assign({ aiFallback: true }, this._analysisFailureState(model, result)))
        return
      }
      if (!hasContent) {
        this._resetAiLoadingState()
        this.setData({ aiFallback: true, aiErrorText: 'AI 分析结果为空，请稍后重试' })
        return
      }
      this._resetAiLoadingState()
      this._aiResult = normalized
      this._aiGenerationMarker = String((result && result.generated_at) || this._aiGenerationMarker || '')
      this._syncWqCacheAi(wqId, normalized, this._aiGenerationMarker)
      this.setData({
        aiCards: _normalizeAiResult(normalized),
        aiFallback: false,
        aiFromCache: !!(result && result.from_cache),
        aiFromQuestionAnalysis: false,
        aiErrorText: '',
        aiRetryable: true,
      })
    } catch (e) {
      console.error('加载 AI 分析失败', e)
      if (this._isCurrentAiRequest(requestId, wqId)) {
        // wx.request usually reaches its transport ceiling before the backend's
        // provider budget. Queue a best-effort backup, then watch the persisted
        // result from either the original request or the recovery worker.
        this.setData({ aiInlineNotice: 'AI 正在继续生成，完成后会自动显示' })
        this._enqueueAiRecovery(wqId, false, '')
        const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
          requireNewGeneration: true,
          baselineGeneratedAt,
        })
        if (this._applyRecoveredAiResult(recovered)) return
      }
      if (this._isCurrentAiRequest(requestId, wqId)) {
        const msg = _isTimeoutError(e)
          ? 'AI 分析生成超时，请稍后重试'
          : 'AI 分析生成失败，请稍后重试'
        this._resetAiLoadingState()
        this.setData({ aiFallback: true, aiErrorText: msg })
      }
    }
  },

  async regenerateAiAnalysis() {
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId || this.data.aiLoading || this.data.aiRegenerating) return
    // 保存旧内容，失败时恢复
    const oldCards = this.data.aiCards
    const oldResult = this._aiResult
    const baselineGeneratedAt = String(this._aiGenerationMarker || _generationMarker(this.data.wq) || '')
    const requestId = ++this._aiRequestId
    this.setData({
      aiRegenerating: true,
      aiSkeletonVisible: true,
      aiErrorText: '',
      aiRetryable: true,
      aiFallback: false,
      aiInlineNotice: '',
      })
    try {
      const result = await this._requestAiAnalysis(wqId, true)
      // Stale response guard — 必须复位 ai state
      if (!this._isCurrentAiRequest(requestId, wqId)) {
        this._resetAiLoadingState()
        return
      }
      const normalized = _normalizeAiPayload(result)
      const hasContent = _hasAiContent(normalized)
      const model = (result && result.model) || ''
      const fromFallback = !!(result && result.from_fallback)
      const cachePreserved = !!(result && result.cache_preserved)

      // Another request is already generating. For a manual regeneration, wait
      // specifically for a generation marker newer than the old displayed cache.
      if (model === 'generating') {
        this.setData({ aiInlineNotice: 'AI 正在生成中，完成后会自动更新' })
        const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
          requireNewGeneration: true,
          baselineGeneratedAt,
        })
        if (this._applyRecoveredAiResult(recovered, { fromRegeneration: true })) {
          wx.showToast({ title: '已重新生成', icon: 'success' })
          return
        }
        if (!this._isCurrentAiRequest(requestId, wqId)) return
        this._resetAiLoadingState()
        this.setData({ aiInlineNotice: 'AI 正在生成中，请稍后重试' })
        return
      }

      // cache_preserved 且有内容 — 返回旧缓存
      if (cachePreserved && hasContent) {
        this._resetAiLoadingState()
        this._aiResult = normalized
        this._aiGenerationMarker = String((result && result.generated_at) || baselineGeneratedAt || '')
        this._syncWqCacheAi(wqId, normalized, this._aiGenerationMarker)
        this.setData({
          aiCards: _normalizeAiResult(normalized),
          aiFallback: false,
          aiFromCache: true,
          aiFromQuestionAnalysis: false,
          aiInlineNotice: '重新生成失败，已保留历史解析',
        })
        wx.showToast({ title: '重新生成失败，已保留历史解析', icon: 'none' })
        return
      }

      // fallback 带有通用正文，必须按失败处理，不能覆盖成“生成成功”。
      if (fromFallback) {
        this._resetAiLoadingState()
        var failure = this._analysisFailureState(model, result)
        if (oldCards) {
          this.setData({
            aiFallback: false,
            aiInlineNotice: failure.aiErrorText || '重新生成失败，已保留当前解析',
          })
          wx.showToast({ title: '重新生成失败，已保留当前解析', icon: 'none' })
        } else {
          this.setData(Object.assign({ aiFallback: true }, failure))
        }
        return
      }

      // 无内容
      if (!hasContent) {
        if (oldCards) {
          this._resetAiLoadingState()
          this.setData({
            aiFallback: false,
            aiInlineNotice: '返回内容为空，已保留当前解析',
          })
          wx.showToast({ title: '返回内容为空，已保留当前解析', icon: 'none' })
        } else {
          this._resetAiLoadingState()
          this.setData({ aiFallback: true, aiErrorText: 'AI 返回内容为空，请稍后重试' })
        }
        return
      }

      // 成功 — 更新为新内容
      this._resetAiLoadingState()
      this._aiResult = normalized
      this._aiGenerationMarker = String((result && result.generated_at) || this._aiGenerationMarker || '')
      this._syncWqCacheAi(wqId, normalized, this._aiGenerationMarker)
      this.setData({
        aiCards: _normalizeAiResult(normalized),
        aiFallback: false,
        aiFromCache: !!(result && result.from_cache),
        aiFromQuestionAnalysis: false,
        aiErrorText: '',
        aiRetryable: true,
      })
      wx.showToast({ title: '已重新生成', icon: 'success' })
    } catch (e) {
      console.error('重新生成 AI 分析失败', e)
      if (this._isCurrentAiRequest(requestId, wqId)) {
        this.setData({ aiInlineNotice: 'AI 正在继续重新生成，完成后会自动更新' })
        this._enqueueAiRecovery(wqId, true, baselineGeneratedAt)
        const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
          requireNewGeneration: true,
          baselineGeneratedAt,
        })
        if (this._applyRecoveredAiResult(recovered, { fromRegeneration: true })) {
          wx.showToast({ title: '已重新生成', icon: 'success' })
          return
        }
      }
      if (this._isCurrentAiRequest(requestId, wqId)) {
        const timeoutText = _isTimeoutError(e) ? '重新生成超时' : '重新生成失败'
        if (oldCards) {
          this._resetAiLoadingState()
          this._aiResult = oldResult
          this.setData({
            aiCards: oldCards,
            aiFallback: false,
            aiInlineNotice: `${timeoutText}，已保留历史解析`,
          })
          wx.showToast({ title: `${timeoutText}，已保留历史解析`, icon: 'none' })
        } else {
          this._resetAiLoadingState()
          this.setData({ aiErrorText: `${timeoutText}，请稍后重试` })
          wx.showToast({ title: timeoutText, icon: 'none' })
        }
      }
    }
  },

  openMasterConfirm() {
    if (this.data.masterSubmitting || this.data.isCurrentMastered) return
    this.setData({ masterConfirmVisible: true })
  },

  closeMasterConfirm() {
    if (this.data.masterSubmitting) return
    this.setData({ masterConfirmVisible: false })
  },

  openUnmasterConfirm() {
    if (this.data.masterSubmitting || !this.data.isCurrentMastered) return
    this.setData({ unmasterConfirmVisible: true })
  },

  closeUnmasterConfirm() {
    if (this.data.masterSubmitting) return
    this.setData({ unmasterConfirmVisible: false })
  },

  onMasterAction() {
    if (this.data.isCurrentMastered) {
      this.openUnmasterConfirm()
    } else {
      this.openMasterConfirm()
    }
  },

  async confirmMastered() {
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId || this.data.masterSubmitting) return

    this.setData({ masterSubmitting: true, masterConfirmVisible: false })
    try {
      const masterResult = await api.post('/wrong-questions/batch', {
        action: 'mark_mastered',
        ids: [wqId],
      })
      if (!this._alive) return

      const masterSkipped = !!(
        masterResult && Array.isArray(masterResult.skipped_ids) &&
        masterResult.skipped_ids.some(id => String(id) === String(wqId))
      )
      const masterChanged = !masterSkipped && !(
        masterResult && masterResult.updated_count != null && Number(masterResult.updated_count) <= 0
      )
      if (!masterChanged) {
        // The detail can be stale when another page/device already changed this
        // row. Never create an undo for a mutation this request did not perform,
        // otherwise Undo could revert the other surface's pre-existing mastery.
        this._clearMasterUndo()
        this.setData({ masterSubmitting: false })
        await this.loadData(wqId)
        if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
        return
      }

      this._clearMasterUndo()
      this._pendingMasterUndo = {
        wqId,
        originalIdx: this.data.currentIdx,
      }

      if (this._wqCache && this._wqCache[wqId]) {
        this._wqCache[wqId].data = Object.assign({}, this._wqCache[wqId].data, { is_mastered: true })
      }
      if (this.data.wq && String(this.data.wq.id) === String(wqId)) {
        this.setData({
          wq: Object.assign({}, this.data.wq, { is_mastered: true }),
          isCurrentMastered: true,
          masterSubmitting: false,
          masterUndoVisible: true,
        })
      } else {
        this.setData({ masterSubmitting: false, masterUndoVisible: true })
      }

      this._armMasterUndoExpiry(5000)

      if (this.data.currentIdx < this.data.questionIds.length - 1) {
        this._masterAdvanceTimer = setTimeout(() => {
          this._masterAdvanceTimer = null
          this._navigateTo(this.data.currentIdx + 1, 150)
        }, 120)
      }
    } catch (e) {
      if (!this._alive) return
      console.error('标记已掌握失败', e)
      this.setData({ masterSubmitting: false })
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
    }
  },

  async confirmUnmastered() {
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId || this.data.masterSubmitting) return

    this.setData({ masterSubmitting: true, unmasterConfirmVisible: false })
    try {
      const unmasterResult = await api.post('/wrong-questions/batch', {
        action: 'unmark_mastered',
        ids: [wqId],
      })
      if (!this._alive) return

      const unmasterSkipped = !!(
        unmasterResult && Array.isArray(unmasterResult.skipped_ids) &&
        unmasterResult.skipped_ids.some(id => String(id) === String(wqId))
      )
      if (unmasterSkipped || (unmasterResult && unmasterResult.updated_count != null && Number(unmasterResult.updated_count) <= 0)) {
        this._clearMasterUndo()
        this.setData({ masterSubmitting: false })
        await this.loadData(wqId)
        if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
        return
      }

      this._clearMasterUndo()
      if (this._wqCache && this._wqCache[wqId]) {
        this._wqCache[wqId].data = Object.assign({}, this._wqCache[wqId].data, { is_mastered: false })
      }
      if (this.data.wq && String(this.data.wq.id) === String(wqId)) {
        this.setData({
          wq: Object.assign({}, this.data.wq, { is_mastered: false }),
          isCurrentMastered: false,
          masterSubmitting: false,
        })
      } else {
        this.setData({ masterSubmitting: false })
      }
      wx.showToast({ title: '已重新加入复习', icon: 'none' })
    } catch (e) {
      if (!this._alive) return
      console.error('重新加入复习失败', e)
      this.setData({ masterSubmitting: false })
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
    }
  },

  async undoMastered() {
    const pending = this._pendingMasterUndo
    if (!pending || this._masterUndoInFlight) return
    this._masterUndoInFlight = true
    // Pause the 5s expiry while the undo request is in flight. On a weak
    // network the old timer could expire first, erase the target id, and leave
    // the user with a "retry" toast but no undo button to retry from.
    if (this._masterUndoTimer) {
      clearTimeout(this._masterUndoTimer)
      this._masterUndoTimer = null
    }
    // confirmMastered schedules an automatic jump to the next wrong question.
    // Cancel both the pending timer and an already-started navigation. The
    // navigation sequence guard below prevents its late fetch response from
    // overwriting the restored mastered state.
    if (this._masterAdvanceTimer) {
      clearTimeout(this._masterAdvanceTimer)
      this._masterAdvanceTimer = null
    }
    if (this._switching) this._forceResetSwitchLock()

    try {
      const undoResult = await api.post('/wrong-questions/batch', {
        action: 'unmark_mastered',
        ids: [pending.wqId],
      })
      if (!this._alive) return

      const undoSkipped = !!(
        undoResult && Array.isArray(undoResult.skipped_ids) &&
        undoResult.skipped_ids.some(id => String(id) === String(pending.wqId))
      ) || !!(
        undoResult && undoResult.updated_count != null && Number(undoResult.updated_count) <= 0
      )
      if (undoSkipped) {
        // A skipped undo is ambiguous: the row may already be unmastered (safe),
        // or it may have been removed from the wrong book while the toast was
        // visible. Re-read the row before restoring anything locally.
        try {
          const fresh = await api.get(`/wrong-questions/${pending.wqId}`)
          if (!this._alive) return
          if (!fresh) throw Object.assign(new Error('not found'), { statusCode: 404 })
          if (this._wqCache) this._wqCache[pending.wqId] = { data: fresh, ts: Date.now() }
          const targetIdx = (this.data.questionIds || []).findIndex(id => String(id) === String(pending.wqId))
          this._clearMasterUndo()
          if (targetIdx >= 0 && targetIdx !== this.data.currentIdx) {
            await this._navigateTo(targetIdx, 150)
          } else if (targetIdx >= 0) {
            await this.loadData(pending.wqId)
          }
          if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
          return
        } catch (freshError) {
          const freshStatus = Number(freshError && (freshError.statusCode || freshError.status)) || 0
          if (freshStatus === 404 || freshStatus === 410) {
            this._clearMasterUndo()
            this._dropQuestionFromNavigation(pending.wqId)
            if (this._alive) wx.showToast({ title: '该错题已被移除，无法撤销', icon: 'none' })
            return
          }
          throw freshError
        }
      }

      if (this._wqCache && this._wqCache[pending.wqId]) {
        this._wqCache[pending.wqId].data = Object.assign({}, this._wqCache[pending.wqId].data, { is_mastered: false })
      }

      const targetIdx = this.data.questionIds.findIndex(id => String(id) === String(pending.wqId))
      this._clearMasterUndo()

      if (targetIdx >= 0 && targetIdx !== this.data.currentIdx) {
        await this._navigateTo(targetIdx, 150)
      } else if (this.data.wq && String(this.data.wq.id) === String(pending.wqId)) {
        this.setData({
          wq: Object.assign({}, this.data.wq, { is_mastered: false }),
          isCurrentMastered: false,
        })
      } else if (targetIdx >= 0) {
        await this.loadData(pending.wqId)
      }
      wx.showToast({ title: '已撤销掌握', icon: 'none' })
    } catch (e) {
      if (!this._alive) return
      console.error('撤销已掌握失败', e)
      if (this._pendingMasterUndo === pending) {
        this.setData({ masterUndoVisible: true })
        this._armMasterUndoExpiry(5000)
      }
      wx.showToast({ title: '撤销失败，请重试', icon: 'none' })
    } finally {
      this._masterUndoInFlight = false
    }
  },

  _armMasterUndoExpiry(ms) {
    if (this._masterUndoTimer) clearTimeout(this._masterUndoTimer)
    var duration = Number(ms) > 0 ? Number(ms) : 5000
    this._masterUndoTimer = setTimeout(() => {
      this._pendingMasterUndo = null
      this._masterUndoTimer = null
      if (this._alive) this.setData({ masterUndoVisible: false })
    }, duration)
  },

  _clearMasterUndo() {
    if (this._masterUndoTimer) {
      clearTimeout(this._masterUndoTimer)
      this._masterUndoTimer = null
    }
    if (this._masterAdvanceTimer) {
      clearTimeout(this._masterAdvanceTimer)
      this._masterAdvanceTimer = null
    }
    this._pendingMasterUndo = null
    if (this._alive && this.data && this.data.masterUndoVisible) {
      this.setData({ masterUndoVisible: false })
    }
  },

  openMoreMenu() {
    this.setData({ moreMenuVisible: true })
  },

  closeMoreMenu() {
    this.setData({ moreMenuVisible: false })
  },

  openRemoveConfirm() {
    this.setData({ moreMenuVisible: false, removeConfirmVisible: true })
  },

  closeRemoveConfirm() {
    if (this.data.removeSubmitting) return
    this.setData({ removeConfirmVisible: false })
  },

  async removeFromWrongBook() {
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId || this.data.removeSubmitting) return

    this._clearMasterUndo()
    this.setData({ removeSubmitting: true })
    try {
      await api.post('/wrong-questions/batch', {
        action: 'remove_from_book',
        ids: [wqId],
      })
      if (!this._alive) return

      const oldIds = this.data.questionIds || []
      const currentIdx = this.data.currentIdx
      const nextIds = oldIds.filter(id => String(id) !== String(wqId))
      if (this._wqCache) delete this._wqCache[wqId]

      try {
        wx.setStorageSync('wrong_detail_nav', { ids: nextIds, ts: Date.now() })
      } catch (_) {}

      this.setData({
        questionIds: nextIds,
        totalQuestions: nextIds.length,
        removeConfirmVisible: false,
        removeSubmitting: false,
      })

      if (!nextIds.length) {
        wx.showToast({ title: '已移出错题本', icon: 'none' })
        if (this._removeBackTimer) clearTimeout(this._removeBackTimer)
        this._removeBackTimer = setTimeout(() => {
          this._removeBackTimer = null
          if (this._alive) this.goBack()
        }, 220)
        return
      }

      const nextIdx = Math.min(currentIdx, nextIds.length - 1)
      this.setData({ currentIdx: nextIdx })
      await this.loadData(nextIds[nextIdx])
      wx.showToast({ title: '已移出错题本', icon: 'none' })
    } catch (e) {
      if (!this._alive) return
      console.error('移出错题本失败', e)
      this.setData({ removeSubmitting: false })
      wx.showToast({ title: '移出失败，请重试', icon: 'none' })
    }
  },

  // ---- Render Invariant + Trace ----

  _checkRenderInvariant(renderModel) {
    if (!renderModel) return
    if (renderModel.mode === 'CODE' && renderModel.rawText) {
      var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
      if (hasHtmlLeak) {
        console.error('[CODE_HTML_LEAK] wrong-detail CODE rawText contains HTML entities')
      }
      var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
      if (hasRenderViolation) {
        console.error('[CODE_RENDER_VIOLATION] wrong-detail CODE mode leaked into html/richTextNodes')
      }
      if ((hasHtmlLeak || hasRenderViolation) && !this.data.safeModeActive) {
        this._enterSafeMode()
      }
    }
    // MIXED mode validation
    if (renderModel.mode === 'MIXED') {
      if (!renderModel.blocks || renderModel.blocks.length === 0) {
        console.error('[MIXED_RENDER_VIOLATION] wrong-detail MIXED mode but blocks is empty')
        return
      }
      for (var mi = 0; mi < renderModel.blocks.length; mi++) {
        var mBlock = renderModel.blocks[mi]
        if (mBlock.type === 'CODE' && mBlock.rawText) {
          if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
            console.error('[CODE_HTML_LEAK] wrong-detail MIXED CODE block #' + mi + ' contains HTML entities')
          }
        }
      }
    }
  },

  _recordRenderTrace(trace) {
    if (!trace || !config.debug) return
    if (!Array.isArray(this.data.renderTraces)) return
    var traces = this.data.renderTraces.concat([trace]).slice(-20)
    this.setData({ renderTraces: traces })
  },

  _enterSafeMode() {
    console.warn('[SELF_HEAL] wrong-detail CODE render violation — entering SAFE_MODE')
    this.setData({ safeModeActive: true })
    if (this.data.wq) {
      var raw = _processWqData(this.data.wq, true)
      if (raw._renderModel) {
        var currentQuestion = Object.assign({}, this.data.wq, {
          _optionList: raw._optionList,
          _optionKeys: raw._optionKeys,
          _opts: raw._opts,
          _blankOptionGroups: raw._blankOptionGroups,
          _hasBlankOptionGroups: raw._blankOptionGroups.length > 0,
          _renderModel: raw._renderModel,
        })
        this._errorTypeLabelText = raw.errorTypeLabelText
        this.setData({
          currentQuestion,
          subjectLabelText: raw.subjectLabelText,
        })
        console.warn('[SELF_HEAL] wrong-detail re-rendered in SAFE_MODE, mode=' + raw._renderModel.mode)
      }
    }
  },

  // ---- AI 学习建议区域左右滑动切题（切题动画由题目+AI整体容器统一承担） ----
  onAiSwipeStart(e) {
    if (this._switching) return
    const touch = e && e.touches && e.touches[0]
    if (!touch) return
    this._aiSwipeStart = {
      x: Number(touch.clientX),
      y: Number(touch.clientY),
      ts: Date.now(),
    }
  },

  onAiSwipeEnd(e) {
    const start = this._aiSwipeStart
    this._aiSwipeStart = null
    if (!start || this._switching) return

    const touch = e && e.changedTouches && e.changedTouches[0]
    if (!touch) return
    const dx = Number(touch.clientX) - start.x
    const dy = Number(touch.clientY) - start.y
    const absX = Math.abs(dx)
    const absY = Math.abs(dy)

    // 仅识别明确的横向滑动，避免阅读 AI 长文本时的纵向滚动误切题。
    if (absX < 56 || absX <= absY * 1.2) return

    const targetIdx = dx < 0 ? this.data.currentIdx + 1 : this.data.currentIdx - 1
    if (targetIdx < 0 || targetIdx >= this.data.questionIds.length) return
    this._navigateTo(targetIdx, 150, dx < 0 ? 'left' : 'right')
  },

  onAiSwipeCancel() {
    this._aiSwipeStart = null
  },

  _beginContentSwitchTransition(direction) {
    if (!this._alive) return
    const dir = direction === 'right' ? 'right' : 'left'
    if (this._contentTransitionTimer) {
      clearTimeout(this._contentTransitionTimer)
      this._contentTransitionTimer = null
    }
    this._contentTransitionStartedAt = Date.now()
    this._contentTransitionDirection = dir
    this.setData({
      contentTransitionClass: dir === 'left' ? 'content-slide-out-left' : 'content-slide-out-right',
    })
  },

  async _waitForContentSwitchOut(direction, animMs) {
    const dir = direction === 'right' ? 'right' : 'left'
    if (!this._contentTransitionStartedAt || this._contentTransitionDirection !== dir) {
      this._beginContentSwitchTransition(dir)
    }
    const requested = Number(animMs)
    const waitTarget = Number.isFinite(requested) && requested > 0
      ? Math.min(QUESTION_SWITCH_OUT_MS, requested)
      : QUESTION_SWITCH_OUT_MS
    const elapsed = Date.now() - this._contentTransitionStartedAt
    if (elapsed < waitTarget) await _sleep(waitTarget - elapsed)
  },

  _finishContentSwitchTransition(direction) {
    const dir = direction === 'right' ? 'right' : 'left'
    const inClass = dir === 'left' ? 'content-slide-in-right' : 'content-slide-in-left'
    if (this._contentTransitionTimer) clearTimeout(this._contentTransitionTimer)
    this._contentTransitionStartedAt = 0
    this._contentTransitionDirection = ''
    this.setData({ contentTransitionClass: inClass })
    this._contentTransitionTimer = setTimeout(() => {
      this._contentTransitionTimer = null
      this._switching = false
      this._clearSwitchWatchdog()
      if (this._alive) this.setData({ contentTransitionClass: '' })
    }, QUESTION_SWITCH_IN_MS)
  },

  _cancelContentSwitchTransition() {
    if (this._contentTransitionTimer) {
      clearTimeout(this._contentTransitionTimer)
      this._contentTransitionTimer = null
    }
    this._contentTransitionStartedAt = 0
    this._contentTransitionDirection = ''
    if (this._alive) this.setData({ contentTransitionClass: '' })
  },

  // ---- 切题锁看门狗：fetch 阶段用长看门狗，动画阶段重武装为短看门狗，
  // 正常路径及时释放锁，异常/回调丢失时强制复位，防止永久卡死 ----
  _armSwitchWatchdog(ms) {
    this._clearSwitchWatchdog()
    var duration = Number(ms) > 0 ? Number(ms) : QUESTION_SWITCH_WATCHDOG_MS
    var self = this
    this._switchWatchdogTimer = setTimeout(function() {
      self._switchWatchdogTimer = null
      console.warn('[wrong-detail] 切题锁看门狗触发，强制复位')
      self._forceResetSwitchLock()
    }, duration)
  },

  _clearSwitchWatchdog() {
    if (this._switchWatchdogTimer) {
      clearTimeout(this._switchWatchdogTimer)
      this._switchWatchdogTimer = null
    }
  },

  _forceResetSwitchLock() {
    // Invalidate the async continuation of the current navigation. A watchdog
    // reset (or mastery undo) must not merely unlock the UI; otherwise the old
    // fetch can return later and overwrite whichever question is now visible.
    this._navigationSeq = Number(this._navigationSeq || 0) + 1
    this._switching = false
    if (this._contentTransitionTimer) {
      clearTimeout(this._contentTransitionTimer)
      this._contentTransitionTimer = null
    }
    if (this._switchMaskTimer) {
      clearTimeout(this._switchMaskTimer)
      this._switchMaskTimer = null
    }
    this._contentTransitionStartedAt = 0
    this._contentTransitionDirection = ''
    this._clearSwitchWatchdog()
    if (this._alive) {
      this.setData({ contentTransitionClass: '', showSwitchMask: false, aiRegenerating: false })
    }
  },

  // ---- Quiz-runner navigation events ----
  goPrevWrong(e) {
    this._navigateTo(e.detail.index, 150, 'right')
  },

  goNextWrong(e) {
    this._navigateTo(e.detail.index, 150, 'left')
  },

  goWrongQuestion(e) {
    this._navigateTo(e.detail.index, 150)
  },

  reloadData() {
    if (this.data.questionIds.length > 0) {
      this.loadData(this.data.questionIds[this.data.currentIdx])
    } else if (this._currentWqId) {
      this.loadData(this._currentWqId)
    } else {
      this.goBack()
    }
  },

  goBack() {
    const pages = getCurrentPages()
    if (pages.length > 1) wx.navigateBack()
    else wx.redirectTo({ url: '/subpackages/study/wrong-book/wrong-book' })
  },

  _dropQuestionFromNavigation(wqId) {
    const currentId = this._currentWqId || (this.data.wq && this.data.wq.id)
    const oldIds = this.data.questionIds || []
    const nextIds = oldIds.filter(id => String(id) !== String(wqId))
    if (nextIds.length === oldIds.length) return false

    if (this._wqCache) delete this._wqCache[wqId]
    try {
      wx.setStorageSync('wrong_detail_nav', { ids: nextIds, ts: Date.now() })
    } catch (_) {}

    let nextCurrentIdx = nextIds.findIndex(id => String(id) === String(currentId))
    if (nextCurrentIdx < 0) nextCurrentIdx = 0
    const wrongQuestions = nextIds.map(() => ({ _answered: true }))
    this.setData({
      questionIds: nextIds,
      totalQuestions: nextIds.length,
      currentIdx: nextCurrentIdx,
      wrongQuestions,
      runnerProgressPercent: nextIds.length > 0
        ? Math.round((nextCurrentIdx + 1) / nextIds.length * 100)
        : 0,
    })
    return true
  },

  async _navigateTo(idx, animMs, direction) {
    const wqId = this.data.questionIds[idx]
    if (!wqId) return
    // 并发保护
    if (this._switching) return
    if (this.data.masterSubmitting || this.data.removeSubmitting) return
    if (idx < 0 || idx >= this.data.questionIds.length) return
    if (idx === this.data.currentIdx) return

    const switchDirection = direction === 'left' || direction === 'right'
      ? direction
      : (idx > this.data.currentIdx ? 'left' : 'right')

    this._aiRequestId++
    this._resetAiLoadingState()
    this._switching = true
    var navigationSeq = Number(this._navigationSeq || 0) + 1
    this._navigationSeq = navigationSeq
    this._armSwitchWatchdog()
    // 延迟显示轻量切换提示（>250ms 才展示）。
    // 注意：slide-out 不在此时触发——保持当前内容可见直到数据就绪，
    // 由下方 _waitForContentSwitchOut 在 fetch 完成后统一退出/进入，避免整段网络等待期空白。
    var self = this
    this._switchMaskTimer = setTimeout(function() {
      if (self._alive) self.setData({ showSwitchMask: true })
    }, 250)

    try {
      // 错题内容可能被后台修订。相邻题预取缓存不能作为前台展示的
      // 权威数据源，否则用户在页面内来回切题时会继续看到旧版本。
      // 每次前台切题都重新向服务端校验；仅在非 404/410 的短暂网络
      // 故障时，允许使用 30 秒内缓存作为弱网兜底。
      var wq = null
      var cached = this._wqCache && this._wqCache[wqId]
      try {
        wq = await api.get(`/wrong-questions/${wqId}`)
        if (!wq) throw new Error('not found')
        if (!this._alive) return
        if (this._wqCache) this._wqCache[wqId] = { data: wq, ts: Date.now() }
      } catch (fetchError) {
        var fetchStatus = Number(fetchError && (fetchError.statusCode || fetchError.status)) || 0
        var canFallback = fetchStatus !== 404 && fetchStatus !== 410 &&
          cached && Date.now() - Number(cached.ts || 0) < 30000
        if (!canFallback) throw fetchError
        wq = cached.data
      }
      if (!this._alive || navigationSeq !== this._navigationSeq) return
      // 预取相邻题
      this._prefetchWrongQuestion(idx - 1)
      this._prefetchWrongQuestion(idx + 1)
      const raw = _processWqData(wq, this.data.safeModeActive)

      // Build quiz-runner compatible currentQuestion
      const currentQuestion = Object.assign({}, wq, {
        _optionList: raw._optionList,
        _optionKeys: raw._optionKeys,
        _opts: raw._opts,
        _blankOptionGroups: raw._blankOptionGroups,
        _hasBlankOptionGroups: raw._blankOptionGroups.length > 0,
        _renderModel: raw._renderModel,
      })
      var totalQ = this.data.totalQuestions || 1
      var wrongQuestions = []
      for (var wi = 0; wi < totalQ; wi++) {
        wrongQuestions.push({ _answered: true })
      }

      var nextAiResult = null

      var nextData = {
        wq,
        currentIdx: idx,
        currentQuestion,
        wrongQuestions,
        runnerProgressPercent: totalQ > 0 ? Math.round((idx + 1) / totalQ * 100) : 0,
        subjectLabelText: raw.subjectLabelText,
        aiLoading: false,
        aiRegenerating: false,
        aiCards: null,
        aiRequested: false,
        aiFromCache: false,
        aiFromQuestionAnalysis: false,
        aiFallback: false,
        aiErrorText: '',
        aiRetryable: true,
        isCurrentMastered: _isWqMastered(wq),
        masterSubmitting: false,
        removeSubmitting: false,
      }

      // 切题时沿用相同优先级：AI 分析优先，否则回退题库解析。
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
      // 题目区域与 AI 学习建议由同一个父容器统一退出/进入，
      // quiz-runner 内部动画已关闭，避免两个区域各自计时造成不同步。
      await this._waitForContentSwitchOut(switchDirection, animMs)
      if (!this._alive || navigationSeq !== this._navigationSeq) return
      this._currentWqId = wqId
      this._errorTypeLabelText = raw.errorTypeLabelText
      this._aiResult = nextAiResult
      clearTimeout(this._switchMaskTimer)
      // fetch 已就绪，动画阶段改挂短看门狗：setData 回调丢失时 5s 内强制复位
      this._armSwitchWatchdog(QUESTION_SWITCH_ANIM_WATCHDOG_MS)
      this.setData(Object.assign({ showSwitchMask: false }, nextData), () => {
        this._finishContentSwitchTransition(switchDirection)
      })
      this._checkRenderInvariant(raw._renderModel)
    } catch (e) {
      if (!this._alive || navigationSeq !== this._navigationSeq) return
      console.error('切换题目失败', e)
      clearTimeout(this._switchMaskTimer)
      // 切换失败时保持当前题不变，同时复位 AI 状态防止永久卡住
      this._switching = false
      this._clearSwitchWatchdog()
      this._cancelContentSwitchTransition()

      const statusCode = Number(e && (e.statusCode || e.status)) || 0
      if (statusCode === 404 || statusCode === 410) {
        // The navigation context can outlive the wrong-book row (another page,
        // device, or batch action may remove it). Drop the dead id immediately;
        // otherwise every "next/previous" tap hits the same 404 forever and the
        // answer-sheet progress still counts a question that no longer exists.
        this._dropQuestionFromNavigation(wqId)
        this.setData({ showSwitchMask: false, aiRegenerating: false })
        wx.showToast({ title: '该错题已被移除，已更新题目列表', icon: 'none' })
        return
      }

      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ showSwitchMask: false, aiRegenerating: false })
    }
  },

  scrollToAiCard() {
    wx.pageScrollTo({ selector: '#ai-card', duration: 220 })
  },

  noop() {},

  _prefetchWrongQuestion(idx) {
    if (idx < 0 || idx >= this.data.questionIds.length) return
    var wqId = this.data.questionIds[idx]
    if (!wqId) return
    var cached = this._wqCache[wqId]
    if (cached && Date.now() - cached.ts < 300000) return
    var requestStartedAt = Date.now()
    var self = this
    api.get(`/wrong-questions/${wqId}`).then(function(wq) {
      if (!wq || !self._alive || !self._wqCache) return
      var latest = self._wqCache[wqId]
      // A foreground navigation/mutation may have produced a newer cache entry
      // while this speculative prefetch was still in flight. Do not let the
      // older response roll mastered/AI/detail state back.
      if (latest && Number(latest.ts || 0) >= requestStartedAt) return
      self._wqCache[wqId] = { data: wq, ts: Date.now() }
    }).catch(function() {})
  },
})
