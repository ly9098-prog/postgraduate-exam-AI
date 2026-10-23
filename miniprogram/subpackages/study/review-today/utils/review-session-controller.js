const { getChinaWallParts, getChinaDate } = require('../../../../utils/china-time')
const { getSubjectName } = require('../../utils/subject-meta')

function createReviewSessionController(options) {
  return {
    createSession() {
      return createSessionImpl()
    },

    setDateStr() {
      setDateStrImpl(options)
    },

    getRequestId(question) {
      return getRequestIdImpl(options, question)
    },

    subjectLabel(name, code) {
      if (name) return name
      return getSubjectName(code || name)
    },
  }
}

function createSessionImpl() {
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
    todayTaskTotalCount: 0,
    completedBeforeSession: 0,
    safeModeActive: false,
    renderTraces: [],
    optionKeys: [],
    reviewOverview: null,
    overviewLoading: false,
    reviewRequestIds: {},
    taskDate: getChinaDate(0),
    timerStartedAt: 0,
    timerLastTickAt: 0,
    timerElapsedMs: 0,
    timerRunning: false,
    timingSegmentId: '',
    timingStartedAtMs: 0,
  }
}

function setDateStrImpl(options) {
  const now = getChinaWallParts(Date.now())
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']
  options.setData({
    _dateStr: `${now.month}月${now.day}日 星期${weekdays[now.weekday]}`
  })
}

function getRequestIdImpl(options, question) {
  const session = options.getSession()
  const key = [
    String(question.schedule_id || ''),
    String(question.question_version_id || ''),
    String(question.occurrence_seq != null ? question.occurrence_seq : ''),
  ].join(':')
  if (!key || key === '::') return ''
  if (!session.reviewRequestIds) session.reviewRequestIds = {}
  if (!session.reviewRequestIds[key]) {
    const randomPart = Math.random().toString(36).slice(2, 10)
    session.reviewRequestIds[key] = `review_${Date.now().toString(36)}_${randomPart}_${question.schedule_id}`
  }
  return session.reviewRequestIds[key]
}

module.exports = {
  createReviewSessionController,
}
