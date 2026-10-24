function createDistributionEntryController(options) {
  return {
    tapPeriod(event) {
      const period = event && event.currentTarget && event.currentTarget.dataset
        ? event.currentTarget.dataset.period
        : ''
      if (!period || period === options.getDistributionPeriod()) return null
      options.loadDistributionForPeriod(period, true)
      return period
    },
    changeCustomStart(event) {
      let date = event && event.detail ? String(event.detail.value || '') : ''
      if (!date) return null

      const anchor = options.getSelectedDate() || options.getTodayDate()
      const minDate = options.getCustomRangePickerStartDate() ||
        (anchor ? options.shiftDate(anchor, -365) : '')
      if (minDate && date < minDate) date = minDate
      if (anchor && date > anchor) date = anchor
      options.setData({ customRangeStartDate: date, distributionPeriod: 'custom' }, () => {
        options.loadDistributionForPeriod('custom', true)
      })
      return date
    },
  }
}

module.exports = {
  createDistributionEntryController,
}
