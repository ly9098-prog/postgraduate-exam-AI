const api = require('../../utils/api')
const { getChinaDate } = require('../../utils/china-time')
const dateFilter = require('./date-range')

Component({
  properties: {
    subjects: { type: Array, value: [] },
    subjectsLoading: { type: Boolean, value: false },
    subjectsError: { type: Boolean, value: false },
    subjectId: { type: Number, value: 0 },
    errorTypes: { type: Array, value: [] },
    errorType: { type: String, value: '' },
    topic: { type: String, value: '' },
    preset: { type: String, value: '' },
    dateFrom: { type: String, value: '' },
    dateTo: { type: String, value: '' },
  },
  data: {
    datePresets: dateFilter.DATE_PRESETS,
    selectedDatePreset: '',
    draftDateFrom: '',
    draftDateTo: '',
    dateRangeText: '',
    dateFilterError: '',
    filterToday: '',
  },
  observers: {
    'preset, dateFrom, dateTo'(preset, dateFrom, dateTo) {
      this.setData({
        selectedDatePreset: preset,
        draftDateFrom: dateFrom,
        draftDateTo: dateTo,
        dateRangeText: dateFilter.rangeLabel(dateFrom, dateTo),
        dateFilterError: '',
      })
    },
  },
  lifetimes: {
    attached() { this._syncToday() },
  },
  pageLifetimes: {
    show() { this._syncToday() },
  },
  methods: {
    _syncToday() { this.setData({ filterToday: getChinaDate(0, api.now()) }) },
    reset() { this.triggerEvent('reset') },
    retrySubjects() { this.triggerEvent('retrysubjects') },
    clearTopic() { this.triggerEvent('cleartopic') },
    selectSubject(e) { this.triggerEvent('subjectchange', { value: e.currentTarget.dataset.value }) },
    selectErrorType(e) { this.triggerEvent('errorchange', { value: e.currentTarget.dataset.value }) },
    selectDatePreset(e) {
      this._syncToday()
      const preset = String(e.currentTarget.dataset.value || '')
      if (!dateFilter.DATE_PRESETS.some(item => item.value === preset)) return
      if (preset === 'custom') {
        const fallback = dateFilter.presetRange('week', api.now())
        this.setData({
          selectedDatePreset: preset,
          draftDateFrom: this.data.dateFrom || fallback.dateFrom,
          draftDateTo: this.data.dateTo || fallback.dateTo,
          dateFilterError: '',
        })
        return
      }
      this.triggerEvent('datechange', { preset, ...dateFilter.presetRange(preset, api.now()) })
    },
    onDateFromChange(e) { this.setData({ draftDateFrom: e.detail.value, dateFilterError: '' }) },
    onDateToChange(e) { this.setData({ draftDateTo: e.detail.value, dateFilterError: '' }) },
    applyDateRange() {
      this._syncToday()
      const dateFrom = this.data.draftDateFrom
      const dateTo = this.data.draftDateTo
      const error = dateFilter.validateRange(dateFrom, dateTo)
      if (error) {
        this.setData({ dateFilterError: error })
        return
      }
      this.triggerEvent('datechange', { preset: 'custom', dateFrom, dateTo })
    },
  },
})
