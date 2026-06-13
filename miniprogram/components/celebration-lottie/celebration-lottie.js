Component({
  properties: {
    show: { type: Boolean, value: false },
    type: { type: String, value: 'steady' },
    title: { type: String, value: '' },
    detail: { type: String, value: '' },
    motto: { type: String, value: '' },
    rewardText: { type: String, value: '' },
    progressText: { type: String, value: '' },
    growthLevel: { type: String, value: '' },
    growthLevelPct: { type: Number, value: 0 },
    growthDesc: { type: String, value: '' },
    duration: { type: Number, value: 2800 },
    gifSrc: { type: String, value: '' },
    pngSrc: { type: String, value: '' },
    enableLottie: { type: Boolean, value: false },
  },

  methods: {
    onDone: function () {
      this.triggerEvent('done')
    },
  },
})
