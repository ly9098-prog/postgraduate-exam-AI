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
const { getSubjectName } = require('../../utils/subject-meta')

var KF = 'schedule_id'

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
    /* ====== Phase ====== */
    // loading | overview | reviewing | group-result | final-result | empty | error
    phase: 'loading',

    /* ====== 入口概览 ====== */
    todayDueCount: 0,
    todayCompletedCount: 0,
    todayRemainingCount: 0,
    todayOverdueCount: 0,
    todayNewDueCount: 0,
    estimatedMinutes: 0,
    reviewBatchSize: 10,
    currentBatchNo: 0,
    totalBatchCount: 0,
    remainingBatchCount: 0,
    todayProgressPercent: 0,
    isStarting: false,
    isContinuing: false,
    batchLoading: false,
    errorText: '',

    /* ====== 练习 ====== */
    groups: [],
    currentGroupIdx: 0,
    groupQuestions: [],
    currentIndex: 0,
    currentQuestion: null,
    masterConfirmId: null,

    runnerProgressPercent: 0,
    runnerSubtitle: '',
    runnerSubjectName: '',

    submittingGroup: false,
    resultTransitioning: false,

    /* ====== 组结果 ====== */
    groupResults: [],
    groupWrongResults: [],
    groupCorrect: 0,
    groupWrong: 0,
    _groupSkipped: 0,
    showGroupDetails: false,

    /* ====== Dialog / undo ====== */
    exitConfirmVisible: false,
    masterUndoVisible: false,
    masterUndoText: '',

    /* ====== 最终结果 ====== */

    /* ====== UI 增强 ====== */
    _dateStr: '',
    reviewResultVm: null,
    _groupProgressStyle: '',

    /* ====== 庆祝 ====== */
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
    skeletonOptions: [1, 2, 3, 4],
    progressSteps: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90],
  },

  /* ==================== 生命周期 ==================== */

  _createReviewSession() {
    return {
      allTodayQuestionIds: [],
      completedQuestionIds: [],
      remainingQuestionIds: [],
      allQuestions: [],
      answers: {},
      sessionId: '',
      currentGroupId: '',
      allGroupResults: [],
      totalCorrect: 0,
      totalWrong: 0,
      totalCompleted: 0,
      safeModeActive: false,
      renderTraces: [],
      optionKeys: [],
      reviewOverview: null,
      overviewLoading: false,
    }
  },

  onLoad() {
    this._reviewSession = this._createReviewSession()
    this._finalCelebrationShown = false
    setRenderGuardPage('review-today')
    this._setDateStr()
    this.loadTodayReviewOverview()
  },

  onShow() {
    // 仅 overview / empty / final-result 阶段刷新，reviewing/group-result 不打断答题
    const phase = this.data.phase
    if (phase === 'overview' || phase === 'empty' || phase === 'final-result') {
      this.loadTodayReviewOverview()
    }
  },

  onHide() {
    this._clearCelebrationTimer()
    if (this.data.showCelebration) this.setData({ showCelebration: false })
  },

  onUnload() {
    resetRenderGuard()
    this._clearCelebrationTimer()
    this._clearMasterUndo()
  },

  _setDateStr() {
    const now = new Date()
    const weekdays = ['日', '一', '二', '三', '四', '五', '六']
    this.setData({
      _dateStr: `${now.getMonth() + 1}月${now.getDate()}日 星期${weekdays[now.getDay()]}`
    })
  },

  /* ==================== 今日复习概览 ==================== */

  async loadTodayReviewOverview() {
    this._reviewSession.overviewLoading = true
    this.setData({ phase: 'loading', isStarting: false, isContinuing: false })
    try {
      const overview = await api.get('/review/today/overview')
      const vm = this.buildReviewOverviewVM(overview)
      this._reviewSession.reviewOverview = overview
      this._reviewSession.allTodayQuestionIds = overview.all_question_ids || []
      this._reviewSession.completedQuestionIds = overview.completed_question_ids || []
      this._reviewSession.remainingQuestionIds = overview.remaining_question_ids || []

      let targetPhase = 'overview'
      if (vm.todayRemainingCount <= 0) {
        targetPhase = vm.todayDueCount > 0 ? 'final-result' : 'empty'
      }

      this._reviewSession.overviewLoading = false
      this.setData({
        ...vm,
        phase: targetPhase,
      })

      // 如果已完成，拉取 today/result
      if (targetPhase === 'final-result') {
        this._loadTodayResult()
      }
    } catch (e) {
      console.error('加载复习概览失败', e)
      this._reviewSession.overviewLoading = false
      this.setData({
        phase: 'error',
        errorText: '复习计划加载失败，请稍后重试',
      })
    }
  },

  /** 静默刷新概览数据（不修改 phase/group-result 等页面状态） */
  async refreshOverviewStatsSilently() {
    try {
      const overview = await api.get('/review/today/overview')
      const vm = this.buildReviewOverviewVM(overview)
      this._reviewSession.reviewOverview = overview
      this._reviewSession.allTodayQuestionIds = overview.all_question_ids || []
      this._reviewSession.completedQuestionIds = overview.completed_question_ids || []
      this._reviewSession.remainingQuestionIds = overview.remaining_question_ids || []
      this.setData({
        ...vm,
      })
    } catch (e) {
      console.error('刷新复习概览失败', e)
    }
  },

  buildReviewOverviewVM(overview) {
    const due = Number(overview.today_due_count || 0)
    const completed = Number(overview.today_completed_count || 0)
    const remaining = Number(overview.today_remaining_count || 0)
    const progress = due > 0 ? Math.round((completed / due) * 100) : 0

    const overdue = Number(overview.today_overdue_count || 0)
    let todayAdviceText = '按当前节奏完成一组，今天的复习就会更轻松。'
    if (overdue > 0) {
      todayAdviceText = `先完成 ${overdue} 道逾期题，把最容易遗忘的内容拉回来。`
    } else if (remaining <= 5) {
      todayAdviceText = `只剩 ${remaining} 道，适合一次完成今天的记忆任务。`
    } else if (completed > 0) {
      todayAdviceText = `已经完成 ${completed} 道，继续一组就能保持复习节奏。`
    }

    return {
      todayDueCount: due,
      todayCompletedCount: completed,
      todayRemainingCount: remaining,
      todayOverdueCount: overdue,
      todayNewDueCount: Number(overview.today_new_due_count || 0),
      estimatedMinutes: Number(overview.estimated_minutes || Math.ceil(remaining * 0.5)),
      reviewBatchSize: Number(overview.batch_size || 10),
      currentBatchNo: Number(overview.current_batch_no || 0),
      totalBatchCount: Number(overview.total_batch_count || 0),
      remainingBatchCount: Number(overview.remaining_batch_count || 0),
      todayProgressPercent: Math.min(100, Math.max(0, progress)),
      todayAdviceText,
    }
  },

  /* ==================== 开始复习 ==================== */

  async startTodayReview() {
    if (this.data.todayRemainingCount <= 0) return
    if (this.data.isStarting || this.data.isContinuing) return

    this._clearCelebrationTimer()
    this._finalCelebrationShown = false
    this.setData({
      isStarting: true,
      batchLoading: true,
      phase: 'reviewing',
      showCelebration: false,
    })
    try {
      const batch = await api.post('/review/today/next-batch', {
        batch_size: this.data.reviewBatchSize,
      })
      const rawQuestions = batch.questions || []
      if (!rawQuestions.length) {
        wx.showToast({ title: '今日没有待复习题目', icon: 'none' })
        this.loadTodayReviewOverview()
        return
      }

      const allQuestions = rawQuestions.map(q => this._enrichQuestion(q))
      const groups = this._splitGroups(allQuestions, allQuestions.length)

      this._reviewSession.allQuestions = allQuestions
      this._reviewSession.answers = {}
      this._reviewSession.sessionId = batch.session_id || ''
      this._reviewSession.currentGroupId = batch.group_id || ''
      this._reviewSession.allGroupResults = []
      this._reviewSession.totalCorrect = 0
      this._reviewSession.totalWrong = 0
      this._reviewSession.totalCompleted = 0
      this._reviewSession.safeModeActive = false
      this._reviewSession.renderTraces = []

      this.setData({
        phase: 'reviewing',
        groups,
        currentGroupIdx: 0,
        groupQuestions: allQuestions,
        currentIndex: 0,
        currentQuestion: null,

        currentBatchNo: batch.batch_no || 1,
        totalBatchCount: batch.total_batch_count || this.data.totalBatchCount,
        todayDueCount: batch.today_due_count || this.data.todayDueCount,
        todayCompletedCount: batch.today_completed_count || this.data.todayCompletedCount,
        todayRemainingCount: batch.today_remaining_count || 0,

        groupResults: [],
        groupWrongResults: [],
        groupCorrect: 0,
        groupWrong: 0,
        _groupSkipped: 0,
        showGroupDetails: false,

        masterConfirmId: null,
        submittingGroup: false,
        resultTransitioning: false,

        batchLoading: false,
        isStarting: false,
        isContinuing: false,
      })
      this._showQuestion(0)
      this._syncAnsweredFlags()
    } catch (e) {
      console.error('加载复习题目失败', e)
      this.setData({
        isStarting: false,
        isContinuing: false,
        batchLoading: false,
        phase: 'overview',
      })
      this.loadTodayReviewOverview()
      wx.showToast({ title: '获取复习题失败，请重试', icon: 'none' })
    }
  },

  _splitGroups(questions, size) {
    const groups = []
    for (let i = 0; i < questions.length; i += size) {
      groups.push(questions.slice(i, i + size))
    }
    return groups
  },

  /* ==================== 今日最终结果 ==================== */

  async _loadTodayResult(options) {
    const shouldCelebrate = !!(options && options.celebrate)
    try {
      const result = await api.get('/review/today/result')
      const vm = this.buildTodayReviewResultVM(result)
      this.setData({ phase: 'final-result', reviewResultVm: vm })
      // 只允许“本次停留内提交最后一组并进入最终结果”触发庆祝。
      // 初次进入、重新进入、下拉刷新、后台恢复、标记最后一题为掌握均不播放。
      if (shouldCelebrate) this._showFinalCelebrationOnce()
    } catch (e) {
      console.error('加载今日复习结果失败', e)
      // 兜底：使用本地累积结果
      const vm = this._buildReviewResultViewModel()
      this.setData({ phase: 'final-result', reviewResultVm: vm })
    }
  },

  buildTodayReviewResultVM(result) {
    const dueCount = Number(result.today_due_count || 0)
    const completedCount = Number(result.today_completed_count || 0)
    const correct = Number(result.correct_count || 0)
    const wrong = Number(result.wrong_count || 0)
    const skipped = Number(result.skipped_count || 0)
    const masteredCount = Number(result.mastered_count || 0)
    const accuracy = result.accuracy || 0
    const accuracyPct = Math.round(accuracy * 100)
    const completionRate = result.completion_rate || 0
    const completionPct = Math.round(completionRate * 100)
    const completionCapped = Math.max(0, Math.min(100, completionPct))
    const completionOver = Math.max(0, completionPct - 100)
    const remainingCount = Math.max(0, dueCount - completedCount)
    const completionHint = remainingCount > 0 ? `还剩 ${remainingCount} 道` : '今日任务已清零'
    const hasWrong = wrong > 0
    const hasSkipped = skipped > 0
    const isPerfect = wrong === 0 && completedCount > 0

    // Level classification (same as before)
    var resultLevelClass, resultTitle, resultDesc, statusText, statusDesc
    var nextStepType, nextStepTitle, nextStepDesc, nextStepTag

    if (completedCount === 0) {
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
    } else if (accuracyPct >= 80) {
      resultLevelClass = 'good'
      resultTitle = '今日复习完成'
      resultDesc = '整体表现不错，但仍有少量错题'
      statusText = '少量错题'
      statusDesc = '建议趁热复盘'
      nextStepType = 'review'
      nextStepTitle = '建议先复盘错题'
      nextStepDesc = '先处理今天的错题，再继续下一组练习'
      nextStepTag = '推荐'
    } else if (accuracyPct >= 60) {
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

    // Subject stats
    const subjectStats = (result.subject_stats || []).map(function(s) {
      return { subject: this.subjectLabel(s.subject || ''), stats: s }
    }, this)

    return {
      dueCount: dueCount,
      completedCount: completedCount,
      remainingCount: remainingCount,
      completionHint: completionHint,
      sessionTotal: completedCount,
      submittedTotal: completedCount,
      total: completedCount,
      correct: correct,
      wrong: wrong,
      skipped: skipped,
      answered: completedCount,
      accuracy: accuracyPct,
      completionRate: completionPct,
      completionCapped: completionCapped,
      completionOver: completionOver,
      wrongRate: completedCount > 0 ? Math.round(wrong / completedCount * 100) : 0,
      groupCount: this.data.totalBatchCount || 1,
      completedGroupCount: this.data.currentBatchNo || 0,
      masteredCount: masteredCount,
      subjectStats: subjectStats,
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
      _frCompletionBarStyle: completionPct + '%',
    }
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

    const hasBlankGroups = adapter.isMultiBlankChoice(q) && adapter.getBlankOptionGroups(q).length > 0
    const blankOptionGroups = hasBlankGroups ? adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), '') : []

    var renderCfg = { enableMathImage: false, DEV: config.DEV }
    if (this._reviewSession.safeModeActive) renderCfg.SAFE_MODE = true
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
      if ((hasHtmlLeak || hasRenderViolation) && !this._reviewSession.safeModeActive) {
        this._enterSafeMode()
      }
    }
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
    var traces = this._reviewSession.renderTraces
    traces = traces.concat([trace])
    if (traces.length > 200) traces = traces.slice(-200)
    this._reviewSession.renderTraces = traces
  },

  _enterSafeMode() {
    console.warn('[SELF_HEAL] review-today CODE render violation — entering SAFE_MODE')
    this._reviewSession.safeModeActive = true
    if (this.data.currentQuestion) {
      const idx = this.data.currentIndex
      const q = this.data.groupQuestions[idx]
      if (q) {
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
    const enriched = adapter.applyAnsweredFlags(this.data.groupQuestions, adapter.buildAnsweredFlags(this.data.groupQuestions, this._reviewSession.answers, KF), KF)
    this.setData({ groupQuestions: enriched })
  },

  _showQuestion(index) {
    const q = this.data.groupQuestions[index]
    if (!q) return
    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, this._reviewSession.answers, KF)
    const optionList = adapter.buildOptionList(q, this._reviewSession.answers, KF)
    const currentQuestion = Object.assign({}, q, { _optionList: optionList })
    this._reviewSession.optionKeys = q._optionKeys
    this.setData({
      currentIndex: index,
      currentQuestion: currentQuestion,
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
      runnerSubtitle: '第 ' + (this.data.currentBatchNo || this.data.currentGroupIdx + 1) + ' / ' + (this.data.totalBatchCount || 1) + ' 组',
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
    const answers = { ...this._reviewSession.answers }

    if (isMultipleChoiceType(q.question_type)) {
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
      if (answers[q.schedule_id] === opt) {
        delete answers[q.schedule_id]
      } else {
        answers[q.schedule_id] = opt
      }
    }
    this._reviewSession.answers = answers
    const optionList = adapter.buildOptionList(q, answers, KF)
    const currentQuestion = Object.assign({}, q, { _optionList: optionList })
    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, answers, KF)
    this.setData({ currentQuestion, _answeredCount: answeredCount })
    this._syncAnsweredFlags()
    this._updateRunnerFields()
  },

  selectBlankOption(e) {
    if (this.data.submittingGroup) return
    const blankId = String(e.detail.blankId || '').trim()
    const opt = String(e.detail.option || '').trim().toUpperCase()
    const q = this.data.currentQuestion
    if (!q || !blankId || !opt) return

    const answer = this._reviewSession.answers[q.schedule_id] || ''
    const blankAnswers = adapter.normalizeBlankAnswer(answer)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    const groups = q._blankOptionGroups || adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), answer)
    const newAnswer = serializeBlankAnswer(groups, blankAnswers)
    const answers = { ...this._reviewSession.answers }
    if (newAnswer) answers[q.schedule_id] = newAnswer
    else delete answers[q.schedule_id]

    const enrichedGroups = adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), newAnswer)
    const currentQuestion = Object.assign({}, q, {
      _blankOptionGroups: enrichedGroups,
      _hasBlankOptionGroups: enrichedGroups.length > 0,
    })

    this._reviewSession.answers = answers
    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, answers, KF)
    this.setData({ currentQuestion, _answeredCount: answeredCount })
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
    const question = (this.data.groupQuestions || []).find(q => String(q.schedule_id) === String(scheduleId))
    const originalIndex = (this.data.groupQuestions || []).findIndex(q => String(q.schedule_id) === String(scheduleId))
    const originalGroupIdx = this.data.currentGroupIdx
    this.setData({ masterConfirmId: null })
    if (!scheduleId || !question) return

    try {
      await api.post(`/review/${scheduleId}/master`)

      this._clearMasterUndo()
      this._pendingMasterUndo = {
        scheduleId,
        question,
        originalIndex: Math.max(0, originalIndex),
        originalGroupIdx,
      }

      const allQuestions = this._reviewSession.allQuestions.filter(q => String(q.schedule_id) !== String(scheduleId))
      const groups = this._splitGroups(allQuestions, Math.max(1, allQuestions.length))

      let currentGroupIdx = this.data.currentGroupIdx
      let currentIndex = this.data.currentIndex
      const groupQuestions = groups[currentGroupIdx] || []

      const answers = { ...this._reviewSession.answers }
      delete answers[scheduleId]
      this._reviewSession.answers = answers
      this._masteredCount = (this._masteredCount || 0) + 1
      this._reviewSession.allQuestions = allQuestions

      this.setData({
        groups,
        currentGroupIdx,
        groupQuestions,
        masterUndoVisible: true,
        masterUndoText: '已标记掌握，不再进入复习计划',
      })

      this._masterUndoTimer = setTimeout(() => {
        this._pendingMasterUndo = null
        this._masterUndoTimer = null
        this.setData({ masterUndoVisible: false })
      }, 5000)

      this.refreshOverviewStatsSilently()

      if (groupQuestions.length === 0) {
        this._loadTodayResult()
        return
      }

      if (currentIndex >= groupQuestions.length) {
        currentIndex = Math.max(0, groupQuestions.length - 1)
      }
      this.setData({ currentIndex })
      this._syncAnsweredFlags()
      this._showQuestion(currentIndex)
    } catch (e) {
      console.error('标记掌握失败', e)
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
    }
  },

  async undoMaster() {
    const pending = this._pendingMasterUndo
    if (!pending) return

    try {
      await api.post(`/review/${pending.scheduleId}/unmaster`)

      const allQuestions = (this._reviewSession.allQuestions || []).slice()
      const insertAt = Math.min(Math.max(0, pending.originalIndex), allQuestions.length)
      allQuestions.splice(insertAt, 0, pending.question)
      const groups = this._splitGroups(allQuestions, Math.max(1, allQuestions.length))
      const groupQuestions = groups[0] || []

      this._reviewSession.allQuestions = allQuestions
      this._masteredCount = Math.max(0, (this._masteredCount || 1) - 1)
      this._clearMasterUndo()

      this.setData({
        phase: 'reviewing',
        groups,
        currentGroupIdx: 0,
        groupQuestions,
        currentIndex: Math.min(insertAt, Math.max(0, groupQuestions.length - 1)),
        masterUndoVisible: false,
      })
      this._syncAnsweredFlags()
      if (groupQuestions.length > 0) {
        this._showQuestion(Math.min(insertAt, groupQuestions.length - 1))
      }
      this.refreshOverviewStatsSilently()
      wx.showToast({ title: '已撤销掌握', icon: 'none' })
    } catch (e) {
      console.error('撤销掌握失败', e)
      wx.showToast({ title: '撤销失败，请重试', icon: 'none' })
    }
  },

  _clearMasterUndo() {
    if (this._masterUndoTimer) {
      clearTimeout(this._masterUndoTimer)
      this._masterUndoTimer = null
    }
    this._pendingMasterUndo = null
    if (this.data && this.data.masterUndoVisible) {
      this.setData({ masterUndoVisible: false })
    }
  },


  /* ==================== 提交本组 ==================== */

  async submitGroup() {
    this._clearMasterUndo()
    const { groupQuestions, submittingGroup } = this.data
    const answers = this._reviewSession.answers
    if (submittingGroup) return

    const answeredCount = adapter.computeAnsweredCount(groupQuestions, answers, KF)
    const totalCount = groupQuestions.length
    const unansweredCount = totalCount - answeredCount

    let treatUnansweredAsWrong = false
    if (unansweredCount > 0) {
      try {
        const confirm = this.selectComponent('#submitConfirm')
        if (!confirm) return
        const choice = await confirm.show({
          scenario: 'unanswered',
          title: '还有未作答题目',
          message: `共 ${totalCount} 题，已作答 ${answeredCount} 题，还有 ${unansweredCount} 题未作答。选择「按不会处理」将把未答题判为错误并进入复习。`,
          confirmText: '按不会处理',
          cancelText: '仅提交已答',
        })
        treatUnansweredAsWrong = !!choice
      } catch (_) { return }
    } else {
      try {
        const confirm = this.selectComponent('#submitConfirm')
        if (!confirm) return
        const confirmed = await confirm.show({
          scenario: 'all-done',
          title: '确认提交',
          message: `共 ${totalCount} 题，已全部作答。确认提交并复盘？`,
          confirmText: '确定提交',
          cancelText: '继续检查',
        })
        if (!confirmed) return
      } catch (_) { return }
    }

    this.setData({ submittingGroup: true })

    const reviews = []
    for (const q of groupQuestions) {
      const isAnswered = adapter.isQuestionAnswered(q, answers, KF)
      if (!isAnswered && !treatUnansweredAsWrong) continue
      reviews.push({
        schedule_id: q.schedule_id,
        question_id: q.question_id,
        user_answer: isAnswered ? (answers[q.schedule_id] || '') : '',
      })
    }

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

      const allGroupResults = _mergeResultsByScheduleId(this._reviewSession.allGroupResults, groupResults)
      const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasSubmitted).length
      const totalWrong = allGroupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
      const totalCompleted = allGroupResults.filter(r => r.wasSubmitted).length

      // 被跳过的题重新入队
      const skippedQuestions = groupQuestions.filter(q => !adapter.isQuestionAnswered(q, answers, KF) && !treatUnansweredAsWrong)
      const newGroups = skippedQuestions.length > 0
        ? [...this.data.groups, skippedQuestions]
        : this.data.groups

      const hasMore = skippedQuestions.length > 0 || this.data.currentGroupIdx + 1 < newGroups.length
      // 或者用 today_remaining_count 判断

      // 静默刷新概览数据（不修改 phase，避免覆盖 group-result）
      this.refreshOverviewStatsSilently()

      this._reviewSession.allGroupResults = allGroupResults
      this._reviewSession.totalCorrect = totalCorrect
      this._reviewSession.totalWrong = totalWrong
      this._reviewSession.totalCompleted = totalCompleted

      this.setData({
        phase: 'group-result',
        groups: newGroups,
        groupResults,
        groupWrongResults: groupResults.filter(r => r.wasSubmitted && !r.isCorrect),
        groupCorrect,
        groupWrong,
        _groupSkipped: groupSkipped,
        showGroupDetails: false,
        submittingGroup: false,
        _groupProgressStyle: 'width: ' + Math.round((this.data.currentGroupIdx + 1) / Math.max(1, newGroups.length) * 100) + '%',
      })

      if (!hasMore && skippedQuestions.length === 0) {
        // 最终完成动画只在最终结果页展示，组结果保持轻量动效。
      }
    } catch (e) {
      console.error('提交失败', e)
      wx.showToast({ title: '提交失败，请重试', icon: 'none' })
      this.setData({ submittingGroup: false })
    }
  },

  /* ==================== 下一组 / 最终结果 ==================== */

  async nextGroup() {
    this._clearMasterUndo()
    if (this.data.resultTransitioning) return
    this.setData({ resultTransitioning: true })

    // 检查是否还有跳过的题在当前组的余量中
    const currentGroups = this.data.groups
    const nextGroupIdx = this.data.currentGroupIdx + 1

    if (nextGroupIdx < currentGroups.length && currentGroups[nextGroupIdx] && currentGroups[nextGroupIdx].length > 0) {
      // 有本地缓存的下一组（跳过题重排的情况）
      this._reviewSession.answers = {}
      this.setData({
        phase: 'reviewing',
        currentGroupIdx: nextGroupIdx,
        groupQuestions: currentGroups[nextGroupIdx],
        currentIndex: 0,
        groupResults: [],
        groupWrongResults: [],
        groupCorrect: 0,
        groupWrong: 0,
        showGroupDetails: false,
        resultTransitioning: false,
      })
      this._syncAnsweredFlags()
      this._showQuestion(0)
      return
    }

    // 检查今天是否还有剩余题
    if (this.data.todayRemainingCount > 0) {
      try {
        const batch = await api.post('/review/today/next-batch', {
          batch_size: this.data.reviewBatchSize,
        })
        const rawQuestions = batch.questions || []
        if (rawQuestions.length > 0) {
          const questions = rawQuestions.map(q => this._enrichQuestion(q))
          this._reviewSession.allQuestions = questions
          this._reviewSession.answers = {}
          this.setData({
            phase: 'reviewing',
            groups: [questions],
            currentGroupIdx: 0,
            groupQuestions: questions,
            currentIndex: 0,
            currentBatchNo: batch.batch_no || this.data.currentBatchNo + 1,
            totalBatchCount: batch.total_batch_count || this.data.totalBatchCount,
            todayDueCount: batch.today_due_count || this.data.todayDueCount,
            todayCompletedCount: batch.today_completed_count || this.data.todayCompletedCount,
            todayRemainingCount: batch.today_remaining_count || 0,
            groupResults: [],
            groupWrongResults: [],
            groupCorrect: 0,
            groupWrong: 0,
            showGroupDetails: false,
            resultTransitioning: false,
          })
          this._syncAnsweredFlags()
          this._showQuestion(0)
          return
        }
      } catch (e) {
        console.error('获取下一组失败', e)
        wx.showToast({ title: '获取下一组失败', icon: 'none' })
        this.setData({ resultTransitioning: false })
        return
      }
    }

    // 没有更多组了 → 最终结果。
    // 这是本次停留内提交最后一组后唯一允许播放最终庆祝动画的入口。
    this._loadTodayResult({ celebrate: true })
  },

  /* ==================== 完成反馈 ==================== */

  _showGroupCelebration(correct, total) {
    const groupIndex = this.data.currentGroupIdx + 1
    this._showCelebration({
      celebrationType: 'group',
      celebrationTitle: `第 ${groupIndex} 组完成`,
      celebrationDetail: `答对 ${correct}/${total} 题`,
      celebrationMotto: correct >= total ? '这组很稳' : '复盘后会更牢固',
    }, 2400)
  },

  _showFinalCelebrationOnce() {
    if (this._finalCelebrationShown) return
    this._finalCelebrationShown = true
    return this._showFinalCelebration()
  },

  _showFinalCelebration() {
    this._showCelebration({
      celebrationType: 'final',
      celebrationTitle: '今日复习完成',
      celebrationDetail: '今天的记忆计划已经更新',
      celebrationMotto: '清晰一点，再稳一点',
    }, 3400)
  },

  _showCelebration(copy, duration) {
    const displayDuration = duration || 3000
    this._clearCelebrationTimer()
    this.setData({
      celebrationTitle: copy.celebrationTitle || '',
      celebrationDetail: copy.celebrationDetail || '',
      celebrationMotto: copy.celebrationMotto || '',
      celebrationType: copy.celebrationType || 'final',

      // 清空复杂内容，AnimatedView 只展示精简信息
      celebrationProgressText: '',
      celebrationRewardText: '',
      growthLevel: '',
      growthLevelPct: 0,
      growthDesc: '',

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

  /* ==================== 最终结果视图模型（兜底） ==================== */

  _buildReviewResultViewModel() {
    var allResults = this._reviewSession.allGroupResults || []
    var sessionTotal = allResults.length
    var submittedTotal = allResults.filter(function(r) { return r.wasSubmitted }).length
    var correct = allResults.filter(function(r) { return r.isCorrect && r.wasSubmitted }).length
    var wrong = allResults.filter(function(r) { return r.wasSubmitted && !r.isCorrect }).length
    var skipped = Math.max(0, sessionTotal - submittedTotal)
    var accuracy = submittedTotal > 0 ? Math.round(correct / submittedTotal * 100) : 0
    var wrongRate = submittedTotal > 0 ? Math.round(wrong / submittedTotal * 100) : 0
    var dueCount = this.data.todayDueCount || sessionTotal
    var completedCount = this.data.todayCompletedCount || submittedTotal
    var completionRate = dueCount > 0 ? Math.round(completedCount / dueCount * 100) : (completedCount > 0 ? 100 : 0)
    var completionCapped = Math.max(0, Math.min(100, completionRate))
    var completionOver = Math.max(0, completionRate - 100)
    var remainingCount = Math.max(0, dueCount - completedCount)
    var completionHint = remainingCount > 0 ? `还剩 ${remainingCount} 道` : '今日任务已清零'

    var groupCount = this.data.groups.length
    var completedGroupCount = Math.min(this.data.currentGroupIdx + 1, groupCount)
    var masteredCount = this._masteredCount || 0
    var isPerfect = wrong === 0 && submittedTotal > 0
    var hasWrong = wrong > 0
    var hasSkipped = skipped > 0

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
      dueCount, completedCount, remainingCount, completionHint,
      sessionTotal, submittedTotal, total: sessionTotal,
      correct, wrong, skipped, answered: submittedTotal,
      accuracy, completionRate, completionCapped, completionOver, wrongRate,
      groupCount, completedGroupCount, masteredCount,
      subjectStats: subjectStatsArr,
      resultLevelClass, resultTitle, resultDesc,
      statusText, statusDesc,
      nextStepType, nextStepTitle, nextStepDesc, nextStepTag,
      hasWrong, hasSkipped, isPerfect,
      _frCompletionBarStyle: completionRate + '%',
    }
  },

  /* ==================== 导航按钮 ==================== */

  finishReview() {
    wx.reLaunch({ url: '/pages/home/home' })
  },

  goWrongBook() {
    wx.navigateTo({ url: '/pages/wrong-book/wrong-book' })
  },

  goPractice() {
    wx.navigateTo({ url: '/pages/practice/practice' })
  },

  goHome() {
    wx.reLaunch({ url: '/pages/home/home' })
  },

  onNavBack() {
    if (this.data.phase === 'reviewing') {
      this.setData({ exitConfirmVisible: true })
      return
    }
    const pages = getCurrentPages()
    if (pages.length > 1) wx.navigateBack()
    else wx.reLaunch({ url: '/pages/home/home' })
  },

  closeExitConfirm() {
    this.setData({ exitConfirmVisible: false })
  },

  confirmExitReview() {
    this._clearMasterUndo()
    this.setData({ exitConfirmVisible: false })
    const pages = getCurrentPages()
    if (pages.length > 1) wx.navigateBack()
    else wx.reLaunch({ url: '/pages/home/home' })
  },

  toggleGroupDetails() {
    this.setData({ showGroupDetails: !this.data.showGroupDetails })
  },

  retryLoad() {
    this.loadTodayReviewOverview()
  },

  noop() {},

  /* ==================== 工具 ==================== */

  subjectLabel(s) {
    return getSubjectName(s)
  },

})
