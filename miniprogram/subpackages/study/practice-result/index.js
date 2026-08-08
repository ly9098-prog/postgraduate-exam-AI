const ERROR_COLORS = ['#B8FF13', '#78D74D', '#43B968', '#238E58', '#86A83E', '#C9DC73'];

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

function pad2(n) {
  return String(Math.max(0, Number(n) || 0)).padStart(2, '0');
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

function getQuestionTitle(question) {
  if (!question) return '';
  const content = question.content || {};
  return (
    content.stem ||
    content.text ||
    question.stem ||
    question.text ||
    question.title ||
    ''
  ).replace(/\s+/g, ' ').trim();
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

function unwrapApiBody(body) {
  let current = body;
  for (let i = 0; i < 3; i += 1) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) break;

    if (
      Object.prototype.hasOwnProperty.call(current, 'data') &&
      current.data !== null &&
      typeof current.data === 'object'
    ) {
      const keys = Object.keys(current);
      const wrapperKeys = ['data', 'code', 'message', 'msg', 'success', 'status'];
      const looksWrapped = keys.every(key => wrapperKeys.indexOf(key) !== -1);
      if (looksWrapped) {
        current = current.data;
        continue;
      }
    }

    if (
      Object.prototype.hasOwnProperty.call(current, 'result') &&
      current.result !== null &&
      typeof current.result === 'object' &&
      Object.keys(current).length <= 4
    ) {
      current = current.result;
      continue;
    }
    break;
  }
  return current;
}

function extractToken(value) {
  if (!value) return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value !== 'object') return '';

  const keys = [
    'access_token',
    'accessToken',
    'token',
    'authToken',
    'auth_token',
    'userToken',
    'jwt'
  ];
  for (const key of keys) {
    if (typeof value[key] === 'string' && value[key].trim()) return value[key].trim();
  }

  const nestedKeys = ['auth', 'tokenInfo', 'loginInfo', 'session', 'user'];
  for (const key of nestedKeys) {
    const nested = extractToken(value[key]);
    if (nested) return nested;
  }
  return '';
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

function resolveApiUrl(baseUrl, path) {
  const rawBase = String(baseUrl || '').trim().replace(/\/+$/, '');
  const rawPath = String(path || '').trim();
  if (!rawBase) return '';
  if (/^https?:\/\//i.test(rawPath)) return rawPath;

  const normalizedPath = rawPath.charAt(0) === '/' ? rawPath : `/${rawPath}`;

  if (/\/api\/v1$/i.test(rawBase) && normalizedPath.indexOf('/api/v1/') === 0) {
    return `${rawBase}${normalizedPath.slice('/api/v1'.length)}`;
  }
  if (/\/api$/i.test(rawBase) && normalizedPath.indexOf('/api/') === 0) {
    return `${rawBase}${normalizedPath.slice('/api'.length)}`;
  }
  if (/\/v1$/i.test(rawBase) && normalizedPath.indexOf('/api/v1/') === 0) {
    return `${rawBase}${normalizedPath.slice('/api/v1'.length)}`;
  }
  return `${rawBase}${normalizedPath}`;
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
      { key: 'wrong', label: '答错' }
    ],
    questionFilter: 'all',

    subjectName: '',
    correctCount: 0,
    wrongCount: 0,
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
    trendSummary: '近 7 天',
    trendLoading: true,

    growthGain: 0,
    growth: DEFAULT_GROWTH,
    unlockedBadgeCount: 0
  },

  onLoad(options) {
    this._pageReady = false;
    this._sessionPayload = null;

    this.bindEventChannel();
    const optionPayload = this.readPayloadFromOptions(options || {});
    const cachePayload = optionPayload ? null : this.readPayloadFromCache();
    this.applyPracticePayload(optionPayload || cachePayload || {});

    this.loadDashboardData();
  },

  onReady() {
    this._pageReady = true;
    this.drawVisibleCharts();
  },

  onShow() {
    if (this._pageReady) this.drawVisibleCharts();
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

  readPayloadFromCache() {
    const keys = [
      'practiceResult',
      'practice_result',
      'lastPracticeResult',
      'practiceSessionResult'
    ];
    for (const key of keys) {
      try {
        const value = wx.getStorageSync(key);
        if (value && typeof value === 'object') return value;
        const parsed = safeDecodeJson(value);
        if (parsed) return parsed;
      } catch (e) {}
    }
    return null;
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

    let correctCount = Number.isFinite(Number(explicitCorrect))
      ? Number(explicitCorrect)
      : reviewItems.filter(item => item.isCorrect).length;

    let wrongCount = Number.isFinite(Number(explicitWrong))
      ? Number(explicitWrong)
      : reviewItems.filter(item => !item.isCorrect).length;

    let totalCount =
      Number(source.totalCount ?? source.total_count ?? source.total) ||
      (correctCount + wrongCount) ||
      reviewItems.length;

    if (!correctCount && !wrongCount && reviewItems.length) {
      correctCount = reviewItems.filter(item => item.isCorrect).length;
      wrongCount = reviewItems.length - correctCount;
      totalCount = reviewItems.length;
    }

    const explicitAccuracy = source.accuracy ?? source.accuracyPct ?? source.correctRate ?? source.correct_rate;
    const accuracyPct = explicitAccuracy !== undefined && explicitAccuracy !== null
      ? normalizePercent(explicitAccuracy)
      : (totalCount ? Math.round(correctCount / totalCount * 100) : 0);

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

    const wrongReviewItems = reviewItems.filter(item => !item.isCorrect);
    const localErrorDistribution = this.buildLocalErrorDistribution(wrongReviewItems);

    const resultTip = this.getResultTip(accuracyPct, wrongCount);

    this.setData({
      subjectName,
      correctCount,
      wrongCount,
      totalCount,
      accuracyPct,
      accuracyDotDeg: Math.round(accuracyPct * 3.6 - 90),
      durationText: formatDuration(usedTime),
      resultTip,
      growthGain,
      ...(embeddedGrowth ? {
        growth: embeddedGrowth,
        unlockedBadgeCount: embeddedGrowth.badges.filter(item => item && item.unlocked).length
      } : {}),
      reviewItems,
      filteredReviewItems: reviewItems,
      wrongReviewItems,
      errorDistribution: localErrorDistribution,
    }, () => {
      if (this._pageReady) this.drawVisibleCharts();
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

    const kpList = normalizeKpList(
      result.knowledge_points ??
      result.knowledgePoints ??
      question.knowledge_points ??
      question.knowledgePoints
    );

    return {
      questionId,
      displayIndex: pad2(index + 1),
      title: getQuestionTitle(question) || `第 ${index + 1} 题`,
      isCorrect: !!isCorrectRaw,
      userAnswer: answer.user_answer ?? answer.userAnswer ?? result.user_answer ?? result.userAnswer ?? '',
      correctAnswer: result.correct_answer ?? result.correctAnswer ?? question.answer ?? '',
      analysis: result.analysis ?? question.analysis ?? '',
      knowledgePoints: kpList,
      knowledgePoint: kpList[0] || '未标注知识点'
    };
  },

  normalizeReviewItem(item, index) {
    const isCorrectRaw = item.is_correct ?? item.isCorrect ?? item.correct ?? false;
    const kpList = normalizeKpList(item.knowledge_points ?? item.knowledgePoints ?? item.knowledgePoint);
    return {
      questionId: item.questionId ?? item.question_id ?? item.id ?? index + 1,
      displayIndex: item.displayIndex || pad2(index + 1),
      title: item.title || getQuestionTitle(item) || `第 ${index + 1} 题`,
      isCorrect: !!isCorrectRaw,
      userAnswer: item.userAnswer ?? item.user_answer ?? item.wrong_answer ?? '',
      correctAnswer: item.correctAnswer ?? item.correct_answer ?? item.answer ?? '',
      analysis: item.analysis ?? '',
      knowledgePoints: kpList,
      knowledgePoint: item.knowledgePoint || kpList[0] || '未标注知识点'
    };
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

  getResultTip(accuracy, wrongCount) {
    if (wrongCount === 0 && this.data.totalCount > 0) return '本组表现稳定，可以继续挑战更高难度。';
    if (accuracy >= 80) return '整体掌握较好，建议快速复盘错题后继续练习。';
    if (accuracy >= 60) return '基础已掌握，优先复盘错题对应知识点。';
    return '本组错题较多，建议先定位错误原因，再进行同类题巩固。';
  },

  async loadDashboardData() {
    await Promise.allSettled([
      this.loadTrends(),
      this.loadGrowth(),
      this.loadBehavior()
    ]);

    if (this._pageReady) this.drawVisibleCharts();
  },

  async loadTrends() {
    this.setData({ trendLoading: true });
    try {
      const raw = await this.requestApi('/api/v1/stats/trends', { days: 7 });
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
        }

        this.setData({ trendData, trendSummary });
      } else {
        this.setData({ trendData: this.buildFallbackTrend() });
      }
    } catch (e) {
      this.setData({ trendData: this.buildFallbackTrend() });
    } finally {
      this.setData({ trendLoading: false }, () => {
        if (this._pageReady && this.data.activeTab === 'overview') this.drawTrendChart();
      });
    }
  },

  buildFallbackTrend() {
    const today = new Date();
    const list = [];
    for (let i = 6; i >= 0; i -= 1) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const mm = pad2(d.getMonth() + 1);
      const dd = pad2(d.getDate());
      list.push({
        date: `${d.getFullYear()}-${mm}-${dd}`,
        accuracy: i === 0 ? this.data.accuracyPct : 0,
        questions: i === 0 ? this.data.totalCount : 0
      });
    }
    return list;
  },

  async loadGrowth() {
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
        const growth = normalizeGrowthProfile(dashboard && dashboard.growth);
        if (growth && (growth.total_exp > 0 || !resolved)) resolved = growth;
      } catch (e) {}
    }

    // 4. 成长接口仍为 0 时，用 overview 按后端 stats_service.py 的同一公式计算。
    if (!resolved || (resolved.total_exp === 0 && this.data.totalCount > 0)) {
      try {
        const overview = await this.requestApi('/api/v1/stats/overview');
        const growth = growthFromOverview(overview);
        if (growth && (growth.total_exp > 0 || !resolved)) resolved = growth;
      } catch (e) {}
    }

    // 5. 最后才做本地兜底：当前页已有练习结果时不再展示 0 / 200。
    if (!resolved || (resolved.total_exp === 0 && this.data.totalCount > 0)) {
      const localQuestionCount = Math.max(
        Number(this.data.totalCount) || 0,
        Array.isArray(this.data.reviewItems) ? this.data.reviewItems.length : 0
      );
      const localExp = Math.max(
        Number(this.data.growthGain) || 0,
        localQuestionCount * 10
      );
      resolved = growthFromTotalExp(localExp, localQuestionCount > 0 ? 1 : 0);
    }

    if (!resolved) return;

    const unlockedBadgeCount = (resolved.badges || []).filter(item => item && item.unlocked).length;
    this.setData({
      growth: resolved,
      unlockedBadgeCount
    });
  },

  async loadBehavior() {
    try {
      const raw = await this.requestApi('/api/v1/stats/behavior');
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
        this.setData({ errorDistribution }, () => {
          if (this._pageReady && this.data.activeTab === 'overview') this.drawErrorChart();
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
    return new Promise((resolve, reject) => {
      let app = null;
      try {
        app = typeof getApp === 'function' ? getApp() : null;
      } catch (e) {}

      const globalData = (app && app.globalData) || {};
      const config = globalData.config || globalData.env || globalData.apiConfig || {};

      const baseCandidates = [
        globalData.apiBaseUrl,
        globalData.apiBaseURL,
        globalData.apiBase,
        globalData.baseUrl,
        globalData.baseURL,
        globalData.baseApi,
        globalData.apiHost,
        globalData.host,
        globalData.serverUrl,
        globalData.serverURL,
        globalData.apiUrl,
        globalData.apiURL,
        config.apiBaseUrl,
        config.apiBaseURL,
        config.baseUrl,
        config.baseURL,
        config.apiHost,
        config.host
      ];

      const storageBaseKeys = [
        'apiBaseUrl',
        'apiBaseURL',
        'baseUrl',
        'baseURL',
        'apiHost',
        'serverUrl',
        'serverURL'
      ];
      storageBaseKeys.forEach(key => {
        try {
          const value = wx.getStorageSync(key);
          if (value) baseCandidates.push(value);
        } catch (e) {}
      });

      const baseUrl = baseCandidates
        .map(value => typeof value === 'string' ? value.trim() : '')
        .find(Boolean) || '';

      const url = resolveApiUrl(baseUrl, path);
      if (!url) {
        reject(new Error('API base URL not found'));
        return;
      }

      const tokenSources = [
        globalData.access_token,
        globalData.accessToken,
        globalData.token,
        globalData.authToken,
        globalData.auth,
        globalData.tokenInfo,
        globalData.loginInfo,
        globalData.user
      ];

      const tokenKeys = [
        'access_token',
        'accessToken',
        'token',
        'authToken',
        'auth_token',
        'userToken',
        'jwt',
        'tokenInfo',
        'loginInfo',
        'auth',
        'userInfo',
        'user'
      ];
      tokenKeys.forEach(key => {
        try {
          const value = wx.getStorageSync(key);
          if (value) tokenSources.push(value);
        } catch (e) {}
      });

      let token = '';
      for (const source of tokenSources) {
        token = extractToken(source);
        if (token) break;
      }

      const header = {
        'content-type': 'application/json',
        Accept: 'application/json'
      };
      if (token) {
        header.Authorization = /^Bearer\s/i.test(token) ? token : `Bearer ${token}`;
      }

      wx.request({
        url,
        method: 'GET',
        data,
        header,
        success: res => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(unwrapApiBody(res.data));
            return;
          }

          const detail = res && res.data && (res.data.detail || res.data.message || res.data.msg);
          reject(new Error(detail || `HTTP ${res.statusCode}`));
        },
        fail: reject
      });
    });
  },

  switchTab(e) {
    const key = e.currentTarget.dataset.key;
    if (!key || key === this.data.activeTab) return;
    this.setData({ activeTab: key }, () => {
      if (key === 'overview') {
        wx.nextTick(() => this.drawVisibleCharts());
      }
    });
  },

  switchQuestionFilter(e) {
    const key = e.currentTarget.dataset.key || 'all';
    let filteredReviewItems = this.data.reviewItems;
    if (key === 'correct') filteredReviewItems = filteredReviewItems.filter(item => item.isCorrect);
    if (key === 'wrong') filteredReviewItems = filteredReviewItems.filter(item => !item.isCorrect);
    this.setData({ questionFilter: key, filteredReviewItems });
  },

  openQuestionDetail(e) {
    const id = e.currentTarget.dataset.id;
    const target = this.data.reviewItems.find(item => String(item.questionId) === String(id));
    if (!target) return;

    if (!target.isCorrect) {
      this.setData({ activeTab: 'wrong' });
    } else {
      wx.showToast({
        title: `本题答对：${target.correctAnswer || '正确'}`,
        icon: 'none'
      });
    }
  },


  handleBack() {
    const pages = getCurrentPages ? getCurrentPages() : [];
    if (pages.length > 1) {
      wx.navigateBack({ delta: 1 });
    } else {
      wx.reLaunch({ url: '/pages/index/index' });
    }
  },

  drawVisibleCharts() {
    if (!this._pageReady || this.data.activeTab !== 'overview') return;
    wx.nextTick(() => {
      this.drawTrendChart();
      this.drawErrorChart();
    });
  },

  drawTrendChart() {
    const query = wx.createSelectorQuery().in(this);
    query.select('#trendCanvas').fields({ node: true, size: true }).exec(res => {
      const target = res && res[0];
      if (!target || !target.node || !target.width || !target.height) return;

      const canvas = target.node;
      const ctx = canvas.getContext('2d');
      const dpr = wx.getWindowInfo ? (wx.getWindowInfo().pixelRatio || 1) : (wx.getSystemInfoSync().pixelRatio || 1);

      canvas.width = target.width * dpr;
      canvas.height = target.height * dpr;
      ctx.scale(dpr, dpr);

      const width = target.width;
      const height = target.height;
      ctx.clearRect(0, 0, width, height);

      const data = (this.data.trendData || []).slice(-7);
      if (!data.length) return;

      const left = 34;
      const right = 18;
      const top = 18;
      const bottom = 42;
      const chartW = width - left - right;
      const chartH = height - top - bottom;

      ctx.lineWidth = 1;
      ctx.strokeStyle = '#E9EEEA';
      ctx.fillStyle = '#99A19C';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';

      [0, 50, 100].forEach(value => {
        const y = top + chartH * (1 - value / 100);
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(left + chartW, y);
        ctx.stroke();
        ctx.fillText(`${value}%`, left - 8, y);
      });

      const step = data.length > 1 ? chartW / (data.length - 1) : chartW;
      const points = data.map((item, index) => {
        const x = left + step * index;
        const y = top + chartH * (1 - clamp(item.accuracy, 0, 100) / 100);
        return { x, y, item };
      });

      const gradient = ctx.createLinearGradient(0, top, 0, top + chartH);
      gradient.addColorStop(0, 'rgba(53, 166, 87, .20)');
      gradient.addColorStop(1, 'rgba(53, 166, 87, 0)');

      if (points.length > 1) {
        ctx.beginPath();
        ctx.moveTo(points[0].x, top + chartH);
        points.forEach(point => ctx.lineTo(point.x, point.y));
        ctx.lineTo(points[points.length - 1].x, top + chartH);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        ctx.beginPath();
        points.forEach((point, index) => {
          if (index === 0) ctx.moveTo(point.x, point.y);
          else ctx.lineTo(point.x, point.y);
        });
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#319D54';
        ctx.stroke();
      }

      points.forEach((point, index) => {
        ctx.beginPath();
        ctx.arc(point.x, point.y, index === points.length - 1 ? 4 : 3, 0, Math.PI * 2);
        ctx.fillStyle = index === points.length - 1 ? '#2F9E54' : '#FFFFFF';
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#2F9E54';
        ctx.stroke();

        const dateText = String(point.item.date || '').slice(5).replace('-', '/');
        ctx.fillStyle = '#9AA29D';
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(dateText || `${index + 1}`, point.x, top + chartH + 13);
      });

      const last = points[points.length - 1];
      if (last) {
        const label = `${last.item.accuracy}%`;
        ctx.font = 'bold 10px sans-serif';
        const labelWidth = ctx.measureText(label).width + 12;
        const bx = Math.min(width - labelWidth - 4, Math.max(4, last.x - labelWidth / 2));
        const by = Math.max(2, last.y - 28);

        ctx.fillStyle = '#2E9250';
        ctx.beginPath();
        if (ctx.roundRect) {
          ctx.roundRect(bx, by, labelWidth, 20, 6);
        } else {
          ctx.rect(bx, by, labelWidth, 20);
        }
        ctx.fill();

        ctx.fillStyle = '#FFFFFF';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, bx + labelWidth / 2, by + 10);
      }
    });
  },

  drawErrorChart() {
    const query = wx.createSelectorQuery().in(this);
    query.select('#errorCanvas').fields({ node: true, size: true }).exec(res => {
      const target = res && res[0];
      if (!target || !target.node || !target.width || !target.height) return;

      const canvas = target.node;
      const ctx = canvas.getContext('2d');
      const dpr = wx.getWindowInfo ? (wx.getWindowInfo().pixelRatio || 1) : (wx.getSystemInfoSync().pixelRatio || 1);

      canvas.width = target.width * dpr;
      canvas.height = target.height * dpr;
      ctx.scale(dpr, dpr);

      const width = target.width;
      const height = target.height;
      ctx.clearRect(0, 0, width, height);

      const cx = width / 2;
      const cy = height / 2;
      const radius = Math.min(width, height) / 2 - 8;
      const lineWidth = Math.max(13, radius * .25);

      ctx.beginPath();
      ctx.arc(cx, cy, radius - lineWidth / 2, 0, Math.PI * 2);
      ctx.strokeStyle = '#EEF2EF';
      ctx.lineWidth = lineWidth;
      ctx.stroke();

      const data = this.data.errorDistribution || [];
      const total = data.reduce((sum, item) => sum + Number(item.count || 0), 0);
      if (!total) return;

      let start = -Math.PI / 2;
      data.forEach(item => {
        const ratio = Number(item.count || 0) / total;
        const gap = Math.min(.035, ratio * .12);
        const end = start + Math.PI * 2 * ratio;

        ctx.beginPath();
        ctx.arc(
          cx,
          cy,
          radius - lineWidth / 2,
          start + gap,
          end - gap
        );
        ctx.strokeStyle = item.color || '#37A7D8';
        ctx.lineWidth = lineWidth;
        ctx.lineCap = 'round';
        ctx.stroke();

        start = end;
      });
    });
  }
});
