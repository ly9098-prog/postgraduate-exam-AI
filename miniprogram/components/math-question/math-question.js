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
  methods: {
    onImgError: function(e) {
      var index = e.currentTarget.dataset.index
      var key = 'localSegments[' + index + ']._error'
      var update = {}
      update[key] = true
      this.setData(update)
    }
  }
})
