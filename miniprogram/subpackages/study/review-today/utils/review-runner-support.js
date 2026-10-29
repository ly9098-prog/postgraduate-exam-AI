// Shared pure helpers for the review-today page and its page adapters.
var KF = 'schedule_id'
var REVIEW_BATCH_SIZE_OPTIONS = [5, 10, 20, 30]
var REVIEW_DRAFT_PREFIX = 'review_today_draft_v1'

function normalizeReviewBatchSize(value) {
var num = Number(value)
if (isNaN(num) || num <= 0) return 10
for (var i = 0; i < REVIEW_BATCH_SIZE_OPTIONS.length; i++) {
if (num === REVIEW_BATCH_SIZE_OPTIONS[i]) return num
}
return 10
}

function formatReviewElapsed(sec) {
var s = Math.max(0, sec || 0)
var m = Math.floor(s / 60)
var ss = s % 60
return (m < 10 ? '0' : '') + m + ':' + (ss < 10 ? '0' : '') + ss
}

function reviewFailureNeedsRefresh(result) {
if (!result || result.success !== false) return false
if (result.refresh_required === true) return true
if (result.retryable === false && result.retryable !== undefined && result.retryable !== null) return true
var text = String(result.error || '')
return /刷新|已失效|已经提交|已标记掌握|复习记录不存在|版本.*(?:更新|不存在)|不匹配|request_id.*不同提交/.test(text)
}

function normalizeReviewQuestion(raw) {
if (!raw || typeof raw !== 'object') return null
var content = raw.content
if (typeof content === 'string') {
content = { text: content }
} else if (!content || typeof content !== 'object') {
content = { text: raw.stem || '' }
}
var opts = raw.options
if (!opts || typeof opts !== 'object' || Array.isArray(opts)) {
opts = {}
}
return {
schedule_id: raw.schedule_id,
question_id: raw.question_id,
question_version_id: raw.question_version_id,
occurrence_seq: raw.occurrence_seq,
id: raw.id || raw.question_id,
subject_id: raw.subject_id != null ? raw.subject_id : null,
subject_code: raw.subject_code || '',
subject_name: raw.subject_name || '',
question_type: raw.question_type || '',
stem: raw.stem || '',
options: opts,
content: content,
image_url: raw.image_url || null,
interval: raw.interval || 0,
repetitions: raw.repetitions || 0,
ease_factor: raw.ease_factor || 2.5,
}
}

module.exports = {
  KF,
  REVIEW_BATCH_SIZE_OPTIONS,
  REVIEW_DRAFT_PREFIX,
  normalizeReviewBatchSize,
  formatReviewElapsed,
  reviewFailureNeedsRefresh,
  normalizeReviewQuestion,
}
