const store = require('../../../../utils/launch-session-store')
const storage = require('../../../../utils/storage-core')
const { buildRecoveryQuestions } = require('./recovery-questions-builder')
const { monotonicNow } = require('./monotonic-clock')
const adapter = require('../../utils/question-runner-adapter')

const SESSION_FIELDS = [
  'traceId', 'requestId', 'recommendationRequestId', 'batchToken', 'batchMode',
  'knowledgeScope', 'startedAtMs', 'answerMap', 'answeredFlags', 'questionTimeMap',
  'comboCount', 'correctCount',
]
const VIEW_FIELDS = [
  'selectedSubjectId', 'selectedSubjectName', 'selectedSubjectHasChildren', 'expandedSubjectId',
  'selectedMode', 'selectedModeLabel', 'count', 'countDisplay', 'sequentialProgress',
]
const LAUNCH_FIELDS = [
  '_launchPreset', '_launchKnowledgePoint', '_launchKnowledgePointId', '_launchIncludeDescendants',
  '_launchQuestionIds', '_launchAllowRepeat', '_launchSource', '_launchPlanToken', '_launchReturnTo',
]

function pick(source, fields) {
  return Object.fromEntries(fields.filter(field => source[field] !== undefined)
    .map(field => [field, source[field]]))
}

function elapsedSnapshot(session, clock) {
  const now = clock()
  const end = session._timingPauseActive && session._timingPauseStartedMonoMs != null
    ? session._timingPauseStartedMonoMs
    : (session._backgroundStartedMonoMs == null ? now : session._backgroundStartedMonoMs)
  const elapsedMs = Math.max(0, end - session.activeStartedMonoMs - (session.backgroundMs || 0))
  const questionTimeMap = { ...session.questionTimeMap }
  return { elapsedMs, questionTimeMap, end }
}

function persist(page, clock = monotonicNow) {
  const session = page._practiceSession
  if (!session || !page.data.started || page.data.loading || page.data.submitting ||
    page.data.submitted || session.submissionSnapshot || !session.batchToken || !session.requestId) return
  if (!ownsPage(page)) return
  const timing = elapsedSnapshot(session, clock)
  const current = page.data.questions[page.data.currentIndex]
  if (current && session.currentQuestionStartedMonoMs && !session._timingPauseActive &&
    session._backgroundStartedMonoMs == null) {
    const seconds = Math.floor(Math.max(0, timing.end - session.currentQuestionStartedMonoMs) / 1000)
    timing.questionTimeMap[current.id] = (Number(timing.questionTimeMap[current.id]) || 0) + seconds
  }
  store.savePractice({
    ...pick(session, SESSION_FIELDS),
    ...pick(page.data, VIEW_FIELDS),
    launch: pick(page, LAUNCH_FIELDS),
    createdAt: page._coldResumeCreatedAt,
    questions: buildRecoveryQuestions(page.data.questions),
    currentIndex: page.data.currentIndex,
    elapsedMs: timing.elapsedMs,
    questionTimeMap: timing.questionTimeMap,
  })
}

function restore(page, clock = monotonicNow) {
  if (!page._coldResumeRequested) return false
  page._coldResumeRequested = false
  const snapshot = store.readPractice()
  if (!snapshot) {
    returnHome(page)
    return true
  }
  try {
    if (!storage.get(storage.KEYS.TOKEN) || !store.userId() || !ownsPage(page)) {
      throw new Error('resume_auth_required')
    }
    applySnapshot(page, snapshot, clock)
  } catch (error) {
    clear(page)
    returnHome(page)
  }
  return true
}

function applySnapshot(page, snapshot, clock) {
  page._resetSession()
  const session = page._practiceSession
  Object.assign(session, pick(snapshot, SESSION_FIELDS))
  session.answerMap = { ...snapshot.answerMap }
  session.questionTimeMap = { ...snapshot.questionTimeMap }
  session.answeredFlags = adapter.buildAnsweredFlags(snapshot.questions, session.answerMap, 'id')
  session.activeStartedMonoMs = clock() - snapshot.elapsedMs || -0.001
  session.backgroundMs = 0
  session._backgroundStartedMonoMs = null
  session._timingPauseActive = false
  session.elapsedSec = Math.floor(snapshot.elapsedMs / 1000)
  session.currentQuestionStartedMonoMs = 0
  Object.assign(page, pick(snapshot.launch || {}, LAUNCH_FIELDS))
  page._coldResumeCreatedAt = snapshot.createdAt
  page.setData({
    ...pick(snapshot, VIEW_FIELDS), started: true, submitted: false, submitting: false,
    loading: false, launchingPreset: false, questions: adapter.applyAnsweredFlags(
      snapshot.questions, session.answeredFlags, 'id'),
    totalQuestions: snapshot.questions.length,
    answeredCount: adapter.countAnswered(session.answeredFlags),
    elapsedText: page._fmt(session.elapsedSec),
  })
  page._showQuestion(snapshot.currentIndex)
  if (!page.data.currentQuestion || page.data.currentIndex !== snapshot.currentIndex) {
    throw new Error('resume_render_failed')
  }
  page._setPracticeUnloadGuard(true)
  page._startTimer()
  page._updateComputedFields()
}

function returnHome(page) {
  page._clearTimer && page._clearTimer()
  page._setPracticeUnloadGuard(false)
  page.setData({ started: false, loading: false })
  wx.reLaunch({ url: '/pages/home/home' })
}

function ownsPage(page) {
  return page._coldResumeOwner === undefined || page._coldResumeOwner === store.userId()
}

function clear(page) {
  if (!page || ownsPage(page)) store.clearPractice()
}

module.exports = {
  persist, restore, clear, userId: store.userId,
  hasPending: () => Boolean(store.readPending()),
}
