const api = require('../../utils/api')
const config = require('../../config')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage,
  toPlainInlineMathText, needsRichRender, textToHtml
} = require('../../utils/stem-render')
const { isTrueFalseType } = require('../../utils/answer')
const adapter = require('../../utils/question-runner-adapter')
const { normalizeAiAnalysisPayload, hasAiAnalysisContent } = require('../../utils/ai-analysis-normalizer')

function _subjectLabel(s) {
  const { getSubjectName } = require('../../utils/subject-meta')
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
    subjectLabelText: _subjectLabel(wq.subject),
    errorTypeLabelText: _errorTypeLabel(wq.error_type),
  }
}

function _buildAiRichText(value) {
  const raw = String(value || '').trim()
  if (!raw) {
    return { raw: '', text: '', html: '', needsRich: false }
  }
  const plain = toPlainInlineMathText(raw)
  const needsRich = !plain && needsRichRender(raw)
  return {
    raw,
    text: plain || raw,
    html: needsRich ? textToHtml(raw) : '',
    needsRich,
  }
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

function _detectAiCache(wq) {
  if (!wq || !wq.ai_analysis) return false
  var raw = wq.ai_analysis
  if (typeof raw === 'object' && !Array.isArray(raw) && Object.keys(raw).length > 0) return true
  if (Array.isArray(raw) && raw.length > 0) return true
  if (typeof raw === 'string') {
    var t = raw.trim()
    if (!t) return false
    if (t.charAt(0) === '{' || t.charAt(0) === '[') return true
  }
  return false
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
    aiRequested: false,
    aiFromCache: false,
    loading: true,
    errorText: '',
    questionIds: [],
    currentIdx: 0,
    totalQuestions: 0,
    safeModeActive: false,
    aiCards: null,
    aiRegenerating: false,
    aiSkeletonVisible: false,
    aiInlineNotice: '',
    showSwitchMask: false,
    renderTraces: [],

    masterConfirmVisible: false,
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
  _aiResult: null,
  _errorTypeLabelText: '',

  onLoad(options) {
    setRenderGuardPage('wrong-detail')
    this._alive = true
    this._aiRequestId = 0
    this._currentWqId = null
    this._switching = false
    // 页面实例级别的缓存（含 TTL），避免模块全局变量跨用户串用
    this._wqCache = {}
    this._switchMaskTimer = null
    this._masterUndoTimer = null
    this._masterAdvanceTimer = null
    this._pendingMasterUndo = null
    const currentId = Number(options.id)
    if (!Number.isFinite(currentId) || currentId <= 0) {
      this.setData({ loading: false, errorText: '错题ID无效', wq: null })
      return
    }
    let questionIds = []
    try {
      if (options.source === 'wrong-book') {
        const nav = wx.getStorageSync('wrong_detail_nav')
        if (nav && Array.isArray(nav.ids) && Date.now() - Number(nav.ts || 0) < 30 * 60 * 1000) {
          const normalized = nav.ids.map(Number).filter(Number.isFinite)
          if (normalized.includes(currentId)) questionIds = normalized
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
    this._clearMasterUndo()
    // 清空页面实例缓存，防止跨页面串用
    this._wqCache = null
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
      aiRequested: false,
      aiFromCache: false,
      masterConfirmVisible: false,
      moreMenuVisible: false,
      removeConfirmVisible: false,
      masterSubmitting: false,
      removeSubmitting: false,
    })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')
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
        aiFallback: false,
        aiErrorText: '',
        isCurrentMastered: _isWqMastered(wq),
        masterSubmitting: false,
        removeSubmitting: false,
      }

      // 如果后端已返回持久化的 AI 分析，直接展示
      var cachedAi = _detectAiCache(wq)
      if (cachedAi) {
        this._aiResult = normalizeAiAnalysisPayload(wq.ai_analysis)
        data.aiCards = _normalizeAiResult(this._aiResult)
        data.aiRequested = true
        data.aiFromCache = true
        data.aiFallback = false
        data.aiErrorText = ''
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

  onTapAiAnalysis() {
    if (this.data.aiLoading || this.data.aiRegenerating) return
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId) {
      wx.showToast({ title: '缺少错题ID', icon: 'none' })
      return
    }
    this.loadAiAnalysis(wqId)
  },

  async loadAiAnalysis(wqId) {
    if (!wqId) return
    if (this.data.aiLoading) return
    const requestId = ++this._aiRequestId
    this.setData({
      aiLoading: true,
      aiRequested: true,
      aiFallback: false,
      aiErrorText: '',
      aiInlineNotice: '',
    })
    try {
      const result = await api.post('/ai/error-analysis', { wrong_question_id: wqId }, { timeout: 60000 })
      // Stale response guard
      if (requestId !== this._aiRequestId || !this._alive || !this.data.wq || String(this.data.wq.id) !== String(wqId)) {
        this._resetAiLoadingState()
        return
      }
      const normalized = _normalizeAiPayload(result)
      const hasContent = _hasAiContent(normalized)
      const model = (result && result.model) || ''
      const fromFallback = !!(result && result.from_fallback)

      if (model === 'generating') {
        this._resetAiLoadingState()
        this.setData({ aiFallback: true, aiErrorText: 'AI 分析正在生成中，请稍后重试' })
        return
      }
      if (fromFallback && !hasContent) {
        this._resetAiLoadingState()
        this.setData({ aiFallback: true, aiErrorText: 'AI 服务暂时不可用，请稍后重试' })
        return
      }
      if (!hasContent) {
        this._resetAiLoadingState()
        this.setData({ aiFallback: true, aiErrorText: 'AI 分析结果为空，请稍后重试' })
        return
      }
      this._resetAiLoadingState()
      this._aiResult = normalized
      this.setData({
        aiCards: _normalizeAiResult(normalized),
        aiFallback: false,
        aiFromCache: !!(result && result.from_cache),
        aiErrorText: '',
      })
    } catch (e) {
      console.error('加载 AI 分析失败', e)
      if (requestId === this._aiRequestId && this._alive && this.data.wq && String(this.data.wq.id) === String(wqId)) {
        const msg = e && e.message && String(e.message).includes('timeout')
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
    const requestId = ++this._aiRequestId
    this.setData({
      aiRegenerating: true,
      aiSkeletonVisible: true,
      aiErrorText: '',
      aiFallback: false,
      aiInlineNotice: '',
    })
    try {
      const result = await api.post('/ai/error-analysis', {
        wrong_question_id: wqId,
        force_regenerate: true,
      }, { timeout: 60000 })
      // Stale response guard — 必须复位 ai state
      if (requestId !== this._aiRequestId || !this._alive || !this.data.wq || String(this.data.wq.id) !== String(wqId)) {
        this._resetAiLoadingState()
        return
      }
      const normalized = _normalizeAiPayload(result)
      const hasContent = _hasAiContent(normalized)
      const model = (result && result.model) || ''
      const fromFallback = !!(result && result.from_fallback)
      const cachePreserved = !!(result && result.cache_preserved)

      // generating 中
      if (model === 'generating') {
        this._resetAiLoadingState()
        this.setData({ aiInlineNotice: 'AI 正在生成中，请稍后重试' })
        return
      }

      // cache_preserved 且有内容 — 返回旧缓存
      if (cachePreserved && hasContent) {
        this._resetAiLoadingState()
        this._aiResult = normalized
        this.setData({
          aiCards: _normalizeAiResult(normalized),
          aiFallback: false,
          aiFromCache: true,
          aiInlineNotice: '重新生成失败，已保留历史解析',
        })
        wx.showToast({ title: '重新生成失败，已保留历史解析', icon: 'none' })
        return
      }

      // from_fallback 且有旧内容 — 保留旧内容
      if (fromFallback && oldCards) {
        this._resetAiLoadingState()
        this.setData({
          aiFallback: false,
          aiInlineNotice: '重新生成失败，已保留当前解析',
        })
        wx.showToast({ title: '重新生成失败，已保留当前解析', icon: 'none' })
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
      this.setData({
        aiCards: _normalizeAiResult(normalized),
        aiFallback: false,
        aiFromCache: !!(result && result.from_cache),
        aiErrorText: '',
      })
      wx.showToast({ title: '已重新生成', icon: 'success' })
    } catch (e) {
      console.error('重新生成 AI 分析失败', e)
      if (requestId === this._aiRequestId && this._alive && this.data.wq && String(this.data.wq.id) === String(wqId)) {
        if (oldCards) {
          this._resetAiLoadingState()
          this.setData({
            aiFallback: false,
            aiInlineNotice: '重新生成失败，已保留历史解析',
          })
          wx.showToast({ title: '重新生成失败，已保留历史解析', icon: 'none' })
        } else {
          this._resetAiLoadingState()
          this.setData({ aiErrorText: '重新生成失败，请稍后重试' })
          wx.showToast({ title: '重新生成失败', icon: 'none' })
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

  async confirmMastered() {
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId || this.data.masterSubmitting) return

    this.setData({ masterSubmitting: true, masterConfirmVisible: false })
    try {
      await api.post('/wrong-questions/batch', {
        action: 'mark_mastered',
        ids: [wqId],
      })

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

      this._masterUndoTimer = setTimeout(() => {
        this._pendingMasterUndo = null
        this._masterUndoTimer = null
        this.setData({ masterUndoVisible: false })
      }, 5000)

      if (this.data.currentIdx < this.data.questionIds.length - 1) {
        this._masterAdvanceTimer = setTimeout(() => {
          this._masterAdvanceTimer = null
          this._navigateTo(this.data.currentIdx + 1, 150)
        }, 120)
      }
    } catch (e) {
      console.error('标记已掌握失败', e)
      this.setData({ masterSubmitting: false })
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
    }
  },

  async undoMastered() {
    const pending = this._pendingMasterUndo
    if (!pending) return

    try {
      await api.post('/wrong-questions/batch', {
        action: 'unmark_mastered',
        ids: [pending.wqId],
      })

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
      console.error('撤销已掌握失败', e)
      wx.showToast({ title: '撤销失败，请重试', icon: 'none' })
    }
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
    if (this.data && this.data.masterUndoVisible) {
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
        setTimeout(() => this.goBack(), 220)
        return
      }

      const nextIdx = Math.min(currentIdx, nextIds.length - 1)
      this.setData({ currentIdx: nextIdx })
      await this.loadData(nextIds[nextIdx])
      wx.showToast({ title: '已移出错题本', icon: 'none' })
    } catch (e) {
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

  // ---- Quiz-runner navigation events ----
  goPrevWrong(e) {
    this._navigateTo(e.detail.index, 150)
  },

  goNextWrong(e) {
    this._navigateTo(e.detail.index, 150)
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
    else wx.redirectTo({ url: '/pages/wrong-book/wrong-book' })
  },

  async _navigateTo(idx, animMs) {
    const wqId = this.data.questionIds[idx]
    if (!wqId) return
    // 并发保护
    if (this._switching) return
    if (idx < 0 || idx >= this.data.questionIds.length) return
    if (idx === this.data.currentIdx) return

    this._aiRequestId++
    this._resetAiLoadingState()
    this._switching = true
    // 延迟显示轻量切换提示（>250ms 才展示）
    var self = this
    this._switchMaskTimer = setTimeout(function() {
      self.setData({ showSwitchMask: true })
    }, 250)

    try {
      // 优先读缓存（含 TTL 保护）
      var wq = null
      var cached = this._wqCache[wqId]
      if (cached && Date.now() - cached.ts < 300000) {
        wq = cached.data
      }
      if (!wq) {
        wq = await api.get(`/wrong-questions/${wqId}`)
        if (!wq) throw new Error('not found')
        this._wqCache[wqId] = { data: wq, ts: Date.now() }
      }
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

      this._currentWqId = wqId
      this._errorTypeLabelText = raw.errorTypeLabelText
      this._aiResult = null

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
        aiFallback: false,
        aiErrorText: '',
        isCurrentMastered: _isWqMastered(wq),
        masterSubmitting: false,
        removeSubmitting: false,
      }

      // 检查切换后题目是否有已缓存 AI 分析
      var cachedAi = _detectAiCache(wq)
      if (cachedAi) {
        this._aiResult = normalizeAiAnalysisPayload(wq.ai_analysis)
        nextData.aiCards = _normalizeAiResult(this._aiResult)
        nextData.aiRequested = true
        nextData.aiFromCache = true
        nextData.aiFallback = false
        nextData.aiErrorText = ''
      }
      clearTimeout(this._switchMaskTimer)
      this._switching = false
      this.setData({ showSwitchMask: false })
      this.setData(nextData)
      this._checkRenderInvariant(raw._renderModel)
    } catch (e) {
      console.error('切换题目失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      clearTimeout(this._switchMaskTimer)
      // 切换失败时保持当前题不变，同时复位 AI 状态防止永久卡住
      this._switching = false
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
    var self = this
    api.get(`/wrong-questions/${wqId}`).then(function(wq) {
      if (wq) self._wqCache[wqId] = { data: wq, ts: Date.now() }
    }).catch(function() {})
  },
})
