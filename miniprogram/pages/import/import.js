const api = require('../../utils/api')
const config = require('../../config')
const auth = require('../../utils/auth')
const fileReq = require('../../utils/file-request')

const SUPPORTED_EXTENSIONS = ['xlsx', 'xls', 'pdf', 'txt', 'jpg', 'jpeg', 'png', 'webp']
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']

const STATUS_LABELS = {
  queued: '排队中',
  parsing: '解析中',
  processing: '处理中',
  ocr_running: 'OCR识别中',
  running: '处理中',
  paused: '部分失败，可恢复',
  completed: '已完成',
  failed: '失败',
}

const STAGE_LABELS = {
  extract: '文本提取',
  normalize_text: '文本清洗',
  ocr_correction: 'OCR纠错',
  analyze_structure: '结构分析',
  classify_pages: '页面分类',
  split: '题目切分',
  match: '答案匹配',
  normalize_schema: '格式标准化',
  batch_validation: '批量校验',
  batch_dedup: '去重检查',
  repair: 'AI修复',
  ai_validation: 'AI验证',
  similarity_match: '相似匹配',
  review: '入库整理',
}

function getExtension(name) {
  if (!name) return ''
  const parts = name.split('.')
  return parts.length > 1 ? parts.pop().toLowerCase() : ''
}

Page({
  data: {
    loading: false,
    error: '',
    pipelineTask: null,
    pipelinePolling: false,
    pipelinePollError: '',
    uploading: false,
    importStatus: '',
    showPageRange: false,
    pageStart: '',
    pageEnd: '',
  },

  onLoad() {
    // 管理员权限校验
    if (!auth.requireAdminAccess()) {
      // 未登录时 requireAdminAccess 已触发跳转登录页；
      // 非管理员用户则主动跳回首页
      if (auth.isLoggedIn()) {
        wx.reLaunch({ url: '/pages/home/home' })
      }
      return
    }
    this._adminChecked = true
    this._alive = true
    this._visible = true
    this._pollGeneration = 0
    this.initPage()
  },

  initPage() {
    // 页面初始化逻辑（当前为空，保留扩展点）
  },

  onShow() {
    // 页面显示时重新校验管理员身份
    if (this._adminChecked && !auth.isAdmin()) {
      wx.showToast({ title: '权限不足', icon: 'none' })
      setTimeout(() => wx.reLaunch({ url: '/pages/home/home' }), 500)
      return
    }
    this._visible = true
    const task = this.data.pipelineTask
    if (task && task.pipeline_id && this.data.pipelinePolling) {
      this.pollPipeline(task.pipeline_id)
    }
  },

  onUnload() {
    this._alive = false
    this._visible = false
    this._pollGeneration++
    if (this.pollTimer) clearTimeout(this.pollTimer)
  },

  onHide() {
    this._visible = false
    this._pollGeneration++
    if (this.pollTimer) clearTimeout(this.pollTimer)
  },

  onPullDownRefresh() {
    wx.stopPullDownRefresh()
  },

  chooseFile() {
    wx.showActionSheet({
      itemList: ['从聊天记录选文件', '拍照/相册选图片'],
      success: (res) => {
        if (res.tapIndex === 0) {
          this.pickFromMessage()
        } else if (res.tapIndex === 1) {
          this.pickImage()
        }
      },
    })
  },

  pickFromMessage() {
    if (!wx.chooseMessageFile) {
      wx.showModal({
        title: '提示',
        content: '当前微信版本不支持文件选择，请升级微信',
        showCancel: false,
      })
      return
    }
    wx.chooseMessageFile({
      count: 1,
      type: 'all',
      success: (res) => {
        const file = res.tempFiles[0]
        if (!file) return
        const name = (file.name || '').toLowerCase()
        const ext = getExtension(name)
        if (!SUPPORTED_EXTENSIONS.includes(ext)) {
          wx.showToast({ title: '不支持该格式，仅支持 xlsx/pdf/txt/jpg/png/webp', icon: 'none' })
          return
        }
        this.setData({ showPageRange: ext === 'pdf' })
        if (ext === 'pdf') {
          this.setData({ _pendingFile: { path: file.path, name: file.name || name, size: file.size } })
        } else {
          this.unifiedUpload({ path: file.path, name: file.name || name, size: file.size })
        }
      },
      fail: (err) => {
        if (err && err.errMsg && err.errMsg.includes('cancel')) return
        wx.showToast({ title: '选择文件失败', icon: 'none' })
      },
    })
  },

  pickImage() {
    if (wx.chooseMedia) {
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album', 'camera'],
        success: (res) => {
          const file = res.tempFiles && res.tempFiles[0]
          if (!file) return
          this.unifiedUpload({ path: file.tempFilePath, name: 'photo.jpg', size: file.size })
        },
        fail: (err) => {
          if (err && err.errMsg && err.errMsg.includes('cancel')) return
          wx.showToast({ title: '选择图片失败', icon: 'none' })
        },
      })
      return
    }
    if (!wx.chooseMessageFile) {
      wx.showModal({
        title: '提示',
        content: '当前微信版本不支持图片选择，请升级微信',
        showCancel: false,
      })
      return
    }
    wx.chooseMessageFile({
      count: 1,
      type: 'image',
      success: (res) => {
        const file = res.tempFiles[0]
        if (!file) return
        this.unifiedUpload({ path: file.path, name: file.name || 'image.jpg', size: file.size })
      },
      fail: (err) => {
        if (err && err.errMsg && err.errMsg.includes('cancel')) return
        wx.showToast({ title: '选择图片失败', icon: 'none' })
      },
    })
  },

  async unifiedUpload(fileInfo) {
    var path = fileInfo.path
    var name = fileInfo.name || ''
    var size = fileInfo.size
    var mimeType = fileInfo.mimeType || ''

    const ps = parseInt(this.data.pageStart, 10)
    const pe = parseInt(this.data.pageEnd, 10)
    if (this.data.pageStart && (isNaN(ps) || ps < 1)) {
      wx.showToast({ title: '起始页必须为正整数', icon: 'none' })
      return
    }
    if (this.data.pageEnd && (isNaN(pe) || pe < 1)) {
      wx.showToast({ title: '结束页必须为正整数', icon: 'none' })
      return
    }
    if (ps && pe && pe < ps) {
      wx.showToast({ title: '结束页不能小于起始页', icon: 'none' })
      return
    }

    // 文件校验（传递 size 让 validateFile 检查文件大小）
    const validation = fileReq.validateFile({ name, path, size })
    if (!validation.valid) {
      wx.showToast({ title: validation.error, icon: 'none' })
      return
    }

    wx.showLoading({ title: '上传中...' })
    try {
      let uploadUrl = `${config.BASE_URL}/import/pipeline/upload`
      const params = []
      if (this.data.pageStart) params.push(`page_start=${this.data.pageStart}`)
      if (this.data.pageEnd) params.push(`page_end=${this.data.pageEnd}`)
      if (params.length) uploadUrl += '?' + params.join('&')
      const res = await fileReq.authUploadFile({
        url: uploadUrl,
        filePath: path,
        name: 'file',
      })
      wx.hideLoading()
      this.setData({
        pipelineTask: {
          pipeline_id: res.pipeline_id,
          status: res.status || 'parsing',
          source_type: res.source_type || '',
          raw_text_preview: '',
          errors: [],
          error_message: '',
          source_file: name,
        },
        pipelinePolling: true,
        showPageRange: false,
        pageStart: '',
        pageEnd: '',
        _pendingFile: null,
      })
      this.pollPipeline(res.pipeline_id)
    } catch (err) {
      wx.hideLoading()
      wx.showModal({
        title: '上传失败',
        content: err.message || '未知错误',
        showCancel: false,
      })
    }
  },

  onPageStartInput(e) {
    this.setData({ pageStart: e.detail.value })
  },

  onPageEndInput(e) {
    this.setData({ pageEnd: e.detail.value })
  },

  confirmUpload() {
    const f = this.data._pendingFile
    if (!f) return
    this.unifiedUpload({ path: f.path, name: f.name, size: f.size })
  },

  async pollPipeline(pipelineId) {
    if (!pipelineId) return
    if (!this._alive || !this._visible) return
    if (this.pollTimer) clearTimeout(this.pollTimer)
    const generation = ++this._pollGeneration
    try {
      const status = await api.get(`/import/pipelines/${pipelineId}`)
      if (!this._alive || !this._visible || generation !== this._pollGeneration) return
      this._pollRetries = 0
      const currentTask = this.data.pipelineTask || {}
      if (currentTask.pipeline_id !== pipelineId) return
      const errors = status.errors || []

      // Compute stage progress
      const stages = status.stages || {}
      const stageKeys = Object.keys(stages)
      const totalStages = stageKeys.length
      const completedStages = stageKeys.filter(k => stages[k].status === 'completed').length
      const currentStage = status.current_stage || ''
      let progressPercent = totalStages > 0 ? Math.round((completedStages / totalStages) * 100) : 0

      // P2-6: chunked PDF imports surface chunk_progress; prefer it over
      // stage-derived percent so the bar reflects per-chunk completion on
      // long imports (400+ pages).
      const chunkProgress = status.chunk_progress || null
      let chunkProgressText = ''
      let failedChunkDetails = []
      if (chunkProgress && chunkProgress.total_chunks > 0) {
        const total = chunkProgress.total_chunks
        const done = chunkProgress.completed_chunks || 0
        const failed = chunkProgress.failed_chunks || 0
        progressPercent = Math.min(100, Math.round((done / total) * 100))
        chunkProgressText = `分块进度 ${done}/${total}`
        if (failed > 0) chunkProgressText += `（${failed} 个失败）`
        failedChunkDetails = chunkProgress.failed_chunk_details || []
      }

      // When inside extract stage with OCR progress, show partial progress
      const ocrProgress = status.ocr_progress || ''
      let ocrProgressText = ''
      if (ocrProgress) {
        const m = ocrProgress.match(/(\d+)\/(\d+)/)
        if (m) {
          const done = parseInt(m[1], 10)
          const total = parseInt(m[2], 10)
          ocrProgressText = `OCR识别中 ${done}/${total} 页`
          if (!chunkProgress && (totalStages === 0 || (progressPercent === 0 && total > 0))) {
            progressPercent = Math.max(1, Math.round((done / total) * 50))
          }
        }
      } else if (currentStage === 'extract' && progressPercent === 0) {
        ocrProgressText = '文件预处理中...'
        progressPercent = 1
      }

      // Build stage list for UI
      const stageList = stageKeys.map(k => ({
        key: k,
        label: STAGE_LABELS[k] || k,
        status: stages[k].status || 'pending',
      }))

      // Elapsed time
      let elapsed = ''
      if (status.started_at) {
        const startedMs = new Date(status.started_at).getTime()
        if (Number.isFinite(startedMs)) {
          const diffSec = Math.max(0, Math.floor((Date.now() - startedMs) / 1000))
          const min = Math.floor(diffSec / 60)
          const sec = diffSec % 60
          elapsed = min > 0 ? `${min}分${sec}秒` : `${sec}秒`
        } else {
          elapsed = '--'
        }
      }

      const isPaused = status.status === 'paused'
      const totalQuestionCount = (chunkProgress && chunkProgress.question_count) ||
        status.question_count || (status.stats && status.stats.to_review) || 0
      const task = {
        ...currentTask,
        ...status,
        errors,
        error_message: errors[0] || '',
        raw_text_preview: (status.raw_text_preview || '').slice(0, 200),
        question_count: totalQuestionCount,
        statusLabel: STATUS_LABELS[status.status] || status.status,
        currentStageLabel: chunkProgressText || ocrProgressText ||
          STAGE_LABELS[currentStage] || currentStage || '准备中',
        progressPercent,
        stageList,
        elapsed,
        ocr_progress: ocrProgressText,
        chunk_progress: chunkProgress,
        failed_chunk_details: failedChunkDetails,
      }
      const isTerminal = ['completed', 'failed', 'paused'].includes(task.status)
      this.setData({ pipelineTask: task, pipelinePolling: !isTerminal })
      if (task.status === 'completed') {
        wx.showToast({ title: `导入完成，共解析 ${task.question_count || 0} 题`, icon: 'none' })
        return
      }
      if (task.status === 'failed') {
        wx.showModal({
          title: '导入失败',
          content: task.error_message || '解析失败',
          showCancel: false,
        })
        return
      }
      if (isPaused) {
        wx.showModal({
          title: '导入中断',
          content: '导入中断，可选择原 PDF 恢复导入，或重新上传开始新的导入。',
          confirmText: '我知道了',
          showCancel: false,
        })
        return
      }
      this.pollTimer = setTimeout(() => this.pollPipeline(pipelineId), 2000)
    } catch (e) {
      console.error('查询导入状态失败', e)
      const retries = (this._pollRetries || 0) + 1
      if (retries < 3) {
        this._pollRetries = retries
        this.pollTimer = setTimeout(() => this.pollPipeline(pipelineId), 3000)
      } else {
        this._pollRetries = 0
        this.setData({ pipelinePolling: false, pipelinePollError: '网络异常，进度查询已暂停' })
      }
    }
  },

  resumePipeline() {
    const pipelineId = this.data.pipelineTask && this.data.pipelineTask.pipeline_id
    if (!pipelineId) {
      wx.showToast({ title: '缺少导入任务ID', icon: 'none' })
      return
    }
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf'],
      success: (res) => {
        const file = res.tempFiles && res.tempFiles[0]
        if (!file || !file.path) {
          wx.showToast({ title: '未选择文件', icon: 'none' })
          return
        }
        this.uploadResumeFile(pipelineId, file.path)
      },
      fail: () => {},
    })
  },

  async uploadResumeFile(pipelineId, filePath) {
    this.setData({ uploading: true, importStatus: 'resuming' })
    try {
      const data = await fileReq.authUploadFile({
        url: `${config.BASE_URL}/import/pipelines/${pipelineId}/resume`,
        filePath,
        name: 'file',
      })
      wx.showToast({ title: '已恢复导入', icon: 'success' })
      this.setData({
        uploading: false,
        pipelineId,
        importStatus: data.status || 'processing',
      })
      this.startPolling(pipelineId)
    } catch (e) {
      wx.showToast({ title: e.message || '恢复失败', icon: 'none' })
      this.setData({ uploading: false })
    }
  },

  startPolling(pipelineId) {
    this._pollRetries = 0
    this.setData({ pipelinePolling: true, pipelinePollError: '' })
    this.pollPipeline(pipelineId)
  },

  resumePipelinePolling() {
    const id = this.data.pipelineTask && this.data.pipelineTask.pipeline_id
    if (!id) return
    this._pollRetries = 0
    this.setData({ pipelinePolling: true, pipelinePollError: '' })
    this.pollPipeline(id)
  },

  async downloadTemplate() {
    wx.showLoading({ title: '下载模板中...' })
    try {
      const res = await fileReq.authDownloadFile({
        url: `${config.BASE_URL}/import/template`,
      })
      if (res.statusCode !== 200) throw new Error('下载失败')
      await wx.openDocument({ filePath: res.tempFilePath, fileType: 'xlsx' })
      wx.hideLoading()
    } catch (err) {
      wx.hideLoading()
      wx.showToast({ title: err.message || '下载失败', icon: 'none' })
    }
  },
})
