const api = require('../../utils/api')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage,
  toPlainInlineMathText, needsRichRender, stripLeadingOptionLabel,
  optionTextToHtml, RENDER_MODE
} = require('../../utils/stem-render')

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

function _processWqData(wq) {
  const opts = wq.options || null
  const optionKeys = opts ? Object.keys(opts) : []
  const _renderModel = buildRenderModel(wq, opts)
  const blankOptionGroups = _enrichBlankOptionGroups(wq.content && wq.content.blank_option_groups, wq.answer, wq.wrong_answer)
  const optionItems = optionKeys.map((key) => {
    const rawText = (opts && opts[key]) || ''
    const stripped = stripLeadingOptionLabel(key, rawText)
    const plain = toPlainInlineMathText(stripped)
    const text = plain || stripped
    const needsRich = !plain && needsRichRender(stripped)
    const isCorrect = key === wq.answer
    const isUserAnswer = key === wq.wrong_answer
    let lineClass = ''
    let valueClass = 'option-value'
    if (isCorrect) {
      lineClass = 'correct'
      valueClass += ' right'
    } else if (isUserAnswer) {
      lineClass = 'user-answer'
      valueClass += ' wrong'
    }
    return {
      key,
      text,
      html: needsRich ? optionTextToHtml(key, stripped) : '',
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
      return Object.assign({}, opt, {
        key,
        _text: plain || optionText,
        _isCorrect: isCorrect,
        _isUserAnswer: !isCorrect && wrongAnswers[groupId] === key,
        _needsRich: needsRich,
        _html: needsRich ? optionTextToHtml(key, optionText) : '',
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
    questionIds: [],
    currentIdx: 0,
    totalQuestions: 0,
    swiperEnabled: false,
    contentState: '',
    showSwipeHint: false,
  },

  onLoad(options) {
    setRenderGuardPage('wrong-detail')
    const { id, ids } = options
    const questionIds = ids ? ids.split(',').map(Number).filter(Boolean) : []
    const currentId = Number(id)
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
    this.setData({ loading: true })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')
      const data = _processWqData(wq)
      data.aiResult = null
      data.aiFallback = false
      this.setData(data)
      this.setData({ loading: false })
      this.loadAiAnalysis(wqId)
    } catch (e) {
      console.error('加载错题详情失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false })
    }
  },

  async loadAiAnalysis(wqId) {
    this.setData({ aiLoading: true })
    try {
      const result = await api.post('/ai/error-analysis', { wrong_question_id: wqId })
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
      this.setData({ aiLoading: false, aiFallback: true })
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

  async _navigateTo(idx, animMs) {
    const wqId = this.data.questionIds[idx]
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')
      const data = _processWqData(wq)
      data.currentIdx = idx
      data.aiResult = null
      data.aiFallback = false

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
