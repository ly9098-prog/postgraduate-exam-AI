const api = require('../../utils/api')
const config = require('../../config')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage,
  toPlainInlineMathText, needsRichRender, stripLeadingOptionLabel,
  textToHtml
} = require('../../utils/stem-render')
const {
  isMultipleChoiceType, isMultiBlankType, isTrueFalseType,
  normalizeChoiceAnswer, serializeChoiceAnswer, serializeBlankAnswer,
} = require('../../utils/answer')

const GROUP_SIZES = [5, 10, 20]

/* ---- Blank answer helpers (ported from practice.js) ---- */

function _normalizeBlankAnswer(answer) {
  if (!answer) return {}
  if (typeof answer === 'object') return answer
  var result = {}
  String(answer).split(/[;；,，\n]+/).forEach(function(part) {
    var m = part.trim().match(/^(.+?)\s*[:：=]\s*([A-Za-z])$/)
    if (m) result[m[1].trim()] = m[2].trim().toUpperCase()
  })
  return result
}

function _normalizeBlankOptionList(options) {
  if (Array.isArray(options)) return options
  if (options && typeof options === 'object') {
    return Object.keys(options).map(function(key) {
      return { key: key, text: options[key] }
    })
  }
  return []
}

function _getBlankOptionGroups(q) {
  if (!q) return []
  if (q.content && Array.isArray(q.content.blank_option_groups)) return q.content.blank_option_groups
  if (Array.isArray(q.blank_option_groups)) return q.blank_option_groups
  return []
}

function _enrichBlankOptionGroups(groups, answer) {
  var blankAnswers = _normalizeBlankAnswer(answer)
  return (groups || []).map(function(group) {
    var groupId = String((group && group.id) || '').trim()
    return {
      id: groupId,
      options: _normalizeBlankOptionList(group && group.options).map(function(opt) {
        var key = String((opt && opt.key) || '').trim().toUpperCase()
        var text = String((opt && opt.text) || '').trim()
        var optionText = stripLeadingOptionLabel(key, text)
        var cleanedText = optionText.replace(/[\r\n]+/g, ' ')
        var plain = toPlainInlineMathText(cleanedText)
        var needsRich = !plain && needsRichRender(cleanedText)
        return Object.assign({}, opt, {
          key: key,
          _text: plain || optionText,
          _selected: blankAnswers[groupId] === key,
          _needsRich: needsRich,
          _html: needsRich ? textToHtml(optionText) : '',
        })
      }).filter(function(opt) { return opt.key }),
    }
  }).filter(function(group) {
    return group.id && group.options.length > 0
  })
}

function _buildOptionList(q, optionKeys, answers) {
  var answer = (answers && answers[q.schedule_id]) || ''
  var isMulti = isMultipleChoiceType(q.question_type)
  return (optionKeys || []).map(function(key) {
    var selected = isMulti ? normalizeChoiceAnswer(answer).indexOf(key) >= 0 : String(answer).trim().toUpperCase() === key
    return {
      key: key,
      _selected: selected,
      _icon: selected ? (isMulti ? 'check' : 'dot') : '',
    }
  })
}

function _isQuestionAnswered(q, answers) {
  var answer = (answers || {})[q.schedule_id] || ''
  if (isMultiBlankType(q.question_type)) {
    var blankAnswers = _normalizeBlankAnswer(answer)
    var groups = _getBlankOptionGroups(q)
    if (!groups.length) return !!answer
    return groups.every(function(group) {
      return !!blankAnswers[String((group && group.id) || '').trim()]
    })
  }
  return !!answer
}

function _computeAnsweredCount(groupQuestions, answers) {
  return (groupQuestions || []).filter(function(q) {
    var answer = (answers || {})[q.schedule_id] || ''
    if (isMultiBlankType(q.question_type)) {
      var blankAnswers = _normalizeBlankAnswer(answer)
      var groups = _getBlankOptionGroups(q)
      if (!groups.length) return !!answer
      return groups.every(function(group) {
        return !!blankAnswers[String((group && group.id) || '').trim()]
      })
    }
    return !!answer
  }).length
}

function _buildBlankSelectedFlags(groups, answer) {
  var blankAnswers = _normalizeBlankAnswer(answer)
  var flags = {}
  ;(groups || []).forEach(function(group) {
    var groupId = String((group && group.id) || '').trim()
    flags[groupId] = {}
    ;(group.options || []).forEach(function(opt) {
      flags[groupId][opt.key] = blankAnswers[groupId] === opt.key
    })
  })
  return flags
}

Page({
  data: {
    // 页面阶段: entry / practice / group-result / final-result
    phase: 'entry',

    // 入口
    stats: null,
    entryLoading: true,
    groupSize: 10,
    groupSizeOptions: GROUP_SIZES,

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
    totalCompleted: 0,

    // UI 增强
    _dateStr: '',
    _motivationMsg: '',
    _ringStyle: '',
    _accuracyStyle: '',
    entryDone: false,
    _accuracyText: '0%',
    _reviewGroupCountText: '0',
    _groupProgressStyle: '',

    // 进度
    groupProgress: 0,

    showCelebration: false,
    celebrationTitle: '',
    celebrationDetail: '',
    celebrationMotto: '',
    celebrationType: 'group',
    celebrationProgressText: '',
    celebrationRewardText: '',
    celebrationDuration: 2600,
    growthLevel: '',
    growthExpText: '',
    growthLevelPct: 0,
    growthBadgeCount: 0,
    growthDesc: '',

    safeModeActive: false,
    renderTraces: [],
  },

  onLoad() {
    setRenderGuardPage('review-today')
    this._setDateStr()
    this._loadEntry()
  },

  onHide() {
    this._clearCelebrationTimer()
    if (this.data.showCelebration) this.setData({ showCelebration: false })
  },

  onUnload() {
    resetRenderGuard()
    this._clearCelebrationTimer()
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
    return `background: conic-gradient(#4F7FFF 0deg, #6EC1FF ${mid}deg, #8BB8FF ${pct}deg, rgba(226, 234, 247, 0.4) 0deg)`
  },

  _calcAccuracyStyle(correctCount, totalQuestions) {
    const pct = totalQuestions > 0 ? Math.round(correctCount / totalQuestions * 360) : 0
    if (pct <= 0) return ''
    const mid = Math.round(pct * 0.5)
    return `background: conic-gradient(#22C55E 0deg, #4ADE80 ${mid}deg, #86EFAC ${pct}deg, #E2EAF7 0deg)`
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
        _accuracyLast7dText: `${Math.round((stats.accuracy_last_7d || 0) * 100)}%`,
        _reviewGroupCountText: stats.remaining_today > 0 ? Math.ceil(stats.remaining_today / this.data.groupSize) : 0,
      })
    } catch (e) {
      console.error('加载复习统计失败', e)
      this.setData({ entryLoading: false })
    }
  },

  selectGroupSize(e) {
    const groupSize = parseInt(e.currentTarget.dataset.size) || 10
    const stats = this.data.stats
    this.setData({
      groupSize,
      _reviewGroupCountText: stats && stats.remaining_today > 0 ? Math.ceil(stats.remaining_today / groupSize) : 0,
    })
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
        _answeredCount: 0,
        allGroupResults: [],
        totalCorrect: 0,
        totalWrong: 0,
        safeModeActive: false,
        renderTraces: [],
        practiceLoading: false,
      })
      this._showQuestion(0)
    } catch (e) {
      console.error('加载复习题目失败', e)
      this.setData({ practiceLoading: false, phase: 'entry' })
      this._loadEntry()
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
    if (isTrueFalseType(q.question_type)) {
      opts = { A: '正确', B: '错误' }
      optionKeys = ['A', 'B']
    }

    // Blank option groups for multi_blank_choice
    const hasBlankGroups = isMultiBlankType(q.question_type) && _getBlankOptionGroups(q).length > 0
    const blankOptionGroups = hasBlankGroups ? _enrichBlankOptionGroups(_getBlankOptionGroups(q), '') : []

    var renderCfg = { enableMathImage: false, DEV: config.DEV }
    if (this.data.safeModeActive) renderCfg.SAFE_MODE = true
    const _renderModel = buildRenderModel(q, opts, renderCfg)

    const optText = {}
    const optNeedsRich = {}
    const optHtml = {}
    for (const key of optionKeys) {
      const raw = (opts && opts[key]) || ''
      const text = stripLeadingOptionLabel(key, raw)
      const plain = toPlainInlineMathText(text)
      optText[key] = plain || text
      optNeedsRich[key] = !plain && needsRichRender(text)
      optHtml[key] = optNeedsRich[key] ? textToHtml(text) : ''
    }

    return {
      ...q,
      _opts: opts,
      _optionKeys: optionKeys,
      _optText: optText,
      _optNeedsRich: optNeedsRich,
      _optHtml: optHtml,
      _blankOptionGroups: blankOptionGroups,
      _hasBlankGroups: blankOptionGroups.length > 0,
      _optionList: [],
      _renderModel,
      _stemPreview: stemText.length > 60 ? `${stemText.slice(0, 60)}...` : stemText,
      _subjectLabel: this.subjectLabel(q.subject),
    }
  },

  // ---- Render Invariant + Trace ----

  _checkRenderInvariant(renderModel) {
    if (!renderModel) return
    if (renderModel.mode === 'CODE' && renderModel.rawText) {
      var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
      if (hasHtmlLeak) {
        console.error('[CODE_HTML_LEAK] review-today CODE rawText contains HTML entities')
      }
      var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
      if (hasRenderViolation) {
        console.error('[CODE_RENDER_VIOLATION] review-today CODE mode leaked into html/richTextNodes')
      }
      if ((hasHtmlLeak || hasRenderViolation) && !this.data.safeModeActive) {
        this._enterSafeMode()
      }
    }
    // MIXED mode validation
    if (renderModel.mode === 'MIXED') {
      if (!renderModel.blocks || renderModel.blocks.length === 0) {
        console.error('[MIXED_RENDER_VIOLATION] review-today MIXED mode but blocks is empty')
        return
      }
      for (var mi = 0; mi < renderModel.blocks.length; mi++) {
        var mBlock = renderModel.blocks[mi]
        if (mBlock.type === 'CODE' && mBlock.rawText) {
          if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
            console.error('[CODE_HTML_LEAK] review-today MIXED CODE block #' + mi + ' contains HTML entities')
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
    console.warn('[SELF_HEAL] review-today CODE render violation — entering SAFE_MODE')
    this.setData({ safeModeActive: true })
    if (this.data.currentQuestion) {
      const idx = this.data.currentIndex
      const q = this.data.groupQuestions[idx]
      if (q) {
        // Re-enrich current question with safe mode
        const enriched = this._enrichQuestion(q)
        const groupQuestions = [...this.data.groupQuestions]
        groupQuestions[idx] = enriched
        this.setData({ groupQuestions })
        this._showQuestion(idx)
      }
      console.warn('[SELF_HEAL] review-today re-rendered at index ' + idx + ' in SAFE_MODE')
    }
  },

  _showQuestion(index) {
    const q = this.data.groupQuestions[index]
    if (!q) return
    const answeredCount = _computeAnsweredCount(this.data.groupQuestions, this.data.answers)
    const optionList = _buildOptionList(q, q._optionKeys, this.data.answers)
    const currentQuestion = Object.assign({}, q, { _optionList: optionList })
    this.setData({
      currentIndex: index,
      currentQuestion: currentQuestion,
      optionKeys: q._optionKeys,
      _answeredCount: answeredCount,
    })
    this._checkRenderInvariant(q._renderModel)
    this._recordRenderTrace(q._renderModel && q._renderModel.renderTrace)
  },

  /* ==================== 选择答案 ==================== */

  selectOption(e) {
    if (this.data.submittingGroup) return
    const opt = e.currentTarget.dataset.option
    if (!opt) return
    const q = this.data.currentQuestion
    const answers = { ...this.data.answers }

    if (isMultipleChoiceType(q.question_type)) {
      // Multiple choice: toggle in sorted set
      const prev = answers[q.schedule_id] || ''
      const sel = normalizeChoiceAnswer(prev)
      const idx = sel.indexOf(opt)
      if (idx >= 0) sel.splice(idx, 1)
      else sel.push(opt)
      sel.sort()
      const newAnswer = serializeChoiceAnswer(sel.join(','))
      if (newAnswer) answers[q.schedule_id] = newAnswer
      else delete answers[q.schedule_id]
    } else {
      // Single choice / true_false: toggle
      if (answers[q.schedule_id] === opt) {
        delete answers[q.schedule_id]
      } else {
        answers[q.schedule_id] = opt
      }
    }
    const optionList = _buildOptionList(q, q._optionKeys, answers)
    const currentQuestion = Object.assign({}, q, { _optionList: optionList })
    const answeredCount = _computeAnsweredCount(this.data.groupQuestions, answers)
    this.setData({ answers, currentQuestion, _answeredCount: answeredCount })
  },

  selectBlankOption(e) {
    if (this.data.submittingGroup) return
    const blankId = String(e.currentTarget.dataset.blankId || '').trim()
    const opt = String(e.currentTarget.dataset.option || '').trim().toUpperCase()
    const q = this.data.currentQuestion
    if (!q || !blankId || !opt) return

    const answer = this.data.answers[q.schedule_id] || ''
    const blankAnswers = _normalizeBlankAnswer(answer)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    const groups = q._blankOptionGroups || _enrichBlankOptionGroups(_getBlankOptionGroups(q), answer)
    const newAnswer = serializeBlankAnswer(groups, blankAnswers)
    const answers = { ...this.data.answers }
    if (newAnswer) answers[q.schedule_id] = newAnswer
    else delete answers[q.schedule_id]

    // Re-enrich blank groups with updated selection
    const enrichedGroups = _enrichBlankOptionGroups(_getBlankOptionGroups(q), newAnswer)
    const currentQuestion = Object.assign({}, q, {
      _blankOptionGroups: enrichedGroups,
      _hasBlankGroups: enrichedGroups.length > 0,
    })

    const answeredCount = _computeAnsweredCount(this.data.groupQuestions, answers)
    this.setData({ answers, currentQuestion, _answeredCount: answeredCount })
  },

  /* ==================== 题目导航 ==================== */

  goQuestion(e) {
    if (this._animating) return
    const index = Number(e.currentTarget.dataset.index)
    if (!Number.isInteger(index) || index < 0 || index >= this.data.groupQuestions.length) return
    if (index === this.data.currentIndex) return
    this._showQuestion(index)
  },

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
        const newGroupQuestions = groups[currentGroupIdx] || []
        this.setData({
          allQuestions,
          groups,
          currentGroupIdx,
          groupQuestions: newGroupQuestions,
          answers,
          currentIndex: 0,
          _answeredCount: _computeAnsweredCount(newGroupQuestions, answers),
        })
        if (groups[currentGroupIdx] && groups[currentGroupIdx].length > 0) {
          this._showQuestion(0)
        } else {
          // No groups left → all mastered
          const denom = this.data.totalCompleted || this.data.allGroupResults.length
          this.setData({
            phase: 'final-result',
            _accuracyStyle: this._calcAccuracyStyle(this.data.totalCorrect, denom),
            _accuracyText: denom > 0 ? `${Math.round(this.data.totalCorrect / denom * 100)}%` : '0%',
          })
          this._showFinalCelebration()
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
          _answeredCount: _computeAnsweredCount(groupQuestions, answers),
        })
        // All questions mastered → go to final result
        if (groups.length === 0 || groups.every(g => g.length === 0)) {
          const denom = this.data.totalCompleted || this.data.allGroupResults.length
          this.setData({
            phase: 'final-result',
            _accuracyStyle: this._calcAccuracyStyle(this.data.totalCorrect, denom),
            _accuracyText: denom > 0 ? `${Math.round(this.data.totalCorrect / denom * 100)}%` : '0%',
          })
          this._showFinalCelebration()
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
    const { groupQuestions, answers, submittingGroup } = this.data
    if (submittingGroup) return

    const answeredCount = _computeAnsweredCount(groupQuestions, answers)
    const totalCount = groupQuestions.length
    const unansweredCount = totalCount - answeredCount

    // 存在未作答题目时，提示用户选择处理方式
    let treatUnansweredAsWrong = false
    if (unansweredCount > 0) {
      try {
        const choice = await new Promise(resolve => {
          wx.showModal({
            title: '还有未作答题目',
            content: `共 ${totalCount} 题，已作答 ${answeredCount} 题，还有 ${unansweredCount} 题未作答。\n\n选择"按不会处理"将把未答题判为错误并进入复习。`,
            confirmText: '按不会处理',
            cancelText: '仅提交已答',
            success: (r) => resolve(r.confirm ? 'wrong' : 'skip'),
            fail: () => resolve('cancel'),
          })
        })
        if (choice === 'cancel') return
        if (choice === 'wrong') treatUnansweredAsWrong = true
        // choice === 'skip': 只提交已作答的
      } catch (_) { return }
    } else {
      // 全部已作答，正常确认
      try {
        const confirmed = await new Promise(resolve => {
          wx.showModal({
            title: '确认提交',
            content: `共 ${totalCount} 题，已全部作答。确认提交并复盘？`,
            success: (r) => resolve(r.confirm),
            fail: () => resolve(false),
          })
        })
        if (!confirmed) return
      } catch (_) { return }
    }

    this.setData({ submittingGroup: true })

    // Build payload
    const reviews = []
    for (const q of groupQuestions) {
      const isAnswered = _isQuestionAnswered(q, answers)
      // 跳过未作答的题目（除非用户选择按不会处理）
      if (!isAnswered && !treatUnansweredAsWrong) continue
      reviews.push({
        schedule_id: q.schedule_id,
        question_id: q.question_id,
        user_answer: isAnswered ? (answers[q.schedule_id] || '') : '',
      })
    }

    // Guard: empty submit
    if (reviews.length === 0) {
      wx.showToast({ title: '请至少作答 1 题，或选择按不会处理', icon: 'none' })
      this.setData({ submittingGroup: false })
      return
    }

    try {
      const res = await api.post('/review/grade-batch', { reviews })
      const groupResults = groupQuestions.map(q => {
        const r = res.results.find(rr => rr.question_id === q.question_id)
        const isAnswered = _isQuestionAnswered(q, answers)
        const wasSubmitted = !!r
        return {
          ...q,
          isCorrect: r ? r.is_correct : false,
          correctAnswer: r ? r.correct_answer : '',
          userAnswer: answers[q.schedule_id] || '',
          wasAnswered: isAnswered,
          wasSubmitted,
          wasSkipped: !isAnswered && !wasSubmitted,
        }
      })
      const groupCorrect = groupResults.filter(r => r.isCorrect && r.wasAnswered).length
      const groupWrong = groupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
      const groupSkipped = groupResults.filter(r => r.wasSkipped).length

      const allGroupResults = [...this.data.allGroupResults, ...groupResults]
      const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasAnswered).length
      const totalWrong = allGroupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
      const totalCompleted = allGroupResults.filter(r => r.wasSubmitted).length

      this.setData({
        phase: 'group-result',
        groupResults,
        groupCorrect,
        groupWrong,
        groupSkipped,
        submittingGroup: false,
        allGroupResults,
        totalCorrect,
        totalWrong,
        totalCompleted,
        unansweredCount: groupSkipped,
        _groupProgressStyle: this._calcGroupProgressStyle(this.data.currentGroupIdx + 1, this.data.groups.length),
      })
      this._showGroupCelebration(groupCorrect, groupQuestions.length)
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
      const { totalCorrect, totalCompleted, allGroupResults } = this.data
      const denom = totalCompleted || allGroupResults.length
      this.setData({
        phase: 'final-result',
        _accuracyStyle: this._calcAccuracyStyle(totalCorrect, denom),
        _accuracyText: denom > 0 ? `${Math.round(totalCorrect / denom * 100)}%` : '0%',
      })
      this._showFinalCelebration()
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

  /* ==================== 完成反馈 ==================== */

  _calcGroupProgressStyle(doneGroups, totalGroups) {
    const total = totalGroups || 1
    const pct = Math.max(0, Math.min(100, Math.round(doneGroups * 100 / total)))
    return `width: ${pct}%`
  },

  _showGroupCelebration(correct, total) {
    const groupIndex = this.data.currentGroupIdx + 1
    const groupTotal = this.data.groups.length || groupIndex
    this._showCelebration({
      celebrationType: 'group',
      celebrationTitle: `第 ${groupIndex} 组复盘完成`,
      celebrationDetail: `答对 ${correct}/${total} 题`,
      celebrationMotto: correct >= total ? '这组很稳，继续保持节奏' : '错题已暴露，复盘后会更牢固',
      celebrationProgressText: `今日进度 ${groupIndex}/${groupTotal} 组`,
      celebrationRewardText: correct >= total ? '获得专注星光 +1' : '获得复盘能量 +1',
    }, 2400)
  },

  async _showFinalCelebration() {
    const denom = this.data.totalCompleted || this.data.allGroupResults.length
    const correct = this.data.totalCorrect
    const accuracy = denom > 0 ? Math.round(correct / denom * 100) : 0
    await this._loadGrowthForCelebration()
    this._showCelebration({
      celebrationType: 'final',
      celebrationTitle: '今日复习完成',
      celebrationDetail: `完成 ${denom} 题 · 答对 ${correct} 题`,
      celebrationMotto: '记忆曲线已更新，今天的积累会在明天生效',
      celebrationProgressText: `今日正确率 ${accuracy}%`,
      celebrationRewardText: '解锁今日复习徽章',
    }, 3600)
  },

  async _loadGrowthForCelebration() {
    try {
      const growth = await api.get('/stats/growth')
      if (!growth) return
      const unlockedCount = (growth.badges || []).filter(b => b.unlocked).length
      this.setData({
        growthLevel: growth.level_title || 'Lv1 起步',
        growthExpText: `${growth.exp_current || 0} / ${growth.exp_to_next || 0} EXP`,
        growthLevelPct: growth.level_progress_pct || 0,
        growthBadgeCount: unlockedCount,
        growthDesc: unlockedCount > 0
          ? `已点亮 ${unlockedCount} 个徽章 · ${growth.level_title || ''}`
          : `当前 ${growth.level_title || 'Lv1 起步'} · 继续保持`,
      })
    } catch (_) {}
  },

  _showCelebration(copy, duration) {
    const displayDuration = duration || 2600
    this._clearCelebrationTimer()
    this.setData({
      ...copy,
      celebrationDuration: displayDuration,
      showCelebration: true,
    })
    this._celebrationTimer = setTimeout(() => {
      this.setData({ showCelebration: false })
      this._celebrationTimer = null
    }, displayDuration)
  },

  dismissCelebration() {
    this._clearCelebrationTimer()
    this.setData({ showCelebration: false })
  },

  _clearCelebrationTimer() {
    if (this._celebrationTimer) {
      clearTimeout(this._celebrationTimer)
      this._celebrationTimer = null
    }
  },

  /* ==================== 完成复习 ==================== */

  finishReview() {
    wx.navigateBack()
  },

  noop() {},

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
