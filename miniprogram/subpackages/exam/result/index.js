const api = require('../../../utils/api')
const aiTeacher408 = require('../../study/utils/ai-teacher-408')
const { createExamResultLoadController } = require('../utils/exam-result-load-controller')
const { createExam408TeacherController } = require('../utils/exam-408-teacher-controller')

const RADAR_SIZE = 5
const RADAR_ANGLES = [-90, -18, 54, 126, 198]

function clamp(value, min, max) {
  const n = Number(value)
  if (!Number.isFinite(n)) return min
  return Math.min(max, Math.max(min, n))
}

function percentNumber(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.round(clamp(n <= 1 ? n * 100 : n, 0, 100))
}

function compactDuration(sec) {
  const total = Math.max(0, Math.round(Number(sec) || 0))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad2 = n => String(n).padStart(2, '0')
  return h > 0 ? `${pad2(h)}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`
}

function compactScore(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0'
  if (Math.abs(n - Math.round(n)) < 0.001) return String(Math.round(n))
  return n.toFixed(1).replace(/\.0$/, '')
}

function normalizeName(value, fallback) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text || fallback || '未命名知识点'
}

function shortName(value, maxLength = 8) {
  const text = normalizeName(value, '')
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(2, maxLength - 1))}…`
}

function masteryTag(accuracyPct) {
  const pct = clamp(accuracyPct, 0, 100)
  if (pct >= 85) return { label: '优秀', tone: 'excellent' }
  if (pct >= 70) return { label: '良好', tone: 'good' }
  return { label: '待提升', tone: 'weak' }
}

function encouragement(scoreRatePct, accuracyPct) {
  const value = Math.max(scoreRatePct, accuracyPct)
  if (value >= 90) return '状态很棒！'
  if (value >= 80) return '表现不错！'
  if (value >= 60) return '继续保持！'
  return '再接再厉！'
}

function encouragementTail(wrongCount, unansweredCount) {
  const wrong = Math.max(0, Number(wrongCount) || 0)
  const unanswered = Math.max(0, Number(unansweredCount) || 0)
  if (wrong > 0) return '，继续查漏补缺'
  if (unanswered > 0) return `，还有 ${unanswered} 道题未作答`
  return '，继续保持！'
}

function firstWrongIdByQuestion(question) {
  const id = Number(question && question.wrong_question_id)
  return Number.isFinite(id) && id > 0 ? id : 0
}

function buildKnowledgeMetrics(result) {
  const questions = Array.isArray(result && result.questions) ? result.questions : []
  const stats = new Map()

  questions.forEach((question) => {
    const names = Array.isArray(question && question.knowledge_points)
      ? Array.from(new Set(question.knowledge_points.map(name => normalizeName(name, '')).filter(Boolean)))
      : []
    names.forEach((name) => {
      let item = stats.get(name)
      if (!item) {
        item = { name, questionCount: 0, correctCount: 0, wrongQuestionId: 0, source: 'knowledge' }
        stats.set(name, item)
      }
      item.questionCount += 1
      if (question.status === 'correct') item.correctCount += 1
      if (!item.wrongQuestionId && question.status !== 'correct') {
        item.wrongQuestionId = firstWrongIdByQuestion(question)
      }
    })
  })

  let metrics = Array.from(stats.values()).map((item) => ({
    ...item,
    accuracyPct: item.questionCount ? Math.round(item.correctCount / item.questionCount * 100) : 0,
  }))
  metrics.sort((a, b) => {
    if (b.questionCount !== a.questionCount) return b.questionCount - a.questionCount
    if (b.accuracyPct !== a.accuracyPct) return b.accuracyPct - a.accuracyPct
    return a.name.localeCompare(b.name, 'zh-CN')
  })
  metrics = metrics.slice(0, RADAR_SIZE)

  const usedNames = new Set(metrics.map(item => item.name))
  const subjectBreakdown = Array.isArray(result && result.subject_breakdown) ? result.subject_breakdown : []
  for (let index = 0; index < subjectBreakdown.length && metrics.length < RADAR_SIZE; index += 1) {
    const subject = subjectBreakdown[index] || {}
    const name = normalizeName(subject.subject_name, `科目${index + 1}`)
    if (usedNames.has(name)) continue
    const matchingWrong = questions.find(question => (
      normalizeName(question && question.subject_name, '') === name &&
      question && question.status !== 'correct' &&
      firstWrongIdByQuestion(question)
    ))
    metrics.push({
      name,
      questionCount: Number(subject.question_count || 0),
      correctCount: Number(subject.correct_count || 0),
      accuracyPct: percentNumber(subject.accuracy),
      wrongQuestionId: firstWrongIdByQuestion(matchingWrong),
      source: 'subject',
    })
    usedNames.add(name)
  }

  const overallAccuracy = percentNumber(result && result.accuracy)
  if (metrics.length < RADAR_SIZE) {
    metrics.push({
      name: '综合表现',
      questionCount: Number(result && result.question_count || 0),
      correctCount: Number(result && result.correct_count || 0),
      accuracyPct: overallAccuracy,
      wrongQuestionId: firstWrongIdByQuestion(questions.find(q => q && q.status === 'wrong' && firstWrongIdByQuestion(q))),
      source: 'overall',
    })
  }

  while (metrics.length < RADAR_SIZE) {
    const index = metrics.length + 1
    metrics.push({
      name: `能力维度${index}`,
      questionCount: Number(result && result.question_count || 0),
      correctCount: Number(result && result.correct_count || 0),
      accuracyPct: overallAccuracy,
      wrongQuestionId: 0,
      source: 'fallback',
    })
  }

  return metrics.slice(0, RADAR_SIZE)
}

function buildRadar(items) {
  const center = 50
  const maxRadius = 42.5
  const points = []
  const radarItems = (items || []).slice(0, RADAR_SIZE).map((item, index) => {
    const angleDeg = RADAR_ANGLES[index]
    const angle = angleDeg * Math.PI / 180
    const ratio = clamp(item.accuracyPct, 0, 100) / 100
    const radius = maxRadius * ratio
    const x = center + Math.cos(angle) * radius
    const y = center + Math.sin(angle) * radius
    const tag = masteryTag(item.accuracyPct)
    points.push(`${x.toFixed(2)}% ${y.toFixed(2)}%`)
    return {
      ...item,
      index,
      displayName: shortName(item.name),
      tagLabel: tag.label,
      tagTone: tag.tone,
      pointX: x,
      pointY: y,
      pointStyle: `left:${x.toFixed(2)}%;top:${y.toFixed(2)}%;`,
    }
  })
  const radarEdges = radarItems.map((item, index) => {
    const next = radarItems[(index + 1) % radarItems.length]
    const x1 = Number(item.pointX)
    const y1 = Number(item.pointY)
    const x2 = Number(next.pointX)
    const y2 = Number(next.pointY)
    const dx = x2 - x1
    const dy = y2 - y1
    const length = Math.sqrt(dx * dx + dy * dy)
    const angle = Math.atan2(dy, dx) * 180 / Math.PI
    return {
      index,
      style: `left:${x1.toFixed(2)}%;top:${y1.toFixed(2)}%;width:${length.toFixed(2)}%;transform:rotate(${angle.toFixed(2)}deg);`,
    }
  })
  return {
    radarItems,
    radarEdges,
    radarPolygonStyle: `clip-path:polygon(${points.join(',')});-webkit-clip-path:polygon(${points.join(',')});`,
  }
}

function buildScoreRing(ratePct) {
  const rate = clamp(ratePct, 0, 100)
  if (rate <= 0 || rate >= 100) {
    return { showScoreRingCaps: false, scoreRingEndStyle: '' }
  }
  const angle = (-90 + rate * 3.6) * Math.PI / 180
  const radius = 46.3
  const x = 50 + Math.cos(angle) * radius
  const y = 50 + Math.sin(angle) * radius
  return {
    showScoreRingCaps: true,
    scoreRingEndStyle: `left:${x.toFixed(2)}%;top:${y.toFixed(2)}%;`,
  }
}

function buildTopItems(metrics) {
  return (metrics || [])
    .filter(item => item && item.source !== 'fallback')
    .slice()
    .sort((a, b) => {
      if (b.accuracyPct !== a.accuracyPct) return b.accuracyPct - a.accuracyPct
      if (b.questionCount !== a.questionCount) return b.questionCount - a.questionCount
      return a.name.localeCompare(b.name, 'zh-CN')
    })
    .slice(0, 3)
    .map((item, index) => ({
      ...item,
      rank: index + 1,
      displayName: shortName(item.name, 12),
      progressPct: clamp(item.accuracyPct, 0, 100),
    }))
}

function collectWrongIds(result) {
  const ids = []
  const seen = new Set()
  ;(Array.isArray(result && result.questions) ? result.questions : []).forEach((question) => {
    const id = firstWrongIdByQuestion(question)
    if (!id || seen.has(id)) return
    seen.add(id)
    ids.push(id)
  })
  return ids
}

Page({
  data: {
    loading: true,
    errorText: '',
    attemptId: 0,
    statusBarHeightPx: 20,
    navBarHeightPx: 44,
    navTotalHeightPx: 64,
    result: null,
    radarItems: [],
    radarEdges: [],
    radarPolygonStyle: '',
    topItems: [],
    weakCount: 0,
    wrongDetailCount: 0,
    teacherActions: aiTeacher408.ACTIONS,
    teacherLoading: false,
    teacherResult: null,
    teacherErrorText: '',
    teacherSheetVisible: false,
    teacherFeedbackSent: '',
    icons: {
      sprout: '/subpackages/exam/result/assets/sprout.png',
      radarGrid: '/subpackages/exam/result/assets/radar-grid.png',
    },
  },

  onLoad(options) {
    this._pageAlive = true
    this._teacherRequestSeq = 0
    this._activeTeacherCacheKey = ''
    this._teacherCache = Object.create(null)
    this._teacherFeedbackCache = Object.create(null)
    this._teacherInflight = Object.create(null)
    this._loadSeq = 0
    this._loadPromise = null
    this._navigationLocked = false
    this._wrongIds = []
    this._diagnosisIdByWrongId = Object.create(null)

    // onLoad 只做首屏必需的轻量初始化：导航栏测量结果和 attemptId
    // 合并为一次 setData，避免连续两次数据同步；网络请求延后到首屏提交后再启动。
    const attemptId = Number(options && options.attempt_id)
    const navigation = this.getNavigationMetrics()
    if (!attemptId) {
      this.setData({
        ...navigation,
        attemptId: 0,
        loading: false,
        errorText: '缺少考试记录 ID',
      })
      return
    }

    this.setData({ ...navigation, attemptId })
    this.deferInitialLoad()
  },

  onShow() {
    this._navigationLocked = false
  },

  onUnload() {
    this._pageAlive = false
    this._loadSeq += 1
    this._loadPromise = null
  },

  getNavigationMetrics() {
    let statusBarHeight = 20
    let navBarHeight = 44
    try {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
      statusBarHeight = Math.max(0, Number(info.statusBarHeight) || 20)
      const menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect()
      if (menu && Number(menu.height) > 0 && Number(menu.top) >= statusBarHeight) {
        navBarHeight = Math.max(40, Number(menu.height) + 2 * (Number(menu.top) - statusBarHeight))
      }
    } catch (_) {}
    return {
      statusBarHeightPx: Math.round(statusBarHeight),
      navBarHeightPx: Math.round(navBarHeight),
      navTotalHeightPx: Math.round(statusBarHeight + navBarHeight),
    }
  },

  measureNavigation() {
    this.setData(this.getNavigationMetrics())
  },

  deferInitialLoad() {
    const run = () => {
      if (!this._pageAlive || !this.data.attemptId) return
      this.loadResult({ skipLoadingState: true })
    }
    if (typeof wx.nextTick === 'function') {
      wx.nextTick(run)
      return
    }
    setTimeout(run, 0)
  },

  async loadResult(options = {}) {
    return this._examResultLoadController().load(options)
  },

  _examResultLoadController() {
    if (!this._examResultLoad) {
      this._examResultLoad = createExamResultLoadController({
        getInflight: () => this._loadPromise,
        setInflight: value => { this._loadPromise = value },
        nextSequence: () => ++this._loadSeq,
        getSequence: () => this._loadSeq,
        isPageAlive: () => this._pageAlive,
        setData: patch => this.setData(patch),
        fetchResult: () => api.get(`/exams/attempts/${this.data.attemptId}/result`),
        getErrorMessage: error => api.getErrorMessage(error),
        percentNumber,
        clamp,
        compactScore,
        compactDuration,
        encouragement,
        encouragementTail,
        buildKnowledgeMetrics,
        buildScoreRing,
        buildRadar,
        buildTopItems,
        collectWrongIds,
        firstWrongIdByQuestion,
        setWrongIds: ids => { this._wrongIds = ids },
        getWrongIdsLength: () => this._wrongIds.length,
        resetDiagnosisIndex: () => { this._diagnosisIdByWrongId = Object.create(null) },
        setDiagnosisId: (wrongId, diagnosisId) => { this._diagnosisIdByWrongId[wrongId] = diagnosisId },
        setFirstQuestionId: id => { this._firstQuestionId = id },
      })
    }
    return this._examResultLoad
  },

  openWeakReview() {
    if (!this._wrongIds.length) {
      wx.showToast({ title: '本次暂无可复盘错题', icon: 'none' })
      return
    }
    this.openWrongDetailById(this._wrongIds[0])
  },

  openRadarItem(e) {
    const id = Number(e.currentTarget.dataset.wqid || 0)
    if (id > 0) this.openWrongDetailById(id)
  },

  openWrongDetailById(wqId) {
    const id = Number(wqId || 0)
    if (!id || this._navigationLocked) return
    const ids = this._wrongIds.slice()
    if (!ids.includes(id)) ids.unshift(id)
    const idx = Math.max(0, ids.indexOf(id))
    const diagnosis_id = Number(this._diagnosisIdByWrongId[id] || 0)
    try {
      wx.setStorageSync('wrong_detail_nav', { ids, ts: Date.now(), source: 'exam-result', diagnosis_id })
    } catch (error) {
      console.warn('保存考试错题详情导航上下文失败', error)
    }
    if (!diagnosis_id) this.prefetchWrongDiagnosis(id)
    this._navigationLocked = true
    wx.navigateTo({
      url: `/subpackages/study/wrong-detail/wrong-detail?id=${encodeURIComponent(id)}&idx=${idx}&source=exam-result`,
      fail: () => {
        this._navigationLocked = false
        if (this._pageAlive) wx.showToast({ title: '暂时无法打开错题详情', icon: 'none' })
      },
    })
  },


  prefetchWrongDiagnosis(wqId) {
    const id = Number(wqId || 0)
    if (!id || Number(this._diagnosisIdByWrongId[id] || 0) > 0) return
    api.get(`/wrong-questions/${id}/diagnosis`).then((diagnosis) => {
      const diagnosis_id = Number(diagnosis && diagnosis.id || 0)
      if (diagnosis_id > 0) this._diagnosisIdByWrongId[id] = diagnosis_id
    }).catch(() => {})
  },

  _returnToPaperList() {
    if (this._navigationLocked) return
    this._navigationLocked = true
    const targetRoute = 'subpackages/exam/paper-list/index'
    const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
    let targetIndex = -1
    for (let index = pages.length - 2; index >= 0; index -= 1) {
      if (String((pages[index] || {}).route || '').replace(/^\//, '') === targetRoute) {
        targetIndex = index
        break
      }
    }
    if (targetIndex >= 0) {
      wx.navigateBack({
        delta: Math.max(1, pages.length - 1 - targetIndex),
        fail: () => {
          this._navigationLocked = false
          wx.redirectTo({ url: '/subpackages/exam/paper-list/index' })
        },
      })
      return
    }
    wx.redirectTo({
      url: '/subpackages/exam/paper-list/index',
      fail: () => {
        this._navigationLocked = false
        wx.reLaunch({ url: '/pages/home/home' })
      },
    })
  },

  handleBack() {
    this._returnToPaperList()
  },

  goPaperList() {
    this._returnToPaperList()
  },

  open408Teacher() {
    if (!this.data.attemptId) return
    const questionId = Number(this._firstQuestionId || 0)
    if (!questionId) {
      wx.showToast({ title: '本次暂无可复盘题目', icon: 'none' })
      return
    }
    const action = this.data.result && this.data.result.wrongCount > 0 ? 'core_concept' : 'explain_correct'
    this.run408Teacher(action, questionId)
  },

  select408TeacherAction(e) {
    const action = String(e.currentTarget.dataset.action || '')
    if (action) this.run408Teacher(action)
  },

  async run408Teacher(action, questionId) {
    return this._exam408TeacherController().run(action, questionId)
  },

  _exam408TeacherController() {
    if (!this._exam408Teacher) {
      this._exam408Teacher = createExam408TeacherController({
        getAttemptId: () => this.data.attemptId,
        getTeacherLoading: () => this.data.teacherLoading,
        isPageAlive: () => this._pageAlive,
        setData: patch => this.setData(patch),
        getCacheEntry: key => this._teacherCache[key],
        setCacheEntry: (key, value) => { this._teacherCache[key] = value },
        getFeedbackEntry: key => this._teacherFeedbackCache[key],
        setActiveCacheKey: key => { this._activeTeacherCacheKey = key },
        getInflight: key => this._teacherInflight[key],
        setInflight: (key, promise) => { this._teacherInflight[key] = promise },
        deleteInflight: key => { delete this._teacherInflight[key] },
        nextRequestSequence: () => ++this._teacherRequestSeq,
        getRequestSequence: () => this._teacherRequestSeq,
        postTeacher: payload => api.post('/ai/408-teacher', payload, { timeout: 55000 }),
        normalizeResult: raw => aiTeacher408.normalizeResult(raw),
        errorMessage: error => aiTeacher408.errorMessage(error, api),
      })
    }
    return this._exam408Teacher
  },

  close408Teacher() {
    this.setData({ teacherSheetVisible: false })
  },

  async feedback408Teacher(e) {
    if (this.data.teacherFeedbackSent || !this.data.teacherResult || !this.data.attemptId) return
    const feedbackType = String(e.currentTarget.dataset.type || '')
    if (!feedbackType) return
    try {
      await api.post('/ai/feedback', {
        source: '408_teacher',
        feedback_type: feedbackType,
        exam_attempt_id: Number(this.data.attemptId),
        detail: [
          this.data.teacherResult.action ? `action=${this.data.teacherResult.action}` : '',
          this.data.teacherResult.promptVersion ? `prompt_version=${this.data.teacherResult.promptVersion}` : '',
          `fallback=${this.data.teacherResult.fromFallback ? 1 : 0}`,
        ].filter(Boolean).join(';'),
      })
      if (this._activeTeacherCacheKey) this._teacherFeedbackCache[this._activeTeacherCacheKey] = feedbackType
      this.setData({ teacherFeedbackSent: feedbackType })
      wx.showToast({ title: '反馈已记录', icon: 'success' })
    } catch (error) {
      wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
    }
  },
})
