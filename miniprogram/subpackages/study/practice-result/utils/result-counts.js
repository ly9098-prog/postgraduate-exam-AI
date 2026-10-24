/**
 * Pure helper for computing practice result counts from source data and review items.
 *
 * Extracted from practice-result/index.js applyPracticePayload.
 */

/**
 * Resolve explicit or inferred counts from the payload source and review items.
 *
 * Falls back to counting by status when explicit counts are missing.
 */
function resolveResultCounts(source, reviewItems) {
  var items = reviewItems || []
  var explicitCorrect = source.total_correct != null ? source.total_correct : (source.totalCorrect != null ? source.totalCorrect : (source.correctCount != null ? source.correctCount : source.correct_count))
  var explicitWrong = source.total_wrong != null ? source.total_wrong : (source.totalWrong != null ? source.totalWrong : (source.wrongCount != null ? source.wrongCount : source.wrong_count))
  var explicitSkipped = source.total_skipped != null ? source.total_skipped : (source.totalSkipped != null ? source.totalSkipped : (source.skippedCount != null ? source.skippedCount : (source.skipped_count != null ? source.skipped_count : source.skipped)))
  var explicitPartial = source.total_partial != null ? source.total_partial : (source.totalPartial != null ? source.totalPartial : (source.partialCount != null ? source.partialCount : (source.partial_count != null ? source.partial_count : source.partial)))

  function countByStatus(status) {
    return items.filter(function(item) { return item.status === status }).length
  }

  var correctCount = Number.isFinite(Number(explicitCorrect)) ? Number(explicitCorrect) : countByStatus('correct')
  var wrongCount = Number.isFinite(Number(explicitWrong)) ? Number(explicitWrong) : countByStatus('wrong')
  var skippedCount = Number.isFinite(Number(explicitSkipped)) ? Number(explicitSkipped) : countByStatus('skipped')
  var partialCount = Number.isFinite(Number(explicitPartial)) ? Number(explicitPartial) : countByStatus('partial')
  var totalCount =
    Number(source.totalCount != null ? source.totalCount : (source.total_count != null ? source.total_count : source.total)) ||
    (correctCount + wrongCount + skippedCount + partialCount) ||
    items.length

  if (!correctCount && !wrongCount && !skippedCount && !partialCount && items.length) {
    correctCount = countByStatus('correct')
    wrongCount = countByStatus('wrong')
    skippedCount = countByStatus('skipped')
    partialCount = countByStatus('partial')
    totalCount = items.length
  }

  return {
    correctCount: correctCount,
    wrongCount: wrongCount,
    skippedCount: skippedCount,
    partialCount: partialCount,
    totalCount: totalCount,
  }
}

module.exports = { resolveResultCounts }
