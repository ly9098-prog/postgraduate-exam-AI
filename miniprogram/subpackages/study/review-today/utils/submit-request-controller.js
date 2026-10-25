const {
  buildReviewSubmission,
  buildGroupResults,
} = require('./submit-request-state')

function createGroupSubmitRequestController(options) {
  return {
    async submit(input) {
      const reviewBuild = buildReviewSubmission(input)
      if (reviewBuild.error === 'version') {
        options.showToast({ title: '复习任务版本信息缺失，请刷新后重试', icon: 'none' })
        options.setSubmitting(false)
        return { status: 'version' }
      }
      if (reviewBuild.error) {
        options.showToast({ title: '请完成全部题目后再提交', icon: 'none' })
        options.setSubmitting(false)
        return { status: 'incomplete' }
      }

      const reviews = reviewBuild.reviews
      // Timing is captured before the request so network latency is excluded.
      const timingSession = input.buildTimingSession()
      const response = await options.postGrade(timingSession ? { reviews, session: timingSession } : { reviews })
      if (!options.isPageAlive()) return { status: 'dead' }

      const results = Array.isArray(response && response.results) ? response.results : []
      if (results.length < reviews.length) {
        options.showToast({
          title: results.length ? '部分题目批改失败' : '批改结果为空，请重试',
          icon: 'none',
        })
        if (!results.length) {
          options.setSubmitting(false)
          return { status: 'empty' }
        }
      }

      const groupResults = buildGroupResults(input, reviews, results)
      return { status: 'submitted', results, groupResults }
    },
  }
}

module.exports = {
  createGroupSubmitRequestController,
}
