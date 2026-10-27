/**
 * Pure review-analysis normalisation and view builders for the practice result page,
 * extracted from practice-result/index.js.
 */
const { normalizeAiAnalysisPayload, hasAiAnalysisContent } = require('../../utils/ai-analysis-normalizer')
const { formatMathPreviewText } = require('./review-preview-format')

function looksLikeStructuredReviewAnalysis(value) {
if (value && typeof value === 'object') return true;
if (typeof value !== 'string') return false;
const text = value.trim();
if (!text) return false;
if (/^```(?:json|javascript|js)?/i.test(text)) return true;
if (/^[\[{]/.test(text)) {
try {
const parsed = JSON.parse(text);
if (parsed && typeof parsed === 'object') {
if (!Array.isArray(parsed)) return true;
if (parsed.some(item => typeof item === 'string' || (item && typeof item === 'object'))) return true;
}
} catch (_) {}
}
return /["'](?:mistake_diagnosis|mistakediagnosis|mistakeDiagnosis|error_analysis|diagnosis|knowledge_patch|knowledgePatch|knowledgepatch|knowledge_weakness|review_task|reviewTask|reviewtask|reviewask|suggestion|错因诊断|补漏重点|复练任务|analysis|explanation|solution|answer_analysis|answerAnalysis|解析|题目解析)["']\s*:/i.test(text);
}

function containsRawAnalysisJson(value) {
if (typeof value !== 'string') return false;
return /(?:["']?(?:mistake_diagnosis|mistakediagnosis|mistakeDiagnosis|error_analysis|knowledge_patch|knowledgePatch|knowledgepatch|knowledge_weakness|review_task|reviewTask|reviewtask|reviewask)["']?\s*:|["'](?:错因诊断|补漏重点|复练任务)["']\s*:)/i.test(value);
}

function formatReviewAnalysisText(value) {
if (value === undefined || value === null) return '';
const text = String(value).trim();
if (!text || containsRawAnalysisJson(text)) return '';
return text
.split(/\r?\n+/)
.map(line => formatMathPreviewText(line))
.filter(Boolean)
.join('\n')
.trim();
}

function buildReadableReviewParagraphs(value) {
const text = String(value || '').trim();
if (!text) return [];
const explicitParagraphs = text
.split(/\n+/)
.map(part => part.trim())
.filter(Boolean);
const result = [];
explicitParagraphs.forEach(part => {
if (part.length < 72) {
result.push(part);
return;
}
const sentences = part.match(/[^。！？!?；]+[。！？!?；]?/g) || [part];
let bucket = '';
sentences.forEach(sentence => {
const piece = String(sentence || '').trim();
if (!piece) return;
if (bucket && (bucket.length + piece.length > 76)) {
result.push(bucket);
bucket = piece;
} else {
bucket += piece;
}
});
if (bucket) result.push(bucket);
});
return result.length ? result : [text];
}

function extractGenericReviewAnalysis(value, depth = 0) {
if (depth > 4 || value === undefined || value === null) return '';
let current = value;
if (typeof current === 'string') {
let text = current.trim();
if (!text) return '';
text = text.replace(/^```(?:json|javascript|js)?\s*/i, '').replace(/\s*```$/, '').trim();
if (!/^[\[{]/.test(text)) return '';
try {
current = JSON.parse(text);
} catch (_) {
return '';
}
}
if (Array.isArray(current)) {
const parts = current
.map(item => typeof item === 'string'
? formatReviewAnalysisText(item)
: extractGenericReviewAnalysis(item, depth + 1))
.filter(Boolean);
return parts.join('\n');
}
if (!current || typeof current !== 'object') return '';
const keys = [
'analysis', 'explanation', 'solution', 'answer_analysis', 'answerAnalysis',
'解析', '题目解析', 'text', 'content', 'value', 'description'
];
for (let keyIndex = 0; keyIndex < keys.length; keyIndex++) {
const key = keys[keyIndex];
const raw = current[key];
if (raw === undefined || raw === null) continue;
if (typeof raw === 'string') {
const direct = formatReviewAnalysisText(raw);
if (direct) return direct;
const nested = extractGenericReviewAnalysis(raw, depth + 1);
if (nested) return nested;
} else {
const nested = extractGenericReviewAnalysis(raw, depth + 1);
if (nested) return nested;
}
}
return '';
}

function buildReviewAnalysisView(value) {
if (value === undefined || value === null || value === '') {
return { sections: [], formatError: false };
}
const normalized = normalizeAiAnalysisPayload(value);
const structured = looksLikeStructuredReviewAnalysis(value);
const sections = [];
const append = (key, title, tone) => {
const text = formatReviewAnalysisText(normalized && normalized[key]);
if (text) sections.push({ key, title, tone, text });
};
if (hasAiAnalysisContent(normalized)) {
if (structured) {
append('mistake_diagnosis', '解析要点', 'primary');
append('knowledge_patch', '知识补充', 'knowledge');
append('review_task', '复习建议', 'task');
} else {
const plain = formatReviewAnalysisText(normalized.mistake_diagnosis);
if (plain) sections.push({ key: 'analysis', title: '题目解析', tone: 'primary', text: plain });
append('knowledge_patch', '知识补充', 'knowledge');
append('review_task', '复习建议', 'task');
}
}
if (!sections.length && structured) {
const genericText = extractGenericReviewAnalysis(value);
if (genericText) {
sections.push({ key: 'analysis', title: '题目解析', tone: 'primary', text: genericText });
}
}
if (!sections.length && !structured && typeof value === 'string') {
const plainFallback = formatReviewAnalysisText(value);
if (plainFallback) {
sections.push({ key: 'analysis', title: '题目解析', tone: 'primary', text: plainFallback });
}
}
return {
sections: sections.map(section => ({
...section,
paragraphs: buildReadableReviewParagraphs(section.text).map((text, index) => ({
key: `${section.key || 'section'}-${index}`,
text
}))
})),
formatError: structured && (sections.length === 0 || !!(normalized && normalized.formatError))
};
}

module.exports = {
  looksLikeStructuredReviewAnalysis,
  containsRawAnalysisJson,
  formatReviewAnalysisText,
  buildReadableReviewParagraphs,
  extractGenericReviewAnalysis,
  buildReviewAnalysisView,
}
