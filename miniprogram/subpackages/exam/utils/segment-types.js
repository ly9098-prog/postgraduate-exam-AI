// Central segment-type taxonomy for question rendering. stem-render,
// question-adapter-images, table-structure and math-question all classify
// segment types; keeping the sets here prevents the per-type drift that
// silently dropped code blocks (011cbf2d) and question images (2026-11-09).
// math-question.wxml cannot import JS: when adding a visual type here, also
// extend its render branch there (study and exam copies).
var VISUAL_SEGMENT_TYPES = { image: true, table_image: true, code_image: true }
var IMAGE_LIKE_SEGMENT_TYPES = {
  image: true,
  math_image: true,
  table_image: true,
  code_image: true,
}
function _normalizeSegmentType(type) {
  return String(type || '').trim().toLowerCase()
}
function isVisualSegmentType(type) {
  return VISUAL_SEGMENT_TYPES[_normalizeSegmentType(type)] === true
}
function isImageLikeSegmentType(type) {
  return IMAGE_LIKE_SEGMENT_TYPES[_normalizeSegmentType(type)] === true
}
function hasVisualSegments(segments) {
  if (!Array.isArray(segments)) return false
  return segments.some(function (segment) {
    return segment && typeof segment === 'object' && isVisualSegmentType(segment.type)
  })
}
module.exports = {
  VISUAL_SEGMENT_TYPES,
  IMAGE_LIKE_SEGMENT_TYPES,
  isVisualSegmentType,
  isImageLikeSegmentType,
  hasVisualSegments,
}
