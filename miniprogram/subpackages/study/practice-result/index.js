const { toPlainInlineMathText } = require('../utils/stem-render');
const { formatInlineMathText } = require('../utils/math-format');
const { normalizeAiAnalysisPayload, hasAiAnalysisContent } = require('../utils/ai-analysis-normalizer');
const api = require('../../../utils/api');
const { getChinaDate } = require('../../../utils/china-time');
const errorDiagnosis = require('../../../utils/error-diagnosis');

const ERROR_COLORS = ['#B8FF13', '#78D74D', '#43B968', '#238E58', '#86A83E', '#C9DC73'];
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

// 图表放在 scroll-view 内时，部分微信 Android 基础库会让 2D canvas
// 使用独立原生层，滚动后出现“画布留在原位、图形漂到其它卡片”的错位。
// 结果页图表数据量很小，改用普通 view 绘制可彻底避开原生 canvas 层。
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
    ? ['0% 100%', ...points.map(point => `${point.leftPct}% ${point.topPct}%`), '100% 100%']
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
  // 原 Canvas 的 210rpx 只是容器尺寸；实际绘制尺寸由 selectorQuery 返回的
  // CSS px 决定，且圆环固定向内缩 8px。SVG 如果直接按 210x210 绘制会明显偏大。
  // 这里把 210rpx 换算回当前设备的 CSS px，逐项复刻原 drawErrorChart 的参数。
  let windowWidth = 375;
  try {
    if (typeof wx !== 'undefined') {
      const info = wx.getWindowInfo
        ? wx.getWindowInfo()
        : (wx.getSystemInfoSync ? wx.getSystemInfoSync() : null);
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

  // 复刻原生 Canvas 圆环，而不是做“近似的甜甜圈”。关键细节：
  // 1. 210rpx 容器内固定向内缩 8 CSS px；
  // 2. stroke 宽度为 max(13px, radius * .25)；
  // 3. 每段按原公式留 gap，并使用 round lineCap；
  // 4. 后画的分段覆盖前一段圆帽，保留原 UI 的圆润交界形态。
  // SVG 由普通 image 承载，因此不会重新触发 scroll-view 中 2D canvas 的原生层漂移。
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
  for (const text of candidates) {
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

  // 结果页题目列表是单行摘要，不适合直接挂 mp-html。
  // 优先复用题干渲染层的“列表预览”转换；复杂 LaTeX 再降级为 Unicode/纯文本形式，
  // 避免把 $...$、\leq、\frac 等源码直接显示给用户。
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

  // 只有能被实际解析为对象/文本数组，或出现明确结构化字段时才按 JSON
  // 处理，避免把“{x | x > 0}”“[1, 2] 区间”之类数学正文误判。
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

  // 解析正文允许多行展示；逐行复用题干的数学文本转换，避免 LaTeX 源码
  // 与 HTML 标签直接出现在复盘弹层中。
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
    // 模型经常把整段内容压成一个超长段落。仅在没有显式换行且文本较长时，
    // 按完整句号边界分组，不拆英文缩写、数字或公式内部内容。
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
  for (const key of keys) {
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

  // 兼容题库接口把普通解析包装成 {analysis/explanation/solution: ...}
  // 的 JSON。只提取白名单字段，未知结构仍不回显原始对象。
  if (!sections.length && structured) {
    const genericText = extractGenericReviewAnalysis(value);
    if (genericText) {
      sections.push({ key: 'analysis', title: '题目解析', tone: 'primary', text: genericText });
    }
  }

  // normalizer 对以 { / [ 开头的普通数学文字会采取保守策略。若本地判断
  // 它并非结构化响应，则恢复为普通解析文本，避免误伤集合/区间表达式。
  if (!sections.length && !structured && typeof value === 'string') {
    const plainFallback = formatReviewAnalysisText(value);
    if (plainFallback) {
      sections.push({ key: 'analysis', title: '题目解析', tone: 'primary', text: plainFallback });
    }
  }

  // 结构化内容解析失败时只展示友好状态，绝不回退到原始字符串，
  // 从根源上避免 {"knowledge_patch": ...} 之类后端 JSON 暴露给用户。
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
    content.stem ||
    content.text ||
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
      analysisFormatError: false
    },

    // 自定义导航栏不能只依赖 env(safe-area-inset-top)：部分 Android 真机
    // 会返回 0，导致返回按钮压到状态栏。这里使用微信运行时实测值。
    heroTopPaddingPx: 28
  },

  onLoad(options) {
    this._pageAlive = true;
    this._navigationLocked = false;
    this._sessionPayload = null;
    this._dashboardLoadId = 0;

    this.measureSafeNavigation();
    this.bindEventChannel();
    const optionPayload = this.readPayloadFromOptions(options || {});
    const cachePayload = optionPayload ? null : this.readPayloadFromCache(options || {});
    const primaryPayload = optionPayload || cachePayload;
    const summaryPayload = primaryPayload ? null : this.readSummaryFromOptions(options || {});
    this.applyPracticePayload(primaryPayload || summaryPayload || {});

    const requestId = String((options || {})._rid || '');
    if (primaryPayload && this._hasDetailedPracticePayload(primaryPayload)) {
      // The result page is the acknowledgement boundary for the persisted
      // idempotent submission snapshot. Navigation success alone is not enough.
      if (requestId) this._clearPendingSubmission(requestId);
    } else if (requestId) {
      // Always try the idempotent replay when detailed data is absent. `_recover`
      // is only a hint from the previous page and can be stale if local storage
      // was evicted between cache-write success and this page's onLoad.
      this.recoverSubmittedResult(options || {});
    }
    this.loadDashboardData();
  },

  onUnload() {
    this._pageAlive = false;
    this._dashboardLoadId++;
  },

  onShow() {
    this._navigationLocked = false;
  },

  measureSafeNavigation() {
    let statusBarHeight = 20;
    let menuTop = 0;
    try {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
      statusBarHeight = Math.max(0, Number(info.statusBarHeight) || 20);
    } catch (e) {}

    try {
      const menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect();
      if (menu && Number(menu.top) > 0) menuTop = Number(menu.top);
    } catch (e) {}

    // 与右上角胶囊顶部对齐；拿不到胶囊数据时至少避开系统状态栏。
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
          if (payload && typeof payload === 'object') {
            this.applyPracticePayload(payload);
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
      (Array.isArray(source.resultList) && source.resultList.length > 0) ||
      (Array.isArray(source.questions) && source.questions.length > 0);
  },

  readPayloadFromOptions(options) {
    const keys = ['payload', 'result', 'data', 'session', 'practiceResult'];
    for (const key of keys) {
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
      const id = user && (user.id ?? user.user_id ?? user.openid);
      return id === undefined || id === null ? '' : String(id);
    } catch (_) {
      return '';
    }
  },

  _isResultCacheValid(value, expectedCacheKey) {
    if (!value || typeof value !== 'object') return false;

    if (expectedCacheKey && String(value._cacheKey || '') !== expectedCacheKey) return false;

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
    const keys = [
      'practiceResult',
      'practice_result',
      'lastPracticeResult',
      'practiceSessionResult'
    ];
    for (const key of keys) {
      try {
        const value = wx.getStorageSync(key);
        if (value && typeof value === 'object' && this._isResultCacheValid(value, expectedCacheKey)) return value;
        const parsed = safeDecodeJson(value);
        if (parsed && this._isResultCacheValid(parsed, expectedCacheKey)) return parsed;
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
      _cacheKey: cacheKey,
      _userId: this._getCurrentUserId(),
      _createdAt: Date.now(),
    };
  },

  async recoverSubmittedResult(options) {
    const requestId = String((options || {})._rid || '');
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
    const source = payload && payload.data && !payload.results && typeof payload.data === 'object'
      ? payload.data
      : (payload || {});
    this._sessionPayload = source;

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
    // 与 PracticeRecord / 趋势接口统一：正确率只针对实际作答题。
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
      errorDistribution: localErrorDistribution,
      errorDonutGradient: buildErrorDonutGradient(localErrorDistribution),
      errorDonutSvg: buildErrorDonutSvg(localErrorDistribution)
    });
  },

  buildReviewItem(question, result, answer, index) {
    const questionId =
      question.id ??
      question.question_id ??
      question.questionId ??
      result.question_id ??
      result.questionId ??
      index + 1;

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
      errorDiagnosis: errorDiagnosis.normalizeDiagnosis(result.error_diagnosis ?? result.errorDiagnosis),
      errorDiagnosisLabel: errorDiagnosis.labelOf(
        (result.error_diagnosis && result.error_diagnosis.primary_type) ||
        (result.errorDiagnosis && result.errorDiagnosis.primaryType) ||
        'unknown'
      )
    };
  },

  normalizeReviewItem(item, index) {
    const isCorrectRaw = item.is_correct ?? item.isCorrect ?? item.correct ?? false;
    const status = normalizeReviewStatus(item, !!isCorrectRaw);
    const kpList = normalizeKpList(item.knowledge_points ?? item.knowledgePoints ?? item.knowledgePoint);
    return {
      questionId: item.questionId ?? item.question_id ?? item.id ?? index + 1,
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
      errorDiagnosis: errorDiagnosis.normalizeDiagnosis(item.errorDiagnosis ?? item.error_diagnosis),
      errorDiagnosisLabel: errorDiagnosis.labelOf(
        (item.errorDiagnosis && item.errorDiagnosis.primaryType) ||
        (item.error_diagnosis && item.error_diagnosis.primary_type) ||
        item.error_type || 'unknown'
      )
    };
  },

  quickClassifyWrong(e) {
    const wqId = Number(e.currentTarget.dataset.wqid || 0);
    if (!wqId) {
      wx.showToast({ title: '错题记录尚未就绪，可进入详情后标记', icon: 'none' });
      return;
    }
    const options = errorDiagnosis.QUICK_TYPES;
    wx.showActionSheet({
      itemList: options.map(item => item.label),
      success: async (res) => {
        const picked = options[Number(res.tapIndex)];
        if (!picked) return;
        try {
          const target = (this.data.wrongReviewItems || []).find(item => Number(item.wrongQuestionId) === wqId)
            || (this.data.reviewItems || []).find(item => Number(item.wrongQuestionId) === wqId);
          const raw = await api.put(`/wrong-questions/${wqId}/diagnosis`, {
            diagnosis_id: target && target.errorDiagnosis ? Number(target.errorDiagnosis.id || 0) || undefined : undefined,
            primary_type: picked.type,
            secondary_types: [],
          });
          const normalized = errorDiagnosis.normalizeDiagnosis(raw);
          const update = (list) => (list || []).map(item => item.wrongQuestionId === wqId
            ? Object.assign({}, item, { errorDiagnosis: normalized, errorDiagnosisLabel: picked.label })
            : item);
          this.setData({
            reviewItems: update(this.data.reviewItems),
            filteredReviewItems: update(this.data.filteredReviewItems),
            wrongReviewItems: update(this.data.wrongReviewItems),
          });
          wx.showToast({ title: '错因已记录', icon: 'success' });
        } catch (err) {
          wx.showToast({ title: api.getErrorMessage(err), icon: 'none' });
        }
      }
    });
  },

  buildLocalErrorDistribution(wrongItems) {
    if (!wrongItems.length) return [];
    const map = {};
    wrongItems.forEach(item => {
      const label = item.knowledgePoint || '其他';
      map[label] = (map[label] || 0) + 1;
    });

    const sorted = Object.keys(map)
      .map(label => ({ label, count: map[label] }))
      .sort((a, b) => b.count - a.count);

    let display = sorted.slice(0, 4);
    if (sorted.length > 4) {
      const rest = sorted.slice(4).reduce((sum, item) => sum + item.count, 0);
      display.push({ label: '其他', count: rest });
    }

    const total = display.reduce((sum, item) => sum + item.count, 0);
    return display.map((item, index) => ({
      ...item,
      percent: total ? Math.round(item.count / total * 100) : 0,
      color: ERROR_COLORS[index % ERROR_COLORS.length]
    }));
  },

  getResultTip(accuracy, wrongCount, skippedCount, partialCount, totalCount) {
    if (wrongCount === 0 && skippedCount === 0 && partialCount === 0 && Number(totalCount) > 0) return '本组表现稳定，可以继续挑战更高难度。';
    if (wrongCount === 0 && (skippedCount > 0 || partialCount > 0)) {
      const parts = [];
      if (partialCount > 0) parts.push(`${partialCount} 题未完成`);
      if (skippedCount > 0) parts.push(`${skippedCount} 题跳过`);
      return `本组有 ${parts.join('、')}，建议补看答案与解析后再继续。`;
    }
    if (accuracy >= 80) return '整体掌握较好，建议快速复盘错题后继续练习。';
    if (accuracy >= 60) return '基础已掌握，优先复盘错题对应知识点。';
    return '本组错题较多，建议先定位错误原因，再进行同类题巩固。';
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

    // 1. 优先使用练习提交结果里已经携带的成长数据，避免页面首屏闪 0。
    const embedded = normalizeGrowthProfile(
      this._sessionPayload && (
        this._sessionPayload.growth ||
        this._sessionPayload.growth_profile ||
        this._sessionPayload.growthProfile ||
        (this._sessionPayload.stats && this._sessionPayload.stats.growth)
      )
    );
    if (embedded) resolved = embedded;

    // 2. 后端独立成长接口是最完整的数据源。
    try {
      const raw = await this.requestApi('/api/v1/stats/growth');
      if (!this._isDashboardLoadCurrent(loadId)) return;
      const growth = normalizeGrowthProfile(raw);
      if (growth) resolved = growth;
    } catch (e) {}

    // 3. 若独立接口不可用，兼容后端聚合看板接口。
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

    // 不再用“本次题数 × 固定值”或本地公式伪造累计等级。权威成长接口
    // 都不可用时，结果页明确显示暂不可用，避免用户看到错误的 Lv1/Lv2。
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
    // This page previously bypassed the shared API client with a raw wx.request,
    // which broke auth refresh, correlation headers, and safe error handling.
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

      this.setData({
        reviewDialogVisible: true,
        reviewDialog: {
          title,
          questionTitle: target.title || '',
          status: target.status,
          statusLabel,
          userAnswer: target.userAnswer || '未作答',
          correctAnswer: target.correctAnswer || '-',
          analysisSections: analysisView.sections,
          analysisFormatError: analysisView.formatError
        }
      });
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

    // Preserve the current result group's wrong-question order so the detail
    // page can swipe left/right directly across this practice session instead
    // of forcing the user back to the result list for every question.
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
    const pages = getCurrentPages ? getCurrentPages() : [];
    if (pages.length > 1) {
      wx.navigateBack({ delta: 1 });
    } else {
      wx.reLaunch({ url: '/pages/home/home' });
    }
  },



});
