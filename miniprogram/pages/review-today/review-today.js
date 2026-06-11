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

const GROUP_SIZES = [5, 10, 20]

Page({
  data: {
    // 页面阶段: entry / practice / group-result / final-result
    phase: 'entry',

    // 入口
    stats: null,
    entryLoading: true,
    groupSize: 10,

    // 练习
    allQuestions: [],
    groups: [],
    currentGroupIdx: 0,
    groupQuestions: [],
    answers: {},         // {schedule_id: selectedOption}
    currentIndex: 0,
    currentQuestion: null,
    optionKeys: [],

    // 已掌握确认
    masterConfirmId: null,

    // 滑动动画
    animClass: '',

    // 提交中
    submittingGroup: false,

    // 组结果
    groupResults: [],
    groupCorrect: 0,
    groupWrong: 0,

    // 最终
    allGroupResults: [],
    totalCorrect: 0,
    totalWrong: 0,

    // UI 增强
    _dateStr: '',
    _motivationMsg: '',
    _ringStyle: '',
    _accuracyStyle: '',
    entryDone: false,
    enableMathImage: false,

    // 进度
    groupProgress: 0,
  },

  onLoad() {
    this.setData({ enableMathImage: config.enableMathImage || false })
    this._setDateStr()
    this._loadEntry()
  },

  _setDateStr() {
    const now = new Date()
    const weekdays = ['日', '一', '二', '三', '四', '五', '六']
    this.setData({
      _dateStr: `${now.getMonth() + 1}月${now.getDate()}日 星期${weekdays[now.getDay()]}`
    })
  },

  _calcRingStyle(stats) {
    if (!stats || stats.total_scheduled === 0) return ''
    const done = stats.total_scheduled - stats.remaining_today
    const pct = Math.round(done / stats.total_scheduled * 360)
    if (pct <= 0) return ''
    const mid = Math.round(pct * 0.4)
    return `background: conic-gradient(#5B7B9A 0deg, #7BA0BE ${mid}deg, #A5C5D9 ${pct}deg, rgba(255,255,255,0.25) 0deg)`
  },

  _calcAccuracyStyle(correctCount, totalQuestions) {
    const pct = totalQuestions > 0 ? Math.round(correctCount / totalQuestions * 360) : 0
    if (pct <= 0) return ''
    const mid = Math.round(pct * 0.5)
    return `background: conic-gradient(#6B9B6B 0deg, #8BC88B ${mid}deg, #A8D8A8 ${pct}deg, #EDF1F5 0deg)`
  },

  _calcMotivationMsg(stats) {
    if (!stats) return ''
    if (stats.total_scheduled === 0) return '刷题后系统会自动安排复习'
    if (stats.remaining_today === 0) return '太棒了！今日复习全部完成'
    const done = stats.total_scheduled - stats.remaining_today
    const pct = Math.round(done / stats.total_scheduled * 100)
    if (pct === 0) return '开始今天的复习吧，每一步都算数'
    if (pct < 30) return '好的开始是成功的一半，继续加油'
    if (pct < 60) return '保持节奏，稳步前进'
    if (pct < 90) return '快完成啦，再坚持一下'
    return '就差一点点了！'
  },

  /* ==================== 入口 ==================== */

  async _loadEntry() {
    this.setData({ entryLoading: true })
    try {
      const stats = await api.get('/review/schedule-stats')
      const _motivationMsg = this._calcMotivationMsg(stats)
      const entryDone = stats && stats.total_scheduled > 0 && stats.remaining_today === 0
      this.setData({
        stats,
        entryLoading: false,
        _ringStyle: this._calcRingStyle(stats),
        _motivationMsg,
        entryDone,
      })
    } catch (e) {
      console.error('加载复习统计失败', e)
      this.setData({ entryLoading: false })
    }
  },

  selectGroupSize(e) {
    this.setData({ groupSize: parseInt(e.currentTarget.dataset.size) || 10 })
  },

  async startReview() {
    this.setData({ practiceLoading: true, phase: 'practice' })
    try {
      const res = await api.get('/review/today', { limit: 100 })
      const allQuestions = (res.questions || []).map(q => this._enrichQuestion(q))
      if (allQuestions.length === 0) {
        wx.showToast({ title: '今日没有待复习题目', icon: 'none' })
        this.setData({ practiceLoading: false, phase: 'entry' })
        this._loadEntry()
        return
      }

      const groups = this._splitGroups(allQuestions, this.data.groupSize)
      this.setData({
        allQuestions,
        groups,
        currentGroupIdx: 0,
        groupQuestions: groups[0] || [],
        answers: {},
        currentIndex: 0,
        allGroupResults: [],
        totalCorrect: 0,
        totalWrong: 0,
        practiceLoading: false,
      })
      this._showQuestion(0)
    } catch (e) {
      console.error('加载复习题目失败', e)
      this.setData({ practiceLoading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  _splitGroups(questions, size) {
    const groups = []
    for (let i = 0; i < questions.length; i += size) {
      groups.push(questions.slice(i, i + size))
    }
    return groups
  },

  /* ==================== 题目渲染 ==================== */

  _enrichQuestion(q) {
    const stemText = (q.content && (q.content.text || q.content.stem)) || q.stem || ''
    let opts = null
    let optionKeys = []
    if (q.options && Object.keys(q.options).length > 0) {
      opts = q.options
      optionKeys = Object.keys(opts)
    }
    if (q.question_type === 'true_false' || q.question_type === 'judgement') {
      opts = { A: '正确', B: '错误' }
      optionKeys = ['A', 'B']
    }

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
    const q = this.data.groupQuestions[index]
    if (!q) return
    this.setData({
      currentIndex: index,
      currentQuestion: q,
      optionKeys: q._optionKeys,
    })
  },

  /* ==================== 选择答案 ==================== */

  selectOption(e) {
    if (this.data.submittingGroup) return
    const opt = e.currentTarget.dataset.option
    if (!opt) return
    const q = this.data.currentQuestion
    const answers = { ...this.data.answers }
    // Toggle: tap same option to deselect (allow skipping)
    if (answers[q.schedule_id] === opt) {
      delete answers[q.schedule_id]
    } else {
      answers[q.schedule_id] = opt
    }
    this.setData({ answers })

    // (the WXML template reads answers directly from data)
  },

  /* ==================== 题目导航 ==================== */

  goNext() {
    if (this._animating) return
    const next = this.data.currentIndex + 1
    if (next >= this.data.groupQuestions.length) return
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

  onTouchStart(e) {
    if (this.data.submittingGroup || this._animating) return
    const t = e.touches[0]
    this._touchX = t.clientX
    this._touchY = t.clientY
  },

  onTouchEnd(e) {
    if (this.data.submittingGroup || this._animating) return
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

  /* ==================== 已掌握 ==================== */

  tapMaster(e) {
    const scheduleId = parseInt(e.currentTarget.dataset.sid)
    this.setData({ masterConfirmId: scheduleId })
  },

  cancelMaster() {
    this.setData({ masterConfirmId: null })
  },

  async confirmMaster() {
    const scheduleId = this.data.masterConfirmId
    this.setData({ masterConfirmId: null })
    try {
      await api.post(`/review/${scheduleId}/master`)

      // Remove from current group and allQuestions
      const allQuestions = this.data.allQuestions.filter(q => q.schedule_id !== scheduleId)
      const groups = this._splitGroups(allQuestions, this.data.groupSize)

      // If current group is now empty or we're past it, adjust
      let { currentGroupIdx, currentIndex, answers } = this.data
      const groupQuestions = groups[currentGroupIdx] || []

      // Clean answer entry
      delete answers[scheduleId]
      answers = { ...answers }

      if (groupQuestions.length === 0 && groups.length > 0) {
        // All questions in current group mastered, move to next group
        currentGroupIdx = Math.min(currentGroupIdx, groups.length - 1)
        this.setData({
          allQuestions,
          groups,
          currentGroupIdx,
          groupQuestions: groups[currentGroupIdx] || [],
          answers,
          currentIndex: 0,
        })
        if (groups[currentGroupIdx] && groups[currentGroupIdx].length > 0) {
          this._showQuestion(0)
        } else {
          // No groups left → all mastered
          this.setData({ phase: 'final-result', totalCorrect: 0, totalWrong: 0, _accuracyStyle: '' })
        }
      } else {
        // Adjust current index if needed
        if (currentIndex >= groupQuestions.length) {
          currentIndex = Math.max(0, groupQuestions.length - 1)
        }
        this.setData({
          allQuestions,
          groups,
          currentGroupIdx,
          groupQuestions: groupQuestions.length > 0 ? groupQuestions : groups[currentGroupIdx] || [],
          answers,
          currentIndex,
        })
        // All questions mastered → go to final result
        if (groups.length === 0 || groups.every(g => g.length === 0)) {
          this.setData({ phase: 'final-result', totalCorrect: 0, totalWrong: 0, _accuracyStyle: '' })
          return
        }
        if (groupQuestions.length > 0) {
          this._showQuestion(Math.min(currentIndex, groupQuestions.length - 1))
        }
      }
      wx.showToast({ title: '已标记为已掌握', icon: 'none' })
    } catch (e) {
      wx.showToast({ title: '操作失败', icon: 'none' })
    }
  },

  /* ==================== 提交本组 ==================== */

  async submitGroup() {
    const { groupQuestions, answers } = this.data
    const unanswered = groupQuestions.filter(q => !answers[q.schedule_id])

    this.setData({ submittingGroup: true })

    // Build payload — only submit answered questions
    const reviews = []
    for (const q of groupQuestions) {
      const answer = answers[q.schedule_id]
      reviews.push({
        schedule_id: q.schedule_id,
        question_id: q.question_id,
        user_answer: answer || '',
      })
    }

    try {
      const res = await api.post('/review/grade-batch', { reviews })
      const groupResults = groupQuestions.map(q => {
        const r = res.results.find(rr => rr.question_id === q.question_id)
        return {
          ...q,
          isCorrect: r ? r.is_correct : false,
          correctAnswer: r ? r.correct_answer : '',
          userAnswer: answers[q.schedule_id] || '',
          wasAnswered: !!answers[q.schedule_id],
        }
      })
      const groupCorrect = groupResults.filter(r => r.isCorrect && r.wasAnswered).length
      const groupWrong = groupResults.filter(r => !r.isCorrect || !r.wasAnswered).length

      const allGroupResults = [...this.data.allGroupResults, ...groupResults]
      const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasAnswered).length
      const totalWrong = allGroupResults.filter(r => !r.isCorrect || !r.wasAnswered).length

      this.setData({
        phase: 'group-result',
        groupResults,
        groupCorrect,
        groupWrong,
        submittingGroup: false,
        allGroupResults,
        totalCorrect,
        totalWrong,
        unansweredCount: unanswered.length,
      })
    } catch (e) {
      console.error('提交失败', e)
      wx.showToast({ title: '提交失败，请重试', icon: 'none' })
      this.setData({ submittingGroup: false })
    }
  },

  /* ==================== 下一组 / 最终结果 ==================== */

  nextGroup() {
    const nextGroupIdx = this.data.currentGroupIdx + 1
    if (nextGroupIdx >= this.data.groups.length) {
      // All groups done
      const { totalCorrect, allGroupResults } = this.data
      this.setData({
        phase: 'final-result',
        _accuracyStyle: this._calcAccuracyStyle(totalCorrect, allGroupResults.length),
      })
      return
    }
    this.setData({
      phase: 'practice',
      currentGroupIdx: nextGroupIdx,
      groupQuestions: this.data.groups[nextGroupIdx],
      answers: {},
      currentIndex: 0,
      groupResults: [],
      groupCorrect: 0,
      groupWrong: 0,
    })
    this._showQuestion(0)
  },

  /* ==================== 完成复习 ==================== */

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

  _stripTrailing(optKey) {
    return optKey ? optKey.replace(/[.．、:：）)]\s*$/, '') : ''
  },
})
