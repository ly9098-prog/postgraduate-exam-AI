const api = require('../../../utils/api');
const { knowledgePracticeSync } = require('../../../utils/storage');
const { getChinaDate } = require('../../../utils/china-time');
const errorDiagnosis = require('../utils/error-diagnosis');
const { buildLocalErrorDistribution: _buildLocalErrorDistribution, getResultTip: _getResultTip } = require('./utils/result-tips');
const { hasDetailedPracticePayload: _hasDetailedPayload, readSummaryFromOptions: _readSummaryFromOptions } = require('./utils/payload-readers');
const { isPayloadRequestValid: _isPayloadRequestValid, extractCreatedAtFromCacheKey } = require('./utils/cache-validation');
const { resolveResultCounts } = require('./utils/result-counts');
const { buildReviewItem: _buildReviewItem, normalizeReviewItem: _normalizeReviewItem } = require('./utils/review-item-builder');
const { normalizePercent: _normalizePercent, getQuestionListHeightRpx: _getQuestionListHeightRpx, formatDuration: _formatDuration, buildErrorDonutGradient: _buildErrorDonutGradient } = require('./utils/format-helpers');
const { stripLevelPrefix: _stripLevelPrefix, growthFromTotalExp: _growthFromTotalExp, normalizeGrowthProfile: _normalizeGrowthProfile, growthFromOverview: _growthFromOverview } = require('./utils/growth-helpers');
const { buildTrendPlot: _buildTrendPlot } = require('./utils/trend-plot-builder');
const { buildRecoveredResultPayload: _buildRecoveredResultPayload } = require('./utils/recovered-payload-builder');
const { normalizePracticeReturnRoute: _normalizePracticeReturnRoute, safeDecodeJson: _safeDecodeJson } = require('./utils/route-helpers');
const aiTeacher408 = require('../utils/ai-teacher-408');
const { safeDecodeURIComponent } = require('../utils/route-params');
const { formatMathPreviewText, formatAnswerPreview, normalizeReviewStatus, pad2, getQuestionTitle, normalizeKpList } = require('./utils/review-preview-format');
const { buildReviewAnalysisView } = require('./utils/review-analysis-view');
const {
  applyPracticePayloadOrchestration,
} = require('./utils/practice-payload-mapper');
const { createTrendLoadController } = require('./utils/trend-load-controller');
const { createReview408TeacherController } = require('./utils/review-408-teacher-controller');
const { createBatchDiagnosisController } = require('./utils/batch-diagnosis-controller');
const { createBackNavigationController } = require('./utils/back-navigation-controller');
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
function normalizePracticeReturnRoute(value) { return _normalizePracticeReturnRoute(value) }
function normalizePercent(value) { return _normalizePercent(value) }
function getQuestionListHeightRpx(count) { return _getQuestionListHeightRpx(count) }
function buildTrendPlot(data) { return _buildTrendPlot(data) }
function buildErrorDonutGradient(distribution) { return _buildErrorDonutGradient(distribution) }
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
function formatDuration(seconds) { return _formatDuration(seconds) }
function safeDecodeJson(value) { return _safeDecodeJson(value) }
function stripLevelPrefix(title, level) { return _stripLevelPrefix(title, level) }
function growthFromTotalExp(totalExp, streakDays, badges) { return _growthFromTotalExp(totalExp, streakDays, badges) }
function normalizeGrowthProfile(raw) { return _normalizeGrowthProfile(raw) }
function growthFromOverview(overview) { return _growthFromOverview(overview) }
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
return _hasDetailedPayload(payload);
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
return _readSummaryFromOptions(options);
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
return _isPayloadRequestValid(value, expectedRequestId);
},
_isResultCacheValid(value, expectedCacheKey, expectedRequestId) {
if (!value || typeof value !== 'object') return false;
if (expectedCacheKey && String(value._cacheKey || '') !== expectedCacheKey) return false;
if (!this._isPayloadRequestValid(value, expectedRequestId)) return false;
const currentUserId = this._getCurrentUserId();
const cachedUserId = value._userId === undefined || value._userId === null ? '' : String(value._userId);
if (cachedUserId && (!currentUserId || cachedUserId !== currentUserId)) return false;
let createdAt = Number(value._createdAt || 0);
if (!(createdAt > 0)) createdAt = extractCreatedAtFromCacheKey(value._cacheKey);
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
    return _buildRecoveredResultPayload(submission, submitResult, String((options || {})._ck || ""));
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
    return this._practicePayloadController().apply(payload)
  },

  _practicePayloadController() {
    if (!this._practicePayloadCtl) {
      this._practicePayloadCtl = {
        apply: payload => applyPracticePayloadOrchestration(
          payload, this._practicePayloadPorts(), this._practicePageState()
        ),
      }
    }
    return this._practicePayloadCtl
  },

  _practicePageState() {
    return {
      incrementDiagnosisRefreshSeq: () => { this._diagnosisRefreshSeq = (this._diagnosisRefreshSeq || 0) + 1 },
      setSessionPayload: source => { this._sessionPayload = source },
      isPageAlive: () => this._pageAlive,
      isResultVisible: () => this._resultVisible,
      setData: patch => this.setData(patch),
      refreshWrongDiagnoses: () => this.refreshWrongDiagnoses(),
    }
  },

  _practicePayloadPorts() {
    if (!this._practicePayloadPortsCached) {
      this._practicePayloadPortsCached = {
        buildReviewItem: (q, r, a, i) => this.buildReviewItem(q, r, a, i),
        normalizeReviewItem: (item, index) => this.normalizeReviewItem(item, index),
        resolveResultCounts: (source, reviewItems) => resolveResultCounts(source, reviewItems),
        normalizePercent,
        formatDuration,
        getQuestionListHeightRpx,
        buildErrorDonutGradient,
        buildErrorDonutSvg,
        normalizeGrowthProfile,
        buildLocalErrorDistribution: items => this.buildLocalErrorDistribution(items),
        getResultTip: (acc, wrong, skipped, partial, total) =>
          this.getResultTip(acc, wrong, skipped, partial, total),
        getLaunchKnowledgePointId: () => this._launchKnowledgePointId,
        getLaunchSource: () => this._launchSource,
        getLaunchSubjectId: () => this._launchSubjectId,
        getPracticeRequestId: () => this._practiceRequestId,
        recordKnowledgePractice: data => knowledgePracticeSync.record(data),
        consumeKnowledgeBaseline: (subjectId, kpId) =>
          knowledgePracticeSync.consumeBaseline(subjectId, kpId),
      };
    }
    return this._practicePayloadPortsCached;
  },
buildReviewItem(question, result, answer, index) {
  return _buildReviewItem(question, result, answer, index, { normalizeReviewStatus, pad2, getQuestionTitle, formatAnswerPreview, formatMathPreviewText, normalizeKpList });
},
normalizeReviewItem(item, index) {
  return _normalizeReviewItem(item, index, { normalizeReviewStatus, pad2, getQuestionTitle, formatAnswerPreview, formatMathPreviewText, normalizeKpList });
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
    return this._batchDiagnosisController().apply()
  },

  _batchDiagnosisController() {
    if (!this._batchDiagnosis) {
      this._batchDiagnosis = createBatchDiagnosisController({
        getBatchDiagnosisSaving: () => this.data.batchDiagnosisSaving,
        getBatchSelectedMap: () => this.data.batchSelectedMap,
        getWrongReviewItems: () => this.data.wrongReviewItems,
        getReviewItems: () => this.data.reviewItems,
        getFilteredReviewItems: () => this.data.filteredReviewItems,
        isPageAlive: () => this._pageAlive,
        setData: patch => this.setData(patch),
        showToast: options => wx.showToast(options),
        getQuickTypes: () => errorDiagnosis.QUICK_TYPES,
        showOptions: opts => this._showAppOptions(opts),
        incrementDiagnosisRefreshSeq: () => { this._diagnosisRefreshSeq = (this._diagnosisRefreshSeq || 0) + 1 },
        putDiagnosis: (wqId, payload) => api.put(`/wrong-questions/${wqId}/diagnosis`, payload),
        normalizeDiagnosis: raw => errorDiagnosis.normalizeDiagnosis(raw),
      })
    }
    return this._batchDiagnosis
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
    return this._trendLoadController().load(loadId)
  },

  _trendLoadController() {
    if (!this._trendLoad) {
      this._trendLoad = createTrendLoadController({
        isLoadCurrent: id => this._isDashboardLoadCurrent(id),
        setData: patch => this.setData(patch),
        requestTrends: () => this.requestApi('/api/v1/stats/trends', { days: 7 }),
        normalizePercent,
        buildTrendPlot: data => buildTrendPlot(data),
      })
    }
    return this._trendLoad
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
    return this._review408TeacherController().run(action)
  },

  _review408TeacherController() {
    if (!this._review408Teacher) {
      this._review408Teacher = createReview408TeacherController({
        getTeacherLoading: () => this.data.teacherLoading,
        getReviewDialog: () => this.data.reviewDialog,
        setData: patch => this.setData(patch),
        buildCacheKey: (dialog, action) => this._teacherCacheKey(dialog, action),
        getCacheEntry: key => this._teacherCache && this._teacherCache[key],
        setCacheEntry: (key, value) => {
          if (!this._teacherCache) this._teacherCache = Object.create(null)
          this._teacherCache[key] = value
        },
        getFeedbackEntry: key => (this._teacherFeedbackCache && this._teacherFeedbackCache[key]) || '',
        setActiveCacheKey: key => { this._activeTeacherCacheKey = key },
        getInflight: key => {
          if (!this._teacherInflight) this._teacherInflight = Object.create(null)
          return this._teacherInflight[key]
        },
        setInflight: (key, promise) => {
          if (!this._teacherInflight) this._teacherInflight = Object.create(null)
          this._teacherInflight[key] = promise
        },
        deleteInflight: key => { delete this._teacherInflight[key] },
        nextRequestSequence: () => ++this._teacherRequestSeq,
        getRequestSequence: () => this._teacherRequestSeq,
        isPageAlive: () => this._pageAlive,
        postTeacher: payload => api.post('/ai/408-teacher', payload, { timeout: 55000 }),
        normalizeResult: raw => aiTeacher408.normalizeResult(raw),
        errorMessage: error => aiTeacher408.errorMessage(error, api),
      })
    }
    return this._review408Teacher
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
    return this._backNavigationController().back()
  },

  _backNavigationController() {
    if (!this._backNavigation) {
      this._backNavigation = createBackNavigationController({
        getNavigationLocked: () => this._navigationLocked,
        setNavigationLocked: value => { this._navigationLocked = value },
        getReturnTo: () => this._returnTo || '',
        getLaunchSource: () => this._launchSource,
        getLaunchSubjectId: () => this._launchSubjectId,
        isPageAlive: () => this._pageAlive,
        getCurrentPages: () => (typeof getCurrentPages === 'function' ? getCurrentPages() : []),
        navigateBack: options => wx.navigateBack(options),
        redirectTo: options => wx.redirectTo(options),
        reLaunch: options => wx.reLaunch(options),
        showToast: options => wx.showToast(options),
        setTimeout,
      })
    }
    return this._backNavigation
  },
});
