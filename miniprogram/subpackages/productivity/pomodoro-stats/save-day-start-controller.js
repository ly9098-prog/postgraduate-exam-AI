function createSaveDayStartController(options) {
  return {
    async save(minute) {
      options.showLoading()
      try {
        await options.saveSettings(minute)
        const today = options.getChinaStudyDate(minute)
        let selectedDate = options.getSelectedDate()
        // Collapse the old selected date to today when the new day-start moves
        // the maximum date backward.
        if (!selectedDate || selectedDate > today) selectedDate = today
        options.markSettingsLoaded()
        options.setData({
          dayStartMinute: minute,
          dayStartTime: options.minuteToTimeText(minute),
          studyDayRangeText: options.getStudyDayRangeText(minute),
          _todayDate: today,
          selectedDate,
          pieDateLabel: options.formatPieDateLabel(selectedDate),
          selectedDurationLabel: options.formatSelectedDurationLabel(selectedDate),
          canGoNextDate: !!(selectedDate && selectedDate < today),
          customRangeStartDate: options.getCustomRangeStartDate() && options.getCustomRangeStartDate() <= selectedDate
            ? options.getCustomRangeStartDate()
            : selectedDate,
          selectedSubjectDetail: null,
          _selectedSubject: null,
        }, () => {
          if (!options.isAlive() || !options.isViewReady()) return
          // Reload all stats and redraw charts after the day-start change.
          options.loadData()
        })
      } catch (e) {
        options.logError('保存统计日设置失败', e)
        options.showToast('保存失败，请重试')
      } finally {
        options.hideLoading()
      }
    },
  }
}

module.exports = {
  createSaveDayStartController,
}
