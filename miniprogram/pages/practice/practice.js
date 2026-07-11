const api = require('../../utils/api')
const config = require('../../config')
const { createTraceId, debugLog, saveDebugSnapshot, shouldDebugQuestion } = require('../../utils/debug')
const { buildRenderModel, setRenderGuardPage, resetRenderGuard } = require('../../utils/stem-render')
const adapter = require('../../utils/question-runner-adapter')

Page({
  data: {
    // 设置
    subjectTree: [],
    selectedSubjectId: null,
    selectedSubjectName: '',
    expandedSubjectId: null,
    selectedMode: 'random',
    selectedModeLabel: '随机',
    count: 5,
    started: false,
    loading: false,
    submitting: false,

    // computed
    progressPercent: 0,

    // 题目列表
    questions: [],
    currentIndex: 0,
    totalQuestions: 0,
    currentQuestion: null,

    // 答题卡
    answeredCount: 0,
    // 提交后
    submitted: false,
    feedbackVisible: false,
    feedbackType: '',
    feedbackTitle: '',
    feedbackDetail: '',
    feedbackComboText: '',
    feedbackComboLevel: '',
    feedbackStarCount: 0,

    // 计时
    elapsedText: '00:00',
    _timer: null,

    // 公式图片化
    enableMathImage: false,

    // Perfect celebration
    showPerfectCelebration: false,
    perfectCelebrationType: 'practice',
    perfectCelebrationTitle: '全对完成',
    perfectCelebrationDetail: '',
    perfectCelebrationMotto: '这组掌握很稳，继续保持',
    perfectCelebrationRewardText: '',
  },

  _practiceSession: {
    traceId: '',
    safeModeActive: false,
    answerMap: {},
    answeredFlags: {},
    correctCount: 0,
    comboCount: 0,
    elapsedSec: 0,
    startTime: 0,
    questionTimeMap: {},
    currentQuestionStartedAt: 0,
    requestId: '',
    optionKeys: [],
  },

  onLoad() {
    this._pendingResultUrl = ''
    this.setData({ enableMathImage: config.enableMathImage || false })
    setRenderGuardPage('practice')
    resetRenderGuard()
    this.loadPracticeSubjects()
  },

  onUnload() {
    resetRenderGuard()
    this._clearTimer()
    if (this._feedbackTimer) {
      clearTimeout(this._feedbackTimer)
      this._feedbackTimer = null
    }
  },

  onShow() {
  },

  onReady() {
    if (config.DEV) console.log('[LAYER6_ONREADY]', Date.now())
  },

  /* ==================== 设置阶段 ==================== */

  async loadPracticeSubjects() {
    try {
      const res = await api.get('/practice/subjects')
      const subjectTree = this.normalizeSubjectTree(res || [])
      this.setData({ subjectTree })
      this.initDefaultSubject(subjectTree)
    } catch (e) {
      console.error('加载科目树失败', e)
      wx.showToast({ title: '加载科目失败', icon: 'none' })
    }
  },

  /**
   * 规范化科目树。保留后端返回的已有树结构，不做展平-重建。
   * - 如果节点已带 children，递归归一化每个子节点
   * - 如果原始是平铺列表（含 parent_id），按 parent_id 组装树
   * - 顶层只保留 level=1 或 parent_id 为空的节点
   * - 过滤 is_active=false
   * - 父级与子级均按 sort_order 升序
   */
  normalizeSubjectTree(raw) {
    if (!Array.isArray(raw) || raw.length === 0) return []

    const toId = (n) => (n.subject_id != null ? n.subject_id : n.id)
    const toName = (n) => (n.display_name != null ? n.display_name : (n.name != null ? n.name : ''))
    const toCode = (n) => (n.subject_code != null ? n.subject_code : (n.code != null ? n.code : ''))
    const bySort = (a, b) => (a.sort_order - b.sort_order) || (a.subject_id - b.subject_id)

    const normalize = (n) => {
      if (!n) return null
      if (n.is_active === false) return null
      return {
        subject_id: Number(toId(n)),
        display_name: toName(n),
        subject_code: toCode(n),
        parent_id: n.parent_id != null ? Number(n.parent_id) : null,
        level: n.level != null ? Number(n.level) : null,
        path: n.path || '',
        sort_order: n.sort_order != null ? Number(n.sort_order) : 0,
        is_active: true,
        children: Array.isArray(n.children)
          ? n.children.map(normalize).filter(Boolean).sort(bySort)
          : [],
      }
    }

    // 先递归归一化（保留已有 children 结构）
    const items = raw.map(normalize).filter(Boolean)
    if (items.length === 0) return []

    // 拆分父级与子级
    const parentItems = []
    const childItems = []
    const nodes = {}

    items.forEach((n) => {
      nodes[n.subject_id] = n
      const isParent = n.level === 1 || n.parent_id == null
      if (isParent) parentItems.push(n)
      else childItems.push(n)
    })

    // 将无父级 children 的子级挂到对应父级
    childItems.forEach((child) => {
      const parent = child.parent_id != null ? nodes[child.parent_id] : null
      if (parent) {
        if (!parent.children.some((c) => c.subject_id === child.subject_id)) {
          parent.children.push(child)
        }
        parent.children.sort(bySort)
      } else {
        // 找不到父级，升级为根节点
        parentItems.push(child)
      }
    })

    parentItems.sort(bySort)
    return parentItems
  },

  /**
   * 初始化默认选中（方案 2：默认展开第一个父级并选中第一个子级）
   * 保证 expandedSubjectId / selectedSubjectId / selectedSubjectName 同时被正确设置，
   * 避免出现 selectedSubjectId 为空但页面看起来已选择的不一致状态。
   */
  initDefaultSubject(subjectTree) {
    if (!subjectTree || subjectTree.length === 0) {
      this.setData({
        selectedSubjectId: null,
        selectedSubjectName: '',
        expandedSubjectId: null,
      })
      return
    }
    const first = subjectTree[0]
    const children = Array.isArray(first.children) ? first.children : []
    if (children.length > 0) {
      const firstChild = children[0]
      this.setData({
        expandedSubjectId: first.subject_id,
        selectedSubjectId: firstChild.subject_id,
        selectedSubjectName: firstChild.display_name,
      })
    } else {
      this.setData({
        expandedSubjectId: first.subject_id,
        selectedSubjectId: first.subject_id,
        selectedSubjectName: first.display_name,
      })
    }
  },

  /**
   * 点击父级科目行（纵向折叠列表）：
   * - 有 children：纯 toggle expandedSubjectId（点击已展开的父级会收起；不修改 selectedSubjectId）
   * - 无 children：该父级本身作为可选科目，更新 selectedSubjectId / selectedSubjectName
   */
  toggleParentSubject(e) {
    const ds = e.currentTarget.dataset || {}
    const subjectId = Number(ds.subjectId)
    const subjectName = ds.subjectName
    const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
    if (!subjectId) return

    if (hasChildren) {
      // 纯 toggle：已展开则收起，未展开则展开；不动 selectedSubjectId
      const next = this.data.expandedSubjectId === subjectId ? null : subjectId
      this.setData({ expandedSubjectId: next })
    } else {
      // 叶子父级：直接选中；展开态也指向它，让行显示 selected 视觉
      if (
        this.data.selectedSubjectId === subjectId &&
        this.data.expandedSubjectId === subjectId
      ) return
      this.setData({
        expandedSubjectId: subjectId,
        selectedSubjectId: subjectId,
        selectedSubjectName: subjectName,
      })
    }
  },

  /**
   * 点击子级科目 chip：真正更新当前选中科目。
   * 不自动开始练习，只更新选择；保持当前展开态不变。
   */
  chooseChildSubject(e) {
    const ds = e.currentTarget.dataset || {}
    const subjectId = Number(ds.subjectId)
    const subjectName = ds.subjectName
    if (!subjectId) return
    // 已是当前选中项则跳过，避免无意义的 setData
    if (this.data.selectedSubjectId === subjectId) return
    this.setData({
      selectedSubjectId: subjectId,
      selectedSubjectName: subjectName,
    })
  },

  chooseMode(e) {
    this.setData({ selectedMode: e.currentTarget.dataset.mode }, () => {
      this._updateComputedFields()
    })
  },

  setCount(e) {
    this.setData({ count: Number(e.currentTarget.dataset.count) })
  },

  async startPractice() {
    const traceId = createTraceId()
    const now = Date.now()
    this._practiceSession.traceId = traceId
    this._practiceSession.safeModeActive = false
    this._practiceSession.answerMap = {}
    this._practiceSession.answeredFlags = {}
    this._practiceSession.correctCount = 0
    this._practiceSession.comboCount = 0
    this._practiceSession.elapsedSec = 0
    this._practiceSession.startTime = now
    this._practiceSession.questionTimeMap = {}
    this._practiceSession.currentQuestionStartedAt = 0
    this._practiceSession.requestId = ''
    this._practiceSession.optionKeys = []
    this.setData({
      started: true,
      currentIndex: 0,
      answeredCount: 0,
      results: [],
      submitted: false,
      wrongCount: 0,
      feedbackVisible: false,
      feedbackType: '',
      feedbackTitle: '',
      feedbackDetail: '',
      feedbackComboText: '',
    })
    this._startTimer()
    await this._loadQuestions()
  },

  _startTimer() {
    this._clearTimer()
    this._timer = setInterval(() => {
      const sec = Math.floor((Date.now() - this._practiceSession.startTime) / 1000)
      this._practiceSession.elapsedSec = sec
      this.setData({ elapsedText: this._fmt(sec) })
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
      const subjectId = this.data.selectedSubjectId
      if (!subjectId) {
        this._clearTimer()
        this.setData({
          loading: false,
          started: false,
          questions: [],
          totalQuestions: 0,
          currentQuestion: null,
        })
        wx.showToast({ title: '请选择科目', icon: 'none' })
        return
      }
      const params = {
        subject_id: subjectId,
        include_children: true,
        count: this.data.count || 5,
        mode: this.data.selectedMode || 'random',
        exclude_answered: true,
        no_repeat_days: 30,
        use_leitner: true,
        _traceId: this._practiceSession.traceId,
      }
      // V4: smart 模式默认使用综合打分策略
      if (params.mode === 'smart') {
        params.smart_strategy = 'scored'
      }
      const res = await api.get('/practice/questions', params)
      const questions = adapter.applyAnsweredFlags(res.questions || [], {}, 'id')
      debugLog(this._practiceSession.traceId, 'STATE_AFTER_API', {
        total: questions.length,
        responseTraceId: res.trace_id,
      })
      saveDebugSnapshot(this._practiceSession.traceId, 'state_after_api', {
        total: questions.length,
        questionIds: questions.map(q => q.id),
      })
      this._practiceSession.answeredFlags = {}
      this._practiceSession.comboCount = 0
      this._practiceSession.requestId = res.request_id || ''
      this.setData({ questions, totalQuestions: questions.length, loading: false })
      if (questions.length > 0) {
        this._showQuestion(0)
      } else {
        const name = this.data.selectedSubjectName || String(subjectId)
        this._clearTimer()
        this.setData({ started: false, loading: false, questions: [], totalQuestions: 0, currentQuestion: null })
        wx.showModal({
          title: '该科目暂无题目',
          content: `「${name}」目前没有已发布的题目。\n请确认：\n1. 导入批次已审核通过\n2. 题目科目分类是否正确（导入时混合 PDF 可能被错分）\n3. 试试其他科目分类`,
          showCancel: false,
          confirmText: '返回选择科目',
          success: () => {},
        })
      }
    } catch (e) {
      console.error('加载题目失败', e)
      this._clearTimer()
      this.setData({
        loading: false,
        started: false,
        questions: [],
        totalQuestions: 0,
        currentQuestion: null,
        errorText: '加载题目失败，请重试或返回重新选择科目',
      })
      wx.showToast({ title: '加载题目失败', icon: 'none' })
    }
  },

  _settleQuestionTime() {
    const { currentIndex, questions } = this.data
    const currentQuestionStartedAt = this._practiceSession.currentQuestionStartedAt
    const questionTimeMap = this._practiceSession.questionTimeMap
    if (!currentQuestionStartedAt || !questions.length) return
    const q = questions[currentIndex]
    if (!q) return
    const elapsed = Math.floor((Date.now() - currentQuestionStartedAt) / 1000)
    const key = String(q.id)
    const map = { ...questionTimeMap }
    map[key] = (map[key] || 0) + elapsed
    this._practiceSession.questionTimeMap = map
  },

  _showQuestion(index) {
    // 结算上一题的用时
    this._settleQuestionTime()

    const q = this.data.questions[index]
    if (!q) return
    const isBlankChoice = adapter.isMultiBlankChoice(q)
    const answer = this._practiceSession.answerMap[String(q.id)] || ''
    const blankOptionGroups = isBlankChoice ? adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), answer) : []
    const isTrueFalse = q.question_type === 'true_false' || q.question_type === 'judgement'
    const opts = !isBlankChoice && q.options && Object.keys(q.options).length > 0
      ? q.options
      : (!isBlankChoice && isTrueFalse ? { A: '正确', B: '错误' } : null)
    const optionKeys = opts ? Object.keys(opts) : []
    const isMulti = q.question_type === 'multiple_choice'
    const selectedFlags = {}
    for (const key of optionKeys) {
      selectedFlags[key] = isMulti ? answer.split(',').indexOf(key) >= 0 : answer === key
    }
    // 统一渲染模型 — 题干渲染的唯一入口
    var renderCfg = { enableMathImage: config.enableMathImage || false, DEV: config.DEV }
    if (this._practiceSession.safeModeActive) renderCfg.SAFE_MODE = true
    const renderModel = buildRenderModel(q, opts, renderCfg)
    // 不直接突变 q，创建新对象避免 _renderModel 引用持久化
    const currentQuestion = Object.assign({}, q, {
      _renderModel: renderModel,
      _opts: opts,
      _optionList: adapter.buildOptionListFromFlags(opts, optionKeys, selectedFlags),
      _blankOptionGroups: blankOptionGroups,
      _hasBlankOptionGroups: blankOptionGroups.length > 0,
    })

    if (shouldDebugQuestion(q.id)) {
      debugLog(this._practiceSession.traceId || q.trace_id, 'BEFORE_RENDER', {
        questionId: q.id,
        index,
        optionKeys,
        blankGroupCount: blankOptionGroups.length,
        renderMode: renderModel.mode,
        sourceLen: ((q.content && (q.content.stem || q.content.text)) || '').length,
      })
    }
    this._practiceSession.optionKeys = optionKeys
    this._practiceSession.currentQuestionStartedAt = Date.now()
    this.setData({
      currentIndex: index,
      currentQuestion: currentQuestion,
    }, () => {
      this._updateComputedFields()
    })

    // Render invariant: verify only one render mode is active
    this._checkRenderInvariant(currentQuestion._renderModel)
  },

  goQuestion(e) {
    const idx = e.detail.index
    if (idx >= 0 && idx < this.data.totalQuestions) {
      this._showQuestion(idx)
    }
  },

  /* ==================== 导航事件（来自 quiz-runner 组件） ==================== */

  goNext(e) {
    this._showQuestion(e.detail.index)
  },

  goPrev(e) {
    this._showQuestion(e.detail.index)
  },

  selectOption(e) {
    if (this.data.submitted) return
    const opt = e.detail.option
    const q = this.data.currentQuestion
    if (!q) return

    const isMulti = q.question_type === 'multiple_choice'
    const key = String(q.id)
    const prev = this._practiceSession.answerMap[key] || ''

    let newAnswer
    if (isMulti) {
      const sel = prev ? prev.split(',') : []
      const idx = sel.indexOf(opt)
      if (idx >= 0) sel.splice(idx, 1)
      else sel.push(opt)
      sel.sort()
      newAnswer = sel.join(',')
    } else {
      newAnswer = prev === opt ? '' : opt
    }

    const answerMap = { ...this._practiceSession.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = adapter.buildAnsweredFlags(this.data.questions, answerMap, 'id')
    const answeredCount = adapter.countAnswered(answeredFlags)
    const questions = adapter.applyAnsweredFlags(this.data.questions, answeredFlags, 'id')
    if (shouldDebugQuestion(q.id)) {
      debugLog(this._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this._practiceSession.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }
    const optionKeys = this._practiceSession.optionKeys
    const selectedFlags = {}
    for (const k of optionKeys) {
      selectedFlags[k] = isMulti
        ? newAnswer.split(',').indexOf(k) >= 0
        : newAnswer === k
    }
    const optionList = adapter.buildOptionListFromFlags(q._opts, optionKeys, selectedFlags)
    const cq = Object.assign({}, this.data.currentQuestion, { _optionList: optionList })
    this._practiceSession.answerMap = answerMap
    this._practiceSession.answeredFlags = answeredFlags
    this.setData({ questions, answeredCount, currentQuestion: cq }, () => {
      this._updateComputedFields()
    })
    this._showAnswerFeedback(q, newAnswer)
  },

  selectBlankOption(e) {
    if (this.data.submitted) return
    const blankId = String(e.detail.blankId || '').trim()
    const opt = String(e.detail.option || '').trim().toUpperCase()
    const q = this.data.currentQuestion
    if (!q || !adapter.isMultiBlankChoice(q) || !blankId || !opt) return

    const key = String(q.id)
    const prev = this._practiceSession.answerMap[key] || ''
    const blankAnswers = adapter.normalizeBlankAnswer(prev)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    const groupsForAnswer = q._blankOptionGroups || adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), prev)
    const newAnswer = adapter.serializeBlankAnswer(groupsForAnswer, blankAnswers)
    const answerMap = { ...this._practiceSession.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = adapter.buildAnsweredFlags(this.data.questions, answerMap, 'id')
    const answeredCount = adapter.countAnswered(answeredFlags)
    const questions = adapter.applyAnsweredFlags(this.data.questions, answeredFlags, 'id')
    const groups = adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), newAnswer)
    const currentQuestion = Object.assign({}, q, {
      _blankOptionGroups: groups,
      _hasBlankOptionGroups: groups.length > 0,
    })

    if (shouldDebugQuestion(q.id)) {
      debugLog(this._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this._practiceSession.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }

    this._practiceSession.answerMap = answerMap
    this._practiceSession.answeredFlags = answeredFlags
    this.setData({ questions, answeredCount, currentQuestion }, () => {
      this._updateComputedFields()
    })
    this._showAnswerFeedback(q, newAnswer)
  },

  /* ==================== computed fields ==================== */

  _modeLabel: function(m) {
    var map = { random: '随机', sequential: '顺序', smart: '智能推荐' }
    return map[m] || m || ''
  },

  _updateComputedFields: function(extras) {
    var data = {}
    // selectedModeLabel
    data.selectedModeLabel = this._modeLabel(this.data.selectedMode)
    // progressPercent
    var total = this.data.totalQuestions || 0
    var answered = this.data.answeredCount || 0
    data.progressPercent = total > 0 ? Math.round(answered / total * 100) : 0
    if (extras) Object.assign(data, extras)
    this.setData(data)
  },

  noop() {},

  _showAnswerFeedback(q, answer) {
    const isCorrect = adapter.isAnswerCorrect(q, answer)
    const hasAnswer = !!answer
    const nextCombo = isCorrect === true ? this._practiceSession.comboCount + 1 : (isCorrect === false ? 0 : this._practiceSession.comboCount)
    if (!hasAnswer) {
      this._practiceSession.comboCount = nextCombo
      this.setData({ feedbackVisible: false })
      return
    }

    // 仅在明确判对/判错时弹出反馈，无法判定则不弹
    if (isCorrect !== true && isCorrect !== false) {
      this._practiceSession.comboCount = nextCombo
      return
    }

    const feedbackType = isCorrect === true ? 'correct' : 'wrong'
    let feedbackTitle, feedbackDetail, feedbackComboText, feedbackComboLevel, feedbackStarCount

    if (isCorrect === true) {
      if (nextCombo >= 10) {
        feedbackTitle = '学霸连击'
        feedbackDetail = '状态火热，无人能挡'
        feedbackComboText = `🔥 ${nextCombo} 连对`
        feedbackComboLevel = 'fire'
        feedbackStarCount = 6
      } else if (nextCombo >= 5) {
        feedbackTitle = '五连斩'
        feedbackDetail = '进入心流状态，继续推进'
        feedbackComboText = `⚡ ${nextCombo} 连对`
        feedbackComboLevel = 'hot'
        feedbackStarCount = 5
      } else if (nextCombo >= 3) {
        feedbackTitle = '三连对'
        feedbackDetail = '手感正热，保持这个状态'
        feedbackComboText = `${nextCombo} 连对`
        feedbackComboLevel = 'warm'
        feedbackStarCount = 3
      } else {
        feedbackTitle = '回答正确'
        feedbackDetail = '这题很稳，保持当前节奏'
        feedbackComboText = ''
        feedbackComboLevel = ''
        feedbackStarCount = 0
      }
    } else {
      feedbackTitle = '继续加油'
      feedbackDetail = '先记录选择，交卷后集中复盘'
      feedbackComboText = ''
      feedbackComboLevel = ''
      feedbackStarCount = 0
    }

    if (this._feedbackTimer) clearTimeout(this._feedbackTimer)
    this._practiceSession.comboCount = nextCombo
    this.setData({
      feedbackVisible: true,
      feedbackType,
      feedbackTitle,
      feedbackDetail,
      feedbackComboText,
      feedbackComboLevel,
      feedbackStarCount,
    })
    this._feedbackTimer = setTimeout(() => {
      this.setData({ feedbackVisible: false })
      this._feedbackTimer = null
    }, feedbackComboText ? 2000 : 1200)
  },

  /* ==================== Render Invariant ==================== */

  _checkRenderInvariant(renderModel) {
    if (!renderModel) return
    // Count how many render paths would activate
    let activePaths = 0
    if (renderModel.mode === 'SEGMENTS') activePaths++
    if (renderModel.mode === 'RICH_TEXT') activePaths++
    if (renderModel.mode === 'CODE') activePaths++
    if (renderModel.mode === 'LATEX') activePaths++
    if (renderModel.mode === 'MIXED') {
      activePaths++
      if (!renderModel.blocks || renderModel.blocks.length === 0) {
        console.error('[MIXED_RENDER_VIOLATION] MIXED mode but blocks is empty')
      }
    }
    if (activePaths !== 1) {
      console.error('[RENDER_INVARIANT] _renderModel.mode="' + renderModel.mode + '" yields ' + activePaths + ' active paths (expected 1)')
    }
    // CODE_HTML_LEAK: code rawText must not contain HTML entities
    if (renderModel.mode === 'CODE' && renderModel.rawText) {
      var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
      if (hasHtmlLeak) {
        console.error(
          '[CODE_HTML_LEAK] CODE rawText contains HTML entities\n' +
          '  tail: ' + renderModel.rawText.slice(-60)
        )
      }
      // CODE_RENDER_VIOLATION: html or richTextNodes must be empty
      var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
      if (hasRenderViolation) {
        console.error(
          '[CODE_RENDER_VIOLATION] CODE mode leaked into html/richTextNodes ' +
          '(html=' + renderModel.html.length + ', nodes=' + renderModel.richTextNodes.length + ')'
        )
      }
      // Auto self-heal: enter safe mode on any violation
      if ((hasHtmlLeak || hasRenderViolation) && !this._practiceSession.safeModeActive) {
        this._enterSafeMode()
      }
    }
    // MIXED mode: check each CODE block for HTML entity leaks
    if (renderModel.mode === 'MIXED' && renderModel.blocks) {
      for (var mi = 0; mi < renderModel.blocks.length; mi++) {
        var mBlock = renderModel.blocks[mi]
        if (mBlock.type === 'CODE' && mBlock.rawText) {
          if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
            console.error('[CODE_HTML_LEAK] MIXED CODE block #' + mi + ' contains HTML entities')
          }
        }
      }
    }
  },

  _enterSafeMode() {
    console.warn('[SELF_HEAL] CODE render violation detected — entering SAFE_MODE')
    this._practiceSession.safeModeActive = true
    // Re-render current question in safe mode
    this._reRenderCurrentQuestion()
  },

  _reRenderCurrentQuestion() {
    const q = this.data.questions[this.data.currentIndex]
    if (!q) return
    var renderCfg = { enableMathImage: config.enableMathImage || false, DEV: config.DEV, SAFE_MODE: true }
    const renderModel = buildRenderModel(q, q.options && Object.keys(q.options).length > 0 ? q.options : null, renderCfg)
    const currentQuestion = Object.assign({}, this.data.currentQuestion, {
      _renderModel: renderModel,
    })
    this.setData({ currentQuestion })
    console.warn('[SELF_HEAL] Re-rendered q' + q.id + ' in SAFE_MODE, mode=' + renderModel.mode)
  },


  /* ==================== 交卷 ==================== */

  _showSubmitConfirm(opts) {
    var comp = this.selectComponent('#submitConfirm')
    if (!comp || typeof comp.show !== 'function') {
      // Fallback: native modal if component unavailable
      return new Promise(function (resolve) {
        wx.showModal({
          title: opts.title || '',
          content: opts.message || '',
          confirmText: opts.confirmText || '确定',
          cancelText: opts.cancelText || '取消',
          success: function (r) { resolve(r.confirm) },
          fail: function () { resolve(false) },
        })
      })
    }
    return comp.show(opts)
  },

  async doSubmit(skipConfirm) {
    if (this.data.submitting) return
    const { questions, selectedSubjectId, selectedSubjectName } = this.data
    const { answerMap, startTime, comboCount } = this._practiceSession
    const total = questions.length || 0
    const answeredFlags = adapter.buildAnsweredFlags(questions, answerMap, 'id')
    const answeredCount = adapter.countAnswered(answeredFlags)
    const completedQuestions = questions.filter(function(q) {
      return answeredFlags[String(q.id)]
    })
    const unanswered = total - answeredCount

    if (answeredCount === 0) {
      wx.showToast({ title: '请至少作答 1 题再提交', icon: 'none' })
      return
    }

    var confirmed = false
    if (unanswered > 0) {
      confirmed = await this._showSubmitConfirm({
        scenario: 'unanswered',
        title: '还有题目未作答',
        message: `还有 ${unanswered} 道题未作答，确定提交吗？`,
        confirmText: '确定提交',
        cancelText: '继续作答',
      })
    } else if (skipConfirm !== true) {
      confirmed = await this._showSubmitConfirm({
        scenario: 'all-done',
        title: '确认交卷',
        message: `共 ${total} 题，已全部作答。确认提交并复盘？`,
        confirmText: '确定提交',
        cancelText: '取消',
      })
    } else {
      confirmed = true
    }
    if (!confirmed) return

    this._clearTimer()
    // 结算最后一题的用时
    this._settleQuestionTime()
    this.setData({ submitting: true })

    const questionTimeMap = this._practiceSession.questionTimeMap

    // ═══════════════════════════════════════════════════
    // 阶段一：服务器提交 — 只有此步骤失败才提示"提交失败"
    // ═══════════════════════════════════════════════════
    var submitResult, storedResults, duration
    const requestId = this._practiceSession.requestId || ('req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8))
    // 持久化 requestId 供重试时复用
    if (!this._practiceSession.requestId) {
      this._practiceSession.requestId = requestId
    }
    const answers = completedQuestions.map(q => ({
      question_id: q.id,
      user_answer: answerMap[String(q.id)] || '',
      used_time: questionTimeMap[String(q.id)] || 0,
      request_id: requestId,
    }))

    try {
      submitResult = await api.post('/practice/batch-submit', {
        answers,
        _traceId: this._practiceSession.traceId,
      })
    } catch (e) {
      console.error('提交失败', e)
      // 恢复页面可操作状态和计时器
      this._startTimer()
      this.setData({ submitting: false })
      wx.showToast({ title: '提交失败', icon: 'none' })
      return
    }

    // ═══════════════════════════════════════════════════
    // 阶段二：本地结果缓存 — 失败不阻断流程
    // ═══════════════════════════════════════════════════
    duration = Math.floor((Date.now() - startTime) / 1000)
    storedResults = (submitResult.results || []).map(function(rr) {
      return Object.assign({}, rr, {
        user_answer: answerMap[String(rr.question_id)] || '',
      })
    })
    // 只保存结果页必需的最小数据，不缓存整套题目对象
    // 但需要保留轻量题目数组（id + stem + options）供结果页渲染题干
    var lightQuestions = []
    for (var qi = 0; qi < questions.length; qi++) {
      var qq = questions[qi]
      if (qq && qq.id) {
        lightQuestions.push({
          id: qq.id,
          stem: (qq.content && (qq.content.stem || qq.content.text)) || qq.stem || '',
          options: qq.options || null,
          question_type: qq.question_type || '',
        })
      }
    }
    var userId = ''
    try {
      var userInfo = wx.getStorageSync('user')
      if (userInfo && userInfo.id) userId = String(userInfo.id)
    } catch (_) {}
    // 生成唯一缓存键，用于结果页验证
    var cacheKey = 'pr_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
    try {
      wx.setStorageSync('lastPracticeResult', {
        correct: submitResult.total_correct || 0,
        wrong: submitResult.total_wrong || 0,
        skipped: unanswered,
        total,
        subject_id: selectedSubjectId,
        subject_name: selectedSubjectName,
        duration,
        traceId: submitResult.trace_id || this._practiceSession.traceId,
        results: storedResults,
        questions: lightQuestions,
        comboCount,
        _cacheKey: cacheKey,
        _userId: userId,
      })
    } catch (storageError) {
      console.warn('答题已提交成功，但本地结果缓存失败', storageError)
    }

    // ═══════════════════════════════════════════════════
    // 阶段三：进入结果页
    // ═══════════════════════════════════════════════════
    const resultUrl = [
      `/pages/practice-result/practice-result`,
      `?correct=${submitResult.total_correct || 0}`,
      `&wrong=${submitResult.total_wrong || 0}`,
      `&total=${total}`,
      `&subject_id=${selectedSubjectId}`,
      `&subject_name=${encodeURIComponent(selectedSubjectName || '')}`,
      `&duration=${duration}`,
      `&_ck=${cacheKey}`,
    ].join('')

    // 全对时展示庆祝动画再跳转
    const isPerfect = submitResult.total_wrong === 0 && submitResult.total_correct > 0 && answeredCount === total
    this.setData({ submitting: false })
    if (isPerfect) {
      this._pendingResultUrl = resultUrl
      this.setData({
        showPerfectCelebration: true,
        perfectCelebrationDetail: `答对 ${submitResult.total_correct}/${total} 题`,
        perfectCelebrationMotto: '这组掌握很稳，继续保持',
        perfectCelebrationRewardText: `专注星光 +${Math.max(1, submitResult.total_correct)}`,
      })
    } else {
      wx.redirectTo({ url: resultUrl })
    }
  },

  goPracticeResultAfterCelebration() {
    const url = this._pendingResultUrl
    this._pendingResultUrl = ''
    this.setData({ showPerfectCelebration: false, submitting: false })
    if (url) wx.redirectTo({ url })
  },

  goPomodoro() {
    const subjectId = this.data.selectedSubjectId || ''
    wx.navigateTo({ url: `/pages/pomodoro/pomodoro?subject_id=${subjectId}` })
  },
})
