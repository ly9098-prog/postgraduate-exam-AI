/**
 * Export configuration page — range, format, title, date, answer/analysis, sort, group, space.
 */
const exportApi = require('../../services/export')
const api = require('../../utils/api')

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

Page({
  data: {
    // Expose options to WXML (cannot use require or global vars in WXML)
    SORT_OPTIONS: SORT_OPTIONS,
    GROUP_OPTIONS: GROUP_OPTIONS,
    SPACE_OPTIONS: SPACE_OPTIONS,
    POSITION_OPTIONS: POSITION_OPTIONS,

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

    // Date
    showDate: true,
    exportDate: '',

    // Sort & Group
    sortBy: 'newest',
    sortByLabel: '加入时间最新优先',
    sortByIndex: 0,
    groupBy: 'none',
    groupByLabel: '连续排列',
    groupByIndex: 0,

    // Answer & Analysis
    answerPosition: 'none',
    answerPositionLabel: '不打印',
    answerPositionIndex: 0,
    analysisPosition: 'none',
    analysisPositionLabel: '不打印',
    analysisPositionIndex: 0,

    // Space
    spaceStyle: 'standard',
    spaceStyleLabel: '标准',
    spaceStyleIndex: 1,

    // Preview count
    previewCount: 0,
    countLoading: false,
    countError: '',

    // Submit
    submitting: false,
    submitError: '',

    // Capability
    _exportEnabled: false,
    _wsEnabled: false,
    capabilityLoading: true,
    capabilityError: '',
    maxQuestionCount: 100,
  },

  // Non-reactive fields
  _navigating: false,

  onShow() {
    // Reset transient state when returning from export records page
    this._navigating = false
    if (this.data.submitting) {
      this.setData({ submitting: false })
    }
  },

  onUnload() {
    // Clean up transient state — do NOT cancel back-end export tasks
    this._navigating = false
  },

  async onLoad(options) {
    // Recover selected IDs / active filters from the opener. Context can
    // arrive after onLoad, so every update also refreshes preview count once
    // export capability is ready.
    const eventChannel = this.getOpenerEventChannel()
    if (eventChannel) {
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

    // Set default date
    const today = this._formatDate(new Date())
    this.setData({ exportDate: today })

    // Auto-generate title from subjects
    this._autoGenerateTitle()

    // Check capabilities first, then preview only if export is enabled
    await this._checkCapabilities()
  },

  async _checkCapabilities() {
    this.setData({ capabilityLoading: true, capabilityError: '' })
    try {
      const cap = await exportApi.getCapabilities()
      const wordDisabled = !cap.docx_enabled
      const wordTip = wordDisabled ? 'Word 导出暂未开放' : ''
      const exportEnabled = cap.export_enabled !== false
      this.setData({
        wordDisabled,
        wordTip,
        _wsEnabled: cap.websocket_enabled,
        _exportEnabled: exportEnabled,
        maxQuestionCount: cap.max_question_count || 100,
        capabilityLoading: false,
        capabilityError: '',
      })
      // If docx is disabled and currently selected, switch to pdf
      if (wordDisabled && this.data.format === 'docx') {
        this.setData({ format: 'pdf' })
      }
      if (!exportEnabled) {
        const msg = exportApi.getExportCapabilityErrorMessage(null, cap)
        this.setData({ capabilityError: msg })
        return
      }
      // Capability OK — now load preview count
      this._updatePreviewCount()
    } catch (e) {
      // Capability check failed — safe degrade
      const msg = exportApi.getExportCapabilityErrorMessage(e, null)
      this.setData({
        wordDisabled: true,
        _exportEnabled: false,
        capabilityLoading: false,
        capabilityError: msg,
        countLoading: false,
        previewCount: 0,
      })
    }
  },

  onRetryCapability() {
    this._checkCapabilities()
  },

  // ── Navigation ──
  onBack() {
    const pages = getCurrentPages()
    const fallback = () => {
      wx.redirectTo({
        url: '/pages/wrong-book/wrong-book',
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

    this.setData({ rangeType: value, countError: '' }, () => {
      if (this.data._exportEnabled) {
        this._updatePreviewCount()
      }
    })
  },

  // ── Format buttons use bindtap — read from dataset, not detail ──
  onFormatChange(e) {
    const value = e.currentTarget.dataset.value
    if (!value || (value === 'docx' && this.data.wordDisabled)) return
    this.setData({ format: value })
  },

  // ── Title ──
  onTitleInput(e) {
    this.setData({ title: e.detail.value })
  },

  // ── Date ──
  onDateToggle(e) {
    this.setData({ showDate: !!(e.detail && e.detail.value) })
  },

  onDateChange(e) {
    this.setData({ exportDate: e.detail.value })
  },

  // ── Sort: picker e.detail.value is an index into SORT_OPTIONS ──
  onSortChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = SORT_OPTIONS[idx]
    if (!option) return
    this.setData({ sortBy: option.value, sortByLabel: option.label, sortByIndex: idx })
  },

  // ── Group: picker e.detail.value is an index into GROUP_OPTIONS ──
  onGroupChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = GROUP_OPTIONS[idx]
    if (!option) return
    this.setData({ groupBy: option.value, groupByLabel: option.label, groupByIndex: idx })
  },

  // ── Answer position: picker e.detail.value is an index ──
  onAnswerPositionChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = POSITION_OPTIONS[idx]
    if (!option) return
    this.setData({ answerPosition: option.value, answerPositionLabel: option.label, answerPositionIndex: idx })
  },

  // ── Analysis position: picker e.detail.value is an index ──
  onAnalysisPositionChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = POSITION_OPTIONS[idx]
    if (!option) return
    this.setData({ analysisPosition: option.value, analysisPositionLabel: option.label, analysisPositionIndex: idx })
  },

  // ── Space style: picker e.detail.value is an index ──
  onSpaceChange(e) {
    const idx = parseInt(e.detail.value, 10)
    const option = SPACE_OPTIONS[idx]
    if (!option) return
    this.setData({ spaceStyle: option.value, spaceStyleLabel: option.label, spaceStyleIndex: idx })
  },

  // ── Preview count ──
  async _updatePreviewCount() {
    if (!this.data._exportEnabled) return
    this.setData({ countLoading: true, countError: '' })
    try {
      const params = this._buildRangeParams()
      const res = await exportApi.previewCount(params)
      this.setData({
        previewCount: res.count || 0,
        countLoading: false,
      })
    } catch (err) {
      this.setData({
        countLoading: false,
        countError: err.message || '获取数量失败',
        previewCount: -1,
      })
    }
  },

  // ── Submit ──

  async onSubmit() {
    if (this.data.submitting || this._navigating) return
    if (this.data.capabilityLoading) return
    if (!this.data._exportEnabled) return

    // Validate count
    const count = this.data.previewCount
    const max = this.data.maxQuestionCount || 100
    if (count === 0) {
      wx.showToast({ title: '没有可导出的错题', icon: 'none' })
      return
    }
    if (count > max) {
      wx.showToast({ title: '单次最多导出 ' + max + ' 道，请调整导出范围。', icon: 'none' })
      return
    }

    this.setData({ submitting: true, submitError: '' })

    try {
      const rangeParams = this._buildRangeParams()
      const params = {
        range_type: rangeParams.range_type,
        filters: rangeParams.filters,
        selected_ids: rangeParams.selected_ids,
        title: this.data.title || this.data.titleDefault,
        show_date: this.data.showDate,
        export_date: this.data.showDate ? this.data.exportDate : '',
        sort_by: this.data.sortBy,
        group_by: this.data.groupBy,
        answer_position: this.data.answerPosition,
        analysis_position: this.data.analysisPosition,
        space_style: this.data.spaceStyle,
        file_format: this.data.format,
      }

      const task = await exportApi.createExport(params)

      // Task created — reset submitting immediately, don't wait for file generation
      this.setData({ submitting: false })

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
      this.setData({ submitError: msg, submitting: false })
      wx.showToast({ title: msg, icon: 'none' })
    } finally {
      // Safety net: ensure submitting is reset regardless of path
      if (this.data.submitting) {
        this.setData({ submitting: false })
      }
    }
  },

  /**
   * Promise-based navigation. Tries navigateTo first; if the page stack is
   * full, falls back to redirectTo. Rejects only when both fail.
   */
  _navigateToRecords(taskId) {
    const url = `/pages/export-records/export-records?highlight=${taskId}`

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
    wx.navigateTo({ url: '/pages/export-records/export-records' })
  },

  // ── Helpers ──
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

    this.setData({
      _selectedIds: selectedIds,
      filters,
      hasActiveFilters,
      rangeType,
      countError: '',
    }, () => {
      if (this.data._exportEnabled) this._updatePreviewCount()
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
      show_date: true,
      export_date: '',
      sort_by: 'newest',
      group_by: 'none',
      answer_position: 'none',
      analysis_position: 'none',
      space_style: 'standard',
    }
  },

  _formatDate(date) {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  },

  async _autoGenerateTitle() {
    // Try to get subjects from the resolved questions
    try {
      const params = this._buildRangeParams()
      // We need an API that returns subject context for the title
      // For now, the default title will be set server-side
      // Client can optionally fetch subjects from existing endpoint
    } catch (e) {
      // Ignore — server will use default title logic
    }
  },
})
