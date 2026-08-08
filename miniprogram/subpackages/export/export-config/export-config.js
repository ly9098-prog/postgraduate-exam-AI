/**
 * Export configuration page — range, format, title, date, answer/analysis, sort, group, space.
 */
const exportApi = require('../services/export')

const SORT_OPTIONS = [
  { value: 'newest', label: '加入时间最新优先' },
  { value: 'oldest', label: '加入时间最早优先' },
  { value: 'original', label: '原练习顺序' },
  { value: 'random', label: '随机排序' },
  { value: 'knowledge_point', label: '按知识点排序' },
  { value: 'question_type', label: '按题型排序' },
]

const GROUP_OPTIONS = [
  { value: 'none', label: '连续排列' },
  { value: 'subject', label: '按学科' },
  { value: 'chapter', label: '按章节' },
  { value: 'knowledge_point', label: '按知识点' },
  { value: 'question_type', label: '按题型' },
]

const SPACE_OPTIONS = [
  { value: 'compact', label: '紧凑' },
  { value: 'standard', label: '标准' },
  { value: 'spacious', label: '宽松' },
]

const POSITION_OPTIONS = [
  { value: 'none', label: '不打印' },
  { value: 'after_question', label: '紧跟每道题' },
  { value: 'at_end', label: '集中在末尾' },
]

const LAYOUT_PRESETS = [
  {
    value: 'paper',
    label: '真题试卷',
    caption: '题型分区，答案与解析集中在末尾',
    sortBy: 'question_type',
    groupBy: 'question_type',
    answerPosition: 'at_end',
    analysisPosition: 'at_end',
    spaceStyle: 'standard',
  },
  {
    value: 'review',
    label: '逐题复盘',
    caption: '每题紧跟答案解析，适合订正复习',
    sortBy: 'newest',
    groupBy: 'subject',
    answerPosition: 'after_question',
    analysisPosition: 'after_question',
    spaceStyle: 'compact',
  },
  {
    value: 'blank',
    label: '空白练习',
    caption: '隐藏答案解析，并预留更多书写空间',
    sortBy: 'question_type',
    groupBy: 'question_type',
    answerPosition: 'none',
    analysisPosition: 'none',
    spaceStyle: 'spacious',
  },
]

Page({
  data: {
    // Expose options to WXML (cannot use require or global vars in WXML)
    SORT_OPTIONS: SORT_OPTIONS,
    GROUP_OPTIONS: GROUP_OPTIONS,
    SPACE_OPTIONS: SPACE_OPTIONS,
    POSITION_OPTIONS: POSITION_OPTIONS,
    LAYOUT_PRESETS: LAYOUT_PRESETS,

    // Navigation context
    _selectedIds: [],

    // Range
    rangeType: 'all', // 'all' | 'filtered' | 'selected'
    filters: null,
    hasActiveFilters: false,
    rangeTypes: [
      { value: 'all', label: '全部错题' },
      { value: 'filtered', label: '当前筛选结果' },
      { value: 'selected', label: '已选错题' },
    ],

    // Format
    format: 'pdf',
    wordDisabled: false,
    wordTip: '',

    // Title
    title: '',
    titleDefault: '错题巩固练习',

    // Reference-paper layout uses a clean title without a date line.
    showDate: false,
    exportDate: '',

    // Sort & Group
    sortBy: 'question_type',
    sortByLabel: '按题型排序',
    sortByIndex: 5,
    groupBy: 'question_type',
    groupByLabel: '按题型',
    groupByIndex: 4,

    // Answer & Analysis
    answerPosition: 'at_end',
    answerPositionLabel: '集中在末尾',
    answerPositionIndex: 2,
    analysisPosition: 'at_end',
    analysisPositionLabel: '集中在末尾',
    analysisPositionIndex: 2,

    // Space
    spaceStyle: 'standard',
    spaceStyleLabel: '标准',
    spaceStyleIndex: 1,
    layoutPreset: 'paper',
    layoutSummary: '按题型排序 · 按题型分区 · 答案解析集中在末尾 · 标准留白',

    // Preview count
    previewCount: 0,
    countLoading: false,
    countError: '',
    previewCountReady: false,

    // Submit
    submitting: false,
    submitError: '',

    // Capability metadata
    _wsEnabled: false,
    capabilityLoading: true,
    capabilityError: '',
    maxQuestionCount: 100,

    // Floating primary action
    floatingVisible: false,
    titleInputFocused: false,
    pickerOpen: false,
  },

  // Non-reactive fields
  _navigating: false,
  _previewRequestSeq: 0,
  _previewDebounceTimer: null,
  _floatingIdleTimer: null,
  _floatingEntranceTimer: null,
  _pageDestroyed: false,
  _pageReady: false,

  onLoad(options) {
    this._pageDestroyed = false
    this._pageReady = false

    // getOpenerEventChannel() may return a placeholder object when this page
    // is reached via redirectTo/direct entry. Only register listeners when the
    // real EventChannel API is available.
    const eventChannel = this.getOpenerEventChannel && this.getOpenerEventChannel()
    if (eventChannel && typeof eventChannel.on === 'function') {
      eventChannel.on('acceptDataFromOpenerPage', (data) => {
        this._applyExportContext(data || {})
      })
    }

    // Selected-export entry uses global data because a long ID list should not
    // be placed in the URL. Apply it before the first preview request.
    const app = getApp()
    const globalData = app.getGlobalData && app.getGlobalData()
    if (globalData && globalData.exportSelectedIds) {
      this._applyExportContext({ selectedIds: globalData.exportSelectedIds })
      globalData.exportSelectedIds = null
    }

    this._checkCapabilities()
  },

  onReady() {
    this._pageReady = true
    // Delay one frame so the first appearance uses the same transition as all
    // later reveals instead of rendering abruptly in its final position.
    this._clearFloatingEntranceTimer()
    this._floatingEntranceTimer = setTimeout(() => {
      this._floatingEntranceTimer = null
      this._showFloatingAction(true)
    }, 40)
  },

  onShow() {
    this._navigating = false
    if (this.data.pickerOpen || this.data.titleInputFocused) {
      this.setData({ pickerOpen: false, titleInputFocused: false })
    }
    if (this.data.submitting) {
      this.setData({ submitting: false }, () => {
        if (this._pageReady) this._syncFloatingAction()
      })
    } else if (this._pageReady) {
      this._showFloatingAction(true)
    }
  },

  onHide() {
    this._clearFloatingIdleTimer()
    this._clearFloatingEntranceTimer()
  },

  onUnload() {
    // Clean up transient state — do NOT cancel back-end export tasks.
    this._pageDestroyed = true
    this._navigating = false
    this._previewRequestSeq += 1
    if (this._previewDebounceTimer) {
      clearTimeout(this._previewDebounceTimer)
      this._previewDebounceTimer = null
    }
    this._clearFloatingIdleTimer()
    this._clearFloatingEntranceTimer()
  },

  _clearFloatingIdleTimer() {
    if (this._floatingIdleTimer) {
      clearTimeout(this._floatingIdleTimer)
      this._floatingIdleTimer = null
    }
  },

  _clearFloatingEntranceTimer() {
    if (this._floatingEntranceTimer) {
      clearTimeout(this._floatingEntranceTimer)
      this._floatingEntranceTimer = null
    }
  },

  _isFloatingPinned() {
    const data = this.data
    return !!(
      data.capabilityLoading ||
      data.countLoading ||
      data.submitting ||
      data.capabilityError ||
      data.countError ||
      data.submitError ||
      data.titleInputFocused ||
      data.pickerOpen
    )
  },

  _showFloatingAction(restartTimer = true) {
    if (this._pageDestroyed) return
    if (!this.data.floatingVisible) {
      this.setData({ floatingVisible: true })
    }
    if (restartTimer) this._restartFloatingIdleTimer()
  },

  _restartFloatingIdleTimer() {
    this._clearFloatingIdleTimer()
    if (this._pageDestroyed || this._isFloatingPinned()) return

    this._floatingIdleTimer = setTimeout(() => {
      this._floatingIdleTimer = null
      if (this._pageDestroyed) return
      if (this._isFloatingPinned()) {
        this._showFloatingAction(false)
        return
      }
      this.setData({ floatingVisible: false })
    }, 5000)
  },

  _syncFloatingAction() {
    if (this._pageDestroyed) return
    this._showFloatingAction(false)
    if (this._isFloatingPinned()) {
      this._clearFloatingIdleTimer()
    } else {
      this._restartFloatingIdleTimer()
    }
  },

  _registerInteraction() {
    this._showFloatingAction(true)
  },

  onConfigScroll() {
    // Every scroll event forces the action back into view and refreshes the
    // five-second inactivity window. The final event naturally starts the
    // countdown after scrolling stops.
    this._registerInteraction()
  },

  onPageInteraction() {
    this._registerInteraction()
  },

  onTitleFocus() {
    this.setData({ titleInputFocused: true }, () => this._syncFloatingAction())
  },

  onTitleBlur() {
    this.setData({ titleInputFocused: false }, () => this._syncFloatingAction())
  },

  onPickerOpen() {
    this.setData({ pickerOpen: true }, () => this._syncFloatingAction())
  },

  onPickerCancel() {
    this.setData({ pickerOpen: false }, () => this._syncFloatingAction())
  },

  async _checkCapabilities() {
    // Invalidate any in-flight count request before restarting capability
    // discovery so stale results cannot overwrite the new page state.
    this._previewRequestSeq += 1
    if (this._previewDebounceTimer) {
      clearTimeout(this._previewDebounceTimer)
      this._previewDebounceTimer = null
    }
    this.setData({
      capabilityLoading: true,
      capabilityError: '',
      submitError: '',
    }, () => this._syncFloatingAction())

    try {
      const cap = await exportApi.getCapabilities()
      if (this._pageDestroyed) return
      const wordDisabled = !cap.docx_enabled
      const wordTip = wordDisabled ? 'Word 导出暂未开放' : ''
      this.setData({
        wordDisabled,
        wordTip,
        _wsEnabled: cap.websocket_enabled,
        maxQuestionCount: cap.max_question_count || 100,
        capabilityLoading: false,
        capabilityError: '',
      }, () => this._syncFloatingAction())

      if (wordDisabled && this.data.format === 'docx') {
        this.setData({ format: 'pdf' })
      }
      this._schedulePreviewCount(true)
    } catch (e) {
      if (this._pageDestroyed) return
      // A capability endpoint failure must not leave the page permanently in
      // "checking" state. Continue in PDF-safe mode and try the actual count
      // endpoint; if the current selected range is known locally, it remains
      // exportable even while the lightweight warning is shown.
      const msg = exportApi.getExportCapabilityErrorMessage(e)
      const knownCount = this._knownRangeCount()
      this.setData({
        wordDisabled: true,
        wordTip: '能力检查失败，暂仅提供 PDF 导出',
        format: 'pdf',
        capabilityLoading: false,
        capabilityError: msg,
        countLoading: false,
        previewCount: knownCount !== null ? knownCount : this.data.previewCount,
        previewCountReady: knownCount !== null,
      }, () => {
        this._syncFloatingAction()
        this._schedulePreviewCount(true)
      })
    }
  },

  onRetryCapability() {
    this._registerInteraction()
    this._checkCapabilities()
  },

  onRetryPreviewCount() {
    this._registerInteraction()
    this._schedulePreviewCount(true)
  },

  // ── Navigation ──
  onBack() {
    const pages = getCurrentPages()
    const fallback = () => {
      wx.redirectTo({
        url: '/subpackages/study/wrong-book/wrong-book',
        fail: () => wx.reLaunch({ url: '/pages/home/home' }),
      })
    }

    if (pages && pages.length > 1) {
      wx.navigateBack({
        delta: 1,
        fail: fallback,
      })
      return
    }

    fallback()
  },

  // ── Range selection ──
  onRangeChange(e) {
    const value = e.detail && e.detail.value ? e.detail.value : e.currentTarget.dataset.value
    if (!value) return

    if (value === 'filtered' && !this.data.hasActiveFilters) {
      wx.showToast({ title: '当前没有筛选条件', icon: 'none' })
      return
    }
    if (value === 'selected' && !(this.data._selectedIds || []).length) {
      wx.showToast({ title: '当前没有已选错题', icon: 'none' })
      return
    }

    const selectedCount = value === 'selected'
      ? this._normalizeSelectedIds(this.data._selectedIds).length
      : null
    this.setData({
      rangeType: value,
      countError: '',
      submitError: '',
      previewCount: selectedCount !== null ? selectedCount : this.data.previewCount,
      previewCountReady: selectedCount !== null,
    }, () => {
      this._registerInteraction()
      this._schedulePreviewCount()
    })
  },

  // ── Format buttons use bindtap — read from dataset, not detail ──
  onFormatChange(e) {
    const value = e.currentTarget.dataset.value
    if (!value || (value === 'docx' && this.data.wordDisabled)) return
    this.setData({ format: value, submitError: '' }, () => this._registerInteraction())
  },

  // ── Title ──
  onTitleInput(e) {
    this.setData({ title: e.detail.value, submitError: '' }, () => this._registerInteraction())
  },

  // ── Sort: picker e.detail.value is an index into SORT_OPTIONS ──
  onSortChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = SORT_OPTIONS[idx]
    if (!option) return
    const next = {
      sortBy: option.value,
      sortByLabel: option.label,
      sortByIndex: idx,
      layoutPreset: 'custom',
      submitError: '',
      pickerOpen: false,
    }
    next.layoutSummary = this._buildLayoutSummary({ ...this.data, ...next })
    this.setData(next, () => this._registerInteraction())
  },

  // ── Group: picker e.detail.value is an index into GROUP_OPTIONS ──
  onGroupChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = GROUP_OPTIONS[idx]
    if (!option) return
    const next = {
      groupBy: option.value,
      groupByLabel: option.label,
      groupByIndex: idx,
      layoutPreset: 'custom',
      submitError: '',
      pickerOpen: false,
    }
    next.layoutSummary = this._buildLayoutSummary({ ...this.data, ...next })
    this.setData(next, () => this._registerInteraction())
  },

  // ── Answer position: picker e.detail.value is an index ──
  onAnswerPositionChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = POSITION_OPTIONS[idx]
    if (!option) return
    const next = {
      answerPosition: option.value,
      answerPositionLabel: option.label,
      answerPositionIndex: idx,
      layoutPreset: 'custom',
      submitError: '',
      pickerOpen: false,
    }
    next.layoutSummary = this._buildLayoutSummary({ ...this.data, ...next })
    this.setData(next, () => this._registerInteraction())
  },

  // ── Analysis position: picker e.detail.value is an index ──
  onAnalysisPositionChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = POSITION_OPTIONS[idx]
    if (!option) return
    const next = {
      analysisPosition: option.value,
      analysisPositionLabel: option.label,
      analysisPositionIndex: idx,
      layoutPreset: 'custom',
      submitError: '',
      pickerOpen: false,
    }
    next.layoutSummary = this._buildLayoutSummary({ ...this.data, ...next })
    this.setData(next, () => this._registerInteraction())
  },

  // ── Space style: picker e.detail.value is an index ──
  onSpaceChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = SPACE_OPTIONS[idx]
    if (!option) return
    const next = {
      spaceStyle: option.value,
      spaceStyleLabel: option.label,
      spaceStyleIndex: idx,
      layoutPreset: 'custom',
      submitError: '',
      pickerOpen: false,
    }
    next.layoutSummary = this._buildLayoutSummary({ ...this.data, ...next })
    this.setData(next, () => this._registerInteraction())
  },

  onPresetChange(e) {
    const value = e.currentTarget.dataset.value
    const preset = LAYOUT_PRESETS.find(item => item.value === value)
    if (!preset) return

    const sortByIndex = SORT_OPTIONS.findIndex(item => item.value === preset.sortBy)
    const groupByIndex = GROUP_OPTIONS.findIndex(item => item.value === preset.groupBy)
    const answerPositionIndex = POSITION_OPTIONS.findIndex(item => item.value === preset.answerPosition)
    const analysisPositionIndex = POSITION_OPTIONS.findIndex(item => item.value === preset.analysisPosition)
    const spaceStyleIndex = SPACE_OPTIONS.findIndex(item => item.value === preset.spaceStyle)
    const next = {
      layoutPreset: preset.value,
      sortBy: preset.sortBy,
      sortByLabel: SORT_OPTIONS[sortByIndex].label,
      sortByIndex,
      groupBy: preset.groupBy,
      groupByLabel: GROUP_OPTIONS[groupByIndex].label,
      groupByIndex,
      answerPosition: preset.answerPosition,
      answerPositionLabel: POSITION_OPTIONS[answerPositionIndex].label,
      answerPositionIndex,
      analysisPosition: preset.analysisPosition,
      analysisPositionLabel: POSITION_OPTIONS[analysisPositionIndex].label,
      analysisPositionIndex,
      spaceStyle: preset.spaceStyle,
      spaceStyleLabel: SPACE_OPTIONS[spaceStyleIndex].label,
      spaceStyleIndex,
      submitError: '',
    }
    next.layoutSummary = this._buildLayoutSummary(next)
    this.setData(next, () => this._registerInteraction())
  },

  // ── Preview count ──
  _schedulePreviewCount(immediate = false) {
    if (this._previewDebounceTimer) {
      clearTimeout(this._previewDebounceTimer)
      this._previewDebounceTimer = null
    }
    if (immediate) {
      this._updatePreviewCount()
      return
    }
    this._previewDebounceTimer = setTimeout(() => {
      this._previewDebounceTimer = null
      this._updatePreviewCount()
    }, 180)
  },

  async _updatePreviewCount() {
    const requestSeq = ++this._previewRequestSeq
    const hadReadyCount = !!this.data.previewCountReady
    this.setData({ countLoading: true, countError: '' }, () => this._syncFloatingAction())
    try {
      const params = this._buildRangeParams()
      const res = await exportApi.previewCount(params)
      if (requestSeq !== this._previewRequestSeq || this._pageDestroyed) return
      this.setData({
        previewCount: Number(res && res.count) || 0,
        previewCountReady: true,
        countLoading: false,
        countError: '',
      }, () => this._syncFloatingAction())
    } catch (err) {
      if (requestSeq !== this._previewRequestSeq || this._pageDestroyed) return
      const knownCount = this._knownRangeCount()
      const countReady = hadReadyCount || knownCount !== null
      this.setData({
        previewCount: knownCount !== null ? knownCount : this.data.previewCount,
        previewCountReady: countReady,
        countLoading: false,
        countError: (err && err.message) || '获取数量失败',
      }, () => this._syncFloatingAction())
    }
  },

  // ── Submit ──

  async onSubmit() {
    if (this.data.submitting || this._navigating) return
    if (this.data.capabilityLoading) return
    this._registerInteraction()

    if (!this.data.previewCountReady) {
      const msg = '请先完成题目数量计算'
      this.setData({ submitError: msg }, () => this._syncFloatingAction())
      wx.showToast({ title: msg, icon: 'none' })
      return
    }

    // Validate count
    const count = this.data.previewCount
    const max = this.data.maxQuestionCount || 100
    if (count === 0) {
      const msg = '没有可导出的错题'
      this.setData({ submitError: msg }, () => this._syncFloatingAction())
      wx.showToast({ title: msg, icon: 'none' })
      return
    }
    if (count > max) {
      const msg = '单次最多导出 ' + max + ' 道，请调整导出范围。'
      this.setData({ submitError: msg }, () => this._syncFloatingAction())
      wx.showToast({ title: msg, icon: 'none' })
      return
    }

    this.setData({ submitting: true, submitError: '' }, () => this._syncFloatingAction())

    try {
      const rangeParams = this._buildRangeParams()
      const params = {
        range_type: rangeParams.range_type,
        filters: rangeParams.filters,
        selected_ids: rangeParams.selected_ids,
        title: this.data.title || this.data.titleDefault,
        show_date: false,
        export_date: '',
        sort_by: this.data.sortBy,
        group_by: this.data.groupBy,
        answer_position: this.data.answerPosition,
        analysis_position: this.data.analysisPosition,
        space_style: this.data.spaceStyle,
        file_format: this.data.format,
      }

      const task = await exportApi.createExport(params)

      // Task created — reset submitting immediately, don't wait for file generation
      this.setData({ submitting: false }, () => this._syncFloatingAction())

      if (!task || !task.id) {
        throw new Error('导出任务创建成功，但未返回任务编号')
      }

      // Navigate to export records page with highlight
      this._navigating = true
      try {
        await this._navigateToRecords(task.id)
      } catch (navErr) {
        // Navigation failed — show fallback message
        wx.showToast({
          title: '导出任务已创建，可从「导出记录」中查看',
          icon: 'none',
        })
      } finally {
        this._navigating = false
      }
    } catch (err) {
      const msg = err.message || '创建导出任务失败'
      this.setData({ submitError: msg, submitting: false }, () => this._syncFloatingAction())
      wx.showToast({ title: msg, icon: 'none' })
    } finally {
      // Safety net: ensure submitting is reset regardless of path
      if (this.data.submitting) {
        this.setData({ submitting: false }, () => this._syncFloatingAction())
      }
    }
  },

  /**
   * Promise-based navigation. Tries navigateTo first; if the page stack is
   * full, falls back to redirectTo. Rejects only when both fail.
   */
  _navigateToRecords(taskId) {
    const url = `/subpackages/export/export-records/export-records?highlight=${taskId}`

    return new Promise((resolve, reject) => {
      wx.navigateTo({
        url,
        success: resolve,
        fail: () => {
          // Page stack may be full — try redirectTo as fallback
          wx.redirectTo({
            url,
            success: resolve,
            fail: () => reject(new Error('导航失败')),
          })
        },
      })
    })
  },

  // ── View records ──
  onViewRecords() {
    this._registerInteraction()
    wx.navigateTo({ url: '/subpackages/export/export-records/export-records' })
  },

  // ── Helpers ──
  _knownRangeCount() {
    if (this.data.rangeType !== 'selected') return null
    return this._normalizeSelectedIds(this.data._selectedIds).length
  },

  _normalizeSelectedIds(ids) {
    if (!Array.isArray(ids)) return []
    const seen = {}
    return ids.map(function(id) {
      const value = Number(id)
      return Number.isFinite(value) && value > 0 ? value : null
    }).filter(function(id) {
      if (!id || seen[id]) return false
      seen[id] = true
      return true
    })
  },

  _normalizeFilters(filters) {
    if (!filters || typeof filters !== 'object' || Array.isArray(filters)) {
      return null
    }

    const normalized = {}
    Object.keys(filters).forEach(function(key) {
      const value = filters[key]
      if (value === null || value === undefined || value === '') return
      if (Array.isArray(value) && value.length === 0) return
      if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0) return
      normalized[key] = value
    })
    return Object.keys(normalized).length ? normalized : null
  },

  _applyExportContext(context) {
    const data = context || {}
    const hasSelected = Object.prototype.hasOwnProperty.call(data, 'selectedIds')
    const hasFilters = Object.prototype.hasOwnProperty.call(data, 'filters')
    const selectedIds = hasSelected
      ? this._normalizeSelectedIds(data.selectedIds)
      : (this.data._selectedIds || [])
    const filters = hasFilters
      ? this._normalizeFilters(data.filters)
      : this.data.filters
    const hasActiveFilters = !!filters

    let rangeType = data.rangeType
    if (!['all', 'filtered', 'selected'].includes(rangeType)) {
      if (hasSelected && selectedIds.length) rangeType = 'selected'
      else if (hasFilters && hasActiveFilters) rangeType = 'filtered'
      else if (this.data.rangeType === 'selected' && !selectedIds.length) rangeType = 'all'
      else if (this.data.rangeType === 'filtered' && !hasActiveFilters) rangeType = 'all'
      else rangeType = this.data.rangeType || 'all'
    }
    if (rangeType === 'selected' && !selectedIds.length) rangeType = hasActiveFilters ? 'filtered' : 'all'
    if (rangeType === 'filtered' && !hasActiveFilters) rangeType = selectedIds.length ? 'selected' : 'all'

    const knownCount = rangeType === 'selected' ? selectedIds.length : null
    this.setData({
      _selectedIds: selectedIds,
      filters,
      hasActiveFilters,
      rangeType,
      countError: '',
      submitError: '',
      previewCount: knownCount !== null ? knownCount : this.data.previewCount,
      previewCountReady: knownCount !== null,
    }, () => {
      this._registerInteraction()
      this._schedulePreviewCount()
    })
  },

  _buildRangeParams() {
    const selectedIds = this._normalizeSelectedIds(this.data._selectedIds)
    const filters = this._normalizeFilters(this.data.filters)
    let rangeType = this.data.rangeType

    // Never send an invalid range to the API. With no active filters,
    // "current filtered result" is equivalent to all wrong questions.
    if (rangeType === 'filtered' && !filters) rangeType = 'all'
    if (rangeType === 'selected' && !selectedIds.length) {
      rangeType = filters ? 'filtered' : 'all'
    }

    return {
      range_type: rangeType,
      filters: rangeType === 'filtered' ? filters : null,
      selected_ids: rangeType === 'selected' ? selectedIds : null,
      title: '',
      show_date: false,
      export_date: '',
      sort_by: 'newest',
      group_by: 'question_type',
      answer_position: 'none',
      analysis_position: 'none',
      space_style: 'standard',
    }
  },

  _buildLayoutSummary(data) {
    const state = data || this.data
    const answer = state.answerPosition === 'at_end'
      ? '答案末尾'
      : (state.answerPosition === 'after_question' ? '答案逐题' : '不含答案')
    const analysis = state.analysisPosition === 'at_end'
      ? '解析末尾'
      : (state.analysisPosition === 'after_question' ? '解析逐题' : '不含解析')
    return [
      state.sortByLabel,
      state.groupByLabel + '分区',
      answer,
      analysis,
      state.spaceStyleLabel + '留白',
    ].join(' · ')
  },
})
