const api = require('../../utils/api')
const config = require('../../config')

Page({
  data: {
    batches: [],
    loading: false,
  },

  onShow() {
    this.loadBatches()
  },

  async loadBatches() {
    this.setData({ loading: true })
    try {
      const res = await api.get('/import/batches')
      this.setData({
        batches: (res.items || []).map(b => ({
          ...b,
          _date: b.created_at ? b.created_at.slice(0, 16) : '',
        })),
      })
    } catch (e) {
      console.error('加载批次列表失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  async chooseFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['xlsx', 'xls', 'pdf'],
      success: (res) => {
        const file = res.tempFiles[0]
        const name = file.name.toLowerCase()
        if (!name.endsWith('.xlsx') && !name.endsWith('.xls') && !name.endsWith('.pdf')) {
          wx.showToast({ title: '仅支持 .xlsx / .pdf 文件', icon: 'none' })
          return
        }
        this.uploadFile(file.path, file.name)
      },
      fail: () => {},
    })
  },

  async uploadFile(path, name) {
    wx.showLoading({ title: '上传解析中...' })
    try {
      const token = wx.getStorageSync('token')
      const res = await new Promise((resolve, reject) => {
        wx.uploadFile({
          url: `${require('../../config').BASE_URL}/import/upload`,
          filePath: path,
          name: 'file',
          header: { Authorization: `Bearer ${token}` },
          success: (r) => {
            let body = null
            try {
              body = JSON.parse(r.data)
            } catch (e) {
              console.error('解析上传响应失败', e, 'status=', r.statusCode, 'raw=', r.data)
              const preview = (r.data || '').toString().slice(0, 120)
              return reject(new Error(`服务器返回非 JSON (HTTP ${r.statusCode})：${preview}`))
            }
            if (r.statusCode >= 400) {
              return reject(new Error(body.detail || body.message || `HTTP ${r.statusCode}`))
            }
            resolve(body)
          },
          fail: reject,
        })
      })
      wx.hideLoading()
      wx.showToast({ title: `导入 ${res.total} 道题成功`, icon: 'none' })
      this.loadBatches()
    } catch (err) {
      wx.hideLoading()
      wx.showModal({
        title: '上传失败',
        content: err.message || '未知错误',
        showCancel: false,
      })
    }
  },

  goBatch(e) {
    const batchId = e.currentTarget.dataset.batchId
    wx.navigateTo({ url: `/pages/import-batch/import-batch?batchId=${batchId}` })
  },

  async downloadTemplate() {
    wx.showLoading({ title: '下载模板中...' })
    try {
      const token = wx.getStorageSync('token')
      const res = await new Promise((resolve, reject) => {
        wx.downloadFile({
          url: `${config.BASE_URL}/import/template`,
          header: { Authorization: `Bearer ${token}` },
          success: resolve,
          fail: reject,
        })
      })
      if (res.statusCode !== 200) throw new Error('下载失败')
      await wx.openDocument({ filePath: res.tempFilePath, fileType: 'xlsx' })
      wx.hideLoading()
    } catch (err) {
      wx.hideLoading()
      wx.showToast({ title: '下载失败', icon: 'none' })
    }
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || '-'
  },
})
