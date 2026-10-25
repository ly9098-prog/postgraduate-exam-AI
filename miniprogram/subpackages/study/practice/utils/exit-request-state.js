function exitPrompt(hasPendingSubmit, retryBlocked) {
  return {
    scenario: 'info',
    layout: 'minimal',
    title: '退出练习？',
    message: retryBlocked
      ? '本次提交未通过，退出后可重新开始。'
      : (hasPendingSubmit
        ? '交卷仍在确认中，退出后可下次继续确认。'
        : '本组练习尚未提交，确定退出吗？'),
    confirmText: '退出',
    cancelText: hasPendingSubmit && !retryBlocked ? '继续确认' : '继续作答',
    hideEyebrow: true,
  }
}

function exitSubmissionState(submission) {
  return {
    hasPendingSubmit: !!submission,
    retryBlocked: !!(submission && submission.retryBlocked),
  }
}

module.exports = {
  exitPrompt,
  exitSubmissionState,
}
