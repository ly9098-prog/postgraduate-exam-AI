const { getChinaDate } = require('../../../../utils/china-time')

function createOverviewSyncController(options) {
  return {
    applyOverviewToSession(overview, vm) {
      return applyOverviewImpl(options, overview, vm)
    },

    applyOverviewWithDayReset(overview, vm) {
      return applyOverviewWithDayResetImpl(options, overview, vm)
    },

    adjustVmForActiveSession(vm) {
      return adjustVmImpl(options, vm)
    },

    isSameDay() {
      const session = options.getSession()
      const currentDate = getChinaDate(0)
      return !session || !session.taskDate || String(session.taskDate) === currentDate
    },
  }
}

function applyOverviewImpl(options, overview, vm) {
  const session = options.getSession()
  session.reviewOverview = overview
  session.taskDate = String(overview.date || getChinaDate(0))
  session.allTodayQuestionIds = overview.all_question_ids || []
  session.completedQuestionIds = overview.completed_question_ids || []
  session.remainingQuestionIds = overview.remaining_question_ids || []
}

function applyOverviewWithDayResetImpl(options, overview, vm) {
  const session = options.getSession()
  const currentDate = getChinaDate(0)
  session.taskDate = String((overview && overview.date) || currentDate)
  session.reviewOverview = overview || {}
  session.allTodayQuestionIds = (overview && overview.all_question_ids) || []
  session.completedQuestionIds = (overview && overview.completed_question_ids) || []
  session.remainingQuestionIds = (overview && overview.remaining_question_ids) || []
  session.allGroupResults = []
  session.totalCorrect = 0
  session.totalWrong = 0
  session.totalCompleted = 0
  session.todayTaskTotalCount = Math.max(0, Number(vm.todayDueCount || 0))
  session.completedBeforeSession = Math.max(0, Number(vm.todayCompletedCount || 0))
}

function adjustVmImpl(options, vm) {
  const session = options.getSession()
  if (session.todayTaskTotalCount > 0 && (options.getPhase() === 'reviewing' || options.getPhase() === 'group-result')) {
    const taskTotalCount = Math.max(
      Number(session.todayTaskTotalCount || 0),
      Number(options.getTodayDueCount() || 0)
    )
    const remainingCount = Math.min(taskTotalCount, Math.max(0, Number(vm.todayRemainingCount || 0)))
    vm.todayDueCount = taskTotalCount
    vm.todayRemainingCount = remainingCount
    vm.todayCompletedCount = Math.max(0, taskTotalCount - remainingCount)
    vm.todayProgressPercent = taskTotalCount > 0 ? Math.round(vm.todayCompletedCount / taskTotalCount * 100) : 0
  }
  return vm
}

module.exports = {
  createOverviewSyncController,
}
