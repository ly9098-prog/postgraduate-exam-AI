const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createGroupSubmitConfirmController,
} = require('../subpackages/study/review-today/utils/submit-confirm-controller')

function createHarness(overrides = {}) {
  const state = {
    pending: false,
    phase: 'reviewing',
    alive: true,
    shown: [],
    shownQuestions: [],
    throwOnShow: false,
  }
  const controller = createGroupSubmitConfirmController({
    getConfirm: () => ({
      async show(options) {
        state.shown.push(options)
        if (state.throwOnShow) throw new Error('dialog failed')
        return overrides.showResult ?? true
      },
    }),
    setPending: value => { state.pending = value },
    isPageAlive: () => state.alive,
    getPhase: () => state.phase,
    findUnansweredIndex: () => 2,
    showQuestion: index => { state.shownQuestions.push(index) },
    ...overrides.controller,
  })
  return { controller, state }
}

test('requires a submit confirm component', async () => {
  const controller = createGroupSubmitConfirmController({
    getConfirm: () => null,
    setPending: () => {},
    isPageAlive: () => true,
    getPhase: () => 'reviewing',
    findUnansweredIndex: () => -1,
    showQuestion: () => {},
  })
  assert.equal(await controller.confirm(3, 0), false)
})

test('returns to the first unanswered question', async () => {
  const { controller, state } = createHarness()
  assert.equal(await controller.confirm(3, 2), false)
  assert.deepEqual(state.shownQuestions, [2])
  assert.equal(state.pending, false)
  assert.deepEqual(state.shown, [{
    scenario: 'unanswered',
    layout: 'minimal',
    title: '请先完成本组复习',
    message: '还有 2 题未完成作答。请填写全部题目后再提交，多空题需要填写每一空。',
    confirmText: '继续作答',
    showCancel: false,
  }])
})

test('confirms an all-done group only while the review phase is live', async () => {
  const { controller, state } = createHarness({ showResult: true })
  assert.equal(await controller.confirm(3, 0), true)
  assert.deepEqual(state.shown, [{
    scenario: 'all-done',
    layout: 'minimal',
    title: '提交本组复习？',
    message: '本组 3 题已全部作答，提交后查看复盘结果。',
    confirmText: '提交复习',
    cancelText: '继续检查',
  }])
  assert.equal(state.pending, false)

  state.phase = 'overview'
  state.shown = []
  assert.equal(await controller.confirm(3, 0), false)
  assert.equal(state.shown.length, 1)
  assert.equal(state.pending, false)
})

test('cancel, dialog failure, and page death stop submission', async () => {
  const cancelled = createHarness({ showResult: false })
  assert.equal(await cancelled.controller.confirm(3, 0), false)
  assert.equal(cancelled.state.pending, false)

  const failed = createHarness()
  failed.state.throwOnShow = true
  assert.equal(await failed.controller.confirm(3, 0), false)
  assert.equal(failed.state.pending, false)

  const dead = createHarness({ showResult: true })
  dead.state.alive = false
  assert.equal(await dead.controller.confirm(3, 0), false)
  assert.equal(dead.state.pending, false)
})
