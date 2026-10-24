const { toPlainInlineMathText } = require('../utils/stem-render');
const { formatInlineMathText } = require('../utils/math-format');
const { normalizeAiAnalysisPayload, hasAiAnalysisContent } = require('../utils/ai-analysis-normalizer');
const api = require('../../../utils/api');
const { knowledgePracticeSync } = require('../../../utils/storage');
const { getChinaDate } = require('../../../utils/china-time');
const errorDiagnosis = require('../utils/error-diagnosis');
const { buildLocalErrorDistribution: _buildLocalErrorDistribution, getResultTip: _getResultTip } = require('./utils/result-tips');
const aiTeacher408 = require('../utils/ai-teacher-408');
const { safeDecodeURIComponent } = require('../utils/route-params');
const ERROR_COLORS = ['#7ED8B5', '#55C89B', '#3DA880', '#2F8066', '#8BCDB8', '#B7EBD9'];
const RESULT_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const PRACTICE_PENDING_SUBMISSION_KEY_PREFIX = 'practice_pending_submission_v1';
const PRACTICE_PENDING_SUBMISSION_TTL_MS = 24 * 60 * 60 * 1000;
const DEFAULT_GROWTH = {
total_exp: 0,
level: 1,
level_title: '起步',
levelTitle: '起步',
level_progress_pct: 0,
exp_current: 0,
exp_to_next: 200,
streak_days: 0,
streak_title: '',
daily_boost: '',
badges: []
};
function normalizePracticeReturnRoute(value) {
const route = safeDecodeURIComponent(value, '').trim().slice(0, 512);
if (!route) return '';
if (!/^\/subpackages\/(?:knowledge\/knowledge-(?:detail|subject)|study\/knowledge-(?:detail|subject))\/index(?:\?.*)?$/.test(route)) return '';
return route;
}
function clamp(value, min, max) {
const n = Number(value);
if (!Number.isFinite(n)) return min;
return Math.min(max, Math.max(min, n));
}
function normalizePercent(value) {
const n = Number(value);
if (!Number.isFinite(n)) return 0;
if (n >= 0 && n <= 1) return Math.round(n * 100);
return Math.round(clamp(n, 0, 100));
}
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
function getQuestionListHeightRpx(count) {
const total = Math.max(0, Number(count) || 0);
return total > 0 ? total * 86 : 96;
}
function buildTrendPlot(data) {
const list = Array.isArray(data) ? data : [];
if (!list.length) return { points: [], segments: [], lastPoint: null };
const plotWidthRpx = 580;
const plotHeightRpx = 206;
const aspect = plotHeightRpx / plotWidthRpx;
const denominator = Math.max(1, list.length - 1);
const points = list.map((item, index) => {
const accuracy = clamp(item && item.accuracy, 0, 100);
const leftPct = list.length === 1 ? 50 : (index / denominator) * 100;
const topPct = 100 - accuracy;
const rawDate = String((item && item.date) || '');
const dateLabel = rawDate.slice(5).replace('-', '/') || String(index + 1);
return {
key: `${rawDate || 'day'}-${index}`,
accuracy,
leftPct: Number(leftPct.toFixed(3)),
topPct: Number(topPct.toFixed(3)),
badgeTopPct: Number(Math.max(0, topPct).toFixed(3)),
dateLabel,
isLast: index === list.length - 1
};
});
const segments = [];
for (let index = 0; index < points.length - 1; index += 1) {
const from = points[index];
const to = points[index + 1];
const dxPct = to.leftPct - from.leftPct;
const dyPct = to.topPct - from.topPct;
const scaledDy = dyPct * aspect;
const widthPct = Math.sqrt(dxPct * dxPct + scaledDy * scaledDy);
const angleDeg = Math.atan2(scaledDy, dxPct) * 180 / Math.PI;
segments.push({
key: `segment-${index}`,
leftPct: from.leftPct,
topPct: from.topPct,
widthPct: Number(widthPct.toFixed(3)),
angleDeg: Number(angleDeg.toFixed(3))
});
}
const areaPolygon = points.length > 1
? ['0% 100%'].concat(points.map(point => `${point.leftPct}% ${point.topPct}%`), ['100% 100%'])
: [];
return {
points,
segments,
lastPoint: points[points.length - 1] || null,
areaStyle: areaPolygon.length
? `clip-path: polygon(${areaPolygon.join(', ')});`
: ''
};
}
function buildErrorDonutGradient(distribution) {
const list = Array.isArray(distribution)
? distribution.filter(item => Number(item && item.count) > 0)
: [];
const total = list.reduce((sum, item) => sum + Number(item.count || 0), 0);
if (!total) return '#EEF2EF';
let cursor = 0;
const stops = [];
list.forEach((item, index) => {
const ratio = Number(item.count || 0) / total * 100;
const start = cursor;
const end = index === list.length - 1 ? 100 : cursor + ratio;
stops.push(`${item.color || ERROR_COLORS[index % ERROR_COLORS.length]} ${start.toFixed(3)}% ${end.toFixed(3)}%`);
cursor = end;
});
return `conic-gradient(${stops.join(', ')})`;
}
function getErrorDonutMetrics() {
let windowWidth = 375;
try {
if (typeof wx !== 'undefined') {
const info = wx.getWindowInfo ? wx.getWindowInfo() : null;
if (info && Number(info.windowWidth) > 0) windowWidth = Number(info.windowWidth);
}
} catch (e) {}
const size = Math.max(1, windowWidth * 210 / 750);
const cx = size / 2;
const cy = size / 2;
const radius = Math.max(1, size / 2 - 8);
const lineWidth = Math.max(13, radius * .25);
const pathRadius = Math.max(1, radius - lineWidth / 2);
return { size, cx, cy, radius, lineWidth, pathRadius };
}
function buildErrorDonutSvg(distribution) {
const list = Array.isArray(distribution)
? distribution.filter(item => Number(item && item.count) > 0)
: [];
const total = list.reduce((sum, item) => sum + Number(item.count || 0), 0);
if (!total) return '';
const { size, cx, cy, lineWidth, pathRadius } = getErrorDonutMetrics();
const pointOnCircle = angle => ({
x: cx + pathRadius * Math.cos(angle),
y: cy + pathRadius * Math.sin(angle)
});
let start = -Math.PI / 2;
const paths = list.map((item, index) => {
const ratio = Number(item.count || 0) / total;
const gap = Math.min(.035, ratio * .12);
const segmentEnd = start + Math.PI * 2 * ratio;
const drawStart = start + gap;
const drawEnd = segmentEnd - gap;
start = segmentEnd;
if (drawEnd <= drawStart) return '';
const p1 = pointOnCircle(drawStart);
const p2 = pointOnCircle(drawEnd);
const sweep = drawEnd - drawStart;
const largeArc = sweep > Math.PI ? 1 : 0;
const color = String(item.color || ERROR_COLORS[index % ERROR_COLORS.length]);
return `<path d="M ${p1.x.toFixed(3)} ${p1.y.toFixed(3)} A ${pathRadius.toFixed(3)} ${pathRadius.toFixed(3)} 0 ${largeArc} 1 ${p2.x.toFixed(3)} ${p2.y.toFixed(3)}" fill="none" stroke="${color}" stroke-width="${lineWidth.toFixed(3)}" stroke-linecap="round"/>`;
}).join('');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size.toFixed(3)} ${size.toFixed(3)}" shape-rendering="geometricPrecision"><circle cx="${cx.toFixed(3)}" cy="${cy.toFixed(3)}" r="${pathRadius.toFixed(3)}" fill="none" stroke="#EEF2EF" stroke-width="${lineWidth.toFixed(3)}"/>${paths}</svg>`;
return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}
function formatDuration(seconds) {
const total = Math.max(0, Math.round(Number(seconds) || 0));
const h = Math.floor(total / 3600);
const m = Math.floor((total % 3600) / 60);
const s = total % 60;
if (h > 0) return `${pad2(h)}:${pad2(m)}:${pad2(s)}`;
return `${pad2(m)}分${pad2(s)}秒`;
}
function safeDecodeJson(value) {
if (!value || typeof value !== 'string') return null;
const candidates = [value];
try { candidates.push(decodeURIComponent(value)); } catch (e) {}
for (let candidateIndex = 0; candidateIndex < candidates.length; candidateIndex++) {
const text = candidates[candidateIndex];
try {
const parsed = JSON.parse(text);
if (parsed && typeof parsed === 'object') return parsed;
} catch (e) {}
}
return null;
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
function stripLevelPrefix(title, level) {
const text = String(title || '').trim();
if (!text) return level === 1 ? '起步' : '';
return text.replace(/^Lv\s*\d+\s*/i, '').trim() || text;
}
function growthFromTotalExp(totalExp, streakDays = 0, badges = []) {
const total = Math.max(0, Math.round(Number(totalExp) || 0));
const levels = [
{ lo: 0, hi: 200, level: 1, title: 'Lv1 起步' },
{ lo: 200, hi: 600, level: 2, title: 'Lv2 坚持者' },
{ lo: 600, hi: 1500, level: 3, title: 'Lv3 刷题达人' },
{ lo: 1500, hi: 3500, level: 4, title: 'Lv4 高效进阶' },
{ lo: 3500, hi: null, level: 5, title: 'Lv5 上岸冲刺' }
];
let current = levels[0];
levels.forEach(item => {
if (total >= item.lo) current = item;
});
const expCurrent = Math.max(0, total - current.lo);
const expToNext = current.hi === null ? 0 : current.hi - current.lo;
const progress = current.hi === null
? 100
: Math.min(100, Math.round(expCurrent / expToNext * 100));
return {
...DEFAULT_GROWTH,
total_exp: total,
level: current.level,
level_title: current.title,
levelTitle: stripLevelPrefix(current.title, current.level),
level_progress_pct: progress,
exp_current: expCurrent,
exp_to_next: expToNext,
streak_days: Math.max(0, Number(streakDays) || 0),
badges: Array.isArray(badges) ? badges : []
};
}
function normalizeGrowthProfile(raw) {
if (!raw || typeof raw !== 'object') return null;
const source = raw.growth && typeof raw.growth === 'object'
? raw.growth
: raw;
const level = Math.max(1, Number(source.level) || 1);
const levelTitleFull =
source.level_title ||
source.levelTitle ||
`Lv${level} ${level === 1 ? '起步' : ''}`.trim();
const totalExpValue = Number(source.total_exp ?? source.totalExp);
const expCurrentValue = Number(source.exp_current ?? source.expCurrent);
const expToNextValue = Number(source.exp_to_next ?? source.expToNext);
const progressValue = Number(source.level_progress_pct ?? source.levelProgressPct);
const totalExp = Number.isFinite(totalExpValue) ? Math.max(0, totalExpValue) : 0;
const expCurrent = Number.isFinite(expCurrentValue) ? Math.max(0, expCurrentValue) : 0;
const expToNext = Number.isFinite(expToNextValue)
? Math.max(0, expToNextValue)
: (level >= 5 ? 0 : 200);
let progress = Number.isFinite(progressValue)
? clamp(progressValue, 0, 100)
: (expToNext > 0 ? Math.round(expCurrent / expToNext * 100) : (level >= 5 ? 100 : 0));
if (progress === 0 && expCurrent > 0 && expToNext > 0) {
progress = Math.min(100, Math.round(expCurrent / expToNext * 100));
}
return {
...DEFAULT_GROWTH,
...source,
total_exp: totalExp,
level,
level_title: levelTitleFull,
levelTitle: stripLevelPrefix(levelTitleFull, level),
level_progress_pct: progress,
exp_current: expCurrent,
exp_to_next: expToNext,
streak_days: Math.max(0, Number(source.streak_days ?? source.streakDays) || 0),
badges: Array.isArray(source.badges) ? source.badges : []
};
}
function growthFromOverview(overview) {
if (!overview || typeof overview !== 'object') return null;
const totalQuestions = Math.max(0, Number(overview.total_questions ?? overview.totalQuestions) || 0);
const accuracyRaw = Number(overview.accuracy);
const accuracy = Number.isFinite(accuracyRaw)
? (accuracyRaw > 1 ? accuracyRaw / 100 : accuracyRaw)
: 0;
const streak = Math.max(0, Number(overview.consecutive_days ?? overview.consecutiveDays) || 0);
const mastered = Math.max(0, Number(overview.mastered_count ?? overview.masteredCount) || 0);
let totalExp = totalQuestions * 10 + mastered * 20 + streak * 5;
if (accuracy >= 0.7 && totalQuestions >= 10) {
totalExp += Math.floor(totalQuestions * accuracy * 5);
}
return growthFromTotalExp(totalExp, streak);
}
Page({
data: {
tabs: [
{ key: 'overview', label: '结果概览' },
{ key: 'wrong', label: '错题分析' },
{ key: 'growth', label: '成长记录' }
],
activeTab: 'overview',
questionFilters: [
{ key: 'all', label: '全部' },
{ key: 'correct', label: '答对' },
{ key: 'wrong', label: '答错' },
{ key: 'skipped', label: '跳过' },
{ key: 'partial', label: '未完成' }
],
questionFilter: 'all',
questionListHeightRpx: 96,
subjectName: '',
correctCount: 0,
wrongCount: 0,
skippedCount: 0,
partialCount: 0,
totalCount: 0,
accuracyPct: 0,
accuracyDotDeg: -90,
durationText: '00分00秒',
resultTip: '完成练习后及时复盘，效果会更好。',
reviewItems: [],
filteredReviewItems: [],
wrongReviewItems: [],
batchDiagnosisMode: false,
batchSelectedMap: {},
batchSelectedCount: 0,
batchSelectableCount: 0,
batchDiagnosisSaving: false,
errorDistribution: [],
trendData: [],
trendPoints: [],
trendSegments: [],
trendLastPoint: null,
trendAreaStyle: '',
trendSummary: '近 7 天',
trendLoading: true,
trendAvailable: false,
errorDonutGradient: '#EEF2EF',
errorDonutSvg: '',
growthGain: 0,
growth: DEFAULT_GROWTH,
growthAvailable: false,
unlockedBadgeCount: 0,
reviewDialogVisible: false,
reviewDialog: {
title: '',
questionTitle: '',
status: '',
statusLabel: '',
userAnswer: '',
correctAnswer: '',
analysisSections: [],
analysisFormatError: false,
questionId: 0,
questionVersionId: 0,
diagnosisId: 0
},
teacherActions: aiTeacher408.ACTIONS,
teacherLoading: false,
teacherResult: null,
teacherErrorText: '',
teacherSheetVisible: false,
teacherFeedbackSent: '',
heroTopPaddingPx: 28
},
onLoad(options) {
this._pageAlive = true;
this._resultVisible = false;
this._diagnosisRefreshSeq = 0;
this._returnTo = normalizePracticeReturnRoute((options || {}).return_to);
this._launchSource = String((options || {}).source || '').trim().slice(0, 32);
this._launchSubjectId = Number((options || {}).subject_id) || 0;
this._launchKnowledgePointId = Number((options || {}).knowledge_point_id) || 0;
this._practiceRequestId = safeDecodeURIComponent((options || {})._rid, '').trim().slice(0, 128);
this._navigationLocked = false;
this._sessionPayload = null;
this._dashboardLoadId = 0;
this._teacherRequestSeq = 0;
this._teacherCache = Object.create(null);
this._teacherInflight = Object.create(null);
this._teacherFeedbackCache = Object.create(null);
this._activeTeacherCacheKey = '';
this.measureSafeNavigation();
this.bindEventChannel();
const rawOptionPayload = this.readPayloadFromOptions(options || {});
const optionPayload = rawOptionPayload && this._isPayloadRequestValid(rawOptionPayload, this._practiceRequestId)
? rawOptionPayload
: null;
const cachePayload = optionPayload ? null : this.readPayloadFromCache(options || {});
const primaryPayload = optionPayload || cachePayload;
const summaryPayload = primaryPayload ? null : this.readSummaryFromOptions(options || {});
this.applyPracticePayload(primaryPayload || summaryPayload || {});
const requestId = String(this._practiceRequestId || '').trim();
if (primaryPayload && this._hasDetailedPracticePayload(primaryPayload)) {
if (requestId) this._clearPendingSubmission(requestId);
} else if (requestId) {
this.recoverSubmittedResult(options || {});
}
this.loadDashboardData();
},
onUnload() {
this._pageAlive = false;
this._diagnosisRefreshSeq++;
this._dashboardLoadId++;
this._teacherRequestSeq++;
this._teacherInflight = null;
},
onShow() {
this._navigationLocked = false;
this._resultVisible = true;
this.refreshWrongDiagnoses();
},
onHide() {
this._resultVisible = false;
this._diagnosisRefreshSeq++;
},
async refreshWrongDiagnoses() {
if (!this._pageAlive || this.data.batchDiagnosisSaving) return;
const seq = this._diagnosisRefreshSeq = (this._diagnosisRefreshSeq || 0) + 1;
const ids = [...new Set((this.data.wrongReviewItems || [])
.map(item => Number(item.wrongQuestionId)).filter(id => Number.isInteger(id) && id > 0))];
if (!ids.length) return;
const diagnoses = new Map();
let cursor = 0;
const isCurrent = () => this._pageAlive && seq === this._diagnosisRefreshSeq;
// Fetch only the diagnosis contract, with bounded concurrency for long result lists.
const worker = async () => {
while (cursor < ids.length && isCurrent()) {
const id = ids[cursor++];
try {
const raw = await api.get(`/wrong-questions/${id}/diagnosis`, {}, { suppressNetworkToast: true });
const diagnosis = errorDiagnosis.normalizeDiagnosis(raw);
if (diagnosis && isCurrent()) diagnoses.set(id, diagnosis);
} catch (_) {
// A failed refresh must not erase an already-recorded diagnosis.
}
}
};
await Promise.all(Array.from({ length: Math.min(4, ids.length) }, worker));
if (!isCurrent() || !diagnoses.size || this.data.batchDiagnosisSaving) return;
const update = list => (list || []).map(item => {
const diagnosis = diagnoses.get(Number(item.wrongQuestionId));
return diagnosis ? Object.assign({}, item, {
errorDiagnosis: diagnosis,
errorDiagnosisLabel: diagnosis.primaryLabel,
}) : item;
});
// Preserve current filters, batch selections and the rest of the result dashboard.
this.setData({
reviewItems: update(this.data.reviewItems),
filteredReviewItems: update(this.data.filteredReviewItems),
wrongReviewItems: update(this.data.wrongReviewItems),
});
},
measureSafeNavigation() {
let statusBarHeight = 20;
let menuTop = 0;
try {
const info = wx.getWindowInfo ? wx.getWindowInfo() : {};
statusBarHeight = Math.max(0, Number(info.statusBarHeight) || 20);
} catch (e) {}
try {
const menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect();
if (menu && Number(menu.top) > 0) menuTop = Number(menu.top);
} catch (e) {}
const heroTopPaddingPx = Math.round(Math.max(statusBarHeight + 6, menuTop || 0));
this.setData({ heroTopPaddingPx });
},
bindEventChannel() {
try {
const channel = this.getOpenerEventChannel && this.getOpenerEventChannel();
if (!channel || !channel.on) return;
const eventNames = [
'practiceResult',
'practice-result',
'result',
'submitResult',
'sessionResult'
];
eventNames.forEach(name => {
channel.on(name, payload => {
if (payload && typeof payload === 'object' &&
this._isPayloadRequestValid(payload, this._practiceRequestId)) {
this.applyPracticePayload(payload);
if (this._practiceRequestId && this._hasDetailedPracticePayload(payload)) {
this._clearPendingSubmission(this._practiceRequestId);
}
}
});
});
} catch (e) {}
},
_hasDetailedPracticePayload(payload) {
const source = payload && payload.data && typeof payload.data === 'object'
? payload.data
: payload;
if (!source || typeof source !== 'object') return false;
return (Array.isArray(source.results) && source.results.length > 0) ||
(Array.isArray(source.submitResults) && source.submitResults.length > 0) ||
(Array.isArray(source.resultList) && source.resultList.length > 0);
},
readPayloadFromOptions(options) {
const keys = ['payload', 'result', 'data', 'session', 'practiceResult'];
for (let keyIndex = 0; keyIndex < keys.length; keyIndex++) {
const key = keys[keyIndex];
if (!options[key]) continue;
if (typeof options[key] === 'object') return options[key];
const parsed = safeDecodeJson(options[key]);
if (parsed) return parsed;
}
return null;
},
readSummaryFromOptions(options) {
const keys = ['correct', 'wrong', 'skipped', 'partial', 'total', 'duration', 'subject_id', 'subject_name'];
if (!keys.some(key => options[key] !== undefined && options[key] !== null && options[key] !== '')) return null;
let subjectName = options.subject_name || '';
if (typeof subjectName === 'string') {
try { subjectName = decodeURIComponent(subjectName); } catch (_) {}
}
return {
total_correct: Number(options.correct) || 0,
total_wrong: Number(options.wrong) || 0,
total_skipped: Number(options.skipped) || 0,
total_partial: Number(options.partial) || 0,
total: Math.max(0, Number(options.total) || 0),
duration: Math.max(0, Number(options.duration) || 0),
subject_id: options.subject_id != null ? Number(options.subject_id) : null,
subject_name: subjectName,
};
},
_getCurrentUserId() {
try {
const user = wx.getStorageSync('user');
if (!user || typeof user !== 'object') return '';
const candidates = [user.id, user.user_id, user.openid];
for (let candidateIndex = 0; candidateIndex < candidates.length; candidateIndex++) {
const candidate = candidates[candidateIndex];
if (candidate === undefined || candidate === null) continue;
const value = String(candidate).trim();
if (value) return value;
}
return '';
} catch (_) {
return '';
}
},
_isPayloadRequestValid(value, expectedRequestId) {
if (!value || typeof value !== 'object') return false;
const source = value.data && typeof value.data === 'object' ? value.data : value;
const expected = String(expectedRequestId || '').trim();
if (!expected) return true;
const actual = String(
source.request_id || source.requestId || value.request_id || value.requestId || ''
).trim();
return !!actual && actual === expected;
},
_isResultCacheValid(value, expectedCacheKey, expectedRequestId) {
if (!value || typeof value !== 'object') return false;
if (expectedCacheKey && String(value._cacheKey || '') !== expectedCacheKey) return false;
if (!this._isPayloadRequestValid(value, expectedRequestId)) return false;
const currentUserId = this._getCurrentUserId();
const cachedUserId = value._userId === undefined || value._userId === null ? '' : String(value._userId);
if (cachedUserId && (!currentUserId || cachedUserId !== currentUserId)) return false;
let createdAt = Number(value._createdAt || 0);
if (!(createdAt > 0) && value._cacheKey) {
const match = /^pr_(\d+)_/.exec(String(value._cacheKey));
if (match) createdAt = Number(match[1]) || 0;
}
if (createdAt > 0 && Date.now() - createdAt > RESULT_CACHE_MAX_AGE_MS) return false;
return true;
},
readPayloadFromCache(options) {
const expectedCacheKey = options && options._ck ? String(options._ck) : '';
const expectedRequestId = safeDecodeURIComponent((options || {})._rid, '').trim().slice(0, 128);
const keys = [
'practiceResult',
'practice_result',
'lastPracticeResult',
'practiceSessionResult'
];
for (let keyIndex = 0; keyIndex < keys.length; keyIndex++) {
const key = keys[keyIndex];
try {
const value = wx.getStorageSync(key);
if (value && typeof value === 'object' && this._isResultCacheValid(value, expectedCacheKey, expectedRequestId)) return value;
const parsed = safeDecodeJson(value);
if (parsed && this._isResultCacheValid(parsed, expectedCacheKey, expectedRequestId)) return parsed;
} catch (e) {}
}
return null;
},
_pendingSubmissionStorageKey() {
const userId = this._getCurrentUserId();
return userId ? `${PRACTICE_PENDING_SUBMISSION_KEY_PREFIX}:${userId}` : '';
},
_readPendingSubmissionForRecovery(requestId) {
const key = this._pendingSubmissionStorageKey();
if (!key || !requestId) return null;
try {
const item = wx.getStorageSync(key);
if (!item || item.version !== 1 || !item.submission) return null;
if (String(item.submission.requestId || '') !== String(requestId)) return null;
const freshnessAt = Number(item.updatedAt) || Number(item.createdAt) || 0;
if (!freshnessAt || Date.now() - freshnessAt > PRACTICE_PENDING_SUBMISSION_TTL_MS) return null;
return item;
} catch (_) {
return null;
}
},
_clearPendingSubmission(requestId) {
const key = this._pendingSubmissionStorageKey();
if (!key) return;
try {
const item = wx.getStorageSync(key);
if (!item || !item.submission || String(item.submission.requestId || '') === String(requestId || '')) {
wx.removeStorageSync(key);
}
} catch (_) {}
},
_buildRecoveredResultPayload(submission, submitResult, options) {
const answerMap = submission.answerMap || {};
const partialSet = {};
;(submission.partialQuestionIds || []).forEach(id => { partialSet[String(id)] = true; });
const results = (submitResult.results || []).map(item => {
const qid = String(item.question_id);
const isPartial = item.status === 'skipped' && !!partialSet[qid];
return {
...item,
status: isPartial ? 'partial' : item.status,
_local_partial: isPartial,
_local_skipped: item.status === 'skipped' && !isPartial,
user_answer: answerMap[qid] || '',
};
});
const partialCount = (submission.partialQuestionIds || []).length;
const skippedCount = Math.max(0, (Number(submitResult.total_skipped) || 0) - partialCount);
const cacheKey = String((options || {})._ck || '');
return {
correct: Number(submitResult.total_correct) || 0,
wrong: Number(submitResult.total_wrong) || 0,
skipped: skippedCount,
partial: partialCount,
total: Number(submission.total) || results.length,
subject_id: submission.selectedSubjectId ?? (submission.session && submission.session.subject_id) ?? null,
subject_name: submission.selectedSubjectName || '',
duration: Number(submission.duration ?? (submission.session && submission.session.duration_sec)) || 0,
traceId: submitResult.trace_id || submission.traceId || '',
results,
questions: (submission.recoveryQuestions || []).map(q => ({
...q,
id: q.id,
stem: q.stem || '',
question_type: q.question_type || '',
content: q.content || (q.stem ? { stem: q.stem } : {}),
options: q.options || null,
image_url: q.image_url || null,
})),
comboCount: Number(submission.comboCount) || 0,
knowledge_session: submitResult.knowledge_session || submission.knowledgeScope || null,
request_id: submission.requestId || '',
_cacheKey: cacheKey,
_userId: this._getCurrentUserId(),
_createdAt: Date.now(),
};
},
async recoverSubmittedResult(options) {
const requestId = String(this._practiceRequestId || safeDecodeURIComponent((options || {})._rid, '')).trim();
const pending = this._readPendingSubmissionForRecovery(requestId);
if (!pending || !pending.submission || !this._pageAlive) {
wx.showToast({ title: '详细复盘数据暂无法恢复', icon: 'none' });
return;
}
const submission = pending.submission;
const payload = {
answers: submission.answers || [],
skipped_question_ids: submission.skippedQuestionIds || [],
session: submission.session || null,
_traceId: submission.traceId || '',
};
if (!submission.batchToken) {
wx.showToast({ title: '恢复凭据已失效，请重新进入练习', icon: 'none' });
return;
}
payload.batch_token = submission.batchToken;
try {
const submitResult = await api.post('/practice/batch-submit', payload);
if (!this._pageAlive) return;
const recovered = this._buildRecoveredResultPayload(submission, submitResult || {}, options || {});
let cached = false;
try {
wx.setStorageSync('lastPracticeResult', recovered);
cached = true;
} catch (storageError) {
console.warn('恢复结果后写入本地缓存失败', storageError);
}
this.applyPracticePayload(recovered);
if (cached) this._clearPendingSubmission(requestId);
} catch (e) {
if (!this._pageAlive) return;
console.error('恢复已提交练习结果失败', e);
wx.showToast({ title: '详细复盘恢复失败，可稍后重试', icon: 'none' });
}
},
applyPracticePayload(payload) {
this._diagnosisRefreshSeq = (this._diagnosisRefreshSeq || 0) + 1;
const source = payload && payload.data && !payload.results && typeof payload.data === 'object'
? payload.data
: (payload || {});
this._sessionPayload = source;
const embeddedKnowledgeSession = source.knowledge_session || source.knowledgeSession || null;
const results = Array.isArray(source.results)
? source.results
: Array.isArray(source.submitResults)
? source.submitResults
: Array.isArray(source.resultList)
? source.resultList
: [];
const questions = Array.isArray(source.questions)
? source.questions
: Array.isArray(source.questionList)
? source.questionList
: [];
const answers = Array.isArray(source.answers)
? source.answers
: Array.isArray(source.answerList)
? source.answerList
: [];
const resultMap = {};
results.forEach(item => {
const qid = item.question_id ?? item.questionId ?? item.id;
if (qid !== undefined && qid !== null) resultMap[String(qid)] = item;
});
const answerMap = {};
answers.forEach(item => {
const qid = item.question_id ?? item.questionId ?? item.id;
if (qid !== undefined && qid !== null) answerMap[String(qid)] = item;
});
let reviewItems = [];
if (questions.length) {
reviewItems = questions.map((question, index) => {
const qid = question.id ?? question.question_id ?? question.questionId ?? index + 1;
return this.buildReviewItem(
question,
resultMap[String(qid)] || {},
answerMap[String(qid)] || {},
index
);
});
} else if (Array.isArray(source.reviewItems)) {
reviewItems = source.reviewItems.map((item, index) => this.normalizeReviewItem(item, index));
} else if (results.length) {
reviewItems = results.map((item, index) => this.normalizeReviewItem(item, index));
}
const explicitCorrect = source.total_correct ?? source.totalCorrect ?? source.correctCount ?? source.correct_count;
const explicitWrong = source.total_wrong ?? source.totalWrong ?? source.wrongCount ?? source.wrong_count;
const explicitSkipped = source.total_skipped ?? source.totalSkipped ?? source.skippedCount ?? source.skipped_count ?? source.skipped;
const explicitPartial = source.total_partial ?? source.totalPartial ?? source.partialCount ?? source.partial_count ?? source.partial;
let correctCount = Number.isFinite(Number(explicitCorrect))
? Number(explicitCorrect)
: reviewItems.filter(item => item.status === 'correct').length;
let wrongCount = Number.isFinite(Number(explicitWrong))
? Number(explicitWrong)
: reviewItems.filter(item => item.status === 'wrong').length;
let skippedCount = Number.isFinite(Number(explicitSkipped))
? Number(explicitSkipped)
: reviewItems.filter(item => item.status === 'skipped').length;
let partialCount = Number.isFinite(Number(explicitPartial))
? Number(explicitPartial)
: reviewItems.filter(item => item.status === 'partial').length;
let totalCount =
Number(source.totalCount ?? source.total_count ?? source.total) ||
(correctCount + wrongCount + skippedCount + partialCount) ||
reviewItems.length;
if (!correctCount && !wrongCount && !skippedCount && !partialCount && reviewItems.length) {
correctCount = reviewItems.filter(item => item.status === 'correct').length;
wrongCount = reviewItems.filter(item => item.status === 'wrong').length;
skippedCount = reviewItems.filter(item => item.status === 'skipped').length;
partialCount = reviewItems.filter(item => item.status === 'partial').length;
totalCount = reviewItems.length;
}
const answeredTotal = correctCount + wrongCount;
const explicitAccuracy = source.accuracy ?? source.accuracyPct ?? source.correctRate ?? source.correct_rate;
const accuracyPct = explicitAccuracy !== undefined && explicitAccuracy !== null
? normalizePercent(explicitAccuracy)
: (answeredTotal ? Math.round(correctCount / answeredTotal * 100) : 0);
const usedTime = (
source.used_time ??
source.usedTime ??
source.duration ??
source.durationSec ??
source.elapsed ??
answers.reduce((sum, item) => sum + (Number(item.used_time ?? item.usedTime) || 0), 0)
);
const subjectName =
source.subjectName ||
source.subject_name ||
source.subject ||
(questions[0] && (questions[0].subject_name || questions[0].subjectName)) ||
'';
const growthGain = Number(source.growthGain ?? source.expGain ?? source.exp_gain ?? source.expAdded ?? 0) || 0;
const embeddedGrowth = normalizeGrowthProfile(
source.growth ||
source.growth_profile ||
source.growthProfile ||
(source.stats && source.stats.growth) ||
null
);
const wrongReviewItems = reviewItems.filter(item => item.status === 'wrong');
const localErrorDistribution = this.buildLocalErrorDistribution(wrongReviewItems);
const resultTip = this.getResultTip(accuracyPct, wrongCount, skippedCount, partialCount, totalCount);
const knowledgeSession = embeddedKnowledgeSession && typeof embeddedKnowledgeSession === 'object' ? embeddedKnowledgeSession : null;
const knowledgeRootId = Math.max(0, Number(
(knowledgeSession && (knowledgeSession.root_knowledge_point_id || knowledgeSession.rootKnowledgePointId || knowledgeSession.knowledge_point_id || knowledgeSession.knowledgePointId)) ||
source.knowledge_point_id || source.knowledgePointId || this._launchKnowledgePointId
) || 0);
const knowledgeRootName = String(knowledgeSession && (knowledgeSession.root_name || knowledgeSession.rootName) || '').trim();
const knowledgeScopeCount = Math.max(1, Number(knowledgeSession && (knowledgeSession.knowledge_point_count || knowledgeSession.knowledgePointCount)) || 1);
const knowledgeIncludeDescendants = Boolean(knowledgeSession && (knowledgeSession.include_descendants === true || knowledgeSession.includeDescendants === true));
const knowledgeAnswerCount = Math.max(0, correctCount + wrongCount);
const hasKnowledgeLaunch = Boolean(knowledgeSession || (this._launchSource === 'knowledge_map' && knowledgeRootId));
if (hasKnowledgeLaunch && this._launchSubjectId && knowledgeRootId && knowledgeAnswerCount > 0) {
knowledgePracticeSync.record({
subjectId: this._launchSubjectId,
knowledgePointId: knowledgeRootId,
includeDescendants: knowledgeIncludeDescendants,
answeredCount: knowledgeAnswerCount,
baselineAttemptCount: knowledgePracticeSync.consumeBaseline(this._launchSubjectId, knowledgeRootId),
correctCount,
wrongCount,
requestId: this._practiceRequestId,
rootName: knowledgeRootName,
});
}
if (!this._pageAlive) return;
this.setData({
subjectName,
correctCount,
wrongCount,
skippedCount,
partialCount,
totalCount,
accuracyPct,
accuracyDotDeg: Math.round(accuracyPct * 3.6 - 90),
durationText: formatDuration(usedTime),
resultTip,
growthGain,
...(embeddedGrowth ? {
growth: embeddedGrowth,
growthAvailable: true,
unlockedBadgeCount: embeddedGrowth.badges.filter(item => item && item.unlocked).length
} : {}),
reviewItems,
filteredReviewItems: reviewItems,
questionListHeightRpx: getQuestionListHeightRpx(reviewItems.length),
wrongReviewItems,
batchDiagnosisMode: false,
batchSelectedMap: {},
batchSelectedCount: 0,
batchSelectableCount: wrongReviewItems.filter(item => Number(item.wrongQuestionId) > 0).length,
batchDiagnosisSaving: false,
errorDistribution: localErrorDistribution,
errorDonutGradient: buildErrorDonutGradient(localErrorDistribution),
errorDonutSvg: buildErrorDonutSvg(localErrorDistribution)
});
if (this._resultVisible) this.refreshWrongDiagnoses();
},
buildReviewItem(question, result, answer, index) {
const questionId =
question.id ??
question.question_id ??
question.questionId ??
result.question_id ??
result.questionId ??
index + 1;
const normalizedDiagnosis = errorDiagnosis.normalizeDiagnosis(result.error_diagnosis ?? result.errorDiagnosis);
const isCorrectRaw =
result.is_correct ??
result.isCorrect ??
answer.is_correct ??
answer.isCorrect ??
false;
const status = normalizeReviewStatus(
Object.assign({}, answer || {}, result || {}),
!!isCorrectRaw
);
const kpList = normalizeKpList(
result.knowledge_points ??
result.knowledgePoints ??
question.knowledge_points ??
question.knowledgePoints
);
return {
questionId,
questionVersionId: result.question_version_id ?? result.questionVersionId ?? question.question_version_id ?? question.questionVersionId ?? null,
wrongQuestionId: result.wrong_question_id ?? result.wrongQuestionId ?? null,
displayIndex: pad2(index + 1),
title: getQuestionTitle(question) || `第 ${index + 1} 题`,
status,
isCorrect: status === 'correct',
isSkipped: status === 'skipped',
isPartial: status === 'partial',
userAnswer: formatAnswerPreview(answer.user_answer ?? answer.userAnswer ?? result.user_answer ?? result.userAnswer ?? ''),
correctAnswer: formatAnswerPreview(result.correct_answer ?? result.correctAnswer ?? question.answer ?? ''),
analysis: result.analysis ?? question.analysis ?? '',
knowledgePoints: kpList,
knowledgePoint: kpList[0] || '未标注知识点',
errorDiagnosis: normalizedDiagnosis,
errorDiagnosisLabel: normalizedDiagnosis ? normalizedDiagnosis.primaryLabel : errorDiagnosis.labelOf('unknown')
};
},
normalizeReviewItem(item, index) {
const normalizedDiagnosis = errorDiagnosis.normalizeDiagnosis(item.errorDiagnosis ?? item.error_diagnosis);
const isCorrectRaw = item.is_correct ?? item.isCorrect ?? item.correct ?? false;
const status = normalizeReviewStatus(item, !!isCorrectRaw);
const kpList = normalizeKpList(item.knowledge_points ?? item.knowledgePoints ?? item.knowledgePoint);
return {
questionId: item.questionId ?? item.question_id ?? item.id ?? index + 1,
questionVersionId: item.questionVersionId ?? item.question_version_id ?? null,
wrongQuestionId: item.wrongQuestionId ?? item.wrong_question_id ?? null,
displayIndex: item.displayIndex || pad2(index + 1),
title: formatMathPreviewText(item.title || getQuestionTitle(item)) || `第 ${index + 1} 题`,
status,
isCorrect: status === 'correct',
isSkipped: status === 'skipped',
isPartial: status === 'partial',
userAnswer: formatAnswerPreview(item.userAnswer ?? item.user_answer ?? item.wrong_answer ?? ''),
correctAnswer: formatAnswerPreview(item.correctAnswer ?? item.correct_answer ?? item.answer ?? ''),
analysis: item.analysis ?? '',
knowledgePoints: kpList,
knowledgePoint: item.knowledgePoint || kpList[0] || '未标注知识点',
errorDiagnosis: normalizedDiagnosis,
errorDiagnosisLabel: normalizedDiagnosis ? normalizedDiagnosis.primaryLabel : errorDiagnosis.labelOf(item.error_type || 'unknown')
};
},
_showAppOptions(opts) {
const dialog = this.selectComponent('#appDialog');
if (!dialog || typeof dialog.showOptions !== 'function') return Promise.resolve(-1);
return dialog.showOptions(opts || {});
},
onWrongRowTap(e) {
if (this.data.batchDiagnosisMode) this.toggleBatchWrong(e);
else this.openWrongDetail(e);
},
toggleBatchDiagnosisMode() {
if (this.data.batchDiagnosisSaving) return;
const next = !this.data.batchDiagnosisMode;
this.setData({
batchDiagnosisMode: next,
batchSelectedMap: {},
batchSelectedCount: 0,
});
},
toggleBatchWrong(e) {
if (!this.data.batchDiagnosisMode || this.data.batchDiagnosisSaving) return;
const wqId = Number(e.currentTarget.dataset.wqid || 0);
if (!wqId) return;
const selected = Object.assign({}, this.data.batchSelectedMap || {});
if (selected[wqId]) delete selected[wqId];
else selected[wqId] = true;
this.setData({
batchSelectedMap: selected,
batchSelectedCount: Object.keys(selected).length,
});
},
toggleSelectAllWrong() {
if (!this.data.batchDiagnosisMode || this.data.batchDiagnosisSaving) return;
const rows = (this.data.wrongReviewItems || []).filter(item => Number(item.wrongQuestionId) > 0);
const allSelected = rows.length > 0 && rows.every(item => (this.data.batchSelectedMap || {})[Number(item.wrongQuestionId)]);
const selected = {};
if (!allSelected) rows.forEach(item => { selected[Number(item.wrongQuestionId)] = true; });
this.setData({
batchSelectedMap: selected,
batchSelectedCount: Object.keys(selected).length,
});
},
async applyBatchDiagnosis() {
if (this.data.batchDiagnosisSaving) return;
const selectedIds = Object.keys(this.data.batchSelectedMap || {})
.filter(key => this.data.batchSelectedMap[key])
.map(Number)
.filter(id => Number.isFinite(id) && id > 0);
if (!selectedIds.length) {
wx.showToast({ title: '请先选择错题', icon: 'none' });
return;
}
const options = errorDiagnosis.QUICK_TYPES;
const index = await this._showAppOptions({
title: `为 ${selectedIds.length} 道错题设置错因`,
items: options.map(item => item.label),
});
const picked = options[index];
if (!picked) return;
this._diagnosisRefreshSeq = (this._diagnosisRefreshSeq || 0) + 1;
const byId = {};
;(this.data.wrongReviewItems || []).forEach(item => {
const id = Number(item.wrongQuestionId || 0);
if (id > 0) byId[id] = item;
});
this.setData({ batchDiagnosisSaving: true });
const results = await Promise.all(selectedIds.map(async (wqId) => {
const target = byId[wqId] || null;
try {
const raw = await api.put(`/wrong-questions/${wqId}/diagnosis`, {
diagnosis_id: target && target.errorDiagnosis ? Number(target.errorDiagnosis.id || 0) || undefined : undefined,
primary_type: picked.type,
secondary_types: [],
});
return { wqId, ok: true, diagnosis: errorDiagnosis.normalizeDiagnosis(raw) };
} catch (error) {
return { wqId, ok: false, error };
}
}));
if (!this._pageAlive) return;
const succeeded = results.filter(item => item.ok);
const successMap = {};
succeeded.forEach(item => { successMap[item.wqId] = item.diagnosis; });
const update = (list) => (list || []).map(item => {
const id = Number(item.wrongQuestionId || 0);
if (!successMap[id]) return item;
return Object.assign({}, item, {
errorDiagnosis: successMap[id],
errorDiagnosisLabel: picked.label,
});
});
const failedCount = results.length - succeeded.length;
this.setData({
reviewItems: update(this.data.reviewItems),
filteredReviewItems: update(this.data.filteredReviewItems),
wrongReviewItems: update(this.data.wrongReviewItems),
batchDiagnosisSaving: false,
batchDiagnosisMode: failedCount > 0,
batchSelectedMap: failedCount > 0
? results.reduce((map, item) => { if (!item.ok) map[item.wqId] = true; return map; }, {})
: {},
batchSelectedCount: failedCount,
});
if (!failedCount) wx.showToast({ title: `已标记 ${succeeded.length} 题`, icon: 'success' });
else wx.showToast({ title: `成功 ${succeeded.length} 题，${failedCount} 题失败`, icon: 'none' });
},
buildLocalErrorDistribution(wrongItems) {
return _buildLocalErrorDistribution(wrongItems);
},
getResultTip(accuracy, wrongCount, skippedCount, partialCount, totalCount) {
return _getResultTip(accuracy, wrongCount, skippedCount, partialCount, totalCount);
},
async loadDashboardData() {
if (!this._pageAlive) return;
const loadId = ++this._dashboardLoadId;
await Promise.allSettled([
this.loadTrends(loadId),
this.loadGrowth(loadId)
]);
},
_isDashboardLoadCurrent(loadId) {
return this._pageAlive && loadId === this._dashboardLoadId;
},
async loadTrends(loadId = this._dashboardLoadId) {
if (!this._isDashboardLoadCurrent(loadId)) return;
this.setData({ trendLoading: true });
try {
const raw = await this.requestApi('/api/v1/stats/trends', { days: 7 });
if (!this._isDashboardLoadCurrent(loadId)) return;
const list = Array.isArray(raw)
? raw
: Array.isArray(raw && raw.items)
? raw.items
: Array.isArray(raw && raw.data)
? raw.data
: [];
if (list.length) {
const trendData = list.slice(-7).map(item => ({
date: item.date || '',
accuracy: normalizePercent(item.accuracy),
questions: Number(item.questions ?? item.answer_count ?? item.answered ?? 0) || 0
}));
const nonEmpty = trendData.filter(item => item.questions > 0);
let trendSummary = '近 7 天';
if (nonEmpty.length >= 2) {
const first = nonEmpty[0].accuracy;
const last = nonEmpty[nonEmpty.length - 1].accuracy;
const diff = last - first;
trendSummary = diff > 0 ? `提升 ${diff}%` : diff < 0 ? `下降 ${Math.abs(diff)}%` : '表现稳定';
} else if (nonEmpty.length === 1) {
trendSummary = `当前 ${nonEmpty[0].accuracy}%`;
} else {
trendSummary = '暂无作答记录';
}
const plot = buildTrendPlot(trendData);
this.setData({
trendData,
trendPoints: plot.points,
trendSegments: plot.segments,
trendLastPoint: plot.lastPoint,
trendAreaStyle: plot.areaStyle,
trendSummary,
trendAvailable: true
});
} else {
this.setData({
trendData: [],
trendPoints: [],
trendSegments: [],
trendLastPoint: null,
trendAreaStyle: '',
trendSummary: '暂无历史数据',
trendAvailable: false
});
}
} catch (e) {
if (!this._isDashboardLoadCurrent(loadId)) return;
this.setData({
trendData: [],
trendPoints: [],
trendSegments: [],
trendLastPoint: null,
trendAreaStyle: '',
trendSummary: '趋势暂不可用',
trendAvailable: false
});
} finally {
if (!this._isDashboardLoadCurrent(loadId)) return;
this.setData({ trendLoading: false });
}
},
async loadGrowth(loadId = this._dashboardLoadId) {
if (!this._isDashboardLoadCurrent(loadId)) return;
let resolved = null;
const embedded = normalizeGrowthProfile(
this._sessionPayload && (
this._sessionPayload.growth ||
this._sessionPayload.growth_profile ||
this._sessionPayload.growthProfile ||
(this._sessionPayload.stats && this._sessionPayload.stats.growth)
)
);
if (embedded) resolved = embedded;
try {
const raw = await this.requestApi('/api/v1/stats/growth');
if (!this._isDashboardLoadCurrent(loadId)) return;
const growth = normalizeGrowthProfile(raw);
if (growth) resolved = growth;
} catch (e) {}
if (!resolved || (resolved.total_exp === 0 && this.data.totalCount > 0)) {
try {
const dashboard = await this.requestApi('/api/v1/stats/dashboard-v2', {
trend_days: 7,
include_yearly_summary: false,
include_growth: true,
include_adaptive: false
});
if (!this._isDashboardLoadCurrent(loadId)) return;
const growth = normalizeGrowthProfile(dashboard && dashboard.growth);
if (growth && (growth.total_exp > 0 || !resolved)) resolved = growth;
} catch (e) {}
}
if (!resolved || !this._isDashboardLoadCurrent(loadId)) {
if (this._isDashboardLoadCurrent(loadId)) this.setData({ growthAvailable: false });
return;
}
const unlockedBadgeCount = (resolved.badges || []).filter(item => item && item.unlocked).length;
this.setData({
growth: resolved,
growthAvailable: true,
unlockedBadgeCount
});
},
async loadBehavior(loadId = this._dashboardLoadId) {
if (!this._isDashboardLoadCurrent(loadId)) return;
try {
const raw = await this.requestApi('/api/v1/stats/behavior');
if (!this._isDashboardLoadCurrent(loadId)) return;
const dist = raw && Array.isArray(raw.error_type_distribution)
? raw.error_type_distribution
: [];
if (!dist.length) return;
const normalized = dist
.filter(item => item && Number(item.count) > 0)
.sort((a, b) => Number(b.count) - Number(a.count))
.slice(0, 5);
const total = normalized.reduce((sum, item) => sum + Number(item.count || 0), 0);
const errorDistribution = normalized.map((item, index) => ({
label: this.formatErrorType(item.type),
count: Number(item.count) || 0,
percent: total ? Math.round(Number(item.count || 0) / total * 100) : 0,
color: ERROR_COLORS[index % ERROR_COLORS.length]
}));
if (errorDistribution.length) {
this.setData({
errorDistribution,
errorDonutGradient: buildErrorDonutGradient(errorDistribution),
errorDonutSvg: buildErrorDonutSvg(errorDistribution)
});
}
} catch (e) {}
},
formatErrorType(type) {
const map = {
concept: '知识概念',
calculation: '计算失误',
careless: '粗心审题',
memory: '记忆偏差',
logic: '逻辑推理',
unknown: '其他',
null: '其他',
'': '其他'
};
return map[String(type)] || String(type || '其他');
},
requestApi(path, data = {}) {
const normalizedPath = String(path || '').replace(/^\/api\/v1(?=\/|$)/, '') || '/'
return api.get(normalizedPath, data)
},
switchTab(e) {
const key = e.currentTarget.dataset.key;
if (!key || key === this.data.activeTab) return;
this.setData({ activeTab: key });
},
switchQuestionFilter(e) {
const key = e.currentTarget.dataset.key || 'all';
if (key === this.data.questionFilter) return;
let filteredReviewItems = this.data.reviewItems;
if (key === 'correct') filteredReviewItems = filteredReviewItems.filter(item => item.status === 'correct');
if (key === 'wrong') filteredReviewItems = filteredReviewItems.filter(item => item.status === 'wrong');
if (key === 'skipped') filteredReviewItems = filteredReviewItems.filter(item => item.status === 'skipped');
if (key === 'partial') filteredReviewItems = filteredReviewItems.filter(item => item.status === 'partial');
this.setData({
questionFilter: key,
filteredReviewItems,
questionListHeightRpx: getQuestionListHeightRpx(filteredReviewItems.length)
});
},
openQuestionDetail(e) {
const id = e.currentTarget.dataset.id;
const target = this.data.reviewItems.find(item => String(item.questionId) === String(id));
if (!target) return;
if (target.status === 'wrong') {
if (target.wrongQuestionId) {
this.navigateToWrongDetail(target.wrongQuestionId);
} else {
this.setData({ activeTab: 'wrong' });
wx.showToast({ title: '该题暂无错题详情', icon: 'none' });
}
} else {
const statusLabel = target.status === 'partial'
? '未完成'
: (target.status === 'skipped' ? '已跳过' : '已答对');
const title = target.status === 'partial'
? '未完成题复盘'
: (target.status === 'skipped' ? '跳过题复盘' : '题目复盘');
const analysisView = buildReviewAnalysisView(target.analysis);
this._teacherRequestSeq++;
this._activeTeacherCacheKey = '';
this.setData({
reviewDialogVisible: true,
teacherSheetVisible: false,
teacherLoading: false,
teacherResult: null,
teacherErrorText: '',
teacherFeedbackSent: '',
reviewDialog: {
title,
questionTitle: target.title || '',
status: target.status,
statusLabel,
userAnswer: target.userAnswer || '未作答',
correctAnswer: target.correctAnswer || '-',
analysisSections: analysisView.sections,
analysisFormatError: analysisView.formatError,
questionId: Number(target.questionId || 0),
questionVersionId: Number(target.questionVersionId || 0),
diagnosisId: target.errorDiagnosis ? Number(target.errorDiagnosis.id || 0) : 0
}
});
}
},
_teacherCacheKey(dialog, action) {
const d = dialog || {};
return [
Number(d.questionId || 0),
Number(d.questionVersionId || 0),
Number(d.diagnosisId || 0),
String(action || ''),
String(d.userAnswer || ''),
].join('|');
},
open408TeacherFromReview() {
const dialog = this.data.reviewDialog || {};
if (!dialog.questionId) return;
const action = dialog.status === 'correct' ? 'explain_correct' : 'core_concept';
this.run408TeacherFromReview(action);
},
select408TeacherAction(e) {
const action = String(e.currentTarget.dataset.action || '');
if (action) this.run408TeacherFromReview(action);
},
async run408TeacherFromReview(action) {
if (this.data.teacherLoading) {
this.setData({ teacherSheetVisible: true });
return;
}
const dialog = this.data.reviewDialog || {};
if (!dialog.questionId) return;
const cacheKey = this._teacherCacheKey(dialog, action);
const cached = this._teacherCache && this._teacherCache[cacheKey];
this._activeTeacherCacheKey = cacheKey;
if (cached) {
this.setData({
teacherLoading: false,
teacherResult: cached,
teacherErrorText: '',
teacherSheetVisible: true,
teacherFeedbackSent: (this._teacherFeedbackCache && this._teacherFeedbackCache[cacheKey]) || ''
});
return;
}
const requestSeq = ++this._teacherRequestSeq;
const questionId = Number(dialog.questionId);
const payload = {
question_id: questionId,
action: action
};
if (Number(dialog.questionVersionId) > 0) payload.question_version_id = Number(dialog.questionVersionId);
if (Number(dialog.diagnosisId) > 0) payload.diagnosis_id = Number(dialog.diagnosisId);
if (dialog.userAnswer && dialog.userAnswer !== '未作答') payload.user_answer = String(dialog.userAnswer);
if (!this._teacherInflight) this._teacherInflight = Object.create(null);
let requestPromise = this._teacherInflight[cacheKey];
if (!requestPromise) {
requestPromise = api.post('/ai/408-teacher', payload, { timeout: 55000 });
this._teacherInflight[cacheKey] = requestPromise;
}
this.setData({
teacherLoading: true,
teacherResult: null,
teacherErrorText: '',
teacherSheetVisible: true,
teacherFeedbackSent: ''
});
try {
const raw = await requestPromise;
const normalized = aiTeacher408.normalizeResult(raw);
if (!normalized) throw new Error('AI 返回格式异常');
if (!this._teacherCache) this._teacherCache = Object.create(null);
this._teacherCache[cacheKey] = normalized;
if (requestSeq !== this._teacherRequestSeq || !this._pageAlive) return;
if (Number((this.data.reviewDialog || {}).questionId) !== questionId) {
this.setData({ teacherLoading: false });
return;
}
this._activeTeacherCacheKey = cacheKey;
this.setData({ teacherLoading: false, teacherResult: normalized });
} catch (error) {
if (requestSeq !== this._teacherRequestSeq || !this._pageAlive) return;
this.setData({
teacherLoading: false,
teacherErrorText: aiTeacher408.errorMessage(error, api)
});
} finally {
if (this._teacherInflight && this._teacherInflight[cacheKey] === requestPromise) {
delete this._teacherInflight[cacheKey];
}
}
},
close408Teacher() {
this.setData({ teacherSheetVisible: false });
},
async feedback408Teacher(e) {
if (this.data.teacherFeedbackSent || !this.data.teacherResult) return;
const type = String(e.currentTarget.dataset.type || '');
const dialog = this.data.reviewDialog || {};
const questionId = Number(dialog.questionId || 0);
if (!type || !questionId) return;
try {
await aiTeacher408.submitFeedback(api, { questionId, feedbackType: type, result: this.data.teacherResult });
if (this._activeTeacherCacheKey) {
if (!this._teacherFeedbackCache) this._teacherFeedbackCache = Object.create(null);
this._teacherFeedbackCache[this._activeTeacherCacheKey] = type;
}
this.setData({ teacherFeedbackSent: type });
wx.showToast({ title: '反馈已记录', icon: 'success' });
} catch (error) {
wx.showToast({ title: api.getErrorMessage(error), icon: 'none' });
}
},
closeReviewDialog() {
if (!this.data.reviewDialogVisible) return;
this.setData({ reviewDialogVisible: false });
},
stopPropagation() {},
noop() {},
navigateToWrongDetail(wrongQuestionId) {
if (!wrongQuestionId || this._navigationLocked) return;
const normalizedCurrentId = Number(wrongQuestionId);
const ids = [];
const seen = new Set();
(this.data.wrongReviewItems || []).forEach(item => {
const id = Number(item && item.wrongQuestionId);
if (!Number.isFinite(id) || id <= 0 || seen.has(id)) return;
seen.add(id);
ids.push(id);
});
if (Number.isFinite(normalizedCurrentId) && normalizedCurrentId > 0 && !seen.has(normalizedCurrentId)) {
ids.unshift(normalizedCurrentId);
}
const currentIdx = Math.max(0, ids.indexOf(normalizedCurrentId));
try {
wx.setStorageSync('wrong_detail_nav', {
ids,
ts: Date.now(),
source: 'practice-result'
});
} catch (e) {
console.warn('保存答题结果错题导航上下文失败', e);
}
this._navigationLocked = true;
wx.navigateTo({
url: `/subpackages/study/wrong-detail/wrong-detail?id=${encodeURIComponent(wrongQuestionId)}&idx=${currentIdx}&source=practice-result`,
fail: () => {
this._navigationLocked = false;
if (this._pageAlive) {
wx.showToast({ title: '暂时无法打开题目详情', icon: 'none' });
}
}
});
},
openWrongDetail(e) {
const wrongQuestionId = e.currentTarget.dataset.wqid;
if (!wrongQuestionId) {
wx.showToast({
title: '该题暂无错题详情',
icon: 'none'
});
return;
}
this.navigateToWrongDetail(wrongQuestionId);
},
handleBack() {
if (this._navigationLocked) return;
this._navigationLocked = true;
const originalReturnTo = this._returnTo || '';
const fromKnowledgeDetail = this._launchSource === 'knowledge_map' &&
/^\/subpackages\/knowledge\/knowledge-detail\/index(?:\?.*)?$/.test(originalReturnTo);
const preferredReturnTo = fromKnowledgeDetail && this._launchSubjectId
? `/subpackages/knowledge/knowledge-subject/index?subject_id=${this._launchSubjectId}&restore_state=1`
: originalReturnTo;
const targetPath = String(preferredReturnTo || '').split('?')[0].replace(/^\//, '');
const fallback = () => {
this._navigationLocked = false;
if (preferredReturnTo) {
wx.redirectTo({
url: preferredReturnTo,
fail: () => wx.reLaunch({ url: '/pages/home/home' })
});
return;
}
wx.reLaunch({ url: '/pages/home/home' });
};
const findTargetIndex = (pages) => {
if (!targetPath || !Array.isArray(pages) || pages.length < 2) return -1;
for (let i = pages.length - 2; i >= 0; i -= 1) {
const page = pages[i] || {};
const route = String(page.route || '').replace(/^\//, '');
if (route !== targetPath) continue;
if (targetPath === 'subpackages/knowledge/knowledge-subject/index' && this._launchSubjectId) {
const pageSubjectId = Number(page.subjectId || (page.options && page.options.subject_id)) || 0;
if (pageSubjectId && pageSubjectId !== this._launchSubjectId) continue;
}
return i;
}
return -1;
};
const navigateExisting = (attempt = 0) => {
const pages = getCurrentPages ? getCurrentPages() : [];
const targetIndex = findTargetIndex(pages);
if (targetIndex < 0) {
if (pages.length > 1 && !preferredReturnTo) {
wx.navigateBack({
delta: 1,
fail: fallback
});
return;
}
fallback();
return;
}
const delta = Math.max(1, pages.length - 1 - targetIndex);
wx.navigateBack({
delta,
fail: () => {
if (attempt < 2) {
setTimeout(() => navigateExisting(attempt + 1), attempt === 0 ? 48 : 120);
return;
}
this._navigationLocked = false;
if (this._pageAlive) wx.showToast({ title: '返回失败，请再试一次', icon: 'none' });
}
});
};
navigateExisting(0);
},
});
