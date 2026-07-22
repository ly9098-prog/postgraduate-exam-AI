Component({
  properties: {
    segments: { type: Array, value: [] }
  },
  data: {
    localSegments: []
  },
  observers: {
    'segments': function(val) {
      var arr = this._normalizeSegments(val)
      this.setData({
        localSegments: arr
      })
    }
  },
  attached: function() {
  },
  methods: {
    _normalizeSegments: function(val) {
      if (!Array.isArray(val)) {
        if (typeof val !== 'undefined' && val !== null) {
          this._devWarn('segments expected array, got ' + typeof val)
        }
        return []
      }
      var result = []
      for (var i = 0; i < val.length; i++) {
        var s = val[i]
        if (!s || typeof s !== 'object' || Array.isArray(s)) {
          this._devWarn('segment[' + i + '] is not an object, skipped')
          continue
        }
        result.push(Object.assign({}, s, { _error: false }))
      }
      return result
    },
    _devWarn: function(msg) {
      try {
        var app = getApp()
        if (app && app.globalData && app.globalData.DEV) {
          console.warn('[math-question] ' + msg)
        }
      } catch (_) {}
    },
    onImgError: function(e) {
      var index = e.currentTarget.dataset.index
      var key = 'localSegments[' + index + ']._error'
      var update = {}
      update[key] = true
      this.setData(update)
    },
    onImageTap: function(e) {
      var index = e.currentTarget.dataset.index
      var segs = this.data.localSegments || []
      // Collect all visual image URLs for preview
      var urls = []
      var currentUrl = ''
      for (var i = 0; i < segs.length; i++) {
        var s = segs[i]
        if (s.type === 'image' || s.type === 'math_image' || s.type === 'table_image' || s.type === 'code_image') {
          if (s.url && !s._error) {
            urls.push(s.url)
            if (i === index) currentUrl = s.url
          }
        }
      }
      if (currentUrl && urls.length > 0) {
        wx.previewImage({ current: currentUrl, urls: urls })
      }
    }
  }
})
