const api = require('../../utils/api')
const config = require('../../config')

function _textToHtml(text) {
  if (!text) return ''
  const parts = text.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/)
  const out = parts.map((part, i) => {
    if (i % 2 === 1) return part
    return part.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
  })
  return '<p>' + out.join('') + '</p>'
}

function _needsRichRender(text) {
  if (!text) return false
  return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(text) || /<\/?[a-z][\s\S]*>/i.test(text)
}

function _toPlainInlineMathText(text) {
  if (!text) return ''
  const source = String(text)
  if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
  let plain = source.replace(/\$([^$\n]+?)\$/g, (_, expr) => expr.replace(/\\leq/g, '≤').replace(/\\geq/g, '≥').replace(/\\neq/g, '≠').replace(/\\times/g, '×').replace(/\\cdot/g, '·').trim())
  if (/\\[a-zA-Z]+/.test(plain)) return null
  return plain.replace(/[ \t]+/g, ' ').trim()
}

function _stripLeadingOptionLabel(key, value) {
  const text = String(value || '').trim()
  if (!key || !text) return text
  const label = String(key).trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const labelPattern = new RegExp('^' + label + '[\\s\\u00A0]*[.．、:：）)]\\s*', 'i')
  return text.replace(labelPattern, '')
}

function _segmentsToText(segments) {
  if (!Array.isArray(segments)) return ''
  return segments.map(seg => {
    if (!seg) return ''
    if (seg.type === 'text' || seg.type === 'newline') return seg.text || ''
    return seg.alt ? ('$' + seg.alt + '$') : ''
  }).join('')
}

function _textToSegments(text) {
  if (!text) return []
  const lines = String(text).split('\n')
  return lines.flatMap((line, i) => {
    const segs = line ? [{ type: 'text', text: line }] : []
    if (i < lines.length - 1) segs.push({ type: 'newline' })
    return segs
  })
}

Page({
  data: {
    // 页面阶段: entry / practice / result
    phase: 'entry',

    // 入口
    stats: null,
    entryLoading: true,

    // 练习
    questions: [],
    currentIndex: 0,
    totalQuestions: 0,
    currentQuestion: null,
    optionKeys: [],
    selectedAnswer: '',
    submitted: false,
    isCorrect: false,
    correctAnswer: '',
    practiceLoading: false,
    submittingAnswer: false,
    enableMathImage: false,

    // 滑动动画
    animClass: '',

    // 环图样式（JS 计算避免 WXML 编译问题）
    _ringStyle: '',
    _accuracyStyle: '',

    // 结果
    results: [],
    correctCount: 0,
    wrongCount: 0,
  },

  onLoad() {
    this.setData({ enableMathImage: config.enableMathImage || false })
    this._loadEntry()
  },

  _calcRingStyle(stats) {
    const pct = stats && stats.total_scheduled > 0
      ? Math.round((stats.total_scheduled - stats.remaining_today) / stats.total_scheduled * 360)
      : 0
    return `background: conic-gradient(#5B7B9A ${pct}deg, #EDF1F5 0deg)`
  },

  _calcAccuracyStyle(correctCount, totalQuestions) {
    const pct = totalQuestions > 0 ? Math.round(correctCount / totalQuestions * 360) : 0
    return `background: conic-gradient(#6B9B6B 0deg ${pct}deg, #EDF1F5 0deg)`
  },

  async _loadEntry() {
    this.setData({ entryLoading: true })
    try {
      const stats = await api.get('/review/schedule-stats')
      this.setData({ stats, entryLoading: false, _ringStyle: this._calcRingStyle(stats) })
    } catch (e) {
      console.error('加载复习统计失败', e)
      this.setData({ entryLoading: false })
    }
  },

  async startReview() {
    this.setData({ practiceLoading: true, phase: 'practice' })
    try {
      const res = await api.get('/review/today', { limit: 50 })
      const questions = (res.questions || []).map(q => this._enrichQuestion(q))
      this.setData({
        questions,
        totalQuestions: questions.length,
        practiceLoading: false,
        currentIndex: 0,
        results: [],
        correctCount: 0,
        wrongCount: 0,
        selectedAnswer: '',
        submitted: false,
      })
      if (questions.length > 0) {
        this._showQuestion(0)
      } else {
        // 没有待复习题目
        wx.showToast({ title: '今日没有待复习题目', icon: 'none' })
        this.setData({ phase: 'entry' })
        this._loadEntry()
      }
    } catch (e) {
      console.error('加载复习题目失败', e)
      this.setData({ practiceLoading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  _enrichQuestion(q) {
    const stemText = (q.content && (q.content.text || q.content.stem)) || q.stem || ''
    // 尝试从 options 获取选项
    let opts = null
    let optionKeys = []
    if (q.options && Object.keys(q.options).length > 0) {
      opts = q.options
      optionKeys = Object.keys(opts)
    }
    // 判断题特殊处理
    if (q.question_type === 'true_false' || q.question_type === 'judgement') {
      opts = { A: '正确', B: '错误' }
      optionKeys = ['A', 'B']
    }

    // 提取选项文本
    const optText = {}
    const optNeedsRich = {}
    const optHtml = {}
    for (const key of optionKeys) {
      const raw = (opts && opts[key]) || ''
      const text = _stripLeadingOptionLabel(key, raw)
      const plain = _toPlainInlineMathText(text)
      optText[key] = plain || text
      optNeedsRich[key] = !plain && _needsRichRender(text)
      optHtml[key] = optNeedsRich[key] ? _textToHtml(text) : ''
    }

    // 题目内容
    const plainStem = _toPlainInlineMathText(stemText)
    const stemNeedsRich = !plainStem && _needsRichRender(stemText)
    const stemHtml = stemNeedsRich ? _textToHtml(stemText) : ''
    const stemSegments = (q.content && q.content.render_mode === 'segments') ? _textToSegments(stemText) : []

    return {
      ...q,
      _opts: opts,
      _optionKeys: optionKeys,
      _optText: optText,
      _optNeedsRich: optNeedsRich,
      _optHtml: optHtml,
      _stemText: plainStem || stemText,
      _stemNeedsRich: stemNeedsRich,
      _stemHtml: stemHtml,
      _stemSegments: stemSegments,
    }
  },

  _showQuestion(index) {
    const q = this.data.questions[index]
    if (!q) return
    this.setData({
      currentIndex: index,
      currentQuestion: q,
      optionKeys: q._optionKeys,
      selectedAnswer: '',
      submitted: false,
      isCorrect: false,
      correctAnswer: '',
    })
  },

  /* ==================== 选择答案 ==================== */

  selectOption(e) {
    if (this.data.submitted || this.data.submittingAnswer) return
    const opt = e.currentTarget.dataset.option
    if (!opt) return
    this.setData({ selectedAnswer: opt, submitted: true, submittingAnswer: true })
    this._submitAnswer(opt)
  },

  async _submitAnswer(answer) {
    const q = this.data.currentQuestion
    try {
      const res = await api.post('/review/grade-submit', {
        schedule_id: q.schedule_id,
        question_id: q.question_id,
        user_answer: answer,
      })
      const results = [...this.data.results, {
        question_id: q.question_id,
        is_correct: res.is_correct,
        correct_answer: res.correct_answer,
        user_answer: answer,
      }]
      const correctCount = results.filter(r => r.is_correct).length
      const totalQuestions = this.data.totalQuestions
      this.setData({
        isCorrect: res.is_correct,
        correctAnswer: res.correct_answer,
        submittingAnswer: false,
        results,
        correctCount,
        wrongCount: results.filter(r => !r.is_correct).length,
        _accuracyStyle: this._calcAccuracyStyle(correctCount, totalQuestions),
      })
    } catch (e) {
      console.error('提交答案失败', e)
      wx.showToast({ title: '提交失败', icon: 'none' })
      this.setData({ submitted: false, selectedAnswer: '', submittingAnswer: false })
    }
  },

  /* ==================== 切换题目 ==================== */

  goNext() {
    if (this._animating) return
    const next = this.data.currentIndex + 1
    if (next >= this.data.totalQuestions) {
      this.setData({ phase: 'result' })
      return
    }
    this._animating = true
    this.setData({ animClass: 'slide-out-left' })
    setTimeout(() => {
      this._showQuestion(next)
      this.setData({ animClass: 'slide-in' })
      setTimeout(() => {
        this.setData({ animClass: '' })
        this._animating = false
      }, 120)
    }, 120)
  },

  goPrev() {
    if (this._animating) return
    if (this.data.currentIndex <= 0) return
    this._animating = true
    this.setData({ animClass: 'slide-out-right' })
    setTimeout(() => {
      this._showQuestion(this.data.currentIndex - 1)
      this.setData({ animClass: 'slide-in' })
      setTimeout(() => {
        this.setData({ animClass: '' })
        this._animating = false
      }, 120)
    }, 120)
  },

  /* ==================== 滑动切换 ==================== */

  onTouchStart(e) {
    if (this.data.submittingAnswer || this._animating) return
    const t = e.touches[0]
    this._touchX = t.clientX
    this._touchY = t.clientY
  },

  onTouchEnd(e) {
    if (this.data.submittingAnswer || this._animating) return
    if (this._touchX === undefined) return

    const t = e.changedTouches[0]
    const dx = t.clientX - this._touchX
    const dy = t.clientY - this._touchY

    if (Math.abs(dy) > Math.abs(dx) * 1.5) {
      this._touchX = undefined
      return
    }
    if (Math.abs(dx) < 60) {
      this._touchX = undefined
      return
    }

    this._touchX = undefined
    if (dx < 0) this.goNext()
    else this.goPrev()
  },

  /* ==================== 完成 ==================== */

  finishReview() {
    wx.navigateBack()
  },

  /* ==================== 工具 ==================== */

  subjectLabel(s) {
    const map = {
      math2: '数学二', 'math2-calculus': '数学二·高数', 'math2-linalg': '数学二·线代',
      exam408: '408', 'exam408-ds': '408·DS', 'exam408-os': '408·OS',
      'exam408-co': '408·CO', 'exam408-cn': '408·CN',
      english: '英语',
    }
    return map[s] || s || ''
  },
})
