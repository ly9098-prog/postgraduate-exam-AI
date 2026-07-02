const api = require('../../utils/api')
const config = require('../../config')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage,
  toPlainInlineMathText, needsRichRender, stripLeadingOptionLabel,
  textToHtml, RENDER_MODE
} = require('../../utils/stem-render')
const { normalizeAnswerSet, isTrueFalseType, isMultipleChoiceType } = require('../../utils/answer')

function _normalizeBlankAnswer(answer) {
  if (!answer) return {}
  if (typeof answer === 'object') return answer
  const result = {}
  String(answer).split(/[;；,，\n]+/).forEach((part) => {
    const match = part.trim().match(/^(.+?)\s*[:：=]\s*([A-Za-z])$/)
    if (match) result[match[1].trim()] = match[2].trim().toUpperCase()
  })
  return result
}

function _normalizeBlankOptionList(options) {
  if (Array.isArray(options)) return options
  if (options && typeof options === 'object') {
    return Object.keys(options).map((key) => ({ key, text: options[key] }))
  }
  return []
}

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

function _getBlankOptionGroups(q) {
  if (!q) return []
  if (q.content && Array.isArray(q.content.blank_option_groups)) return q.content.blank_option_groups
  if (Array.isArray(q.blank_option_groups)) return q.blank_option_groups
  return []
}

function _processWqData(wq, safeMode) {
  const questionType = wq.question_type || wq.type || ''
  // Judgement fallback
  let opts = wq.options || null
  if ((!opts || Object.keys(opts).length === 0) && isTrueFalseType(questionType)) {
    opts = { A: '正确', B: '错误' }
  }
  const optionKeys = opts ? Object.keys(opts) : []
  var renderCfg = { enableMathImage: false, DEV: config.DEV }
  if (safeMode) renderCfg.SAFE_MODE = true
  const _renderModel = buildRenderModel(wq, opts, renderCfg)
  const blankOptionGroups = _enrichBlankOptionGroups(_getBlankOptionGroups(wq), wq.answer, wq.wrong_answer)

  // Multi-choice: use set-based comparison
  const correctSet = isMultipleChoiceType(questionType) ? normalizeAnswerSet(wq.answer) : null
  const userSet = isMultipleChoiceType(questionType) ? normalizeAnswerSet(wq.wrong_answer) : null

  const optionItems = optionKeys.map((key) => {
    const rawText = (opts && opts[key]) || ''
    const stripped = stripLeadingOptionLabel(key, rawText)
    const plain = toPlainInlineMathText(stripped)
    const text = plain || stripped
    const needsRich = !plain && needsRichRender(stripped)
    let isCorrect = key === wq.answer
    let isUserAnswer = key === wq.wrong_answer
    if (correctSet) {
      isCorrect = !!correctSet[key]
    }
    if (userSet) {
      isUserAnswer = !!userSet[key]
    }
    let lineClass = ''
    let valueClass = 'option-value'
    if (isCorrect && isUserAnswer) {
      lineClass = 'both'
      valueClass += ' both'
    } else if (isCorrect) {
      lineClass = 'correct'
      valueClass += ' right'
    } else if (isUserAnswer) {
      lineClass = 'user-answer'
      valueClass += ' wrong'
    }
    return {
      key,
      text,
      html: needsRich ? textToHtml(stripped) : '',
      needsRich,
      className: valueClass,
      lineClass,
    }
  })
  return {
    wq,
    optionKeys,
    optionItems,
    blankOptionGroups,
    _renderModel,
    subjectLabelText: _subjectLabel(wq.subject),
    errorTypeLabelText: _errorTypeLabel(wq.error_type),
  }
}

function _enrichBlankOptionGroups(groups, answer, wrongAnswer) {
  const blankAnswers = _normalizeBlankAnswer(answer)
  const wrongAnswers = _normalizeBlankAnswer(wrongAnswer)
  return (groups || []).map((group) => {
    const groupId = String((group && group.id) || '').trim()
    const options = _normalizeBlankOptionList(group && group.options).map((opt) => {
      const key = String((opt && opt.key) || '').trim().toUpperCase()
      const text = String((opt && opt.text) || '').trim()
      const optionText = stripLeadingOptionLabel(key, text)
      const plain = toPlainInlineMathText(optionText)
      const needsRich = !plain && needsRichRender(optionText)
      const isCorrect = blankAnswers[groupId] === key
      const isUser = wrongAnswers[groupId] === key
      return Object.assign({}, opt, {
        key,
        _text: plain || optionText,
        _isCorrect: isCorrect,
        _isUserAnswer: isUser,
        _isBoth: isCorrect && isUser,
        _needsRich: needsRich,
        _html: needsRich ? textToHtml(optionText) : '',
      })
    }).filter((opt) => opt.key)
    return { id: groupId, options }
  }).filter((group) => group.id && group.options.length > 0)
}

Page({
  data: {
    wq: null,
    optionKeys: [],
    _renderModel: null,
    optionItems: [],
    aiResult: null,
    aiLoading: false,
    aiFallback: false,
    loading: true,
    errorText: '',
    currentWqId: null,
    questionIds: [],
    currentIdx: 0,
    totalQuestions: 0,
    swiperEnabled: false,
    contentState: '',
    showSwipeHint: false,
    safeModeActive: false,
    renderTraces: [],
  },

  onLoad(options) {
    setRenderGuardPage('wrong-detail')
    const currentId = Number(options.id)
    // Prefer storage-based ids list (from wrong-book), fallback to single-question mode
    let questionIds = []
    try {
      const stored = wx.getStorageSync('wrong_detail_ids')
      if (Array.isArray(stored) && stored.length > 0) {
        const normalized = stored.map(Number).filter(Number.isFinite)
        if (normalized.includes(currentId)) questionIds = normalized
      }
    } catch (_) {}
    const currentIdx = questionIds.indexOf(currentId)
    const swiperEnabled = questionIds.length > 1
    this.setData({
      questionIds,
      currentIdx: currentIdx >= 0 ? currentIdx : 0,
      totalQuestions: questionIds.length,
      swiperEnabled,
      showSwipeHint: swiperEnabled,
    })
    if (swiperEnabled) {
      setTimeout(() => { this.setData({ showSwipeHint: false }) }, 3000)
    }
    this.loadData(currentId)
  },

  onUnload() {
    resetRenderGuard()
  },

  async loadData(wqId) {
    this.setData({ loading: true, errorText: '' })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')
      const data = _processWqData(wq, this.data.safeModeActive)
      data.aiResult = null
      data.aiFallback = false
      data.errorText = ''
      this.setData(data)
      this.setData({ loading: false, currentWqId: wqId })
      // Render invariant check + trace
      if (data._renderModel) {
        this._checkRenderInvariant(data._renderModel)
        this._recordRenderTrace(data._renderModel.renderTrace)
      }
      this.loadAiAnalysis(wqId)
    } catch (e) {
      console.error('加载错题详情失败', e)
      this.setData({
        loading: false,
        errorText: '错题不存在或已被移除',
        wq: null,
        optionItems: [],
        blankOptionGroups: [],
        aiResult: null,
      })
    }
  },

  async loadAiAnalysis(wqId) {
    const token = wqId + '-' + Date.now()
    this._aiToken = token
    this.setData({ aiLoading: true })
    try {
      const result = await api.post('/ai/error-analysis', { wrong_question_id: wqId })
      // Stale response guard
      if (this._aiToken !== token || !this.data.wq || this.data.wq.id !== wqId) return
      const content = result.content
      if (content) {
        if (content.error_analysis) {
          content.error_analysis = content.error_analysis.replace(/^切入点[：:]\s*/, '')
        }
        if (content.knowledge_weakness) {
          content.knowledge_weakness = content.knowledge_weakness.replace(/^核心考点[：:]\s*/, '')
        }
      }
      this.setData({
        aiResult: content,
        aiFallback: result.from_fallback,
        aiLoading: false,
      })
    } catch (e) {
      console.error('加载 AI 分析失败', e)
      // Only update if still on the same question
      if (this._aiToken === token && this.data.wq && this.data.wq.id === wqId) {
        this.setData({ aiLoading: false, aiFallback: true })
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
      var data = _processWqData(this.data.wq, true)
      if (data._renderModel) {
        data.aiResult = this.data.aiResult
        data.aiFallback = this.data.aiFallback
        this.setData(data)
        console.warn('[SELF_HEAL] wrong-detail re-rendered in SAFE_MODE, mode=' + data._renderModel.mode)
      }
    }
  },

  // ---- 左滑/右滑切换 ----
  onTouchStart(e) {
    if (this._animating || !this.data.swiperEnabled) return
    const t = e.touches[0]
    this._touchX = t.clientX
    this._touchY = t.clientY
    this._touchTime = Date.now()
    this._swiped = false
  },

  onTouchEnd(e) {
    if (this._animating || !this.data.swiperEnabled) return
    if (this._touchX === undefined) return

    const t = e.changedTouches[0]
    const dx = t.clientX - this._touchX
    const dy = t.clientY - this._touchY
    const dt = Date.now() - this._touchTime

    if (Math.abs(dy) > Math.abs(dx) * 1.5) {
      this._touchX = undefined
      return
    }

    if (Math.abs(dx) < 60) {
      this._touchX = undefined
      return
    }

    this._swiped = true
    this._touchX = undefined

    const isLeft = dx < 0
    const currentIdx = this.data.currentIdx
    const total = this.data.totalQuestions
    const canGo = isLeft ? currentIdx < total - 1 : currentIdx > 0

    if (!canGo) {
      this._animating = true
      this.setData({ contentState: isLeft ? 'edge-left' : 'edge-right' })
      setTimeout(() => {
        this.setData({ contentState: '' })
        this._animating = false
      }, 250)
      return
    }

    const animMs = Math.min(Math.max(dt * 0.5, 120), 200)
    this._animating = true
    this._swipeDir = isLeft ? 'left' : 'right'
    this.setData({ contentState: isLeft ? 'slide-out-left' : 'slide-out-right' })

    const nextIdx = currentIdx + (isLeft ? 1 : -1)
    setTimeout(() => {
      this._navigateTo(nextIdx, animMs)
    }, animMs)
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
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')
      const data = _processWqData(wq, this.data.safeModeActive)
      data.currentIdx = idx
      data.currentWqId = wqId
      data.aiResult = null
      data.aiFallback = false
      this._checkRenderInvariant(data._renderModel)
      this._recordRenderTrace(data._renderModel && data._renderModel.renderTrace)

      // 先瞬间定位到滑入起始位置（transition: none）
      const fromState = this._swipeDir === 'left' ? 'from-right' : 'from-left'
      this.setData(Object.assign({ contentState: fromState }, data))

      // 下一帧启用过渡，滑入目标位置
      setTimeout(() => {
        this.setData({ contentState: '' })
        setTimeout(() => { this._animating = false }, animMs)
      }, 50)

      this.loadAiAnalysis(wqId)
    } catch (e) {
      console.error('切换题目失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ contentState: '' })
      this._animating = false
    }
  },
})
