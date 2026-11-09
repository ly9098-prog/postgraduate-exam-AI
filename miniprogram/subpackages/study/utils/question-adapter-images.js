var { stemRender } = require('./question-adapter-dependencies')
var { isImageLikeSegmentType } = require('./segment-types')

function _normalizeUrl(url) {
  if (!url || typeof url !== 'string') return ''
  var s = url.trim()
  if (s.length > 8 && s.charAt(s.length - 1) === '/') s = s.slice(0, -1)
  return s
}

function getQuestionImages(q) {
  if (!q) return []
  var seen = {}
  var urls = []
  if (Array.isArray(q.image_url)) {
    q.image_url.forEach(function (url) {
      if (url && typeof url === 'string' && !seen[url]) {
        seen[url] = true
        urls.push(stemRender.resolveAssetUrl(url))
      }
    })
  }
  if (q.content && Array.isArray(q.content.image_url)) {
    q.content.image_url.forEach(function (url) {
      if (url && typeof url === 'string' && !seen[url]) {
        seen[url] = true
        urls.push(stemRender.resolveAssetUrl(url))
      }
    })
  }
  return urls
}

function getEmbeddedImageUrls(content) {
  if (!content || !Array.isArray(content.segments) || content.segments.length === 0) return []
  var seen = {}
  var urls = []
  for (var i = 0; i < content.segments.length; i++) {
    var seg = content.segments[i]
    if (!seg || typeof seg !== 'object') continue
    var candidateUrls = [seg.url]
    if (String(seg.type || '').toLowerCase() === 'table') {
      candidateUrls.push(seg.source_image_url)
      candidateUrls.push(seg.fallback_image_url)
    }
    for (var ui = 0; ui < candidateUrls.length; ui++) {
      var url = candidateUrls[ui]
      if (url && typeof url === 'string') {
        var resolved = stemRender.resolveAssetUrl(url)
        var normalized = _normalizeUrl(resolved)
        if (normalized && !seen[normalized]) {
          seen[normalized] = true
          urls.push(normalized)
        }
      }
    }
  }
  return urls
}

function computeExtraImages(q) {
  if (!q) return []
  var allUrls = getQuestionImages(q)
  if (!allUrls.length) return []
  var renderMode = (q._renderModel && q._renderModel.mode) || ''
  if (renderMode !== 'SEGMENTS') return allUrls
  var embedded = getEmbeddedImageUrls(q.content || {})
  if (!embedded.length) return allUrls
  var embeddedSet = {}
  for (var i = 0; i < embedded.length; i++) {
    embeddedSet[embedded[i]] = true
  }
  var extra = []
  for (var j = 0; j < allUrls.length; j++) {
    var normalized = _normalizeUrl(allUrls[j])
    if (!embeddedSet[normalized]) {
      extra.push(allUrls[j])
    }
  }
  return extra
}

function getQuestionPrefetchUrls(q) {
  if (!q) return []
  var seen = {}
  var urls = []
  function add(url) {
    if (!url || typeof url !== 'string') return
    var resolved = stemRender.resolveAssetUrl(url)
    var normalized = _normalizeUrl(resolved)
    if (!normalized || seen[normalized]) return
    seen[normalized] = true
    urls.push(normalized)
  }
  function collectSegments(segments) {
    if (!Array.isArray(segments)) return
    for (var i = 0; i < segments.length; i++) {
      var seg = segments[i]
      if (!seg || typeof seg !== 'object') continue
      var type = String(seg.type || '').toLowerCase()
      if (isImageLikeSegmentType(type)) {
        add(seg.url)
      }
      if (type === 'table' || type === 'table_markdown') {
        add(seg.source_image_url)
        add(seg.fallback_image_url)
      }
      if (Array.isArray(seg.segments)) collectSegments(seg.segments)
      if (Array.isArray(seg.blocks)) collectSegments(seg.blocks)
      if (Array.isArray(seg.cells)) {
        for (var ci = 0; ci < seg.cells.length; ci++) {
          var cell = seg.cells[ci]
          if (cell && Array.isArray(cell.blocks)) collectSegments(cell.blocks)
          if (cell && Array.isArray(cell.segments)) collectSegments(cell.segments)
        }
      }
    }
  }
  getQuestionImages(q).forEach(add)
  if (q.content) collectSegments(q.content.segments)
  var options = q.options
  if (options && typeof options === 'object') {
    Object.keys(options).forEach(function (key) {
      var option = options[key]
      if (!option || typeof option !== 'object') return
      add(option.image_url || option.imageUrl)
      collectSegments(option.segments)
    })
  }
  return urls
}

module.exports = {
  getQuestionImages,
  getEmbeddedImageUrls,
  computeExtraImages,
  getQuestionPrefetchUrls,
}
