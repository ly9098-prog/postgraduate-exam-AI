// Pure mapper for applyPracticePayload. Extracted from
// subpackages/study/practice-result/index.js to keep the page a thin delegate.
// All helpers are injected as ports so the mapper has no page state.

function mapPracticePayload(payload, ports) {
  const source = extractSource(payload)
  const embeddedKnowledgeSession = source.knowledge_session || source.knowledgeSession || null
  const results = pickArray(source, ['results', 'submitResults', 'resultList'])
  const questions = pickArray(source, ['questions', 'questionList'])
  const answers = pickArray(source, ['answers', 'answerList'])
  const resultMap = buildIdMap(results)
  const answerMap = buildIdMap(answers)
  const reviewItems = buildReviewItems(source, results, questions, resultMap, answerMap, ports)
  const counts = resolveCounts(source, reviewItems, ports)
  const accuracyPct = computeAccuracy(source, counts, ports)
  const usedTime = computeUsedTime(source, answers)
  const subjectName = computeSubjectName(source, questions)
  const growthGain = Number(source.growthGain ?? source.expGain ?? source.exp_gain ?? source.expAdded ?? 0) || 0
  const embeddedGrowth = ports.normalizeGrowthProfile(
    source.growth || source.growth_profile || source.growthProfile ||
    (source.stats && source.stats.growth) || null
  )
  const wrongReviewItems = reviewItems.filter(item => item.status === 'wrong')
  const localErrorDistribution = ports.buildLocalErrorDistribution(wrongReviewItems)
  const resultTip = ports.getResultTip(accuracyPct, counts.wrongCount, counts.skippedCount, counts.partialCount, counts.totalCount)
  const knowledge = resolveKnowledge(source, embeddedKnowledgeSession, counts, ports)
  return {
    source, reviewItems, counts, accuracyPct, usedTime, subjectName,
    growthGain, embeddedGrowth, wrongReviewItems, localErrorDistribution,
    resultTip, knowledge,
  }
}

function extractSource(payload) {
  return payload && payload.data && !payload.results && typeof payload.data === 'object'
    ? payload.data
    : (payload || {})
}

function pickArray(source, keys) {
  for (const key of keys) {
    if (Array.isArray(source[key])) return source[key]
  }
  return []
}

function buildIdMap(arr) {
  const map = {}
  arr.forEach(item => {
    const qid = item.question_id ?? item.questionId ?? item.id
    if (qid !== undefined && qid !== null) map[String(qid)] = item
  })
  return map
}

function buildReviewItems(source, results, questions, resultMap, answerMap, ports) {
  if (questions.length) {
    return questions.map((question, index) => {
      const qid = question.id ?? question.question_id ?? question.questionId ?? index + 1
      return ports.buildReviewItem(question, resultMap[String(qid)] || {}, answerMap[String(qid)] || {}, index)
    })
  }
  if (Array.isArray(source.reviewItems)) {
    return source.reviewItems.map((item, index) => ports.normalizeReviewItem(item, index))
  }
  if (results.length) {
    return results.map((item, index) => ports.normalizeReviewItem(item, index))
  }
  return []
}

function resolveCounts(source, reviewItems, ports) {
  const c = ports.resolveResultCounts(source, reviewItems)
  return { ...c, answeredTotal: c.correctCount + c.wrongCount }
}

function computeAccuracy(source, counts, ports) {
  const explicit = source.accuracy ?? source.accuracyPct ?? source.correctRate ?? source.correct_rate
  return explicit !== undefined && explicit !== null
    ? ports.normalizePercent(explicit)
    : (counts.answeredTotal ? Math.round(counts.correctCount / counts.answeredTotal * 100) : 0)
}

function computeUsedTime(source, answers) {
  return (
    source.used_time ?? source.usedTime ?? source.duration ??
    source.durationSec ?? source.elapsed ??
    answers.reduce((sum, item) => sum + (Number(item.used_time ?? item.usedTime) || 0), 0)
  )
}

function computeSubjectName(source, questions) {
  return (
    source.subjectName || source.subject_name || source.subject ||
    (questions[0] && (questions[0].subject_name || questions[0].subjectName)) || ''
  )
}

function resolveKnowledge(source, embeddedKnowledgeSession, counts, ports) {
  const knowledgeSession = embeddedKnowledgeSession && typeof embeddedKnowledgeSession === 'object'
    ? embeddedKnowledgeSession : null
  const knowledgeRootId = Math.max(0, Number(
    (knowledgeSession && (knowledgeSession.root_knowledge_point_id || knowledgeSession.rootKnowledgePointId ||
      knowledgeSession.knowledge_point_id || knowledgeSession.knowledgePointId)) ||
    source.knowledge_point_id || source.knowledgePointId || ports.getLaunchKnowledgePointId()
  ) || 0)
  const knowledgeRootName = String(knowledgeSession &&
    (knowledgeSession.root_name || knowledgeSession.rootName) || '').trim()
  const knowledgeIncludeDescendants = Boolean(knowledgeSession &&
    (knowledgeSession.include_descendants === true || knowledgeSession.includeDescendants === true))
  const knowledgeAnswerCount = Math.max(0, counts.correctCount + counts.wrongCount)
  const hasKnowledgeLaunch = Boolean(knowledgeSession ||
    (ports.getLaunchSource() === 'knowledge_map' && knowledgeRootId))
  return {
    knowledgeSession, knowledgeRootId, knowledgeRootName,
    knowledgeIncludeDescendants, knowledgeAnswerCount, hasKnowledgeLaunch,
  }
}

function buildPracticeDataPatch(mapped, ports) {
  const { counts, accuracyPct, usedTime, subjectName, growthGain,
    embeddedGrowth, reviewItems, wrongReviewItems, localErrorDistribution, resultTip } = mapped
  return {
    subjectName,
    correctCount: counts.correctCount,
    wrongCount: counts.wrongCount,
    skippedCount: counts.skippedCount,
    partialCount: counts.partialCount,
    totalCount: counts.totalCount,
    accuracyPct,
    accuracyDotDeg: Math.round(accuracyPct * 3.6 - 90),
    durationText: ports.formatDuration(usedTime),
    resultTip,
    growthGain,
    ...(embeddedGrowth ? {
      growth: embeddedGrowth,
      growthAvailable: true,
      unlockedBadgeCount: embeddedGrowth.badges.filter(item => item && item.unlocked).length,
    } : {}),
    reviewItems,
    filteredReviewItems: reviewItems,
    questionListHeightRpx: ports.getQuestionListHeightRpx(reviewItems.length),
    wrongReviewItems,
    batchDiagnosisMode: false,
    batchSelectedMap: {},
    batchSelectedCount: 0,
    batchSelectableCount: wrongReviewItems.filter(item => Number(item.wrongQuestionId) > 0).length,
    batchDiagnosisSaving: false,
    errorDistribution: localErrorDistribution,
    errorDonutGradient: ports.buildErrorDonutGradient(localErrorDistribution),
    errorDonutSvg: ports.buildErrorDonutSvg(localErrorDistribution),
  }
}

function maybeRecordKnowledgeSync(mapped, ports) {
  const { knowledge, counts } = mapped
  if (!knowledge.hasKnowledgeLaunch || !ports.getLaunchSubjectId() ||
      !knowledge.knowledgeRootId || knowledge.knowledgeAnswerCount <= 0) return
  ports.recordKnowledgePractice({
    subjectId: ports.getLaunchSubjectId(),
    knowledgePointId: knowledge.knowledgeRootId,
    includeDescendants: knowledge.knowledgeIncludeDescendants,
    answeredCount: knowledge.knowledgeAnswerCount,
    baselineAttemptCount: ports.consumeKnowledgeBaseline(ports.getLaunchSubjectId(), knowledge.knowledgeRootId),
    correctCount: counts.correctCount,
    wrongCount: counts.wrongCount,
    requestId: ports.getPracticeRequestId(),
    rootName: knowledge.knowledgeRootName,
  })
}


function applyPracticePayloadOrchestration(payload, ports, pageState) {
  pageState.incrementDiagnosisRefreshSeq()
  const mapped = mapPracticePayload(payload, ports)
  pageState.setSessionPayload(mapped.source)
  maybeRecordKnowledgeSync(mapped, ports)
  if (!pageState.isPageAlive()) return
  pageState.setData(buildPracticeDataPatch(mapped, ports))
  if (pageState.isResultVisible()) pageState.refreshWrongDiagnoses()
}

module.exports = {
  mapPracticePayload,
  buildPracticeDataPatch,
  maybeRecordKnowledgeSync,
  applyPracticePayloadOrchestration,
}
