/**
 * test-review-today-interactions.js
 *
 * Regression test for review-today timer and batch-size switching.
 *
 * Tests pure functions exported by the page module and simulates
 * page state via Page() config capture mocking.
 */

/* eslint-disable no-console */
const assert = require('assert')
const path = require('path')
const fs = require('fs')

// ── Mock WeChat globals before requiring the page module ─────
global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375, pixelRatio: 2 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
  getPerformance() { return { now: function () { return Date.now() } } },
  getStorageSync() { return null },
  setStorageSync() {},
  setNavigationBarColor() {},
  showToast() {},
  showActionSheet(opts) {
    // Default mock: tap on index 0 (每组 5 道)
    if (typeof opts.success === 'function') {
      opts.success({ tapIndex: 0, cancel: false })
    }
  },
  createSelectorQuery() {
    return {
      in() { return this },
      select() { return this },
      fields() { return this },
      exec(cb) { cb && cb([]) },
    }
  },
}

// ── Pre-populate require.cache for utility modules ───────────
var apiMockPath = path.resolve(__dirname, '../utils/api.js')
var stemRenderPath = path.resolve(__dirname, '../subpackages/study/utils/stem-render.js')
var adapterPath = path.resolve(__dirname, '../subpackages/study/utils/question-runner-adapter.js')
var answerPath = path.resolve(__dirname, '../subpackages/study/utils/answer.js')
var subjectMetaPath = path.resolve(__dirname, '../utils/subject-meta.js')
var configPath = path.resolve(__dirname, '../config.js')
var debugPath = path.resolve(__dirname, '../utils/debug.js')

var apiMock = {
  get: function () { return Promise.resolve({}) },
  post: function () { return Promise.resolve({}) },
  now: function () { return Date.now() },
  createRequestId: function () {
    return 'req_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
  },
}
var stemRenderMock = {
  buildRenderModel: function () { return { mode: 'SEGMENTS', segments: [] } },
  setRenderGuardPage: function () {},
  resetRenderGuard: function () {},
  stripLeadingOptionLabel: function (k, v) { return v },
  toPlainInlineMathText: function () { return '' },
  needsRichRender: function () { return false },
  textToHtml: function () { return '' },
}
var adapterMock = {
  isMultiBlankChoice: function () { return false },
  getBlankOptionGroups: function () { return [] },
  enrichBlankOptionGroups: function () { return [] },
  enrichBlankOptionGroupsReadonly: function () { return [] },
  buildOptionList: function () { return [] },
  buildOptionListReadonly: function () { return [] },
  buildOptionListFromFlags: function () { return [] },
  computeAnsweredCount: function () { return 0 },
  buildAnsweredFlags: function () { return {} },
  applyAnsweredFlags: function (qs) { return qs },
  isQuestionAnswered: function () { return false },
  countAnswered: function () { return 0 },
  normalizeBlankAnswer: function () { return {} },
  serializeBlankAnswer: function () { return '' },
  getQuestionImages: function () { return [] },
  computeExtraImages: function () { return [] },
}
var answerMock = {
  isMultipleChoiceType: function () { return false },
  isTrueFalseType: function () { return false },
  normalizeChoiceAnswer: function () { return [] },
  serializeChoiceAnswer: function (a) { return a },
  serializeBlankAnswer: function () { return '' },
}
var subjectMetaMock = { getSubjectName: function (s) { return s || '' } }
var configMock = { DEV: false, enableMathImage: false }
var debugMock = {
  debugLog: function () {},
  isDebugMode: function () { return false },
  saveDebugSnapshot: function () {},
  createTraceId: function () { return '' },
  shouldDebugQuestion: function () { return false },
}

if (!require.cache) require.cache = {}
require.cache[apiMockPath] = { exports: apiMock }
require.cache[stemRenderPath] = { exports: stemRenderMock }
require.cache[adapterPath] = { exports: adapterMock }
require.cache[answerPath] = { exports: answerMock }
require.cache[subjectMetaPath] = { exports: subjectMetaMock }
require.cache[configPath] = { exports: configMock }
require.cache[debugPath] = { exports: debugMock }

// ── Mock Page() to capture config ──────────────────────────────
var capturedPageConfig = null
global.Page = function (config) {
  capturedPageConfig = config
}

// ── Load the page module ───────────────────────────────────────
var pagePath = path.join(__dirname, '../subpackages/study/review-today/review-today.js')
var pageModule
try {
  pageModule = require(pagePath)
} catch (e) {
  console.error('FAILED to load page module:', e.message)
  console.error(e.stack)
  process.exit(1)
}

var fn = pageModule || {}
var normalizeReviewBatchSize = fn.normalizeReviewBatchSize
var formatReviewElapsed = fn.formatReviewElapsed
var REVIEW_BATCH_SIZE_OPTIONS = fn.REVIEW_BATCH_SIZE_OPTIONS

var testsPassed = 0
var testsFailed = 0

function t(desc, fn) {
  try {
    fn()
    testsPassed++
    console.log('  ✓', desc)
  } catch (e) {
    testsFailed++
    console.error('  ✗', desc, '-', e.message)
  }
}

// ══════════════════════════════════════════════════════════════════
// 1. formatReviewElapsed tests
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 1. Timer format: formatReviewElapsed ---')

t('0 seconds → "00:00"', function () {
  assert.strictEqual(formatReviewElapsed(0), '00:00')
})

t('1 second → "00:01"', function () {
  assert.strictEqual(formatReviewElapsed(1), '00:01')
})

t('9 seconds → "00:09"', function () {
  assert.strictEqual(formatReviewElapsed(9), '00:09')
})

t('65 seconds → "01:05"', function () {
  assert.strictEqual(formatReviewElapsed(65), '01:05')
})

t('3600 seconds → "60:00"', function () {
  assert.strictEqual(formatReviewElapsed(3600), '60:00')
})

t('negative → "00:00"', function () {
  assert.strictEqual(formatReviewElapsed(-5), '00:00')
})

t('null → "00:00"', function () {
  assert.strictEqual(formatReviewElapsed(null), '00:00')
})

t('undefined → "00:00"', function () {
  assert.strictEqual(formatReviewElapsed(undefined), '00:00')
})

// ══════════════════════════════════════════════════════════════════
// 2. normalizeReviewBatchSize tests
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 2. Batch size: normalizeReviewBatchSize ---')

t('"20" → 20', function () {
  assert.strictEqual(normalizeReviewBatchSize('20'), 20)
})

t('15 → 10 (fallback)', function () {
  assert.strictEqual(normalizeReviewBatchSize(15), 10)
})

t('NaN → 10', function () {
  assert.strictEqual(normalizeReviewBatchSize(NaN), 10)
})

t('0 → 10', function () {
  assert.strictEqual(normalizeReviewBatchSize(0), 10)
})

t('-5 → 10', function () {
  assert.strictEqual(normalizeReviewBatchSize(-5), 10)
})

t('null → 10', function () {
  assert.strictEqual(normalizeReviewBatchSize(null), 10)
})

t('undefined → 10', function () {
  assert.strictEqual(normalizeReviewBatchSize(undefined), 10)
})

t('5 → 5', function () {
  assert.strictEqual(normalizeReviewBatchSize(5), 5)
})

t('10 → 10', function () {
  assert.strictEqual(normalizeReviewBatchSize(10), 10)
})

t('20 → 20', function () {
  assert.strictEqual(normalizeReviewBatchSize(20), 20)
})

t('30 → 30', function () {
  assert.strictEqual(normalizeReviewBatchSize(30), 30)
})

// ══════════════════════════════════════════════════════════════════
// 3. REVIEW_BATCH_SIZE_OPTIONS constant
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 3. Batch size options constant ---')

t('REVIEW_BATCH_SIZE_OPTIONS strictly equals [5, 10, 20, 30]', function () {
  assert.deepStrictEqual(REVIEW_BATCH_SIZE_OPTIONS, [5, 10, 20, 30])
})

t('Batch size options values are [5, 10, 20, 30]', function () {
  assert.deepStrictEqual(REVIEW_BATCH_SIZE_OPTIONS, [5, 10, 20, 30])
})

// ══════════════════════════════════════════════════════════════════
// 4. Page config method tests
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 4. Page config interaction tests ---')

if (!capturedPageConfig) {
  console.error('  SKIP: Page config not captured')
} else {
  var mockPage = {
    data: {
      phase: 'overview',
      isStarting: false,
      isContinuing: false,
      reviewBatchSize: 10,
      pendingBatchSize: 10,
      showBatchSizeSheet: false,
      batchSizeOptions: [5, 10, 20, 30],
      elapsedText: '00:00',
      groupQuestions: [],
      submittingGroup: false,
    },
    _alive: true,
    _reviewSession: {
      timerStartedAt: 0,
      timerElapsedMs: 0,
      timerRunning: false,
      timerLastTickAt: 0,
      timingSegmentId: '',
      timingStartedAtMs: 0,
      reviewRequestIds: {},
    },
    _timerInterval: null,
    _resultDockFadeTimer: null,
    _userSelectedReviewBatchSize: false,
    _persistReviewDraft: function () {},
    _clearCelebrationTimer: function () {},
    _clearMasterUndo: function () {},
    _clearResultDockFadeTimer: function () {
      if (this._resultDockFadeTimer) {
        clearTimeout(this._resultDockFadeTimer)
        this._resultDockFadeTimer = null
      }
    },
    setData: function (patch) {
      if (typeof patch === 'object' && patch !== null) {
        for (var key in patch) {
          if (patch.hasOwnProperty(key)) {
            mockPage.data[key] = patch[key]
          }
        }
      }
    },
  }

  var methodsToBind = [
    '_safeTickDelta', '_getReviewRequestId',
    '_startReviewTimer', '_pauseReviewTimer', '_resumeReviewTimer',
    '_resetReviewTimer', '_clearReviewTimer', '_buildReviewTimingSession',
    'showBatchSizeSelector', 'closeBatchSizeSheet',
    'selectPendingBatchSize', 'confirmBatchSize',
    '_reviewTimerController', '_batchSizeSheetController',
    '_overviewVMController', '_reviewSessionController',
  ]
  for (var mi = 0; mi < methodsToBind.length; mi++) {
    var mn = methodsToBind[mi]
    if (typeof capturedPageConfig[mn] === 'function') {
      mockPage[mn] = capturedPageConfig[mn].bind(mockPage)
    }
  }

  // ═══ Timer lifecycle tests ═══

  t('Initial elapsedText is "00:00"', function () {
    assert.strictEqual(mockPage.data.elapsedText, '00:00')
  })

  t('_startReviewTimer does not create duplicate intervals', function () {
    mockPage._clearReviewTimer()
    mockPage._resetReviewTimer()
    mockPage._startReviewTimer()
    var first = mockPage._timerInterval
    mockPage._startReviewTimer()
    assert.strictEqual(mockPage._timerInterval, first, 'interval should not be replaced')
    mockPage._clearReviewTimer()
  })

  t('_pauseReviewTimer clears interval and timerRunning = false', function () {
    mockPage._clearReviewTimer()
    mockPage._resetReviewTimer()
    // Start then immediately pause — state check is synchronous
    mockPage._startReviewTimer()
    mockPage._pauseReviewTimer()
    assert.strictEqual(mockPage._timerInterval, null)
    assert.strictEqual(mockPage._reviewSession.timerRunning, false)
  })

  t('_clearReviewTimer clears interval and sets timerRunning = false', function () {
    mockPage._resetReviewTimer()
    mockPage._startReviewTimer()
    assert.ok(mockPage._timerInterval !== null)
    mockPage._clearReviewTimer()
    assert.strictEqual(mockPage._timerInterval, null)
    assert.strictEqual(mockPage._reviewSession.timerRunning, false)
  })

  // ═══ Review timing → 番茄钟统计刷题时长 ═══

  t('_buildReviewTimingSession returns null before any foreground time', function () {
    mockPage._clearReviewTimer()
    mockPage._resetReviewTimer()
    mockPage._startReviewTimer()
    assert.strictEqual(mockPage._buildReviewTimingSession(), null)
    mockPage._clearReviewTimer()
  })

  t('_buildReviewTimingSession reports foreground seconds with a stable segment id', function () {
    mockPage._clearReviewTimer()
    mockPage._resetReviewTimer()
    mockPage._startReviewTimer()
    mockPage._pauseReviewTimer()
    mockPage._reviewSession.timerElapsedMs = 95500 // 95.5s foreground only
    var first = mockPage._buildReviewTimingSession()
    assert.ok(first, 'session payload expected')
    assert.strictEqual(first.duration_sec, 95)
    assert.ok(first.request_id.length >= 8, 'request_id must satisfy server min length')
    var wallSec = (Date.parse(first.finished_at) - Date.parse(first.started_at)) / 1000
    assert.ok(wallSec >= 95, 'wall window must cover foreground duration')
    // 提交失败后重试：同一分段 id，服务端幂等只记一次
    var retry = mockPage._buildReviewTimingSession()
    assert.strictEqual(retry.request_id, first.request_id)
    // 下一组重新开始计时：新分段 id
    mockPage._startReviewTimer()
    mockPage._pauseReviewTimer()
    mockPage._reviewSession.timerElapsedMs = 2000
    var next = mockPage._buildReviewTimingSession()
    assert.notStrictEqual(next.request_id, first.request_id)
    assert.strictEqual(next.duration_sec, 2)
  })

  t('_buildReviewTimingSession does not stop the running timer', function () {
    mockPage._clearReviewTimer()
    mockPage._resetReviewTimer()
    mockPage._startReviewTimer()
    mockPage._reviewSession.timerElapsedMs = 3000
    mockPage._buildReviewTimingSession()
    assert.strictEqual(mockPage._reviewSession.timerRunning, true)
    assert.ok(mockPage._timerInterval !== null)
    mockPage._clearReviewTimer()
  })

  // ═══ Batch size — custom bottom sheet tests ═══

  t('showBatchSizeSelector opens sheet, sets pendingBatchSize to current', function () {
    mockPage._userSelectedReviewBatchSize = false
    mockPage.data.phase = 'overview'
    mockPage.data.reviewBatchSize = 20
    mockPage.data.pendingBatchSize = 10
    mockPage.data.showBatchSizeSheet = false

    mockPage.showBatchSizeSelector()

    assert.strictEqual(mockPage.data.showBatchSizeSheet, true)
    assert.strictEqual(mockPage.data.pendingBatchSize, 20)
  })

  t('selectPendingBatchSize(5) updates only pendingBatchSize, not reviewBatchSize', function () {
    mockPage.data.reviewBatchSize = 10
    mockPage.data.pendingBatchSize = 10
    mockPage.data.showBatchSizeSheet = true

    mockPage.selectPendingBatchSize({ currentTarget: { dataset: { value: 5 } } })

    assert.strictEqual(mockPage.data.pendingBatchSize, 5)
    assert.strictEqual(mockPage.data.reviewBatchSize, 10, 'reviewBatchSize must not change')
  })

  t('selectPendingBatchSize(30) updates only pendingBatchSize', function () {
    mockPage.data.reviewBatchSize = 10
    mockPage.data.pendingBatchSize = 10

    mockPage.selectPendingBatchSize({ currentTarget: { dataset: { value: 30 } } })

    assert.strictEqual(mockPage.data.pendingBatchSize, 30)
    assert.strictEqual(mockPage.data.reviewBatchSize, 10)
  })

  t('selectPendingBatchSize ignores invalid values', function () {
    mockPage.data.pendingBatchSize = 10

    mockPage.selectPendingBatchSize({ currentTarget: { dataset: { value: 99 } } })

    assert.strictEqual(mockPage.data.pendingBatchSize, 10)
  })

  t('confirmBatchSize applies pendingBatchSize and closes sheet', function () {
    mockPage._userSelectedReviewBatchSize = false
    mockPage.data.reviewBatchSize = 10
    mockPage.data.pendingBatchSize = 30
    mockPage.data.showBatchSizeSheet = true

    mockPage.confirmBatchSize()

    assert.strictEqual(mockPage.data.reviewBatchSize, 30)
    assert.strictEqual(mockPage.data.showBatchSizeSheet, false)
    assert.strictEqual(mockPage._userSelectedReviewBatchSize, true)
  })

  t('closeBatchSizeSheet closes without modifying reviewBatchSize', function () {
    mockPage._userSelectedReviewBatchSize = false
    mockPage.data.reviewBatchSize = 10
    mockPage.data.pendingBatchSize = 20
    mockPage.data.showBatchSizeSheet = true

    mockPage.closeBatchSizeSheet()

    assert.strictEqual(mockPage.data.showBatchSizeSheet, false)
    assert.strictEqual(mockPage.data.reviewBatchSize, 10)
    assert.strictEqual(mockPage._userSelectedReviewBatchSize, false)
  })

  t('showBatchSizeSelector • non-overview phase does nothing', function () {
    mockPage.data.showBatchSizeSheet = false
    mockPage.data.phase = 'reviewing'
    mockPage.data.reviewBatchSize = 10

    mockPage.showBatchSizeSelector()

    assert.strictEqual(mockPage.data.showBatchSizeSheet, false)
  })

  t('showBatchSizeSelector • isStarting guard', function () {
    mockPage.data.showBatchSizeSheet = false
    mockPage.data.phase = 'overview'
    mockPage.data.isStarting = true
    mockPage.data.reviewBatchSize = 10

    mockPage.showBatchSizeSelector()

    assert.strictEqual(mockPage.data.showBatchSizeSheet, false)
  })

  t('showBatchSizeSelector • isContinuing guard', function () {
    mockPage.data.showBatchSizeSheet = false
    mockPage.data.phase = 'overview'
    mockPage.data.isContinuing = true
    mockPage.data.reviewBatchSize = 10

    mockPage.showBatchSizeSelector()

    assert.strictEqual(mockPage.data.showBatchSizeSheet, false)
  })

  // ═══ User selection vs API override tests ═══

  t('User selects 20, buildReviewOverviewVM with API batch_size=10 keeps 20', function () {
    mockPage._userSelectedReviewBatchSize = true
    mockPage.data.reviewBatchSize = 20
    if (typeof capturedPageConfig.buildReviewOverviewVM !== 'function') { throw new Error('buildReviewOverviewVM not found') }
    var vm = capturedPageConfig.buildReviewOverviewVM.call(mockPage, {
      batch_size: 10, today_due_count: 50, today_completed_count: 20,
      today_remaining_count: 30, estimated_minutes: 15,
    })
    assert.strictEqual(vm.reviewBatchSize, 20)
  })

  t('User NOT selected, API returns 30, buildReviewOverviewVM uses 30', function () {
    mockPage._userSelectedReviewBatchSize = false
    mockPage.data.reviewBatchSize = 10
    var vm = capturedPageConfig.buildReviewOverviewVM.call(mockPage, {
      batch_size: 30, today_due_count: 50, today_completed_count: 20,
      today_remaining_count: 30, estimated_minutes: 15,
    })
    assert.strictEqual(vm.reviewBatchSize, 30)
  })

  t('startTodayReview wires batch size through start controller', function () {
    var src = capturedPageConfig.startTodayReview.toString()
    assert.ok(src.indexOf('this._startBatchController().start()') >= 0)
    var startSrc = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/utils/start-batch-controller.js'), 'utf8')
    assert.ok(startSrc.indexOf('batch_size: options.getBatchSize()') >= 0)
  })

  t('nextGroup wires batch size through remote batch controller', function () {
    var src = capturedPageConfig.nextGroup.toString()
    assert.ok(src.indexOf('_nextGroupController().next()') >= 0)
    var remoteSrc = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/utils/next-remote-batch-controller.js'), 'utf8')
    assert.ok(remoteSrc.indexOf('batch_size: options.getBatchSize()') >= 0)
  })

  t('review request id is stable for one immutable schedule occurrence', function () {
    mockPage._reviewSession.reviewRequestIds = {}
    var q = { schedule_id: 7, question_version_id: 33, occurrence_seq: 4 }
    var first = mockPage._getReviewRequestId(q)
    var second = mockPage._getReviewRequestId(q)
    assert.ok(first)
    assert.strictEqual(first, second)
    var next = mockPage._getReviewRequestId({ schedule_id: 7, question_version_id: 33, occurrence_seq: 5 })
    assert.notStrictEqual(first, next)
  })

  t('onUnload clears timer interval', function () {
    if (typeof capturedPageConfig.onUnload !== 'function') { throw new Error('onUnload not found') }
    mockPage._timerInterval = 'mock-interval'
    mockPage._reviewSession.timerRunning = true
    capturedPageConfig.onUnload.call(mockPage)
    assert.strictEqual(mockPage._timerInterval, null)
  })

  // ═══ Time-delta guard tests ═══

  t('_safeTickDelta clamps negative delta to 0', function () {
    if (typeof capturedPageConfig._safeTickDelta !== 'function') { throw new Error('_safeTickDelta not found') }
    var bound = capturedPageConfig._safeTickDelta.bind(mockPage)
    assert.strictEqual(bound(-5000), 0, 'negative raw delta should be 0')
    assert.strictEqual(bound(-1), 0, '-1 ms should be 0')
  })

  t('_safeTickDelta caps large delta at 10000', function () {
    if (typeof capturedPageConfig._safeTickDelta !== 'function') { throw new Error('_safeTickDelta not found') }
    var bound = capturedPageConfig._safeTickDelta.bind(mockPage)
    assert.strictEqual(bound(60000), 10000, '60s jump should be capped to 10000')
    assert.strictEqual(bound(3600000), 10000, '1h jump should be capped to 10000')
  })

  t('_safeTickDelta passes normal delta through', function () {
    if (typeof capturedPageConfig._safeTickDelta !== 'function') { throw new Error('_safeTickDelta not found') }
    var bound = capturedPageConfig._safeTickDelta.bind(mockPage)
    assert.strictEqual(bound(500), 500, '500ms should pass through')
    assert.strictEqual(bound(0), 0, '0ms should pass through')
    assert.strictEqual(bound(9999), 9999, '9999ms should pass through')
  })

  t('System time jump backward does not corrupt accumulated time via pause', function () {
    mockPage._clearReviewTimer()
    mockPage._resetReviewTimer()
    mockPage._reviewSession.timerElapsedMs = 5000
    mockPage._reviewSession.timerStartedAt = Date.now() + 60000 // simulate clock went back
    mockPage._timerInterval = 'mock-simulated' // trick _pauseReviewTimer into proceeding

    mockPage._pauseReviewTimer()
    // After fix: negative delta clamped to 0, so timerElapsedMs unchanged
    assert.strictEqual(mockPage._reviewSession.timerElapsedMs, 5000,
      'timerElapsedMs should remain 5000 (negative delta clamped to 0)')
    assert.strictEqual(mockPage._timerInterval, null)
    assert.strictEqual(mockPage._reviewSession.timerRunning, false)
    mockPage._timerInterval = null // clean up
  })
}

// ══════════════════════════════════════════════════════════════════
// 5. WXML structural checks
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 5. WXML / component contract checks ---')

var wxml = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/review-today.wxml'), 'utf8')

t('review-today.wxml passes elapsedText to quiz-runner', function () {
  assert.ok(wxml.indexOf('elapsedText="{{elapsedText}}"') >= 0)
})

t('review-today.wxml mission-batch has bindtap', function () {
  assert.ok(wxml.indexOf('bindtap="showBatchSizeSelector"') >= 0)
})

var reviewTodayJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/review-today.js'), 'utf8')

var groupSubmissionJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/utils/group-submission.js'), 'utf8')
var submitRequestJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/utils/submit-request-controller.js'), 'utf8')
var startBatchJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/utils/start-batch-controller.js'), 'utf8')

t('initial first question keeps enriched render data in groupQuestions', function () {
  assert.ok(startBatchJs.indexOf('preparedQuestions[0] = firstEnriched') >= 0)
  assert.ok(startBatchJs.indexOf('groupQuestions: prepared.preparedQuestions') >= 0)
})

t('review grading payload binds immutable revision, occurrence and request id', function () {
  assert.ok(groupSubmissionJs.indexOf('question_version_id: question.question_version_id') >= 0)
  assert.ok(groupSubmissionJs.indexOf('occurrence_seq: question.occurrence_seq') >= 0)
  assert.ok(groupSubmissionJs.indexOf('request_id: requestId') >= 0)
  assert.ok(submitRequestJs.indexOf('api.post') < 0 || submitRequestJs.indexOf('postGrade') >= 0)
  assert.ok(submitRequestJs.indexOf('{ reviews, session: timingSession }') >= 0)
})

t('review timing session is frozen before grade-batch request (network time excluded)', function () {
  var timingIdx = submitRequestJs.indexOf('const timingSession = input.buildTimingSession()')
  var postIdx = submitRequestJs.indexOf('await options.postGrade(')
  assert.ok(timingIdx >= 0 && postIdx > timingIdx)
})

t('review timer prefers wx.getPerformance monotonic clock', function () {
  assert.ok(reviewTodayJs.indexOf('wx.getPerformance') >= 0)
  assert.ok(reviewTodayJs.indexOf('_reviewMonotonicNow()') >= 0)
})

var questionEnrichmentJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/review-today/utils/question-enrichment-controller.js'), 'utf8')

t('group result hydrates lazy questions before rendering details', function () {
  assert.ok(groupSubmissionJs.indexOf('...options.enrichForResult(options.question)') >= 0)
  assert.ok(questionEnrichmentJs.indexOf('enrichForResultImpl') >= 0)
  // 单题渲染数据异常不能使已成功的批改误报为提交失败：必须有安全降级分支
  assert.ok(questionEnrichmentJs.indexOf('_renderModel: null') >= 0)
})

var runnerWxml = fs.readFileSync(path.join(__dirname, '../subpackages/study/components/quiz-runner/quiz-runner.wxml'), 'utf8')

t('quiz-runner.wxml references elapsedText in timer display', function () {
  assert.ok(runnerWxml.indexOf('{{elapsedText}}') >= 0)
})

// ══════════════════════════════════════════════════════════════════
// 6. quiz-runner has no unconditional self-starting timer
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 6. quiz-runner timer safety ---')

var runnerJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/components/quiz-runner/quiz-runner.js'), 'utf8')

t('quiz-runner.js has 0 setInterval calls', function () {
  var count = (runnerJs.match(/setInterval/g) || []).length
  assert.strictEqual(count, 0)
})

t('quiz-runner.js no timer-related setTimeout logic', function () {
  var hasTimerLogic = /setTimeout[\s\S]{0,200}(elapsed|timer|00:00)/.test(runnerJs)
  assert.strictEqual(hasTimerLogic, false)
})

// ══════════════════════════════════════════════════════════════════
// 7. Cross-page regression
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 7. Cross-page regression checks ---')

var practiceWxml = fs.readFileSync(path.join(__dirname, '../subpackages/study/practice/practice.wxml'), 'utf8')

t('practice.wxml still passes elapsedText', function () {
  assert.ok(practiceWxml.indexOf('elapsedText="{{elapsedText}}"') >= 0)
})

var wrongWxml = fs.readFileSync(path.join(__dirname, '../subpackages/study/wrong-detail/wrong-detail.wxml'), 'utf8')

t('wrong-detail.wxml has no elapsedText', function () {
  assert.strictEqual(wrongWxml.indexOf('elapsedText'), -1)
})

t('wrong-detail.wxml uses compactReviewMode', function () {
  assert.ok(wrongWxml.indexOf('compactReviewMode') >= 0)
})

// ══════════════════════════════════════════════════════════════════
// Summary
// ══════════════════════════════════════════════════════════════════
console.log('\n==============================')
console.log('Passed:', testsPassed, ' Failed:', testsFailed)
console.log('==============================\n')

if (testsFailed > 0) process.exit(1)
