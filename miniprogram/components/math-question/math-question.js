Component({
  properties: {
    segments: { type: Array, value: [] }
  },
  data: {
    localSegments: []
  },
  observers: {
    'segments': function(val) {
      this.setData({
        localSegments: (val || []).map(function(s) {
          return Object.assign({}, s, { _error: false })
        })
      })
    }
  },
  attached: function() {
  },
  methods: {
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
