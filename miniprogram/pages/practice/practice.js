const api = require('../../utils/api')

// 将纯文本（可能含 $...$ LaTeX）转为 mp-html 可接受的 HTML 字符串。
// $...$ 内部保持原样，外部普通文本做 HTML 转义，换行转 <br>。
function _textToHtml(text) {
  if (!text) return ''
  // 按 $$ 和 $ 分段，奇数索引段为公式，偶数索引段为普通文本
  const parts = text.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/)
  const out = parts.map((part, i) => {
    if (i % 2 === 1) return part  // 公式段：原样保留
    return part
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>')
  })
  return '<p>' + out.join('') + '</p>'
}

Page({
  data: {
    // 设置
    selectedSubject: '',
    count: 5,
    started: false,
    loading: false,
    submitting: false,

    // 题目列表
    questions: [],
    currentIndex: 0,
    totalQuestions: 0,
    currentQuestion: null,
    optionKeys: [],
    selectedFlags: {},

    // 答题卡
    answerMap: {},
    answeredCount: 0,

    // 提交后
    submitted: false,
    results: {},
    correctCount: 0,
    wrongCount: 0,

    // 计时
    startTime: 0,
    elapsedSec: 0,
    elapsedText: '00:00',
    _timer: null,

    // 答题卡弹窗
    showSheet: false,

    // 滑动动画
    animClass: '',
  },

  /* ==================== 设置阶段 ==================== */

  chooseSubject(e) {
    this.setData({ selectedSubject: e.currentTarget.dataset.subject })
  },

  setCount(e) {
    this.setData({ count: e.currentTarget.dataset.count })
  },

  async startPractice() {
    this.setData({
      started: true,
      currentIndex: 0,
      answerMap: {},
      answeredCount: 0,
      results: {},
      submitted: false,
      correctCount: 0,
      wrongCount: 0,
      elapsedSec: 0,
      startTime: Date.now(),
    })
    this._startTimer()
    await this._loadQuestions()
  },

  _startTimer() {
    this._clearTimer()
    this._timer = setInterval(() => {
      const sec = Math.floor((Date.now() - this.data.startTime) / 1000)
      this.setData({ elapsedSec: sec, elapsedText: this._fmt(sec) })
    }, 1000)
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
  },

  _clearTimer() {
    if (this._timer) {
      clearInterval(this._timer)
      this._timer = null
    }
  },

  async _loadQuestions() {
    this.setData({ loading: true })
    try {
      const res = await api.post('/practice/batch-questions', {
        subject: this.data.selectedSubject,
        count: this.data.count || 5,
        exclude_ids: [],
      })
      const questions = res.questions || []
      this.setData({ questions, totalQuestions: questions.length, loading: false })
      if (questions.length > 0) {
        this._showQuestion(0)
      } else {
        wx.showToast({ title: '该科目暂无题目', icon: 'none' })
      }
    } catch (e) {
      console.error('加载题目失败', e)
      this.setData({ loading: false })
      wx.showToast({ title: '加载题目失败', icon: 'none' })
    }
  },

  _showQuestion(index) {
    const q = this.data.questions[index]
    if (!q) return
    const optionKeys = q.options ? Object.keys(q.options) : []
    const answer = this.data.answerMap[String(q.id)] || ''
    const isMulti = q.question_type === 'multiple_choice'
    const selectedFlags = {}
    for (const key of optionKeys) {
      selectedFlags[key] = isMulti ? answer.split(',').indexOf(key) >= 0 : answer === key
    }
    // 预处理 LaTeX → mp-html 可接受的 HTML 字符串
    const stemText = (q.content && q.content.text) || ''
    q._stemHtml = _textToHtml(stemText)
    const optHtml = {}
    for (const key of optionKeys) {
      optHtml[key] = _textToHtml(q.options[key] || '')
    }
    q._optHtml = optHtml
    this.setData({
      currentIndex: index,
      currentQuestion: q,
      optionKeys,
      selectedFlags,
    })
  },

  goQuestion(e) {
    const idx = parseInt(e.currentTarget.dataset.index, 10)
    if (!isNaN(idx) && idx >= 0 && idx < this.data.totalQuestions) {
      this.setData({ showSheet: false })
      this._showQuestion(idx)
    }
  },

  toggleSheet() {
    this.setData({ showSheet: !this.data.showSheet })
  },

  closeSheet() {
    this.setData({ showSheet: false })
  },

  /* ==================== 滑动系统 ==================== */

  onTouchStart(e) {
    if (this.data.submitted || this._animating) return
    const t = e.touches[0]
    this._touchX = t.clientX
    this._touchY = t.clientY
    this._touchTime = Date.now()
    this._swiped = false
  },

  onTouchEnd(e) {
    if (this.data.submitted || this._animating) return
    if (this._touchX === undefined) return

    const t = e.changedTouches[0]
    const dx = t.clientX - this._touchX
    const dy = t.clientY - this._touchY
    const dt = Date.now() - this._touchTime

    // 垂直滚动 > 水平移动 → 不触发
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
    const canGo = isLeft
      ? this.data.currentIndex < this.data.totalQuestions - 1
      : this.data.currentIndex > 0

    if (!canGo) {
      // 边界弹性阻尼
      this._animating = true
      this.setData({ animClass: isLeft ? 'edge-left' : 'edge-right' })
      setTimeout(() => {
        this.setData({ animClass: '' })
        this._animating = false
      }, 200)
      return
    }

    // 动画时长：短滑快切
    const animMs = dt < 200 ? 120 : 160
    this._animating = true
    this.setData({ animClass: isLeft ? 'slide-out-left' : 'slide-out-right' })

    setTimeout(() => {
      const next = this.data.currentIndex + (isLeft ? 1 : -1)
      this._showQuestion(next)
      this.setData({ animClass: 'slide-in' })

      setTimeout(() => {
        this.setData({ animClass: '' })
        this._animating = false
        this._swiped = false
      }, animMs)
    }, animMs)
  },

  selectOption(e) {
    if (this._animating || this.data.submitted) return
    if (this._swiped) {
      this._swiped = false
      return
    }

    const opt = e.currentTarget.dataset.option
    const q = this.data.currentQuestion
    if (!q) return

    const isMulti = q.question_type === 'multiple_choice'
    const key = String(q.id)
    const prev = this.data.answerMap[key] || ''

    let newAnswer
    if (isMulti) {
      const sel = prev ? prev.split(',') : []
      const idx = sel.indexOf(opt)
      if (idx >= 0) sel.splice(idx, 1)
      else sel.push(opt)
      newAnswer = sel.join(',')
    } else {
      newAnswer = prev === opt ? '' : opt
    }

    // 空答案从 answerMap 移除，保证统计准确
    const answerMap = { ...this.data.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredCount = Object.keys(answerMap).length
    const optionKeys = this.data.optionKeys
    const selectedFlags = {}
    for (const k of optionKeys) {
      selectedFlags[k] = isMulti
        ? newAnswer.split(',').indexOf(k) >= 0
        : newAnswer === k
    }
    this.setData({ answerMap, answeredCount, selectedFlags })
  },

  goNext() {
    if (this._animating) return
    if (this.data.currentIndex < this.data.totalQuestions - 1) {
      this._animating = true
      this.setData({ animClass: 'slide-out-left' })
      setTimeout(() => {
        this._showQuestion(this.data.currentIndex + 1)
        this.setData({ animClass: 'slide-in' })
        setTimeout(() => {
          this.setData({ animClass: '' })
          this._animating = false
        }, 120)
      }, 120)
    }
  },

  goPrev() {
    if (this._animating) return
    if (this.data.currentIndex > 0) {
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
    }
  },

  /* ==================== 交卷 ==================== */

  async doSubmit() {
    const { answerMap, questions, startTime, selectedSubject } = this.data
    const total = questions.length || 0
    const answeredCount = Object.keys(answerMap).length
    const unanswered = total - answeredCount

    if (unanswered > 0) {
      const { confirm } = await wx.showModal({
        title: '还有题目未作答',
        content: `还有 ${unanswered} 道题未作答，确定提交吗？`,
        confirmText: '确定提交',
        cancelText: '继续作答',
      })
      if (!confirm) return
    }

    this._clearTimer()
    this.setData({ submitting: true })
    wx.showLoading({ title: '批改中...' })

    try {
      const answers = questions.map(q => ({
        question_id: q.id,
        answer: answerMap[String(q.id)] || '',
      }))

      const result = await api.post('/practice/submit', {
        subject: selectedSubject,
        answers,
        duration_sec: Math.floor((Date.now() - startTime) / 1000),
      })

      wx.hideLoading()
      wx.redirectTo({
        url: [
          `/pages/practice-result/practice-result`,
          `?correct=${result.correct_count || 0}`,
          `&wrong=${result.wrong_count || 0}`,
          `&total=${total}`,
          `&record_id=${result.record_id || 0}`,
          `&subject=${selectedSubject}`,
          `&duration=${Math.floor((Date.now() - startTime) / 1000) || 0}`,
        ].join(''),
      })
    } catch (e) {
      console.error('提交失败', e)
      wx.hideLoading()
      this.setData({ submitting: false })
      wx.showToast({ title: '提交失败', icon: 'none' })
    }
  },

  finishEarly() {
    const answered = Object.keys(this.data.answerMap).length
    wx.showModal({
      title: '结束练习',
      content: `已完成 ${answered} / ${this.data.totalQuestions} 题，确定结束吗？`,
      success: (res) => {
        if (res.confirm) this.doSubmit()
      },
    })
  },

  /* ==================== 工具 ==================== */

  _syncAnsweredCount(answerMap) {
    const count = Object.keys(answerMap).filter(k => answerMap[k]).length
    this.setData({ answeredCount: count })
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || ''
  },

  noop() {},

  onUnload() {
    this._clearTimer()
  },
})
