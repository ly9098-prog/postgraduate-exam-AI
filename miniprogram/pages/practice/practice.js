const api = require('../../utils/api')
const config = require('../../config')
const { createTraceId, debugLog, saveDebugSnapshot, shouldDebugQuestion } = require('../../utils/debug')
const { RENDER_MODE, buildRenderModel, buildOptionList, setRenderGuardPage, resetRenderGuard, textToHtml, toPlainInlineMathText, needsRichRender, stripLeadingOptionLabel } = require('../../utils/stem-render')

function _normalizeBlankAnswer(answer) {
  if (!answer) return {}
  if (typeof answer === 'object') return answer
  const result = {}
  String(answer).split(/[;；,，\n]+/).forEach(function(part) {
    const m = part.trim().match(/^(.+?)\s*[:：=]\s*([A-Za-z])$/)
    if (m) result[m[1].trim()] = m[2].trim().toUpperCase()
  })
  return result
}

function _normalizeBlankOptionList(options) {
  if (Array.isArray(options)) return options
  if (options && typeof options === 'object') {
    return Object.keys(options).map(function(key) {
      return { key, text: options[key] }
    })
  }
  return []
}

function _enrichBlankOptionGroups(groups, answer) {
  const blankAnswers = _normalizeBlankAnswer(answer)
  return (groups || []).map(function(group) {
    const groupId = String((group && group.id) || '').trim()
    return {
      id: groupId,
      options: _normalizeBlankOptionList(group && group.options).map(function(opt) {
        const key = String((opt && opt.key) || '').trim().toUpperCase()
        const text = String((opt && opt.text) || '').trim()
        const optionText = stripLeadingOptionLabel(key, text)
        // Clean embedded newlines (OCR artifact) to prevent visual doubling
        const cleanedText = optionText.replace(/[\r\n]+/g, ' ')
        const plain = toPlainInlineMathText(cleanedText)
        const needsRich = !plain && needsRichRender(cleanedText)
        return Object.assign({}, opt, {
          key,
          _text: plain || optionText,
          _selected: blankAnswers[groupId] === key,
          _needsRich: needsRich,
          _html: needsRich ? textToHtml(optionText) : '',
        })
      }).filter(function(opt) {
        return opt.key
      }),
    }
  }).filter(function(group) {
    return group.id && group.options.length > 0
  })
}

function _serializeBlankAnswer(groups, blankAnswers) {
  const parts = []
  ;(groups || []).forEach(function(group) {
    const id = String((group && group.id) || '').trim()
    const value = blankAnswers && blankAnswers[id]
    if (id && value) parts.push(id + ':' + String(value).trim().toUpperCase())
  })
  return parts.join(';')
}

function _getBlankOptionGroups(q) {
  if (!q) return []
  if (q.content && Array.isArray(q.content.blank_option_groups)) return q.content.blank_option_groups
  if (Array.isArray(q.blank_option_groups)) return q.blank_option_groups
  return []
}

function _isMultiBlankChoice(q) {
  return q && (q.question_type === 'multi_blank_choice' || _getBlankOptionGroups(q).length > 0)
}

function _isQuestionAnswered(q, answer) {
  if (!_isMultiBlankChoice(q)) return !!answer
  const groups = _getBlankOptionGroups(q)
  if (!groups.length) return !!answer
  const blankAnswers = _normalizeBlankAnswer(answer)
  return groups.every(function(group) {
    return !!blankAnswers[String((group && group.id) || '').trim()]
  })
}

function _buildAnsweredFlags(questions, answerMap) {
  const flags = {}
  ;(questions || []).forEach(function(q) {
    const id = String(q.id)
    flags[id] = _isQuestionAnswered(q, (answerMap || {})[id] || '')
  })
  return flags
}

function _countAnswered(flags) {
  return Object.keys(flags || {}).filter(function(id) {
    return flags[id]
  }).length
}

function _applyAnsweredFlags(questions, flags) {
  return (questions || []).map(function(q) {
    return Object.assign({}, q, { _answered: !!(flags || {})[String(q.id)] })
  })
}

function _buildBlankSelectedFlags(groups, answer) {
  const blankAnswers = _normalizeBlankAnswer(answer)
  const flags = {}
  ;(groups || []).forEach(function(group) {
    const groupId = String((group && group.id) || '').trim()
    flags[groupId] = {}
    ;(group.options || []).forEach(function(opt) {
      flags[groupId][opt.key] = blankAnswers[groupId] === opt.key
    })
  })
  return flags
}

function _normalizeAnswerValue(answer) {
  return String(answer || '')
    .split(/[;；,，\n]+/)
    .map(item => item.trim().toUpperCase())
    .filter(Boolean)
    .sort()
    .join(',')
}

function _getCorrectAnswer(q) {
  if (!q) return ''
  return q.answer || q.correct_answer || q.standard_answer || q.right_answer || ''
}

function _isAnswerCorrect(q, answer) {
  const correct = _getCorrectAnswer(q)
  if (!correct || !answer) return null
  if (_isMultiBlankChoice(q)) {
    const user = _normalizeBlankAnswer(answer)
    const standard = _normalizeBlankAnswer(correct)
    const groups = _getBlankOptionGroups(q)
    if (!groups.length) return null
    return groups.every(group => {
      const id = String((group && group.id) || '').trim()
      return id && String(user[id] || '').toUpperCase() === String(standard[id] || '').toUpperCase()
    })
  }
  return _normalizeAnswerValue(answer) === _normalizeAnswerValue(correct)
}

Page({
  data: {
    // 设置
    subjectTree: [],
    selectedSubjectId: null,
    selectedSubjectName: '',
    selectedMode: 'random',
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
    answeredFlags: {},
    answeredCount: 0,
    blankSelectedFlags: {},

    // 提交后
    submitted: false,
    results: [],
    correctCount: 0,
    wrongCount: 0,
    comboCount: 0,
    feedbackVisible: false,
    feedbackType: '',
    feedbackTitle: '',
    feedbackDetail: '',
    feedbackComboText: '',
    feedbackComboLevel: '',
    feedbackStarCount: 0,

    // 计时
    startTime: 0,
    elapsedSec: 0,
    elapsedText: '00:00',
    _timer: null,
    questionTimeMap: {},
    currentQuestionStartedAt: 0,

    // 答题卡弹窗
    showSheet: false,

    // 滑动动画
    animClass: '',

    // 公式图片化
    enableMathImage: false,

    // Debug
    traceId: '',
    requestId: '',
    renderCount: 0,
    _renderKey: 0,

    // Render traces (diagnostic, reset each practice session)
    renderTraces: [],

    // Self-healing
    safeModeActive: false,
  },

  onLoad() {
    this.setData({ enableMathImage: config.enableMathImage || false })
    setRenderGuardPage('practice')
    resetRenderGuard()
    this.loadPracticeSubjects()
  },

  onUnload() {
    resetRenderGuard()
    this._clearTimer()
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
      const subjectTree = res || []
      this.setData({ subjectTree })
      // 默认选中第一个一级科目
      if (subjectTree.length > 0) {
        this.setData({
          selectedSubjectId: subjectTree[0].subject_id,
          selectedSubjectName: subjectTree[0].display_name,
        })
      }
    } catch (e) {
      console.error('加载科目树失败', e)
      wx.showToast({ title: '加载科目失败', icon: 'none' })
    }
  },

  chooseSubject(e) {
    const subjectId = Number(e.currentTarget.dataset.subjectId)
    const subjectName = e.currentTarget.dataset.subjectName
    this.setData({
      selectedSubjectId: subjectId,
      selectedSubjectName: subjectName,
    })
  },

  chooseMode(e) {
    this.setData({ selectedMode: e.currentTarget.dataset.mode })
  },

  setCount(e) {
    this.setData({ count: Number(e.currentTarget.dataset.count) })
  },

  async startPractice() {
    const traceId = createTraceId()
    this.setData({
      traceId,
      renderCount: 0,
      renderTraces: [],
      safeModeActive: false,
      started: true,
      currentIndex: 0,
      answerMap: {},
      answeredFlags: {},
      answeredCount: 0,
      blankSelectedFlags: {},
      results: [],
      submitted: false,
      correctCount: 0,
      wrongCount: 0,
      comboCount: 0,
      feedbackVisible: false,
      feedbackType: '',
      feedbackTitle: '',
      feedbackDetail: '',
      feedbackComboText: '',
      elapsedSec: 0,
      startTime: Date.now(),
      questionTimeMap: {},
      currentQuestionStartedAt: 0,
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
      const subjectId = this.data.selectedSubjectId
      if (!subjectId) {
        wx.showToast({ title: '请选择科目', icon: 'none' })
        this.setData({ loading: false })
        return
      }
      const params = {
        subject_id: subjectId,
        include_children: true,
        count: this.data.count || 5,
        mode: this.data.selectedMode || 'random',
        _traceId: this.data.traceId,
      }
      // Phase 3: smart 模式默认使用知识路径策略
      if (params.mode === 'smart') {
        params.smart_strategy = 'path'
      }
      const res = await api.get('/practice/questions', params)
      const questions = _applyAnsweredFlags(res.questions || [], {})
      debugLog(this.data.traceId, 'STATE_AFTER_API', {
        total: questions.length,
        responseTraceId: res.trace_id,
      })
      saveDebugSnapshot(this.data.traceId, 'state_after_api', {
        total: questions.length,
        questionIds: questions.map(q => q.id),
      })
      this.setData({ questions, totalQuestions: questions.length, loading: false, answeredFlags: {}, comboCount: 0, requestId: res.request_id || '' })
      if (questions.length > 0) {
        this._showQuestion(0)
      } else {
        const name = this.data.selectedSubjectName || String(subjectId)
        wx.showModal({
          title: '该科目暂无题目',
          content: `「${name}」目前没有已发布的题目。\n请确认：\n1. 导入批次已审核通过\n2. 题目科目分类是否正确（导入时混合 PDF 可能被错分）\n3. 试试其他科目分类`,
          showCancel: true,
          confirmText: '返回',
          cancelText: '继续等待',
          success: (r) => {
            if (r.confirm) this.setData({ started: false })
          },
        })
      }
    } catch (e) {
      console.error('加载题目失败', e)
      this.setData({ loading: false })
      wx.showToast({ title: '加载题目失败', icon: 'none' })
    }
  },

  _settleQuestionTime() {
    const { currentIndex, questions, currentQuestionStartedAt, questionTimeMap } = this.data
    if (!currentQuestionStartedAt || !questions.length) return
    const q = questions[currentIndex]
    if (!q) return
    const elapsed = Math.floor((Date.now() - currentQuestionStartedAt) / 1000)
    const key = String(q.id)
    const map = { ...questionTimeMap }
    map[key] = (map[key] || 0) + elapsed
    this.setData({ questionTimeMap: map })
  },

  _showQuestion(index) {
    // 结算上一题的用时
    this._settleQuestionTime()

    const q = this.data.questions[index]
    if (!q) return
    const isBlankChoice = _isMultiBlankChoice(q)
    const answer = this.data.answerMap[String(q.id)] || ''
    const blankOptionGroups = isBlankChoice ? _enrichBlankOptionGroups(_getBlankOptionGroups(q), answer) : []
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
    const blankSelectedFlags = _buildBlankSelectedFlags(blankOptionGroups, answer)

    // 统一渲染模型 — 题干渲染的唯一入口
    var renderCfg = { enableMathImage: config.enableMathImage || false, DEV: config.DEV }
    if (this.data.safeModeActive) renderCfg.SAFE_MODE = true
    const renderModel = buildRenderModel(q, opts, renderCfg)
    // 不直接突变 q，创建新对象避免 _renderModel 引用持久化
    const currentQuestion = Object.assign({}, q, {
      _renderModel: renderModel,
      _opts: opts,
      _optionList: buildOptionList(opts, optionKeys, selectedFlags),
      _blankOptionGroups: blankOptionGroups,
      _hasBlankOptionGroups: blankOptionGroups.length > 0,
    })
    const renderCount = (this.data.renderCount || 0) + 1

    if (shouldDebugQuestion(q.id)) {
      debugLog(this.data.traceId || q.trace_id, 'BEFORE_RENDER', {
        questionId: q.id,
        index,
        renderCount,
        optionKeys,
        blankGroupCount: blankOptionGroups.length,
        renderMode: renderModel.mode,
        sourceLen: ((q.content && (q.content.stem || q.content.text)) || '').length,
      })
      saveDebugSnapshot(this.data.traceId || q.trace_id, 'render', {
        questionId: q.id,
        index,
        renderCount,
        optionKeys,
        blankGroupCount: blankOptionGroups.length,
        renderMode: renderModel.mode,
      })
    }
    this.setData({
      currentIndex: index,
      currentQuestion: currentQuestion,
      optionKeys,
      selectedFlags,
      blankSelectedFlags,
      renderCount,
      _renderKey: (this.data._renderKey || 0) + 1,
      currentQuestionStartedAt: Date.now(),
    })

    // Render invariant: verify only one render mode is active
    this._checkRenderInvariant(currentQuestion._renderModel)
    // Detect duplicate DOM nodes (防复发)
    this._detectDuplicateDom()
    // Record render trace
    this._recordRenderTrace(currentQuestion._renderModel.renderTrace)
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
      this._animating = true
      this.setData({ animClass: isLeft ? 'edge-left' : 'edge-right' })
      setTimeout(() => {
        this.setData({ animClass: '' })
        this._animating = false
      }, 200)
      return
    }

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

    const answerMap = { ...this.data.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = _buildAnsweredFlags(this.data.questions, answerMap)
    const answeredCount = _countAnswered(answeredFlags)
    const questions = _applyAnsweredFlags(this.data.questions, answeredFlags)
    if (shouldDebugQuestion(q.id)) {
      debugLog(this.data.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this.data.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }
    const optionKeys = this.data.optionKeys
    const selectedFlags = {}
    for (const k of optionKeys) {
      selectedFlags[k] = isMulti
        ? newAnswer.split(',').indexOf(k) >= 0
        : newAnswer === k
    }
    const optionList = buildOptionList(q._opts, optionKeys, selectedFlags)
    const cq = Object.assign({}, this.data.currentQuestion, { _optionList: optionList })
    this.setData({ questions, answerMap, answeredFlags, answeredCount, selectedFlags, currentQuestion: cq })
    this._showAnswerFeedback(q, newAnswer)
  },

  selectBlankOption(e) {
    if (this._animating || this.data.submitted) return
    if (this._swiped) {
      this._swiped = false
      return
    }

    const blankId = String(e.currentTarget.dataset.blankId || '').trim()
    const opt = String(e.currentTarget.dataset.option || '').trim().toUpperCase()
    const q = this.data.currentQuestion
    if (!q || !_isMultiBlankChoice(q) || !blankId || !opt) return

    const key = String(q.id)
    const prev = this.data.answerMap[key] || ''
    const blankAnswers = _normalizeBlankAnswer(prev)
    if (blankAnswers[blankId] === opt) {
      delete blankAnswers[blankId]
    } else {
      blankAnswers[blankId] = opt
    }

    const groupsForAnswer = q._blankOptionGroups || _enrichBlankOptionGroups(_getBlankOptionGroups(q), prev)
    const newAnswer = _serializeBlankAnswer(groupsForAnswer, blankAnswers)
    const answerMap = { ...this.data.answerMap }
    if (newAnswer) {
      answerMap[key] = newAnswer
    } else {
      delete answerMap[key]
    }
    const answeredFlags = _buildAnsweredFlags(this.data.questions, answerMap)
    const answeredCount = _countAnswered(answeredFlags)
    const questions = _applyAnsweredFlags(this.data.questions, answeredFlags)
    const groups = _enrichBlankOptionGroups(_getBlankOptionGroups(q), newAnswer)
    const blankSelectedFlags = _buildBlankSelectedFlags(groups, newAnswer)
    const currentQuestion = Object.assign({}, q, {
      _blankOptionGroups: groups,
      _hasBlankOptionGroups: groups.length > 0,
    })

    if (shouldDebugQuestion(q.id)) {
      debugLog(this.data.traceId || q.trace_id, 'STATE_CHANGE', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
      saveDebugSnapshot(this.data.traceId || q.trace_id, 'state_change', {
        questionId: q.id,
        previousAnswer: prev,
        nextAnswer: newAnswer,
        answeredCount,
      })
    }

    this.setData({ questions, answerMap, answeredFlags, answeredCount, blankSelectedFlags, currentQuestion })
    this._showAnswerFeedback(q, newAnswer)
  },

  noop() {},

  _showAnswerFeedback(q, answer) {
    const isCorrect = _isAnswerCorrect(q, answer)
    const hasAnswer = !!answer
    const nextCombo = isCorrect === true ? this.data.comboCount + 1 : (isCorrect === false ? 0 : this.data.comboCount)
    if (!hasAnswer) {
      this.setData({ comboCount: nextCombo, feedbackVisible: false })
      return
    }

    // 仅在明确判对/判错时弹出反馈，无法判定则不弹
    if (isCorrect !== true && isCorrect !== false) {
      this.setData({ comboCount: nextCombo })
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
    this.setData({
      comboCount: nextCombo,
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
      if ((hasHtmlLeak || hasRenderViolation) && !this.data.safeModeActive) {
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
    this.setData({ safeModeActive: true })
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
    this.setData({ currentQuestion, _renderKey: (this.data._renderKey || 0) + 1 })
    console.warn('[SELF_HEAL] Re-rendered q' + q.id + ' in SAFE_MODE, mode=' + renderModel.mode)
  },

  _detectDuplicateDom() {
    if (!config.DEV) return
    // Post-render check: uses selector query to detect duplicate rich-text/mp-html
    var self = this
    setTimeout(function() {
      wx.createSelectorQuery().selectAll('.q-content').fields({
        node: false,
        dataset: false,
        id: false,
      }, function(res) {
        if (res && res.length > 1) {
          console.error('[RENDER_INVARIANT] Found ' + res.length + ' .q-content elements (expected 1)', res)
        }
      }).exec()
    }, 100)
  },

  _recordRenderTrace(trace) {
    if (!trace) return
    var traces = this.data.renderTraces
    traces = traces.concat([trace])
    // Keep last 200 traces to avoid memory leak
    if (traces.length > 200) traces = traces.slice(-200)
    this.setData({ renderTraces: traces })
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

  async doSubmit(skipConfirm) {
    if (this.data.submitting) return
    const { answerMap, questions, startTime, selectedSubjectId, selectedSubjectName, comboCount } = this.data
    const total = questions.length || 0
    const answeredFlags = _buildAnsweredFlags(questions, answerMap)
    const answeredCount = _countAnswered(answeredFlags)
    const completedQuestions = questions.filter(function(q) {
      return answeredFlags[String(q.id)]
    })
    const unanswered = total - answeredCount

    if (unanswered > 0) {
      const { confirm } = await wx.showModal({
        title: '还有题目未作答',
        content: `还有 ${unanswered} 道题未作答，确定提交吗？`,
        confirmText: '确定提交',
        cancelText: '继续作答',
      })
      if (!confirm) return
    } else if (skipConfirm !== true) {
      const { confirm } = await wx.showModal({
        title: '确认交卷',
        content: `共 ${total} 题，已全部作答。确认提交并复盘？`,
        confirmText: '确定提交',
        cancelText: '取消',
      })
      if (!confirm) return
    }

    this._clearTimer()
    // 结算最后一题的用时
    this._settleQuestionTime()
    this.setData({ submitting: true })

    const questionTimeMap = this.data.questionTimeMap
    try {
      const answers = completedQuestions.map(q => ({
        question_id: q.id,
        user_answer: answerMap[String(q.id)] || '',
        used_time: questionTimeMap[String(q.id)] || 0,
        request_id: this.data.requestId || undefined,
      }))

      debugLog(this.data.traceId, 'SUBMIT', {
        total: answers.length,
        answeredCount,
      })
      saveDebugSnapshot(this.data.traceId, 'submit_before', {
        answers: answers.map(item => ({ question_id: item.question_id, has_answer: !!item.user_answer })),
      })
      const result = await api.post('/practice/batch-submit', {
        answers,
        _traceId: this.data.traceId,
      })

      const duration = Math.floor((Date.now() - startTime) / 1000)
      // 存储详细结果供 result 页使用
      wx.setStorageSync('lastPracticeResult', {
        correct: result.total_correct || 0,
        wrong: result.total_wrong || 0,
        total,
        subject_id: selectedSubjectId,
        subject_name: selectedSubjectName,
        duration,
        traceId: result.trace_id || this.data.traceId,
        results: result.results || [],
        comboCount,
      })

      wx.redirectTo({
        url: [
          `/pages/practice-result/practice-result`,
          `?correct=${result.total_correct || 0}`,
          `&wrong=${result.total_wrong || 0}`,
          `&total=${total}`,
          `&subject_id=${selectedSubjectId}`,
          `&subject_name=${encodeURIComponent(selectedSubjectName || '')}`,
          `&duration=${duration}`,
        ].join(''),
      })
    } catch (e) {
      console.error('提交失败', e)
      this.setData({ submitting: false })
      wx.showToast({ title: '提交失败', icon: 'none' })
    }
  },

  finishEarly() {
    const answeredFlags = _buildAnsweredFlags(this.data.questions, this.data.answerMap)
    const answered = _countAnswered(answeredFlags)
    wx.showModal({
      title: '结束练习',
      content: `已完成 ${answered} / ${this.data.totalQuestions} 题，确定结束吗？`,
      success: (res) => {
        if (res.confirm) this.doSubmit(true)
      },
    })
  },

  /* ==================== 工具 ==================== */

  modeLabel(m) {
    const map = { random: '随机', sequential: '顺序', smart: '智能推荐' }
    return map[m] || m || ''
  },

  goPomodoro() {
    const subjectId = this.data.selectedSubjectId || ''
    wx.navigateTo({ url: `/pages/pomodoro/pomodoro?subject_id=${subjectId}` })
  },

  onUnload() {
    this._clearTimer()
    if (this._feedbackTimer) {
      clearTimeout(this._feedbackTimer)
      this._feedbackTimer = null
    }
  },
})
