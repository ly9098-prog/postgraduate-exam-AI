const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createImageWarmController,
} = require('../subpackages/study/practice/utils/image-warm-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    dev: false,
    currentIndex: 1,
    questions: [
      { id: 10, urls: ['u10'] },
      { id: 11, urls: ['u11'] },
      { id: 12, urls: ['u12'] },
      { id: 13, urls: ['u13'] },
    ],
    preloads: [],
    views: [],
    warnings: [],
    optionKeys: [],
  }
  const controller = createImageWarmController({
    isPageAlive: () => state.alive,
    getCurrentIndex: () => state.currentIndex,
    getQuestions: () => state.questions,
    getQuestionPrefetchUrls: q => q.urls,
    preloadMany: (urls, concurrency) => {
      const entry = { urls: [...urls], concurrency }
      state.preloads.push(entry)
      return {
        then: callback => {
          entry.resolve = callback
          return Promise.resolve()
        },
      }
    },
    buildQuestionViewModel: (question, force) => {
      if (state.buildThrows) throw new Error('render failed')
      return {
        question: { ...question, refreshed: force },
        answerState: { id: question.id },
        optionKeys: ['A'],
      }
    },
    setOptionKeys: keys => { state.optionKeys = keys },
    setData: patch => state.views.push(patch),
    isDev: () => state.dev,
    logWarn: (...args) => state.warnings.push(args),
    ...overrides,
  })
  return { controller, state }
}

test('preloads the current image with priority three and neighbors with priority two', () => {
  const { controller, state } = createHarness()

  controller.warm(state.questions, 1)

  assert.deepEqual(state.preloads[0], {
    urls: ['u11'],
    concurrency: 3,
    resolve: state.preloads[0].resolve,
  })
  assert.deepEqual(state.preloads[1].urls, ['u12', 'u13', 'u10'])
  assert.equal(state.preloads[1].concurrency, 2)
})

test('refreshes the still-visible current question after current images preload', () => {
  const { controller, state } = createHarness()

  controller.warm(state.questions, 1)
  state.preloads[0].resolve()

  assert.deepEqual(state.optionKeys, ['A'])
  assert.deepEqual(state.views, [{
    currentQuestion: { id: 11, urls: ['u11'], refreshed: true },
    currentAnswerState: { id: 11 },
  }])
})

test('skips the refresh after page death, index change, or question replacement', () => {
  const dead = createHarness()
  dead.controller.warm(dead.state.questions, 1)
  dead.state.alive = false
  dead.state.preloads[0].resolve()
  assert.deepEqual(dead.state.views, [])

  const moved = createHarness()
  moved.controller.warm(moved.state.questions, 1)
  moved.state.currentIndex = 2
  moved.state.preloads[0].resolve()
  assert.deepEqual(moved.state.views, [])

  const replaced = createHarness()
  replaced.controller.warm(replaced.state.questions, 1)
  replaced.state.questions[1] = { id: 99, urls: [] }
  replaced.state.preloads[0].resolve()
  assert.deepEqual(replaced.state.views, [])
})

test('logs render refresh failures only in development', () => {
  const { controller, state } = createHarness()
  state.buildThrows = true
  state.dev = true

  controller.warm(state.questions, 1)
  state.preloads[0].resolve()

  assert.equal(state.warnings.length, 1)
  assert.equal(state.warnings[0][0], '[practice] image cache refresh failed')

  const quiet = createHarness()
  quiet.state.buildThrows = true
  quiet.controller.warm(quiet.state.questions, 1)
  quiet.state.preloads[0].resolve()
  assert.deepEqual(quiet.state.warnings, [])
})

test('ignores invalid inputs and missing prefetch adapter support', () => {
  const empty = createHarness()
  empty.controller.warm([], 1)
  assert.deepEqual(empty.state.preloads, [])

  const missing = createHarness()
  missing.controller.warm(undefined, 1)
  assert.deepEqual(missing.state.preloads, [])

  const unsupported = createHarness({ getQuestionPrefetchUrls: undefined })
  unsupported.controller.warm(unsupported.state.questions, 1)
  assert.deepEqual(unsupported.state.preloads, [])
})
