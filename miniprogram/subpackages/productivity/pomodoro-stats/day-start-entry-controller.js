function createDayStartEntryController(options) {
  return {
    change: event => change(options, event),
  }
}

function change(options, event) {
  const timeText = event && event.detail && event.detail.value
  if (typeof timeText !== 'string') return
  const minute = options.timeTextToMinute(timeText)
  if (minute === options.getDayStartMinute()) return
  options.saveDayStart(minute)
}

module.exports = { createDayStartEntryController }
