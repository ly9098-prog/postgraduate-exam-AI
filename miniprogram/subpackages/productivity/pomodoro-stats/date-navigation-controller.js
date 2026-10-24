function createDateNavigationController(options) {
  const select = date => options.selectDate(date)

  return {
    previous() {
      const current = options.getSelectedDate() || options.getTodayDate()
      if (!current) return null
      return select(options.shiftDate(current, -1))
    },
    next() {
      if (!options.canGoNextDate()) return null
      const current = options.getSelectedDate() || options.getTodayDate()
      const today = options.getTodayDate()
      if (!current || !today) return null
      const next = options.shiftDate(current, 1)
      return select(next > today ? today : next)
    },
    today() {
      const today = options.getTodayDate()
      if (!today || today === options.getSelectedDate()) return null
      return select(today)
    },
  }
}

module.exports = {
  createDateNavigationController,
}
