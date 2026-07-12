Component({
  properties: {
    card: { type: Object, value: {} },
    graphImageUrl: { type: String, value: '' },
  },

  data: {
    showSymbolNotes: false,
    showSecondary: false,
    showErrorTips: false,
    showExamples: false,
  },

  methods: {
    toggleSection(e) {
      const key = e.currentTarget.dataset.key
      this.setData({ [key]: !this.data[key] })
    },

    previewGraph() {
      const url = this.data.graphImageUrl
      if (url) {
        wx.previewImage({ urls: [url] })
      }
    },
  },
})
