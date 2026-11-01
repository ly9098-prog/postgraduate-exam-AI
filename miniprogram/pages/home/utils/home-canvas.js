function drawSubjectPie() {
  const subjectPieData = Array.isArray(this.data.subjectPieData) ? this.data.subjectPieData : []
  if (!subjectPieData.length) return
  const query = wx.createSelectorQuery().in(this)
  query.select('#subject-pie-canvas').boundingClientRect((rect) => {
    if (!rect || !rect.width || !rect.height) return
    const canvasSize = Math.min(rect.width, rect.height)
    const ctx = wx.createCanvasContext('subject-pie-canvas', this)
    const center = canvasSize / 2
    const radius = center - 10
    ctx.clearRect(0, 0, canvasSize, canvasSize)
    subjectPieData.forEach((item) => {
      const start = (item._startAngle - 90) * Math.PI / 180
      const end = (item._endAngle - 90) * Math.PI / 180
      ctx.beginPath()
      ctx.moveTo(center, center)
      ctx.setFillStyle(item._color)
      ctx.arc(center, center, radius, start, end)
      ctx.closePath()
      ctx.fill()
    })
    ctx.draw()
  }).exec()
}

const homeCanvasMethods = { drawSubjectPie }

module.exports = { homeCanvasMethods }
