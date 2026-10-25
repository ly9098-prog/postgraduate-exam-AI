// Pure controller for loading an exam attempt result. Extracted from
// subpackages/exam/result/index.js to keep the page a thin delegate.
// All mapping helpers (buildKnowledgeMetrics, buildRadar, ...) stay in the
// page module and are injected as ports so the controller has no page state.

function createExamResultLoadController(options) {
  return {
    load: loadImpl.bind(null, options),
  }
}

async function loadImpl(options, requestOptions = {}) {
  if (options.getInflight()) return options.getInflight()
  const seq = options.nextSequence()
  if (!requestOptions || requestOptions.skipLoadingState !== true) {
    options.setData({ loading: true, errorText: '' })
  }
  const request = (async () => {
    try {
      const response = await options.fetchResult()
      if (!options.isPageAlive() || seq !== options.getSequence()) return
      await applyResultResponse(options, response)
    } catch (error) {
      if (!options.isPageAlive() || seq !== options.getSequence()) return
      options.setData({ loading: false, errorText: options.getErrorMessage(error) })
    }
  })()

  options.setInflight(request)
  try {
    await request
  } finally {
    if (options.getInflight() === request) options.setInflight(null)
  }
}

async function applyResultResponse(options, response) {
  const accuracyPct = options.percentNumber(response.accuracy)
  const score = Number(response.choice_score || 0)
  const totalScore = Number(response.total_choice_score || 0)
  const scoreRatePct = totalScore > 0
    ? Math.round(options.clamp(score / totalScore * 100, 0, 100))
    : accuracyPct
  const metrics = options.buildKnowledgeMetrics(response)
  const scoreRing = options.buildScoreRing(scoreRatePct)
  const radar = options.buildRadar(metrics)
  const topItems = options.buildTopItems(metrics)
  const weakCount = metrics.filter(item => Number(item.accuracyPct) < 70).length
  options.setWrongIds(options.collectWrongIds(response))
  options.resetDiagnosisIndex()
  const resultQuestions = Array.isArray(response.questions) ? response.questions : []
  const firstResultQuestion = resultQuestions[0] || null
  options.setFirstQuestionId(Number(firstResultQuestion && firstResultQuestion.question_id) || 0)
  indexDiagnoses(options, response)
  options.setData(buildResultPatch(options, response, {
    score, scoreRatePct, accuracyPct, scoreRing, radar, topItems, weakCount,
  }))
}

function indexDiagnoses(options, response) {
  ;(Array.isArray(response.questions) ? response.questions : []).forEach((question) => {
    const wrongId = options.firstWrongIdByQuestion(question)
    if (!wrongId) return
    const diagnosis = question && question.error_diagnosis
    const diagnosisId = Number(diagnosis && diagnosis.id || 0)
    if (diagnosisId > 0) options.setDiagnosisId(wrongId, diagnosisId)
  })
}

function buildResultPatch(options, response, computed) {
  const { score, scoreRatePct, accuracyPct, scoreRing, radar, topItems, weakCount } = computed
  return {
    loading: false,
    result: {
      scoreValue: options.compactScore(score),
      scoreRatePct,
      accuracyPct,
      correctCount: Number(response.correct_count || 0),
      wrongCount: Number(response.wrong_count || 0),
      unansweredCount: Number(response.unanswered_count || 0),
      durationText: options.compactDuration(response.duration_sec),
      headline: options.encouragement(scoreRatePct, accuracyPct),
      encourageTail: options.encouragementTail(
        Number(response.wrong_count || 0),
        Number(response.unanswered_count || 0)
      ),
      showScoreRingCaps: scoreRing.showScoreRingCaps,
      scoreRingEndStyle: scoreRing.scoreRingEndStyle,
    },
    radarItems: radar.radarItems,
    radarEdges: radar.radarEdges,
    radarPolygonStyle: radar.radarPolygonStyle,
    topItems,
    weakCount,
    wrongDetailCount: options.getWrongIdsLength(),
  }
}

module.exports = {
  createExamResultLoadController,
}
