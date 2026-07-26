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
    // Navigation context
    _selectedIds: [],

    // Range
    rangeType: 'selected', // 'all' | 'filtered' | 'selected'
    filters: null,
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
    groupBy: 'none',

    // Answer & Analysis
    answerPosition: 'none',
    analysisPosition: 'none',

    // Space
    spaceStyle: 'standard',

    // Preview count
    previewCount: 0,
    countLoading: false,
    countError: '',

    // Submit
    submitting: false,
    submitError: '',
  },

  onLoad(options) {
    // Recover selected IDs from page data or global state
    const eventChannel = this.getOpenerEventChannel()
    if (eventChannel) {
      eventChannel.on('acceptDataFromOpenerPage', (data) => {
        if (data && data.selectedIds) {
          this.setData({ _selectedIds: data.selectedIds })
        }
        if (data && data.filters) {
          this.setData({ filters: data.filters, rangeType: 'filtered' })
        }
      })
    }

    // Also try to get from app global data
    const app = getApp()
    const globalData = app.getGlobalData && app.getGlobalData()
    if (globalData && globalData.exportSelectedIds) {
      this.setData({ _selectedIds: globalData.exportSelectedIds })
      // Clear after reading
      globalData.exportSelectedIds = null
    }

    // Set default date
    const today = this._formatDate(new Date())
    this.setData({ exportDate: today })

    // Auto-generate title from subjects
    this._autoGenerateTitle()

    // Preview count
    this._updatePreviewCount()
  },

  onUnload() {
    // Stop any pending operations
  },

  // ── Range selection ──
  onRangeChange(e) {
    const value = e.detail && e.detail.value ? e.detail.value : e.currentTarget.dataset.value
    if (!value) return
    this.setData({ rangeType: value, countError: '' }, () => {
      this._updatePreviewCount()
    })
  },

  // ── Format selection ──
  onFormatChange(e) {
    const value = e.detail.value
    this.setData({ format: value })
  },

  // ── Title ──
  onTitleInput(e) {
    this.setData({ title: e.detail.value })
  },

  // ── Date ──
  onDateToggle() {
    this.setData({ showDate: !this.data.showDate })
  },

  onDateChange(e) {
    this.setData({ exportDate: e.detail.value })
  },

  // ── Sort ──
  onSortChange(e) {
    this.setData({ sortBy: e.detail.value })
  },

  // ── Group ──
  onGroupChange(e) {
    this.setData({ groupBy: e.detail.value })
  },

  // ── Answer position ──
  onAnswerPositionChange(e) {
    this.setData({ answerPosition: e.detail.value })
  },

  // ── Analysis position ──
  onAnalysisPositionChange(e) {
    this.setData({ analysisPosition: e.detail.value })
  },

  // ── Space style ──
  onSpaceChange(e) {
    this.setData({ spaceStyle: e.detail.value })
  },

  // ── Preview count ──
  async _updatePreviewCount() {
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
    if (this.data.submitting) return

    // Validate count
    const count = this.data.previewCount
    if (count === 0) {
      wx.showToast({ title: '没有可导出的错题', icon: 'none' })
      return
    }
    if (count > 100) {
      wx.showToast({ title: '单次最多导出 100 道，请调整导出范围。', icon: 'none' })
      return
    }

    this.setData({ submitting: true, submitError: '' })

    try {
      const params = {
        range_type: this.data.rangeType,
        filters: this.data.filters,
        selected_ids: this.data._selectedIds || [],
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

      wx.showToast({ title: '导出任务已创建', icon: 'success' })

      // Navigate to export records
      wx.navigateTo({
        url: '/pages/export-records/export-records?highlight=' + task.id,
      })
    } catch (err) {
      const msg = err.message || '创建导出任务失败'
      this.setData({ submitError: msg, submitting: false })
      wx.showToast({ title: msg, icon: 'none' })
    }
  },

  // ── View records ──
  onViewRecords() {
    wx.navigateTo({ url: '/pages/export-records/export-records' })
  },

  // ── Helpers ──
  _buildRangeParams() {
    const params = {
      range_type: this.data.rangeType,
      filters: null,
      selected_ids: null,
      title: '',
      show_date: true,
      export_date: '',
      sort_by: 'newest',
      group_by: 'none',
      answer_position: 'none',
      analysis_position: 'none',
      space_style: 'standard',
    }
    if (this.data.rangeType === 'filtered' && this.data.filters) {
      params.filters = this.data.filters
    }
    if (this.data.rangeType === 'selected') {
      params.selected_ids = this.data._selectedIds || []
    }
    return params
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
