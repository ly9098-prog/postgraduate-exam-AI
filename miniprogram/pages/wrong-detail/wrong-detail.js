const api = require('../../utils/api')
const config = require('../../config')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage,
  toPlainInlineMathText, needsRichRender, textToHtml
} = require('../../utils/stem-render')
const { isTrueFalseType } = require('../../utils/answer')
const adapter = require('../../utils/question-runner-adapter')

function _subjectLabel(s) {
  var map = {
    math2: '数学二', 'math2-calculus': '数学二·高数', 'math2-linalg': '数学二·线代',
    exam408: '408', 'exam408-ds': '408·DS', 'exam408-os': '408·OS',
    'exam408-co': '408·CO', 'exam408-cn': '408·CN',
    english: '英语',
  }
  return map[s] || s
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
  }
}

function _normalizeAiPayload(result) {
  var content = result && result.content ? result.content : result
  if (!content) return null
  if (typeof content === 'string') {
    return { mistake_diagnosis: content, knowledge_patch: '', review_task: '' }
  }
  return {
    mistake_diagnosis: content.mistake_diagnosis || content.error_analysis || content.diagnosis || content['错因诊断'] || '',
    knowledge_patch: content.knowledge_patch || content.knowledge_weakness || content.knowledge || content['补漏重点'] || '',
    review_task: content.review_task || content.suggestion || content.task || content['复练任务'] || '',
  }
}

function _hasAiContent(content) {
  return !!(content && [content.mistake_diagnosis, content.knowledge_patch, content.review_task].some(function(v) { return String(v || '').trim() }))
}

var _wqCache = {}
var _switchMaskTimer = null

Page({
  data: {
    wq: null,
    aiResult: null,
    aiLoading: false,
    aiFallback: false,
    aiErrorText: '',
    aiRequested: false,
    aiFromCache: false,
    loading: true,
    errorText: '',
    currentWqId: null,
    questionIds: [],
    currentIdx: 0,
    totalQuestions: 0,
    switching: false,
    safeModeActive: false,
    aiCards: null,
    aiRegenerating: false,
    aiInlineNotice: '',
    showSwitchMask: false,

    // quiz-runner data
    currentQuestion: null,
    wrongQuestions: [],
    runnerProgressPercent: 0,
  },

  onLoad(options) {
    setRenderGuardPage('wrong-detail')
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
    const currentIdx = questionIds.indexOf(currentId)
    this.setData({
      questionIds,
      currentIdx: currentIdx >= 0 ? currentIdx : 0,
      totalQuestions: questionIds.length,
    })
    this.loadData(currentId)
  },

  onUnload() {
    resetRenderGuard()
  },

  async loadData(wqId) {
    this._aiToken = ''
    this.setData({
      loading: true,
      errorText: '',
      aiLoading: false,
      aiRegenerating: false,
      aiResult: null,
      aiFallback: false,
      aiErrorText: '',
      aiRequested: false,
      aiFromCache: false,
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

      var data = {
        wq,
        currentQuestion,
        wrongQuestions,
        runnerProgressPercent: totalQ > 0 ? Math.round((this.data.currentIdx + 1) / totalQ * 100) : 0,
        subjectLabelText: raw.subjectLabelText,
        errorTypeLabelText: raw.errorTypeLabelText,
        loading: false,
        currentWqId: wqId,
        aiLoading: false,
        errorText: '',
        aiResult: null,
        aiCards: null,
        aiRequested: false,
        aiFromCache: false,
        aiFallback: false,
        aiErrorText: '',
      }

      // 如果后端已返回持久化的 AI 分析，直接展示
      var cachedAi = wq && wq.ai_analysis && typeof wq.ai_analysis === 'object' && Object.keys(wq.ai_analysis).length > 0
      if (cachedAi) {
        var ca = wq.ai_analysis
        data.aiResult = {
          mistake_diagnosis: ca.mistake_diagnosis || ca.error_analysis || '',
          knowledge_patch: ca.knowledge_patch || ca.knowledge_weakness || '',
          review_task: ca.review_task || ca.suggestion || '',
        }
        data.aiCards = _normalizeAiResult(data.aiResult)
        data.aiRequested = true
        data.aiFromCache = true
        data.aiFallback = false
        data.aiErrorText = ''
      }
      this.setData(data)
      // Render invariant check + trace
      if (data._renderModel) {
        this._checkRenderInvariant(data._renderModel)
        this._recordRenderTrace(data._renderModel.renderTrace)
      }
      // 不再自动调用 AI 分析，用户点击按钮后手动触发
    } catch (e) {
      console.error('加载错题详情失败', e)
      this.setData({
        loading: false,
        errorText: '错题不存在或已被移除',
        wq: null,
        aiResult: null,
        aiLoading: false,
        aiFallback: false,
        aiErrorText: '',
        aiRequested: false,
        aiFromCache: false,
      })
    }
  },

  onTapAiAnalysis() {
    if (this.data.aiLoading || this.data.aiRegenerating) return
    const wqId = this.data.currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId) {
      wx.showToast({ title: '缺少错题ID', icon: 'none' })
      return
    }
    this.loadAiAnalysis(wqId)
  },

  async loadAiAnalysis(wqId) {
    if (!wqId) return
    if (this.data.aiLoading) return
    const token = String(wqId) + '-' + Date.now()
    this._aiToken = token
    this.setData({
      aiLoading: true,
      aiRequested: true,
      aiFallback: false,
      aiErrorText: '',
      aiInlineNotice: '',
    })
    try {
      const result = await api.post('/ai/error-analysis', { wrong_question_id: wqId })
      // Stale response guard
      if (this._aiToken !== token || !this.data.wq || String(this.data.wq.id) !== String(wqId)) return
      const normalized = _normalizeAiPayload(result)
      const hasContent = _hasAiContent(normalized)
      const model = (result && result.model) || ''
      const fromFallback = !!(result && result.from_fallback)

      if (model === 'generating') {
        this.setData({ aiLoading: false, aiFallback: true, aiErrorText: 'AI 分析正在生成中，请稍后重试' })
        return
      }
      if (fromFallback && !hasContent) {
        this.setData({ aiLoading: false, aiFallback: true, aiErrorText: 'AI 服务暂时不可用，请稍后重试' })
        return
      }
      if (!hasContent) {
        this.setData({ aiLoading: false, aiFallback: true, aiErrorText: 'AI 分析结果为空，请稍后重试' })
        return
      }
      this.setData({
        aiResult: normalized,
        aiCards: _normalizeAiResult(normalized),
        aiFallback: false,
        aiFromCache: !!(result && result.from_cache),
        aiErrorText: '',
        aiInlineNotice: '',
        aiLoading: false,
      })
    } catch (e) {
      console.error('加载 AI 分析失败', e)
      if (this._aiToken === token && this.data.wq && String(this.data.wq.id) === String(wqId)) {
        const msg = e && e.errMsg && String(e.errMsg).includes('timeout')
          ? 'AI 分析生成超时，请稍后重试'
          : 'AI 分析生成失败，请稍后重试'
        this.setData({
          aiLoading: false,
          aiFallback: true,
          aiErrorText: msg,
        })
      }
    }
  },

  async regenerateAiAnalysis() {
    const wqId = this.data.currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId || this.data.aiLoading || this.data.aiRegenerating) return
    // 保存旧内容，失败时恢复
    const oldCards = this.data.aiCards
    const oldResult = this.data.aiResult
    const token = String(wqId) + '-' + Date.now()
    this._aiToken = token
    this.setData({
      aiRegenerating: true,
      aiErrorText: '',
      aiFallback: false,
      aiInlineNotice: '',
    })
    try {
      const result = await api.post('/ai/error-analysis', {
        wrong_question_id: wqId,
        force_regenerate: true,
      })
      // Stale response guard — 必须复位 aiRegenerating
      if (this._aiToken !== token || !this.data.wq || String(this.data.wq.id) !== String(wqId)) {
        this.setData({ aiRegenerating: false })
        return
      }
      const normalized = _normalizeAiPayload(result)
      const hasContent = _hasAiContent(normalized)
      const model = (result && result.model) || ''
      const fromFallback = !!(result && result.from_fallback)
      const cachePreserved = !!(result && result.cache_preserved)

      // generating 中
      if (model === 'generating') {
        this.setData({
          aiRegenerating: false,
          aiInlineNotice: 'AI 正在生成中，请稍后重试',
        })
        return
      }

      // cache_preserved 且有内容 — 返回旧缓存
      if (cachePreserved && hasContent) {
        this.setData({
          aiResult: normalized,
          aiCards: _normalizeAiResult(normalized),
          aiRegenerating: false,
          aiFallback: false,
          aiFromCache: true,
          aiInlineNotice: '重新生成失败，已保留历史解析',
        })
        wx.showToast({ title: '重新生成失败，已保留历史解析', icon: 'none' })
        return
      }

      // from_fallback 且有旧内容 — 保留旧内容
      if (fromFallback && oldCards) {
        this.setData({
          aiRegenerating: false,
          aiFallback: false,
          aiInlineNotice: '重新生成失败，已保留当前解析',
        })
        wx.showToast({ title: '重新生成失败，已保留当前解析', icon: 'none' })
        return
      }

      // 无内容
      if (!hasContent) {
        if (oldCards) {
          this.setData({
            aiRegenerating: false,
            aiFallback: false,
            aiInlineNotice: '返回内容为空，已保留当前解析',
          })
          wx.showToast({ title: '返回内容为空，已保留当前解析', icon: 'none' })
        } else {
          this.setData({
            aiRegenerating: false,
            aiFallback: true,
            aiErrorText: 'AI 返回内容为空，请稍后重试',
          })
        }
        return
      }

      // 成功 — 更新为新内容
      this.setData({
        aiResult: normalized,
        aiCards: _normalizeAiResult(normalized),
        aiRegenerating: false,
        aiFallback: false,
        aiFromCache: !!(result && result.from_cache),
        aiInlineNotice: '',
        aiErrorText: '',
      })
      wx.showToast({ title: '已重新生成', icon: 'success' })
    } catch (e) {
      console.error('重新生成 AI 分析失败', e)
      if (this._aiToken === token && this.data.wq && String(this.data.wq.id) === String(wqId)) {
        if (oldCards) {
          this.setData({
            aiRegenerating: false,
            aiFallback: false,
            aiInlineNotice: '重新生成失败，已保留历史解析',
          })
          wx.showToast({ title: '重新生成失败，已保留历史解析', icon: 'none' })
        } else {
          this.setData({ aiRegenerating: false, aiErrorText: '重新生成失败，请稍后重试' })
          wx.showToast({ title: '重新生成失败', icon: 'none' })
        }
      }
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
    if (!trace) return
    var traces = this.data.renderTraces
    traces = traces.concat([trace])
    if (traces.length > 200) traces = traces.slice(-200)
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
        this.setData({
          currentQuestion,
          subjectLabelText: raw.subjectLabelText,
          errorTypeLabelText: raw.errorTypeLabelText,
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
    } else if (this.data.currentWqId) {
      this.loadData(this.data.currentWqId)
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
    if (this.data.switching) return
    if (idx < 0 || idx >= this.data.questionIds.length) return
    if (idx === this.data.currentIdx) return

    this._aiToken = ''
    this.setData({ switching: true })
    // 延迟显示轻量切换提示（>250ms 才展示）
    _switchMaskTimer = setTimeout(() => {
      this.setData({ showSwitchMask: true })
    }, 250)

    try {
      // 优先读缓存
      var wq = _wqCache[wqId]
      if (!wq) {
        wq = await api.get(`/wrong-questions/${wqId}`)
        if (!wq) throw new Error('not found')
        _wqCache[wqId] = wq
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

      var nextData = {
        wq,
        currentIdx: idx,
        currentWqId: wqId,
        currentQuestion,
        wrongQuestions,
        runnerProgressPercent: totalQ > 0 ? Math.round((idx + 1) / totalQ * 100) : 0,
        subjectLabelText: raw.subjectLabelText,
        errorTypeLabelText: raw.errorTypeLabelText,
        switching: false,
        aiLoading: false,
        aiRegenerating: false,
        aiResult: null,
        aiCards: null,
        aiRequested: false,
        aiFromCache: false,
        aiFallback: false,
        aiErrorText: '',
      }

      // 检查切换后题目是否有已缓存 AI 分析
      var cachedAi = wq && wq.ai_analysis && typeof wq.ai_analysis === 'object' && Object.keys(wq.ai_analysis).length > 0
      if (cachedAi) {
        var ca = wq.ai_analysis
        nextData.aiResult = {
          mistake_diagnosis: ca.mistake_diagnosis || ca.error_analysis || '',
          knowledge_patch: ca.knowledge_patch || ca.knowledge_weakness || '',
          review_task: ca.review_task || ca.suggestion || '',
        }
        nextData.aiCards = _normalizeAiResult(nextData.aiResult)
        nextData.aiRequested = true
        nextData.aiFromCache = true
        nextData.aiFallback = false
        nextData.aiErrorText = ''
      }
      clearTimeout(_switchMaskTimer)
      this.setData({ switching: false, showSwitchMask: false })
      this.setData(nextData)
      this._checkRenderInvariant(raw._renderModel)
    } catch (e) {
      console.error('切换题目失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      clearTimeout(_switchMaskTimer)
      // 切换失败时保持当前题不变，同时复位 AI 状态防止永久卡住
      this.setData({ switching: false, showSwitchMask: false, aiRegenerating: false })
    }
  },

  scrollToAiCard() {
    wx.pageScrollTo({ selector: '#ai-card', duration: 220 })
  },

  _prefetchWrongQuestion(idx) {
    if (idx < 0 || idx >= this.data.questionIds.length) return
    var wqId = this.data.questionIds[idx]
    if (!wqId || _wqCache[wqId]) return
    api.get(`/wrong-questions/${wqId}`).then(function(wq) {
      if (wq) _wqCache[wqId] = wq
    }).catch(function() {})
  },
})
