function createSelectDateController(options) {
  return {
    select(date) {
      const nextDate = String(date || '').trim()
      const today = options.getTodayDate()
      if (!nextDate || nextDate === options.getSelectedDate() || (today && nextDate > today)) return
      options.cancelDeferredHistory()
      const patch = {
        selectedDate: nextDate,
        pieDateLabel: options.formatPieDateLabel(nextDate),
        selectedDurationLabel: options.formatSelectedDurationLabel(nextDate),
        canGoNextDate: !!(today && nextDate < today),
        customRangePickerStartDate: options.shiftDate(nextDate, -365),
        selectedSubjectDetail: null,
        _selectedSubject: null,
        durationValueAnimating: true,
      }
      const customMin = patch.customRangePickerStartDate
      const customRangeStartDate = options.getCustomRangeStartDate()
      if (customRangeStartDate && customRangeStartDate > nextDate) {
        patch.customRangeStartDate = nextDate
      } else if (customRangeStartDate && customRangeStartDate < customMin) {
        patch.customRangeStartDate = customMin
      }
      options.setData(patch, () => options.loadDateData(nextDate))
    },
  }
}

module.exports = {
  createSelectDateController,
}
