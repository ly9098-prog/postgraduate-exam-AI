const api = require('../../utils/api')
const config = require('../../config')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage,
  stripLeadingOptionLabel, toPlainInlineMathText, needsRichRender,
  textToHtml
} = require('../../utils/stem-render')
const {
  isMultipleChoiceType, isTrueFalseType,
  normalizeChoiceAnswer, serializeChoiceAnswer, serializeBlankAnswer,
} = require('../../utils/answer')
const adapter = require('../../utils/question-runner-adapter')

const GROUP_SIZES = [5, 10, 20]
var KF = 'schedule_id' // key field for review-today

function _mergeResultsByScheduleId(oldResults, newResults) {
  var order = []
  var map = {}

  ;(oldResults || []).forEach(function(item) {
    var sid = String(item && item.schedule_id || '')
    if (!sid) return
    if (!map[sid]) order.push(sid)
    map[sid] = item
  })

  ;(newResults || []).forEach(function(item) {
    var sid = String(item && item.schedule_id || '')
    if (!sid) return
    if (!map[sid]) order.push(sid)
    map[sid] = item
  })

  return order.map(function(sid) {
    return map[sid]
  })
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
    // 已掌握确认
    masterConfirmId: null,

    runnerProgressPercent: 0,
    runnerSubtitle: '',
    runnerSubjectName: '',

    // 提交中
    submittingGroup: false,
    resultTransitioning: false,

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
    showCelebration: false,
    celebrationTitle: '',
    celebrationDetail: '',
    celebrationMotto: '',
    celebrationType: 'group',
    celebrationProgressText: '',
    celebrationRewardText: '',
    celebrationDuration: 2600,
    growthLevel: '',
    growthLevelPct: 0,
    growthDesc: '',

    reviewResultVm: null,
    _masteredCount: 0,

    safeModeActive: false,
    renderTraces: [],
  },

  onLoad() {
    this._finalCelebrationShown = false
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
    this._clearCelebrationTimer()
    this._finalCelebrationShown = false
    this.setData({ practiceLoading: true, phase: 'practice', showCelebration: false })
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
        currentQuestion: null,
        optionKeys: [],
        _answeredCount: 0,

        groupResults: [],
        groupCorrect: 0,
        groupWrong: 0,

        allGroupResults: [],
        totalCorrect: 0,
        totalWrong: 0,
        totalCompleted: 0,

        masterConfirmId: null,
        submittingGroup: false,
        resultTransitioning: false,

        safeModeActive: false,
        renderTraces: [],
        practiceLoading: false,
      })
      this._showQuestion(0)
      this._syncAnsweredFlags()
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
    const hasBlankGroups = adapter.isMultiBlankChoice(q) && adapter.getBlankOptionGroups(q).length > 0
    const blankOptionGroups = hasBlankGroups ? adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), '') : []

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
      _hasBlankOptionGroups: blankOptionGroups.length > 0,
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

  _syncAnsweredFlags() {
    const enriched = adapter.applyAnsweredFlags(this.data.groupQuestions, adapter.buildAnsweredFlags(this.data.groupQuestions, this.data.answers, KF), KF)
    this.setData({ groupQuestions: enriched })
  },

  _showQuestion(index) {
    const q = this.data.groupQuestions[index]
    if (!q) return
    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, this.data.answers, KF)
    const optionList = adapter.buildOptionList(q, this.data.answers, KF)
    const currentQuestion = Object.assign({}, q, { _optionList: optionList })
    this.setData({
      currentIndex: index,
      currentQuestion: currentQuestion,
      optionKeys: q._optionKeys,
      _answeredCount: answeredCount,
    })
    this._updateRunnerFields()
    this._checkRenderInvariant(q._renderModel)
    this._recordRenderTrace(q._renderModel && q._renderModel.renderTrace)
  },

  _updateRunnerFields() {
    var grp = this.data.groupQuestions || []
    var total = grp.length || 1
    var answered = this.data._answeredCount || 0
    this.setData({
      runnerProgressPercent: Math.round(answered / total * 100),
      runnerSubtitle: '第 ' + (this.data.currentGroupIdx + 1) + ' / ' + (this.data.groups.length) + ' 组',
      runnerSubjectName: this.data.currentQuestion
        ? (this.data.currentQuestion.subject_name || this.data.currentQuestion._subjectLabel || '')
        : '',
    })
  },

  /* ==================== 选择答案 ==================== */

  selectOption(e) {
    if (this.data.submittingGroup) return
    const opt = e.detail.option
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
    const optionList = adapter.buildOptionList(q, answers, KF)
    const currentQuestion = Object.assign({}, q, { _optionList: optionList })
    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, answers, KF)
    this.setData({ answers, currentQuestion, _answeredCount: answeredCount })
    this._syncAnsweredFlags()
    this._updateRunnerFields()
  },

  selectBlankOption(e) {
    if (this.data.submittingGroup) return
    const blankId = String(e.detail.blankId || '').trim()
    const opt = String(e.detail.option || '').trim().toUpperCase()
    const q = this.data.currentQuestion
    if (!q || !blankId || !opt) return

    const answer = this.data.answers[q.schedule_id] || ''
    const blankAnswers = adapter.normalizeBlankAnswer(answer)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    const groups = q._blankOptionGroups || adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), answer)
    const newAnswer = serializeBlankAnswer(groups, blankAnswers)
    const answers = { ...this.data.answers }
    if (newAnswer) answers[q.schedule_id] = newAnswer
    else delete answers[q.schedule_id]

    // Re-enrich blank groups with updated selection
    const enrichedGroups = adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), newAnswer)
    const currentQuestion = Object.assign({}, q, {
      _blankOptionGroups: enrichedGroups,
      _hasBlankOptionGroups: enrichedGroups.length > 0,
    })

    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, answers, KF)
    this.setData({ answers, currentQuestion, _answeredCount: answeredCount })
    this._syncAnsweredFlags()
    this._updateRunnerFields()
  },

  /* ==================== 题目导航 ==================== */

  goQuestion(e) {
    var index = e.detail.index
    if (index === this.data.currentIndex) return
    this._showQuestion(index)
  },

  goNext(e) {
    this._showQuestion(e.detail.index)
  },

  goPrev(e) {
    this._showQuestion(e.detail.index)
  },

  /* ==================== 已掌握 ==================== */

  tapMaster(e) {
    var q = e.detail && e.detail.question
    var scheduleId = q && q.schedule_id
    if (!scheduleId) return
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

      // Track mastered count
      this.data._masteredCount = (this.data._masteredCount || 0) + 1

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
          _answeredCount: adapter.computeAnsweredCount(newGroupQuestions, answers, KF),
        })
        this._syncAnsweredFlags()
        if (groups[currentGroupIdx] && groups[currentGroupIdx].length > 0) {
          this._showQuestion(0)
        } else {
          // No groups left → all mastered
          const reviewResultVm = this._buildReviewResultViewModel()
          this.setData({
            phase: 'final-result',
            reviewResultVm,
          })
          this._showFinalCelebrationOnce()
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
          _answeredCount: adapter.computeAnsweredCount(groupQuestions, answers, KF),
        })
        this._syncAnsweredFlags()
        // All questions mastered → go to final result
        if (groups.length === 0 || groups.every(g => g.length === 0)) {
          const reviewResultVm = this._buildReviewResultViewModel()
          this.setData({
            phase: 'final-result',
            reviewResultVm,
          })
          this._showFinalCelebrationOnce()
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

    const answeredCount = adapter.computeAnsweredCount(groupQuestions, answers, KF)
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
      const isAnswered = adapter.isQuestionAnswered(q, answers, KF)
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
      const results = Array.isArray(res && res.results) ? res.results : []

      if (results.length < reviews.length) {
        wx.showToast({
          title: results.length ? '部分题目批改失败' : '批改结果为空，请重试',
          icon: 'none'
        })
        if (!results.length) {
          this.setData({ submittingGroup: false })
          return
        }
      }

      const groupResults = groupQuestions.map(q => {
        const r = results.find(rr => {
          if (rr.schedule_id !== undefined && rr.schedule_id !== null) {
            return String(rr.schedule_id) === String(q.schedule_id)
          }
          return String(rr.question_id) === String(q.question_id)
        })
        const isAnswered = adapter.isQuestionAnswered(q, answers, KF)
        const wasSubmitted = !!r
        return {
          ...q,
          isCorrect: r ? !!r.is_correct : false,
          correctAnswer: r ? (r.correct_answer || '') : '',
          userAnswer: answers[q.schedule_id] || '',
          wasAnswered: isAnswered,
          wasSubmitted,
          wasSkipped: !isAnswered && !wasSubmitted,
        }
      })
      const groupCorrect = groupResults.filter(r => r.isCorrect && r.wasSubmitted).length
      const groupWrong = groupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
      const groupSkipped = groupResults.filter(r => r.wasSkipped).length

      const allGroupResults = _mergeResultsByScheduleId(this.data.allGroupResults, groupResults)
      const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasSubmitted).length
      const totalWrong = allGroupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
      const totalCompleted = allGroupResults.filter(r => r.wasSubmitted).length

      // Re-queue skipped questions as a new group
      const skippedQuestions = groupQuestions.filter(q => !adapter.isQuestionAnswered(q, answers, KF) && !treatUnansweredAsWrong)
      const groups = skippedQuestions.length > 0
        ? [...this.data.groups, skippedQuestions]
        : this.data.groups

      const isLastGroup = this.data.currentGroupIdx + 1 >= groups.length

      this.setData({
        phase: 'group-result',
        groups,
        groupResults,
        groupCorrect,
        groupWrong,
        submittingGroup: false,
        allGroupResults,
        totalCorrect,
        totalWrong,
        totalCompleted,
        _groupProgressStyle: this._calcGroupProgressStyle(this.data.currentGroupIdx + 1, groups.length),
      })

      if (isLastGroup) {
        this._showFinalCelebrationOnce()
      } else {
        this._showGroupCelebration(groupCorrect, groupQuestions.length)
      }
    } catch (e) {
      console.error('提交失败', e)
      wx.showToast({ title: '提交失败，请重试', icon: 'none' })
      this.setData({ submittingGroup: false })
    }
  },

  /* ==================== 下一组 / 最终结果 ==================== */

  nextGroup() {
    if (this.data.resultTransitioning) return
    this.setData({ resultTransitioning: true })

    const nextGroupIdx = this.data.currentGroupIdx + 1
    if (nextGroupIdx >= this.data.groups.length) {
      const reviewResultVm = this._buildReviewResultViewModel()
      this.setData({
        phase: 'final-result',
        resultTransitioning: false,
        reviewResultVm,
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
      resultTransitioning: false,
    })
    this._syncAnsweredFlags()
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

  _showFinalCelebrationOnce() {
    if (this._finalCelebrationShown) return
    this._finalCelebrationShown = true
    return this._showFinalCelebration()
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
        growthLevelPct: growth.level_progress_pct || 0,
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

  /* ==================== 最终结果视图模型 ==================== */

  _buildReviewResultViewModel() {
    var allResults = this.data.allGroupResults || []
    var sessionTotal = allResults.length
    var submittedTotal = allResults.filter(function(r) { return r.wasSubmitted }).length
    var correct = allResults.filter(function(r) { return r.isCorrect && r.wasSubmitted }).length
    var wrong = allResults.filter(function(r) { return r.wasSubmitted && !r.isCorrect }).length
    var skipped = Math.max(0, sessionTotal - submittedTotal)
    var accuracy = submittedTotal > 0 ? Math.round(correct / submittedTotal * 100) : 0
    var completionRate = sessionTotal > 0 ? Math.round(submittedTotal / sessionTotal * 100) : 0
    var wrongRate = submittedTotal > 0 ? Math.round(wrong / submittedTotal * 100) : 0

    var groupCount = this.data.groups.length
    var completedGroupCount = Math.min(this.data.currentGroupIdx + 1, groupCount)
    var masteredCount = this.data._masteredCount || 0
    var isPerfect = wrong === 0 && submittedTotal > 0
    var hasWrong = wrong > 0
    var hasSkipped = skipped > 0

    // Subject stats from allResults — build array for wx:for compatibility
    var subjectMap = {}
    allResults.forEach(function(r) {
      if (!r.subject) return
      if (!subjectMap[r.subject]) subjectMap[r.subject] = { reviewed: 0, correct: 0, wrong: 0, skipped: 0 }
      var s = subjectMap[r.subject]
      s.reviewed++
      if (!r.wasSubmitted) { s.skipped++; return }
      if (r.isCorrect) s.correct++
      else s.wrong++
    })
    var subjectStatsArr = []
    for (var subj in subjectMap) {
      if (subjectMap.hasOwnProperty(subj)) {
        subjectStatsArr.push({ subject: this.subjectLabel(subj), stats: subjectMap[subj] })
      }
    }

    var resultLevelClass, resultTitle, resultDesc, statusText, statusDesc
    var nextStepType, nextStepTitle, nextStepDesc, nextStepTag

    if (sessionTotal === 0) {
      resultLevelClass = 'empty'
      resultTitle = '暂无复习结果'
      resultDesc = '今天还没有完成可统计的复习题'
      statusText = '未开始'
      statusDesc = '完成一组复习后，这里会生成结果'
      nextStepType = 'start'
      nextStepTitle = '先开始一组复习'
      nextStepDesc = '完成今日复习后，系统会帮你整理正确率和错题情况'
      nextStepTag = '未开始'
    } else if (isPerfect) {
      resultLevelClass = 'excellent'
      resultTitle = '今日复习完成'
      resultDesc = '整体掌握很好，可以保持当前节奏'
      statusText = '状态很好'
      statusDesc = '今天没有明显薄弱点'
      nextStepType = 'continue'
      nextStepTitle = '可以结束今日复习'
      nextStepDesc = '如果还有精力，也可以继续练习新题巩固手感'
      nextStepTag = '完成'
    } else if (accuracy >= 80) {
      resultLevelClass = 'good'
      resultTitle = '今日复习完成'
      resultDesc = '整体表现不错，但仍有少量错题'
      statusText = '少量错题'
      statusDesc = '建议趁热复盘'
      nextStepType = 'review'
      nextStepTitle = '建议先复盘错题'
      nextStepDesc = '先处理今天的错题，再继续下一组练习'
      nextStepTag = '推荐'
    } else if (accuracy >= 60) {
      resultLevelClass = 'normal'
      resultTitle = '今日复习完成'
      resultDesc = '本次复习暴露了一些薄弱点'
      statusText = '需要复盘'
      statusDesc = '错题有较高复盘价值'
      nextStepType = 'review'
      nextStepTitle = '优先处理薄弱点'
      nextStepDesc = '建议立即查看错题，找出今天容易失误的知识点'
      nextStepTag = '复盘优先'
    } else {
      resultLevelClass = 'weak'
      resultTitle = '今日复习完成'
      resultDesc = '今天错题较多，不建议直接继续刷题'
      statusText = '错题较多'
      statusDesc = '先复盘比继续刷题更重要'
      nextStepType = 'review'
      nextStepTitle = '建议立即复盘'
      nextStepDesc = '先把错误原因搞清楚，再继续练习，复习效果会更好'
      nextStepTag = '重点'
    }

    return {
      sessionTotal: sessionTotal,
      submittedTotal: submittedTotal,
      total: sessionTotal,
      correct: correct,
      wrong: wrong,
      skipped: skipped,
      answered: submittedTotal,
      accuracy: accuracy,
      completionRate: completionRate,
      wrongRate: wrongRate,
      groupCount: groupCount,
      completedGroupCount: completedGroupCount,
      masteredCount: masteredCount,
      subjectStats: subjectStatsArr,
      resultLevelClass: resultLevelClass,
      resultTitle: resultTitle,
      resultDesc: resultDesc,
      statusText: statusText,
      statusDesc: statusDesc,
      nextStepType: nextStepType,
      nextStepTitle: nextStepTitle,
      nextStepDesc: nextStepDesc,
      nextStepTag: nextStepTag,
      hasWrong: hasWrong,
      hasSkipped: hasSkipped,
      isPerfect: isPerfect,
    }
  },

  /* ==================== 完成复习 ==================== */

  finishReview() {
    wx.navigateBack()
  },

  goWrongBook() {
    wx.navigateTo({ url: '/pages/wrong-book/wrong-book' })
  },

  goPractice() {
    wx.navigateTo({ url: '/pages/practice/practice' })
  },

  goHome() {
    wx.navigateTo({ url: '/pages/home/home' })
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

})
