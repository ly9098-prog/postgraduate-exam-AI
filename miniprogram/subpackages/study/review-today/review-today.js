const api = require('../../../utils/api')
const config = require('../../../config')
const {
  buildRenderModel, resetRenderGuard, setRenderGuardPage,
  stripLeadingOptionLabel, toPlainInlineMathText, needsRichRender,
  textToHtml
} = require('../utils/stem-render')
const {
  isMultipleChoiceType, isTrueFalseType,
  normalizeChoiceAnswer, serializeChoiceAnswer, serializeBlankAnswer,
} = require('../utils/answer')
const adapter = require('../utils/question-runner-adapter')
const { getSubjectName } = require('../../../utils/subject-meta')

var KF = 'schedule_id'

var REVIEW_BATCH_SIZE_OPTIONS = [5, 10, 20, 30]

/**
 * Normalize review batch size to one of the allowed values.
 * Falls back to 10 for invalid or out-of-range inputs.
 */
function normalizeReviewBatchSize(value) {
  var num = Number(value)
  if (isNaN(num) || num <= 0) return 10
  for (var i = 0; i < REVIEW_BATCH_SIZE_OPTIONS.length; i++) {
    if (num === REVIEW_BATCH_SIZE_OPTIONS[i]) return num
  }
  return 10
}

/**
 * Format elapsed seconds as MM:SS.
 * MM can exceed 59 (60 minutes -> "60:00").
 */
function formatReviewElapsed(sec) {
  var s = Math.max(0, sec || 0)
  var m = Math.floor(s / 60)
  var ss = s % 60
  return (m < 10 ? '0' : '') + m + ':' + (ss < 10 ? '0' : '') + ss
}

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

/**
 * Lightweight normalization of a review question from API response.
 * Does NOT build render model — that happens lazily in _showQuestion().
 * Does NOT compute _optText, _optHtml, _blankOptionGroups, etc.
 */
function normalizeReviewQuestion(raw) {
  if (!raw || typeof raw !== 'object') return null
  var content = raw.content
  if (typeof content === 'string') {
    content = { text: content }
  } else if (!content || typeof content !== 'object') {
    content = { text: raw.stem || '' }
  }
  var opts = raw.options
  if (!opts || typeof opts !== 'object' || Array.isArray(opts)) {
    opts = {}
  }
  return {
    schedule_id: raw.schedule_id,
    question_id: raw.question_id,
    id: raw.id || raw.question_id,
    subject_id: raw.subject_id != null ? raw.subject_id : null,
    subject_code: raw.subject_code || '',
    subject_name: raw.subject_name || '',
    question_type: raw.question_type || '',
    stem: raw.stem || '',
    options: opts,
    content: content,
    image_url: raw.image_url || null,
    interval: raw.interval || 0,
    repetitions: raw.repetitions || 0,
    ease_factor: raw.ease_factor || 2.5,
  }
}

Page({
  data: {
    /* ====== Phase ====== */
    // loading | overview | reviewing | group-result | final-result | empty | error
    phase: 'loading',

    /* ====== Timer ====== */
    elapsedText: '00:00',

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
    groupAccuracyPercent: 0,
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

    batchSizeOptions: [5, 10, 20, 30],

    /* ====== Batch size sheet ====== */
    showBatchSizeSheet: false,
    pendingBatchSize: 10,

    /* ====== Skeleton (loading placeholder) ====== */
    skeletonOptions: [1, 2, 3, 4],
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
      // 复习过程中固定今日任务总数。已完成题会被调度到未来日期，
      // 接口返回的实时待复习数会随提交逐步缩小，不能直接作为完成度分母。
      todayTaskTotalCount: 0,
      completedBeforeSession: 0,
      safeModeActive: false,
      renderTraces: [],
      optionKeys: [],
      reviewOverview: null,
      overviewLoading: false,
      // Timer state (non-observable, kept in session object)
      timerStartedAt: 0,
      timerElapsedMs: 0,
      timerRunning: false,
    }
  },

  onLoad() {
    this._reviewSession = this._createReviewSession()
    this._timerInterval = null
    this._userSelectedReviewBatchSize = false
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
    // 从后台回到 reviewing 页面时恢复计时
    if (phase === 'reviewing' && this._reviewSession && this._reviewSession.timerStartedAt > 0 && !this._reviewSession.timerRunning) {
      this._resumeReviewTimer()
    }
  },

  onHide() {
    // 离开页面时暂停复习计时（保留累计时长）
    this._pauseReviewTimer()
  },

  onUnload() {
    resetRenderGuard()
    this._clearMasterUndo()
    this._clearReviewTimer()
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

      // 已完成的题会被调度到未来日期，导致 overview 的实时 due_count 变成 0。
      // 此时再看一次今日结果，避免用户完成全部任务后重新进入却被当成空状态。
      if (targetPhase === 'empty') {
        try {
          const todayResult = await api.get('/review/today/result')
          const hasTodayResult = Number(todayResult.today_completed_count || 0) > 0 || Number(todayResult.mastered_count || 0) > 0
          if (hasTodayResult) {
            const resultVm = this.buildTodayReviewResultVM(todayResult)
            this._reviewSession.overviewLoading = false
            this.setData({
              ...vm,
              phase: 'final-result',
              reviewResultVm: resultVm,
            })
            return
          }
        } catch (resultError) {
          console.warn('加载今日复习结果兜底失败', resultError)
        }
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

      if (this._reviewSession.todayTaskTotalCount > 0 && (this.data.phase === 'reviewing' || this.data.phase === 'group-result')) {
        const taskTotalCount = Math.max(
          Number(this._reviewSession.todayTaskTotalCount || 0),
          Number(this.data.todayDueCount || 0)
        )
        const remainingCount = Math.min(taskTotalCount, Math.max(0, Number(vm.todayRemainingCount || 0)))
        vm.todayDueCount = taskTotalCount
        vm.todayRemainingCount = remainingCount
        vm.todayCompletedCount = Math.max(0, taskTotalCount - remainingCount)
        vm.todayProgressPercent = taskTotalCount > 0 ? Math.round(vm.todayCompletedCount / taskTotalCount * 100) : 0
      }

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

    // 用户已手动选择时保留其选择，未选择则使用接口返回的合法值
    var batchSize = Number(overview.batch_size || 10)
    batchSize = normalizeReviewBatchSize(batchSize)
    if (this._userSelectedReviewBatchSize) {
      batchSize = this.data.reviewBatchSize
    }

    return {
      todayDueCount: due,
      todayCompletedCount: completed,
      todayRemainingCount: remaining,
      todayOverdueCount: overdue,
      todayNewDueCount: Number(overview.today_new_due_count || 0),
      estimatedMinutes: Number(overview.estimated_minutes || Math.ceil(remaining * 0.5)),
      reviewBatchSize: batchSize,
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

    // Stay in loading phase while fetching (shows skeleton)
    this.setData({
      isStarting: true,
      batchLoading: true,
      phase: 'loading',
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

      // Lightweight normalization only — no render model building
      const allQuestions = rawQuestions.map(normalizeReviewQuestion).filter(Boolean)
      if (!allQuestions.length) {
        throw new Error('所有题目标准化后为空')
      }

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

      // Build render model for first question only
      var firstEnriched = this._enrichQuestion(allQuestions[0])
      var firstOptionList = adapter.buildOptionList(firstEnriched, {}, KF)
      var firstQuestion = Object.assign({}, firstEnriched, {
        _optionList: firstOptionList,
      })
      this._reviewSession.optionKeys = firstEnriched._optionKeys

      // Calculate DEV payload estimate
      this._checkSetDataSize({ phase: 'reviewing', currentQuestion: firstQuestion })

      // 固定本次复习的任务总数，避免后端实时 due_count 在提交后缩小。
      const batchDueCount = Number(batch.today_due_count || 0)
      const batchCompletedCount = Number(batch.today_completed_count || 0)
      const taskTotalCount = Math.max(
        Number(this._reviewSession.todayTaskTotalCount || 0),
        Number(this.data.todayDueCount || 0),
        batchDueCount,
        allQuestions.length
      )
      const completedBeforeSession = Math.max(
        Number(this._reviewSession.completedBeforeSession || 0),
        Number(this.data.todayCompletedCount || 0),
        batchCompletedCount
      )
      this._reviewSession.todayTaskTotalCount = taskTotalCount
      this._reviewSession.completedBeforeSession = completedBeforeSession

      // Atomic state transition: all critical fields set in one setData
      this.setData({
        phase: 'reviewing',
        groups: [allQuestions],
        currentGroupIdx: 0,
        groupQuestions: allQuestions,
        currentIndex: 0,
        currentQuestion: firstQuestion,
        _answeredCount: 0,

        currentBatchNo: batch.batch_no || 1,
        totalBatchCount: batch.total_batch_count || this.data.totalBatchCount,
        todayDueCount: taskTotalCount,
        todayCompletedCount: completedBeforeSession,
        todayRemainingCount: Math.max(0, taskTotalCount - completedBeforeSession),

        groupResults: [],
        groupWrongResults: [],
        groupCorrect: 0,
        groupWrong: 0,
        _groupSkipped: 0,
        groupAccuracyPercent: 0,
        showGroupDetails: false,

        masterConfirmId: null,
        submittingGroup: false,
        resultTransitioning: false,

        batchLoading: false,
        isStarting: false,
        isContinuing: false,
      })
      this._updateRunnerFields()
      this._checkRenderInvariant(firstEnriched._renderModel)
      this._recordRenderTrace(firstEnriched._renderModel && firstEnriched._renderModel.renderTrace)
      this._startReviewTimer()
    } catch (e) {
      console.error('[REVIEW_ERROR] startTodayReview failed',
        'batchSize=' + this.data.reviewBatchSize,
        'statusCode=' + (e.statusCode || 'N/A'),
        'detail=' + (e.detail || e.message || 'unknown'))
      this.setData({
        isStarting: false,
        isContinuing: false,
        batchLoading: false,
        phase: 'error',
        errorText: '获取复习题失败，请检查网络后重试',
      })
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

  async _loadTodayResult() {
    try {
      const result = await api.get('/review/today/result')
      const vm = this.buildTodayReviewResultVM(result)
      this.setData({ phase: 'final-result', reviewResultVm: vm })
    } catch (e) {
      console.error('加载今日复习结果失败', e)
      // 兜底：使用本地累积结果
      const vm = this._buildReviewResultViewModel()
      this.setData({ phase: 'final-result', reviewResultVm: vm })
    }
  },

  buildTodayReviewResultVM(result) {
    const completedCount = Math.max(
      Number(result.today_completed_count || 0),
      Number(this.data.todayCompletedCount || 0)
    )
    const dueCount = Math.max(
      Number(result.today_due_count || 0),
      Number(this._reviewSession && this._reviewSession.todayTaskTotalCount || 0),
      Number(this.data.todayDueCount || 0),
      completedCount
    )
    const correct = Number(result.correct_count || 0)
    const wrong = Number(result.wrong_count || 0)
    const skipped = Number(result.skipped_count || 0)
    const masteredCount = Number(result.mastered_count || 0)
    const accuracy = result.accuracy || 0
    const accuracyPct = Math.round(accuracy * 100)
    const completionPct = dueCount > 0 ? Math.round(completedCount / dueCount * 100) : 0
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
      return {
        subject: this.subjectLabel(s.subject_name, s.subject_code),
        subject_id: s.subject_id != null ? s.subject_id : (s.subject_code || ''),
        stats: s,
      }
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
      _subjectLabel: this.subjectLabel(q.subject_name, q.subject_code),
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

  /**
   * Estimate and warn about large setData payloads in DEV environment.
   * Only stringifies in DEV to avoid production overhead.
   */
  _checkSetDataSize(data) {
    if (!config.DEV) return
    var THRESHOLD = 200 * 1024 // 200 KB warning threshold
    try {
      var size = new Blob([JSON.stringify(data)]).size
      if (size > THRESHOLD) {
        console.warn('[SETDATA_SIZE] payload ~' + (size / 1024).toFixed(0) + 'KB for keys: ' + Object.keys(data).join(', ') + ' (threshold: ' + (THRESHOLD / 1024) + 'KB)')
      }
    } catch (e) {
      // Blob may not be available in all mini-program environments
    }
  },

  _syncAnsweredFlags() {
    const enriched = adapter.applyAnsweredFlags(this.data.groupQuestions, adapter.buildAnsweredFlags(this.data.groupQuestions, this._reviewSession.answers, KF), KF)
    this.setData({ groupQuestions: enriched })
  },

  _showQuestion(index) {
    const q = this.data.groupQuestions[index]
    if (!q) return

    // Lazily build render model — only for the current question, not the whole batch
    var enriched = q._renderModel ? q : this._enrichQuestion(q)

    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, this._reviewSession.answers, KF)
    const optionList = adapter.buildOptionList(enriched, this._reviewSession.answers, KF)

    // Restore blank option selections from answer map
    var blankOptionGroups = enriched._blankOptionGroups || []
    var hasBlankOptionGroups = enriched._hasBlankOptionGroups || false
    if (hasBlankOptionGroups) {
      const answer = this._reviewSession.answers[enriched.schedule_id] || ''
      blankOptionGroups = adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(enriched), answer)
    }

    const currentQuestion = Object.assign({}, enriched, {
      _optionList: optionList,
      _blankOptionGroups: blankOptionGroups,
      _hasBlankOptionGroups: blankOptionGroups.length > 0,
    })
    this._reviewSession.optionKeys = enriched._optionKeys

    // Cache the enriched question so subsequent navigations don't re-build
    if (!q._renderModel) {
      var gq = this.data.groupQuestions.slice()
      gq[index] = enriched
      this.setData({ groupQuestions: gq })
    }

    this._checkSetDataSize({ currentIndex: index, currentQuestion: currentQuestion })
    this.setData({
      currentIndex: index,
      currentQuestion: currentQuestion,
      _answeredCount: answeredCount,
    })
    this._updateRunnerFields()
    this._checkRenderInvariant(enriched._renderModel)
    this._recordRenderTrace(enriched._renderModel && enriched._renderModel.renderTrace)
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
    if (!q || !adapter.isMultiBlankChoice(q) || !blankId || !opt) return

    const answer = this._reviewSession.answers[q.schedule_id] || ''
    const blankAnswers = adapter.normalizeBlankAnswer(answer)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    // Use raw groups for serialization (only needs group.id)
    const rawGroups = adapter.getBlankOptionGroups(q)
    const newAnswer = serializeBlankAnswer(rawGroups, blankAnswers)
    const answers = { ...this._reviewSession.answers }
    if (newAnswer) answers[q.schedule_id] = newAnswer
    else delete answers[q.schedule_id]

    const enrichedGroups = adapter.enrichBlankOptionGroups(rawGroups, newAnswer)

    this._reviewSession.answers = answers
    const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, answers, KF)
    // Consolidate answered flags and progress into single setData
    const enrichedQuestions = adapter.applyAnsweredFlags(this.data.groupQuestions,
      adapter.buildAnsweredFlags(this.data.groupQuestions, answers, KF), KF)

    this.setData({
      _answeredCount: answeredCount,
      runnerProgressPercent: Math.round(answeredCount / (enrichedQuestions.length || 1) * 100),
      runnerSubtitle: '第 ' + (this.data.currentBatchNo || this.data.currentGroupIdx + 1) + ' / ' + (this.data.totalBatchCount || 1) + ' 组',
      runnerSubjectName: q ? (q.subject_name || q._subjectLabel || '') : '',
      'currentQuestion._blankOptionGroups': enrichedGroups,
      'currentQuestion._hasBlankOptionGroups': enrichedGroups.length > 0,
      groupQuestions: enrichedQuestions,
    })
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
      const groupQuestions = allQuestions.slice()

      let currentGroupIdx = this.data.currentGroupIdx
      let currentIndex = this.data.currentIndex

      const answers = { ...this._reviewSession.answers }
      delete answers[scheduleId]
      this._reviewSession.answers = answers
      this._masteredCount = (this._masteredCount || 0) + 1
      this._reviewSession.allQuestions = allQuestions

      this.setData({
        groups: [allQuestions],
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

      await this.refreshOverviewStatsSilently()

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
      const groupQuestions = allQuestions.slice()

      this._reviewSession.allQuestions = allQuestions
      this._masteredCount = Math.max(0, (this._masteredCount || 1) - 1)
      this._clearMasterUndo()

      this.setData({
        phase: 'reviewing',
        groups: [groupQuestions],
        currentGroupIdx: 0,
        groupQuestions,
        currentIndex: Math.min(insertAt, Math.max(0, groupQuestions.length - 1)),
        masterUndoVisible: false,
      })
      this._syncAnsweredFlags()
      if (groupQuestions.length > 0) {
        this._showQuestion(Math.min(insertAt, groupQuestions.length - 1))
      }
      await this.refreshOverviewStatsSilently()
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

      // 本地更新今日任务进度，避免接口中“实时待复习数”因已完成题被改期而缩小，
      // 导致最终页出现 1 / 0、完成度 0% 等不合理展示。
      const todayTaskTotalCount = Math.max(
        Number(this._reviewSession.todayTaskTotalCount || 0),
        Number(this.data.todayDueCount || 0),
        totalCompleted
      )
      const completedBeforeSession = Number(this._reviewSession.completedBeforeSession || 0)
      const todayCompletedCount = Math.min(
        todayTaskTotalCount,
        Math.max(Number(this.data.todayCompletedCount || 0), completedBeforeSession + totalCompleted)
      )
      const todayRemainingCount = Math.max(0, todayTaskTotalCount - todayCompletedCount)
      this._reviewSession.todayTaskTotalCount = todayTaskTotalCount

      this._reviewSession.allGroupResults = allGroupResults
      this._reviewSession.totalCorrect = totalCorrect
      this._reviewSession.totalWrong = totalWrong
      this._reviewSession.totalCompleted = totalCompleted

      // 提交成功进入组结果页时暂停计时
      this._pauseReviewTimer()
      this.setData({
        phase: 'group-result',
        groups: newGroups,
        groupResults,
        groupWrongResults: groupResults.filter(r => r.wasSubmitted && !r.isCorrect),
        groupCorrect,
        groupWrong,
        _groupSkipped: groupSkipped,
        groupAccuracyPercent: Math.round(groupQuestions.length > 0 ? groupCorrect / groupQuestions.length * 100 : 0),
        todayDueCount: todayTaskTotalCount,
        todayCompletedCount: todayCompletedCount,
        todayRemainingCount: todayRemainingCount,
        todayProgressPercent: todayTaskTotalCount > 0 ? Math.round(todayCompletedCount / todayTaskTotalCount * 100) : 0,
        showGroupDetails: false,
        submittingGroup: false,
        _groupProgressStyle: 'width: ' + Math.round((this.data.currentGroupIdx + 1) / Math.max(1, newGroups.length) * 100) + '%',
      })
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
        groupAccuracyPercent: 0,
        showGroupDetails: false,
        resultTransitioning: false,
      })
      this._syncAnsweredFlags()
      this._showQuestion(0)
      // 新组从 00:00 开始计时
      this._startReviewTimer()
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
          const questions = rawQuestions.map(normalizeReviewQuestion).filter(Boolean)
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
            todayDueCount: this._reviewSession.todayTaskTotalCount || this.data.todayDueCount,
            todayCompletedCount: this.data.todayCompletedCount,
            todayRemainingCount: this.data.todayRemainingCount,
            groupResults: [],
            groupWrongResults: [],
            groupCorrect: 0,
            groupWrong: 0,
            groupAccuracyPercent: 0,
            showGroupDetails: false,
            resultTransitioning: false,
          })
          this._syncAnsweredFlags()
          this._showQuestion(0)
          // 新组从 00:00 开始计时
          this._startReviewTimer()
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
    this._loadTodayResult()
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
    var completedCount = Math.max(Number(this.data.todayCompletedCount || 0), submittedTotal)
    var dueCount = Math.max(
      Number(this._reviewSession.todayTaskTotalCount || 0),
      Number(this.data.todayDueCount || 0),
      completedCount,
      sessionTotal
    )
    var completionRate = dueCount > 0 ? Math.round(completedCount / dueCount * 100) : 0
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
      var sid = r.subject_id != null ? r.subject_id : (r.subject_code || '')
      if (sid === '' || sid == null) return
      if (!subjectMap[sid]) subjectMap[sid] = { reviewed: 0, correct: 0, wrong: 0, skipped: 0, subject_name: r.subject_name || '', subject_code: r.subject_code || '' }
      var s = subjectMap[sid]
      s.reviewed++
      if (!r.wasSubmitted) { s.skipped++; return }
      if (r.isCorrect) s.correct++
      else s.wrong++
    })
    var subjectStatsArr = []
    for (var subj in subjectMap) {
      if (subjectMap.hasOwnProperty(subj)) {
        var entry = subjectMap[subj]
        subjectStatsArr.push({ subject: this.subjectLabel(entry.subject_name, entry.subject_code), subject_id: subj, stats: entry })
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
    wx.navigateTo({ url: '/subpackages/study/wrong-book/wrong-book' })
  },

  goPractice() {
    wx.navigateTo({ url: '/subpackages/study/practice/practice' })
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
    this._clearReviewTimer()
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

  subjectLabel(name, code) {
    if (name) return name
    return getSubjectName(code || name)
  },

  /* ==================== 计时 ==================== */

  /**
   * 钳制时间差，防止系统时间后退或大幅度跳跃破坏累计时长。
   * 单 tick 上限 10 秒（setInterval 1 秒 + 合理延迟余量）。
   */
  _safeTickDelta(rawMs) {
    if (rawMs < 0) return 0
    if (rawMs > 10000) return 10000
    return rawMs
  },

  /**
   * 开始新组计时（重置为 00:00）。
   * 基于 Date.now() 时间差计算，不依赖每秒累加。
   */
  _startReviewTimer() {
    if (this._timerInterval) return
    this._reviewSession.timerElapsedMs = 0
    this._reviewSession.timerStartedAt = Date.now()
    this._reviewSession.timerRunning = true
    var self = this
    this._timerInterval = setInterval(function () {
      var session = self._reviewSession
      var rawDelta = Date.now() - session.timerStartedAt
      var totalMs = session.timerElapsedMs + self._safeTickDelta(rawDelta)
      self.setData({ elapsedText: formatReviewElapsed(Math.floor(totalMs / 1000)) })
    }, 1000)
  },

  /**
   * 暂停计时，保留已累计时长。
   * 受系统时间跳变保护：负值截断为零，单次增量上限 10 秒。
   */
  _pauseReviewTimer() {
    if (!this._timerInterval) return
    var rawDelta = Date.now() - this._reviewSession.timerStartedAt
    this._reviewSession.timerElapsedMs += this._safeTickDelta(rawDelta)
    this._reviewSession.timerRunning = false
    clearInterval(this._timerInterval)
    this._timerInterval = null
  },

  /**
   * 从暂停处恢复计时（保留 timerElapsedMs）。
   * 暂停期间经过的 wall-clock 时间不计入，与 resume 点对齐。
   */
  _resumeReviewTimer() {
    if (this._timerInterval || this._reviewSession.timerRunning) return
    this._reviewSession.timerStartedAt = Date.now()
    this._reviewSession.timerRunning = true
    var self = this
    this._timerInterval = setInterval(function () {
      var session = self._reviewSession
      var rawDelta = Date.now() - session.timerStartedAt
      var totalMs = session.timerElapsedMs + self._safeTickDelta(rawDelta)
      self.setData({ elapsedText: formatReviewElapsed(Math.floor(totalMs / 1000)) })
    }, 1000)
  },

  /**
   * 重置为 00:00（不清除 interval，调用后应紧接着 _startReviewTimer/_resumeReviewTimer）。
   */
  _resetReviewTimer() {
    this._pauseReviewTimer()
    this._reviewSession.timerElapsedMs = 0
    this._reviewSession.timerStartedAt = 0
    this._reviewSession.timerRunning = false
    this.setData({ elapsedText: '00:00' })
  },

  /**
   * 销毁定时器（不保留累计时长）。用于页面卸载或退出。
   */
  _clearReviewTimer() {
    if (this._timerInterval) {
      clearInterval(this._timerInterval)
      this._timerInterval = null
    }
    this._reviewSession.timerRunning = false
  },

  /* ==================== 每组题数选择（自定义底部弹层） ==================== */

  /**
   * 打开每组题数底部弹层。
   * 仅在 overview 阶段且无进行中请求时可用。
   * 将 pendingBatchSize 初始化为当前生效的 reviewBatchSize。
   */
  showBatchSizeSelector() {
    if (this.data.phase !== 'overview') return
    if (this.data.isStarting || this.data.isContinuing) return
    this.setData({
      pendingBatchSize: this.data.reviewBatchSize,
      showBatchSizeSheet: true,
    })
  },

  /**
   * 遮罩点击：关闭弹层，不修改正式选择。
   */
  handleBatchSheetMaskTap() {
    this.closeBatchSizeSheet()
  },

  /**
   * 阻止弹层内容区域的点击冒泡到遮罩。
   */
  stopBatchSheetPropagation() {
    /* no-op: catchtap prevents propagation */
  },

  /**
   * 关闭弹层，不修改正式选择。
   * 清理临时状态。
   */
  closeBatchSizeSheet() {
    this.setData({ showBatchSizeSheet: false })
  },

  /**
   * 点击选项，只修改临时选择 pendingBatchSize。
   * 不修改真正的 reviewBatchSize。
   */
  selectPendingBatchSize(e) {
    var value = Number(e.currentTarget.dataset.value)
    if (REVIEW_BATCH_SIZE_OPTIONS.indexOf(value) === -1) return
    this.setData({ pendingBatchSize: value })
  },

  /**
   * 确认使用，将 pendingBatchSize 应用到 reviewBatchSize。
   * 标记用户已主动选择。
   */
  confirmBatchSize() {
    var pending = this.data.pendingBatchSize
    pending = normalizeReviewBatchSize(pending)
    this._userSelectedReviewBatchSize = true
    this.setData({
      reviewBatchSize: pending,
      showBatchSizeSheet: false,
    })
  },

})

// Export pure functions and constants for regression testing
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    normalizeReviewBatchSize,
    formatReviewElapsed,
    normalizeReviewQuestion,
    REVIEW_BATCH_SIZE_OPTIONS,
    // Export data fields for test verification
    BATCH_SIZE_OPTIONS_META: [
      { value: 5, label: '快速复习' },
      { value: 10, label: '推荐' },
      { value: 20, label: '集中巩固' },
      { value: 30, label: '深度复习' },
    ],
  }
}
