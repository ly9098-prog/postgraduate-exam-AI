const { formatElapsedSec } = require('./timer-math')

function buildEndConfirmViewModel(mode, snapshot) {
  if (mode === 'free-complete') {
    const elapsed = Math.max(0, snapshot.elapsedSec || 0)
    const fmt = formatElapsedSec(elapsed)
    const hasElapsed = elapsed >= 1
    return {
      showEndConfirm: true,
      endConfirmTheme: 'free',
      endConfirmTitle: '结束自由计时？',
      endConfirmText: hasElapsed
        ? `本次已专注 ${fmt.friendly}，确认后将计入学习统计。`
        : '当前计时时长较短，确认后仍会结束本次计时。',
      endConfirmLine1: hasElapsed ? '本次已专注' : '当前计时时长较短',
      endConfirmLine2: hasElapsed ? fmt.friendly : '确认后仍会结束本次计时。',
      endConfirmLine3: hasElapsed ? '确认后将计入学习统计。' : '',
      endConfirmOkText: '确认结束',
      endConfirmCancelText: '继续计时',
    }
  }

  if (mode === 'countdown-interrupt') {
    const isBreak = snapshot.phase === 'break'
    const elapsedSec = Math.max(0, (snapshot.totalSec || 0) - (snapshot.remainingSec || 0))
    const fmt = formatElapsedSec(elapsedSec)
    const hasElapsed = elapsedSec > 0
    return {
      showEndConfirm: true,
      endConfirmTheme: isBreak ? 'break' : 'focus',
      endConfirmTitle: isBreak ? '结束休息？' : '结束本次专注？',
      endConfirmText: hasElapsed
        ? `本次已专注 ${fmt.friendly}。确认后将结束当前番茄钟。`
        : '确认后将结束当前番茄钟。',
      endConfirmLine1: hasElapsed ? '本次已专注' : '确认后将结束当前番茄钟。',
      endConfirmLine2: hasElapsed ? fmt.friendly : '',
      endConfirmLine3: hasElapsed ? '确认后将结束当前番茄钟。' : '',
      endConfirmOkText: '结束',
      endConfirmCancelText: isBreak ? '继续休息' : '继续专注',
    }
  }

  throw new Error('Unknown confirm mode: ' + mode)
}

module.exports = { buildEndConfirmViewModel }
