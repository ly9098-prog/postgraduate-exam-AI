function normalizeReviewBatchSize(value, options) {
  var num = Number(value)
  if (isNaN(num) || num <= 0) return options.defaultBatchSize
  for (var i = 0; i < options.batchSizeOptions.length; i++) {
    if (num === options.batchSizeOptions[i]) return num
  }
  return options.defaultBatchSize
}

function createOverviewVMController(options) {
  return {
    buildVM(overview) {
      return buildOverviewVM(options, overview)
    },
  }
}

function buildOverviewVM(options, overview) {
  const due = Number(overview.today_due_count || 0)
  const completed = Number(overview.today_completed_count || 0)
  const remaining = Number(overview.today_remaining_count || 0)
  const progress = due > 0 ? Math.round((completed / due) * 100) : 0
  const overdue = Number(overview.today_overdue_count || 0)

  let todayAdviceText = '按当前节奏完成一组，今天的复习就会更轻松。'
  if (overdue > 0) {
    todayAdviceText = `先完成 ${overdue} 道逾期题，把最容易遗忘的内容拉回来。`
  } else if (remaining <= 5) {
    todayAdviceText = `只剩 ${remaining} 道，适合一次完成今天的记忆任务。`
  } else if (completed > 0) {
    todayAdviceText = `已经完成 ${completed} 道，继续一组就能保持复习节奏。`
  }

  let batchSize = Number(overview.batch_size || 10)
  batchSize = normalizeReviewBatchSize(batchSize, {
    batchSizeOptions: options.getBatchSizeOptions(),
    defaultBatchSize: options.getDefaultBatchSize(),
  })
  if (options.isUserBatchSizeSelected()) {
    batchSize = options.getCurrentUserBatchSize()
  }

  return {
    todayDueCount: due,
    todayCompletedCount: completed,
    todayRemainingCount: remaining,
    todayOverdueCount: overdue,
    todayNewDueCount: Number(overview.today_new_due_count || 0),
    estimatedMinutes: Number(overview.estimated_minutes || Math.ceil(remaining * 0.5)),
    reviewBatchSize: batchSize,
    currentBatchNo: Number(overview.current_batch_no || 0),
    totalBatchCount: Number(overview.total_batch_count || 0),
    remainingBatchCount: Number(overview.remaining_batch_count || 0),
    todayProgressPercent: Math.min(100, Math.max(0, progress)),
    todayAdviceText,
  }
}

module.exports = {
  createOverviewVMController,
}
