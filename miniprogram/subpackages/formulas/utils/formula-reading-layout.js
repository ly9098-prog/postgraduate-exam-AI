/** Pixel-based panel sizing, independent of WeChat. */
function fitReadingHeight(contentHeight, headerHeight, maxHeight) {
  var header = Math.max(0, Number(headerHeight) || 0)
  var content = Math.max(0, Number(contentHeight) || 0)
  var cap = Math.max(1, Number(maxHeight) || 1)
  var height = Math.min(cap, Math.ceil(header + content))
  return { height: height, scrollHeight: Math.max(0, height - header) }
}

function readingViewport(info) {
  info = info || {}
  var width = Number(info.windowWidth) || 375
  var height = Number(info.windowHeight) || 667
  var bottom = info.safeArea ? Math.max(0, (Number(info.screenHeight) || height) - Number(info.safeArea.bottom)) : 0
  return { width: width, rpx: width / 750, maxHeight: Math.floor(height * 0.8), bottomInset: bottom || 0 }
}

/** Size from already-visible reader nodes BEFORE opening; no hidden math tree. */
function prepareReadingLayout(block, measurements, viewport) {
  var rpx = viewport.rpx
  var scale = 32 / 28
  var rects = measurements && measurements[0] || []
  var cursor = 0
  var contentHeight = 40 * rpx + viewport.bottomInset
  var rows = block.readingRows.map(function (row, index) {
    var items = row.lineItems
    var dimensions = items.map(function () { return rects[cursor++] })
    var measured = dimensions.every(function (rect) { return rect && rect.width > 0 && rect.height > 0 })
    var width = measured ? dimensions.reduce(function (sum, rect) { return sum + rect.width }, 0) * scale : 0
    // Separate KaTeX fragments omit the inter-atom space around a joined equality.
    if (items.length > 1) width += 16 * rpx
    var overflows = measured ? width > viewport.width - 48 * rpx : row.isScrollable
    var split = overflows && items.length > 1
    var heights = dimensions.map(function (rect) { return rect ? rect.height * scale : 56 * rpx })
    if (index) contentHeight += 37 * rpx
    if (split) {
      heights.forEach(function (height, lineIndex) {
        contentHeight += height + (lineIndex ? 32 : 44) * rpx
      })
    } else {
      contentHeight += Math.max.apply(Math, heights) + 44 * rpx
    }
    return {
      _key: row._key,
      isScrollable: Boolean(overflows),
      lineItems: split ? items : [row.fullLineItem || items[0]],
    }
  })
  var hasWideRows = rows.some(function (row) { return row.isScrollable })
  var title = measurements && measurements[1]
  var note = measurements && measurements[2]
  // Header dimensions match the actual CSS, including the close target's margins.
  var titleHeight = title && title.height ? title.height * (28 * 1.4) / (24 * 1.45) : 40 * rpx
  var headerHeight = Math.ceil(Math.max(60 * rpx, titleHeight + (hasWideRows ? 41 * rpx : 0)) + 45 * rpx)
  if (block.noteNodes && block.noteNodes.length) contentHeight += (note && note.height || 34 * rpx) + 9 * rpx
  var fitted = fitReadingHeight(contentHeight, headerHeight, viewport.maxHeight)
  return {
    expandedBlock: {
      _key: block._key, label: block.label, latex: block.latex,
      labelNodes: block.labelNodes || [], noteNodes: block.noteNodes || [],
      readingRows: rows, hasWideRows: hasWideRows,
    },
    expandedHeight: fitted.height,
    expandedScrollHeight: fitted.scrollHeight,
    expandedHeaderHeight: headerHeight,
  }
}

module.exports = { fitReadingHeight, readingViewport, prepareReadingLayout }
