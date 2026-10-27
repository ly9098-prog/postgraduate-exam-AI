/**
 * Pure preview and label helpers for the practice result page,
 * extracted from practice-result/index.js.
 */
const { toPlainInlineMathText } = require('../../utils/stem-render')
const { formatInlineMathText } = require('../../utils/math-format')

function normalizeReviewStatus(source, isCorrectFallback) {
const raw = String(
source && (source.status ?? source.answer_status ?? source.answerStatus) || ''
).trim().toLowerCase();
if (raw === 'partial' || raw === 'incomplete' || (source && source._local_partial)) return 'partial';
if (raw === 'skipped' || raw === 'skip' || (source && source._local_skipped)) return 'skipped';
if (raw === 'correct') return 'correct';
if (raw === 'wrong' || raw === 'incorrect') return 'wrong';
return isCorrectFallback ? 'correct' : 'wrong';
}

function pad2(n) {
return String(Math.max(0, Number(n) || 0)).padStart(2, '0');
}

function formatMathPreviewText(value) {
if (value === undefined || value === null) return '';
const source = String(value)
.replace(/<br\s*\/?>/gi, ' ')
.replace(/<[^>]+>/g, ' ')
.replace(/&nbsp;/gi, ' ')
.replace(/&amp;/gi, '&')
.replace(/&lt;/gi, '<')
.replace(/&gt;/gi, '>')
.replace(/\r?\n/g, ' ')
.replace(/\s+/g, ' ')
.trim();
if (!source) return '';
const plain = toPlainInlineMathText(source);
const rendered = plain !== null ? plain : formatInlineMathText(source);
return String(rendered || source).replace(/\s+/g, ' ').trim();
}

function formatAnswerPreview(value) {
if (typeof value !== 'string') return value;
const text = value.trim();
if (!text) return '';
const parts = text.split(';').map(item => item.trim()).filter(Boolean);
if (parts.length && parts.every(item => /^(?:[①-⑳]|\d+|[一二三四五六七八九十]+)[:：].+$/.test(item))) {
return parts.map(item => {
const match = item.match(/^([^:：;]+)[:：](.+)$/);
if (!match) return item;
const slot = match[1].trim();
const answer = match[2].trim();
const label = /^[①-⑳]$/.test(slot) ? slot : `第${slot}空`;
return `${label}：${answer}`;
}).join('；');
}
return formatMathPreviewText(text);
}

function getQuestionTitle(question) {
if (!question) return '';
const content = question.content || {};
return formatMathPreviewText(
content.text ||
content.stem ||
question.stem ||
question.text ||
question.title ||
''
);
}

function normalizeKpList(value) {
if (!value) return [];
if (Array.isArray(value)) {
return value
.map(item => {
if (typeof item === 'string') return item;
if (item && typeof item === 'object') {
return item.name || item.title || item.knowledge_point_name || item.label || '';
}
return '';
})
.filter(Boolean);
}
if (typeof value === 'string') {
return value.split(/[,，、]/).map(v => v.trim()).filter(Boolean);
}
return [];
}

module.exports = {
  normalizeReviewStatus,
  pad2,
  formatMathPreviewText,
  formatAnswerPreview,
  getQuestionTitle,
  normalizeKpList,
}
