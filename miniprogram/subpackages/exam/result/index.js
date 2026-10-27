const api = require('../../../utils/api')
const aiTeacher408 = require('../../study/utils/ai-teacher-408')
const { createExamResultLoadController } = require('../utils/exam-result-load-controller')
const { createExam408TeacherController } = require('../utils/exam-408-teacher-controller')
const { clamp, percentNumber, compactDuration, compactScore, encouragement, encouragementTail, firstWrongIdByQuestion, buildKnowledgeMetrics, buildRadar, buildScoreRing, buildTopItems, collectWrongIds } = require('../utils/exam-result-view')

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
