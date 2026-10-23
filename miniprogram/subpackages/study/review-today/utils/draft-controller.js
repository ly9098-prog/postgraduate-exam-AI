function createReviewDraftController(options) {
  return {
    key() {
      return options.getDraftKey()
    },

    read() {
      return readDraft(options)
    },

    write(payload) {
      writeDraft(options, payload)
    },

    persist() {
      persistDraft(options)
    },

    restore(questions) {
      return restoreDraft(options, questions)
    },

    clearSubmitted(groupQuestions, groupResults) {
      clearSubmittedDraft(options, groupQuestions, groupResults)
    },
  }
}

function readDraft(options) {
  const raw = options.readStorage(options.getDraftKey())
  if (!raw || typeof raw !== 'object') return { answers: {}, position: null }
  return {
    answers: raw.answers && typeof raw.answers === 'object' && !Array.isArray(raw.answers)
      ? raw.answers
      : {},
    position: raw.position && typeof raw.position === 'object' ? raw.position : null,
  }
}

function writeDraft(options, payload) {
  const answers = payload && payload.answers && typeof payload.answers === 'object' ? payload.answers : {}
  if (Object.keys(answers).length === 0) {
    options.removeStorage(options.getDraftKey())
    return
  }
  options.writeStorage(options.getDraftKey(), {
    version: 1,
    date: String(options.getSession().taskDate || options.getCurrentDate()),
    updated_at: options.now(),
    answers,
    position: payload.position || null,
  })
}

function persistDraft(options) {
  const session = options.getSession()
  if (!session || options.getPhase() !== 'reviewing') return
  const questions = options.getGroupQuestions() || []
  if (!questions.length) return

  const stored = readDraft(options)
  const entries = { ...stored.answers }
  const answers = session.answers || {}
  questions.forEach(question => {
    const scheduleId = String(question.schedule_id || '')
    if (!scheduleId) return
    const answer = answers[question.schedule_id] != null
      ? answers[question.schedule_id]
      : answers[scheduleId]
    if (answer !== undefined && answer !== null && String(answer) !== '') {
      entries[scheduleId] = {
        schedule_id: question.schedule_id,
        question_id: question.question_id,
        question_version_id: question.question_version_id,
        occurrence_seq: question.occurrence_seq,
        answer: String(answer),
      }
    } else {
      delete entries[scheduleId]
    }
  })

  const current = options.getCurrentQuestion()
  const position = current ? {
    schedule_id: current.schedule_id,
    question_version_id: current.question_version_id,
    occurrence_seq: current.occurrence_seq,
  } : stored.position
  writeDraft(options, { answers: entries, position })
}

function restoreDraft(options, questions) {
  const list = questions || []
  const stored = readDraft(options)
  const answers = {}
  let restoredCount = 0
  let currentIndex = 0
  list.forEach((question, index) => {
    const scheduleId = String(question.schedule_id || '')
    const entry = scheduleId ? stored.answers[scheduleId] : null
    if (isValidDraftEntry(entry, question)) {
      answers[question.schedule_id] = String(entry.answer)
      restoredCount++
    }
    if (isDraftPosition(stored.position, question, scheduleId)) currentIndex = index
  })
  return { answers, currentIndex, restoredCount }
}

function isValidDraftEntry(entry, question) {
  return Boolean(
    entry
    && String(entry.question_id) === String(question.question_id)
    && String(entry.question_version_id) === String(question.question_version_id)
    && String(entry.occurrence_seq) === String(question.occurrence_seq)
    && String(entry.answer || '') !== ''
  )
}

function isDraftPosition(position, question, scheduleId) {
  return Boolean(
    position
    && String(position.schedule_id) === scheduleId
    && String(position.question_version_id) === String(question.question_version_id)
    && String(position.occurrence_seq) === String(question.occurrence_seq)
  )
}

function clearSubmittedDraft(options, groupQuestions, groupResults) {
  const successfulIds = new Set(
    (groupResults || [])
      .filter(item => item && item.wasSubmitted)
      .map(item => String(item.schedule_id))
  )
  if (!successfulIds.size) return

  const stored = readDraft(options)
  const entries = { ...stored.answers }
  successfulIds.forEach(scheduleId => { delete entries[scheduleId] })
  let position = stored.position
  if (position && successfulIds.has(String(position.schedule_id))) position = null
  writeDraft(options, { answers: entries, position })
}

module.exports = {
  createReviewDraftController,
}
