function createSettingsController(options) {
  let loaded = false
  let promise = null

  return {
    ensure() {
      if (loaded || options.isLoaded()) {
        loaded = true
        return Promise.resolve()
      }
      if (!promise) promise = loadImpl(options, () => { loaded = true }, () => { promise = null })
      return promise
    },
  }
}

async function loadImpl(options, markLoaded, clearPromise) {
  try {
    const settings = await options.getSettings()
    // A concurrent save may have landed a newer day_start_minute while this
    // GET was in flight; applying the stale response would revert the saved
    // setting. The save path marks loaded before resolving, so bail out.
    if (options.isLoaded()) {
      markLoaded()
      return
    }
    const patch = buildSettingsPatch(options, settings)
    markLoaded()
    options.markLoaded()
    options.setData(patch)
  } catch (e) {
    // Settings failures are non-fatal and do not permanently lock the flow:
    // the next loadData retries and server stats reconciliation provides a
    // fallback when the device clock is wrong.
    options.logError('加载统计日设置失败', e)
  } finally {
    clearPromise()
  }
}

function buildSettingsPatch(options, settings) {
  const raw = Number(settings && settings.day_start_minute)
  const dsm = Number.isFinite(raw) ? Math.max(0, Math.min(1439, raw)) : 0
  const prevToday = options.getTodayDate()
  const today = options.getChinaStudyDate(dsm)
  const patch = {
    dayStartMinute: dsm,
    dayStartTime: options.minuteToTimeText(dsm),
    studyDayRangeText: options.getStudyDayRangeText(dsm),
    cumulativePickerStartDate: options.shiftDate(today, -365),
  }
  if (today !== prevToday) patch._todayDate = today

  // Follow the new today when the user stayed on the previous today or the
  // old selected date exceeds the new maximum date.
  const selectedDate = options.getSelectedDate()
  if (!selectedDate || selectedDate === prevToday || selectedDate > today) {
    patch.selectedDate = today
    patch.pieDateLabel = '今日'
    patch.selectedDurationLabel = '今日学习'
  }

  const nextSelected = patch.selectedDate || selectedDate
  patch.canGoNextDate = !!(nextSelected && today && nextSelected < today)
  if (nextSelected) {
    const customMin = options.shiftDate(nextSelected, -365)
    patch.customRangePickerStartDate = customMin
    const customRangeStartDate = options.getCustomRangeStartDate()
    if (customRangeStartDate && customRangeStartDate > nextSelected) {
      patch.customRangeStartDate = nextSelected
    } else if (customRangeStartDate && customRangeStartDate < customMin) {
      patch.customRangeStartDate = customMin
    }
  }
  return patch
}

module.exports = {
  createSettingsController,
}
