/**
 * Builds the view patch that reconciles client-side day-start / today / selected
 * date against the server-authoritative stats response.  All inputs are explicit
 * so the module never touches Page state; the caller applies the patch and reads
 * the returned summary to decide whether to reload.
 */
function reconcileFromServer(options) {
  const {
    stats, summary, dayStartMinute, todayDate, selectedDate,
    customRangeStartDate, minuteToTimeText, getStudyDayRangeText, shiftDate,
  } = options

  const patch = {}
  reconcileDayStart(patch, stats, dayStartMinute, minuteToTimeText, getStudyDayRangeText)

  const today = (stats && stats.today_date) || (summary && summary.date) || ''
  if (today) patch.cumulativePickerStartDate = shiftDate(today, -365)

  const changedToday = reconcileTodayAndSelected(patch, today, todayDate, selectedDate)
  reconcileCustomRange(patch, today, todayDate, selectedDate, customRangeStartDate, shiftDate)

  return {
    patch,
    changedToday,
    today: today || todayDate,
    selectedDate: today && (!selectedDate || selectedDate === todayDate || selectedDate > today)
      ? today
      : selectedDate,
  }
}

function reconcileDayStart(patch, stats, dayStartMinute, minuteToTimeText, getStudyDayRangeText) {
  if (!stats) return
  const rawDsm = stats.day_start_minute
  if (rawDsm == null) return
  const dsm = Number.isFinite(Number(rawDsm)) ? Math.max(0, Math.min(1439, Number(rawDsm))) : dayStartMinute
  if (dsm !== dayStartMinute) {
    patch.dayStartMinute = dsm
    patch.dayStartTime = minuteToTimeText(dsm)
    patch.studyDayRangeText = getStudyDayRangeText(dsm)
  }
}

function reconcileTodayAndSelected(patch, today, todayDate, selectedDate) {
  let changedToday = false
  if (today && today !== todayDate) {
    patch._todayDate = today
    changedToday = true
  }
  if (today && (!selectedDate || selectedDate === todayDate || selectedDate > today)) {
    patch.selectedDate = today
    patch.pieDateLabel = '今日'
    patch.selectedDurationLabel = '今日学习'
    changedToday = true
  }
  return changedToday
}

function reconcileCustomRange(patch, today, todayDate, selectedDate, customRangeStartDate, shiftDate) {
  const finalToday = patch._todayDate || today || todayDate
  const finalSelected = patch.selectedDate || selectedDate
  if (finalToday && finalSelected) patch.canGoNextDate = finalSelected < finalToday
  if (finalSelected) {
    const customMin = shiftDate(finalSelected, -365)
    patch.customRangePickerStartDate = customMin
    if (customRangeStartDate && customRangeStartDate > finalSelected) {
      patch.customRangeStartDate = finalSelected
    } else if (customRangeStartDate && customRangeStartDate < customMin) {
      patch.customRangeStartDate = customMin
    }
  }
}

module.exports = {
  reconcileFromServer,
}
