function createPieTapController(options) {
  return {
    handleTap(event) {
      handleTapImpl(options, event)
    },
  }
}

function handleTapImpl(options, event) {
  if (!options.hasDistributionData()) return
  const touch = (event.changedTouches && event.changedTouches[0]) ||
    (event.touches && event.touches[0])
  const tapX = touch ? touch.clientX : event.detail && event.detail.x
  const tapY = touch ? touch.clientY : event.detail && event.detail.y
  if (typeof tapX !== 'number' || typeof tapY !== 'number') return

  const query = options.createSelectorQuery()
  query.select('#pie-canvas').boundingClientRect(rect => {
    if (!rect || !rect.width) return
    const x = tapX - rect.left
    const y = tapY - rect.top
    const geometry = options.getGeometry(rect)
    const { centerX, centerY, radius, tilt } = geometry

    const dx = x - centerX
    const dy = (y - centerY) / tilt
    const dist = Math.sqrt(dx * dx + dy * dy)
    if (dist > radius) {
      dismissIfSelected(options)
      return
    }

    let angle = Math.atan2(dy, dx)
    if (angle < -Math.PI / 2) angle += Math.PI * 2
    const subjects = options.getSubjects()
    const totalDuration = subjects.reduce((sum, subject) => sum + (subject.duration_sec || 0), 0) || 1
    let cumulativeStart = -Math.PI / 2
    for (let index = 0; index < subjects.length; index++) {
      const subject = subjects[index]
      const percentage = (subject.duration_sec || 0) / totalDuration
      const cumulativeEnd = cumulativeStart + Math.PI * 2 * percentage
      if (percentage > 0 && angle >= cumulativeStart && angle < cumulativeEnd) {
        selectSubject(options, subject)
        return
      }
      cumulativeStart = cumulativeEnd
    }
  }).exec()
}

function dismissIfSelected(options) {
  if (!options.getSelectedSubjectDetail()) return
  options.setData({
    selectedSubjectDetail: null,
    _selectedSubject: null,
  }, () => { if (options.isAlive()) options.renderPie(1) })
}

function selectSubject(options, subject) {
  options.setData({
    selectedSubjectDetail: subject,
    _selectedSubject: subject.subject,
    pieTapped: true,
  }, () => {
    if (!options.isAlive()) return
    options.renderPie(1)
    options.setTimeout(() => {
      if (options.isAlive()) options.setData({ pieTapped: false })
    }, 350)
  })
}

module.exports = {
  createPieTapController,
}
