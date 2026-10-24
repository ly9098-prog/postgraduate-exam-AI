function createCumulativeStartController(options) {
  return {
    change(event) {
      let date = event && event.detail ? String(event.detail.value || '') : ''
      if (!date) return null

      const minDate = options.getPickerStartDate() || options.shiftDate(options.getTodayDate(), -365)
      const maxDate = options.getTodayDate()
      if (minDate && date < minDate) date = minDate
      if (maxDate && date > maxDate) date = maxDate
      if (date === options.getCumulativeStartDate()) return null

      options.markCustomized()
      options.setData({ cumulativeStartDate: date, cumulativeLoading: true }, () => {
        options.refreshCumulativeSummary(date, false)
      })
      return date
    },
  }
}

module.exports = {
  createCumulativeStartController,
}
