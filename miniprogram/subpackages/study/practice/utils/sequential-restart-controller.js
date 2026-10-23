function createSequentialRestartController(options) {
  return {
    async restart(progress, subjectId, subjectName, loadSeq) {
      const total = Number(progress.total_questions || 0)
      const name = subjectName || String(subjectId)
      options.clearTimer()
      options.setUnloadGuard(false)
      options.setData(options.buildResetView())
      const restart = await options.showRestartConfirm({
        scenario: 'info',
        eyebrow: 'ROUND COMPLETE',
        title: '本轮顺序刷题已完成',
        message: `「${name}」本轮 ${total} 题已全部完成。\n重新开始后会从第一道题按顺序再刷一轮。`,
        confirmText: '重新开始一轮',
        cancelText: '返回选题',
      })
      if (!options.isPageAlive() || loadSeq !== options.getRequestSeq()) return false
      if (!restart) return false
      try {
        await options.resetSequentialProgress({
          subject_id: subjectId,
          _traceId: options.getTraceId(),
        })
        if (!options.isPageAlive() || loadSeq !== options.getRequestSeq()) return false
      } catch (error) {
        if (!options.isPageAlive() || loadSeq !== options.getRequestSeq()) return false
        options.logError('重置顺序刷题进度失败', error)
        options.setData({ errorText: '重置进度失败，请稍后重试' })
        options.showToast({ title: '重置进度失败', icon: 'none' })
        return false
      }
      options.resetSequentialTiming(options.getSession())
      options.setData(options.buildSequentialRestartView())
      options.setUnloadGuard(true)
      await options.reloadQuestions()
      return true
    },
  }
}

module.exports = {
  createSequentialRestartController,
}
