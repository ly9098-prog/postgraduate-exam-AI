/* Run with Node; deterministic timers, no WeChat login or network required. */
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const root = path.resolve(__dirname, '..')
const read = file => fs.readFileSync(path.join(root, file), 'utf8')
const runnerDir = 'subpackages/study/components/quiz-runner/'
let runnerDefinition
const oldComponent = global.Component
try {
  global.Component = definition => { runnerDefinition = definition }
  require(path.join(root, runnerDir, 'quiz-runner.js'))
} finally {
  global.Component = oldComponent
}
function runner(overrides = {}) {
  const data = Object.assign({}, runnerDefinition.data)
  for (const [key, prop] of Object.entries(runnerDefinition.properties)) data[key] = prop.value
  Object.assign(data, { mode: 'practice', totalCount: 4, currentIndex: 1 }, overrides)
  const target = Object.assign({
    data, events: [], writes: [],
    setData(patch, callback) {
      this.writes.push(patch)
      Object.assign(this.data, patch)
      if (callback) callback()
    },
    triggerEvent(name, detail) { this.events.push({ name, detail }) },
  }, runnerDefinition.methods)
  runnerDefinition.created.call(target)
  return target
}
const observe = runnerDefinition.observers['currentQuestion, answerState']
const question = id => ({ id, _renderModel: { mode: 'RICH_TEXT', richTextNodes: [] } })
function update(target, id, index) {
  target.data.currentIndex = index
  target.data.currentQuestion = question(id)
  observe.call(target, target.data.currentQuestion, null)
}
function withClock(test) {
  const oldSet = global.setTimeout
  const oldClear = global.clearTimeout
  let now = 0
  let nextId = 0
  const jobs = new Map()
  global.setTimeout = (callback, ms) => {
    const id = ++nextId
    jobs.set(id, { at: now + ms, callback })
    return id
  }
  global.clearTimeout = id => jobs.delete(id)
  const tick = ms => {
    const until = now + ms
    while (true) {
      const first = [...jobs].filter(([, job]) => job.at <= until).sort((a, b) => a[1].at - b[1].at)[0]
      if (!first) break
      now = first[1].at
      jobs.delete(first[0])
      first[1].callback()
    }
    now = until
  }
  try { test(tick, jobs) } finally { global.setTimeout = oldSet; global.clearTimeout = oldClear }
}
withClock((tick, jobs) => {
  const target = runner()
  update(target, 10, 1)
  assert.strictEqual(target.data.animClass, '', 'initial question has no entrance animation')
  target.goNext()
  assert.strictEqual(target.data.animClass, 'question-fade-out')
  assert.strictEqual(target.data._animating, true)
  target.goNext()
  target.goPrev()
  target.goQuestion({ currentTarget: { dataset: { index: 3 } } })
  target.selectOption({ currentTarget: { dataset: { option: 'A' } } })
  tick(99)
  assert.strictEqual(target.events.length, 0, 'old question remains until fade completes; input locked')
  tick(1)
  assert.deepStrictEqual(target.events, [{ name: 'next', detail: { index: 2 } }])
  tick(100)
  assert.strictEqual(target.data.animClass, 'question-fade-out', 'entrance waits for real parent data')
  update(target, 11, 2)
  assert.strictEqual(target.data.animClass, 'slide-in-left')
  assert.ok(!Object.hasOwn(target.data, 'heroCollapsed'), 'header remains fully expanded without collapse state')
  assert.ok(!target.writes.some(patch => patch.questionScrollIntoView), 'top viewport does not bounce')
  target.onQuestionAnimationEnd({ detail: { animationName: 'unrelated-child-animation' } })
  tick(219)
  assert.strictEqual(target.data._animating, true)
  tick(1)
  target.onQuestionAnimationEnd({ detail: { animationName: 'runnerQuestionInLeft' } })
  assert.strictEqual(target.data.animClass, '')
  assert.strictEqual(target.data._animating, false)
  assert.strictEqual(jobs.size, 0)
  target.goPrev()
  tick(100)
  update(target, 10, 1)
  assert.strictEqual(target.data.animClass, 'slide-in-right')
  tick(220)
  target.onQuestionAnimationEnd({ detail: { animationName: 'runnerQuestionInRight' } })
  target.writes.length = 0
  observe.call(target, target.data.currentQuestion, { questionId: 10, answer: 'A' })
  assert.ok(!target.writes.some(patch => Object.hasOwn(patch, 'animClass')), 'answer-only update does not animate')
})
withClock(tick => {
  const target = runner({ showSheet: true })
  update(target, 10, 1)
  target.goQuestion({ currentTarget: { dataset: { index: '3' } } })
  assert.strictEqual(target.data.showSheet, false)
  assert.strictEqual(target.events.length, 0)
  tick(100)
  assert.deepStrictEqual(target.events, [{ name: 'jump', detail: { index: 3 } }])
  tick(800)
  assert.strictEqual(target.data.animClass, '', 'rejected parent switch recovers visibility')
  assert.strictEqual(target.data._animating, false)
})
withClock((tick, jobs) => {
  const target = runner({ swipeEnabled: true })
  update(target, 10, 1)
  target.onTouchStart({ touches: [{ clientX: 200, clientY: 100 }], target: {} })
  target.onTouchEnd({ changedTouches: [{ clientX: 80, clientY: 102 }] })
  assert.strictEqual(target.data.animClass, 'question-fade-out', 'swipe uses same transition')
  runnerDefinition.lifetimes.detached.call(target)
  tick(1000)
  assert.strictEqual(target.events.length, 0, 'detached component never requests a switch')
  assert.strictEqual(jobs.size, 0)
})
for (const overrides of [{ externalSwitchAnimation: true }, { compactReviewMode: true }, { mode: 'wrong-detail' }]) {
  withClock((tick, jobs) => {
    const target = runner(overrides)
    target.goNext()
    assert.deepStrictEqual(target.events, [{ name: 'next', detail: { index: 2 } }])
    assert.strictEqual(target.data.animClass, '')
    assert.strictEqual(jobs.size, 0)
  })
}
withClock(tick => {
  const target = runner({ mode: 'review' })
  update(target, 10, 1)
  target.goNext()
  tick(100)
  update(target, 11, 2)
  assert.strictEqual(target.data.animClass, 'slide-in-left', 'full review shares animation')
  tick(299)
  assert.strictEqual(target.data._animating, true)
  tick(1)
  assert.strictEqual(target.data._animating, false, 'timer recovers when animationend is unavailable')
})
withClock((tick, jobs) => {
  const previousWx = global.wx
  global.wx = { nextTick: () => assert.fail('switch must not stage a fully hidden view tick') }
  try {
    const target = runner()
    update(target, 10, 1)
    target.goNext()
    tick(100)
    target.writes.length = 0
    update(target, 11, 2)
    assert.strictEqual(target.writes[0].animClass, 'slide-in-left', 'new question and entrance class commit in one patch')
    assert.ok(Object.hasOwn(target.writes[0], '_optionList'), 'option rendering is committed with motion')
    assert.strictEqual(target.writes[0]._displayQuestion.id, 11, 'stem snapshot is committed with options and entrance')
    assert.strictEqual(target.writes.length, 1, 'no hidden staging patch or second entrance patch')
    target.onQuestionAnimationEnd({ detail: { animationName: 'runnerQuestionInLeft' } })
    assert.strictEqual(target.data._animating, false)
    assert.strictEqual(jobs.size, 0)
    target.goPrev()
    tick(100)
    update(target, 10, 1)
    runnerDefinition.lifetimes.detached.call(target)
    const count = target.writes.length
    tick(1000)
    assert.strictEqual(target.writes.length, count, 'animation fallback cannot write after detach')
    assert.strictEqual(jobs.size, 0)
  } finally { global.wx = previousWx }
})
let pageDefinition
const wxCalls = []
const context = {
  Page: definition => { pageDefinition = definition },
  require: () => ({}),
  wx: { pageScrollTo: options => wxCalls.push(options) },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
}
vm.runInNewContext(read('subpackages/study/practice/practice.js'), context)
function practice(overrides = {}, snapshot = null) {
  const prompts = []
  const cleared = []
  const target = {
    data: Object.assign({ started: true, submitting: false, submitted: false, selectedSubjectId: 42, selectedSubjectName: '数据结构', selectedMode: 'random', count: 10, recentSubjects: [{ subject_id: 42 }], totalQuestions: 4, questions: [question(10)], currentQuestion: question(10) }, overrides),
    _pageAlive: true, _questionsRequestSeq: 3,
    _practiceSession: { submissionSnapshot: snapshot, answerMap: { 10: 'A' } },
    _launchPreset: { mode: 'random' }, _pendingResultUrl: '',
    prompts, cleared,
    setData(patch) { Object.assign(this.data, patch) },
    _showSubmitConfirm: async options => { prompts.push(options); return true },
    _showSubmitConfirmPaused: async options => { prompts.push(options); return true },
    _setPracticeUnloadGuard(value) { this.guard = value },
    _clearTimer() { this.timerCleared = true },
    _clearPendingSubmission(id) { cleared.push(id) },
    _resetSession: pageDefinition._resetSession,
    requestExitPractice: pageDefinition.requestExitPractice,
    _returnToLaunchOrigin() { assert.fail('exit must not pop to home or original launch route') },
  }
  return target
}
async function main() {
  const target = practice()
  await target.requestExitPractice()
  assert.strictEqual(target.data.started, false)
  assert.strictEqual(target.data.selectedSubjectId, 42, 'exit preserves selected subject')
  assert.strictEqual(target.data.selectedSubjectName, '数据结构')
  assert.strictEqual(target.data.selectedMode, 'random')
  assert.strictEqual(target.data.count, 10)
  assert.strictEqual(target.data.recentSubjects[0].subject_id, 42)
  assert.strictEqual(target.data.currentQuestion, null)
  assert.strictEqual(target.data.totalQuestions, 0)
  assert.strictEqual(target._practiceSession.submissionSnapshot, null)
  assert.strictEqual(Object.keys(target._practiceSession.answerMap).length, 0)
  assert.strictEqual(target._questionsRequestSeq, 4, 'stale question requests are invalidated')
  assert.strictEqual(target.guard, false)
  assert.strictEqual(target.timerCleared, true)
  assert.strictEqual(target._launchPreset, null)
  assert.strictEqual(target.prompts[0].layout, 'minimal')
  assert.strictEqual(target.prompts[0].scenario, 'info')
  assert.strictEqual(wxCalls.length, 1)
  const cancelled = practice()
  cancelled._showSubmitConfirmPaused = async () => false
  await cancelled.requestExitPractice()
  assert.strictEqual(cancelled.data.started, true)
  assert.strictEqual(cancelled._questionsRequestSeq, 3)
  const submitting = practice({ submitting: true })
  await submitting.requestExitPractice()
  assert.strictEqual(submitting.data.started, true)
  assert.strictEqual(submitting.prompts[0].title, '正在交卷')
  assert.strictEqual(submitting.prompts[0].hideCancel, true)
  const pending = practice({}, { requestId: 'pending-id' })
  pending._showSubmitConfirmPaused = () => assert.fail('pending confirmation must not use timing pause prompt')
  await pending.requestExitPractice()
  assert.strictEqual(pending.data.started, false)
  assert.strictEqual(pending.cleared.length, 0, 'uncertain submission remains in persistent cache')
  let recoveryOffers = 0
  pending._readPendingSubmission = () => ({ submission: { requestId: 'pending-id' } })
  pending._offerPendingSubmissionRecovery = async () => { recoveryOffers++ }
  await pageDefinition.startPractice.call(pending)
  assert.strictEqual(recoveryOffers, 1, 'starting again offers recovery before creating a new session')
  assert.strictEqual(pending.data.started, false, 'unresolved submission cannot be overwritten by a new practice')
  const rejected = practice({}, { requestId: 'rejected-id', retryBlocked: true })
  await rejected.requestExitPractice()
  assert.deepStrictEqual(rejected.cleared, ['rejected-id'])
  const accepted = practice({ submitted: true }, { requestId: 'accepted-id', serverAccepted: true })
  accepted._pendingResultUrl = '/subpackages/study/practice-result/index?id=1'
  accepted._openSubmittedResult = (url, snapshot) => { accepted.opened = { url, snapshot } }
  await accepted.requestExitPractice()
  assert.strictEqual(accepted.opened.snapshot.requestId, 'accepted-id')
  assert.strictEqual(accepted.prompts.length, 0, 'accepted submission keeps result navigation')
  const detached = practice()
  detached._showSubmitConfirmPaused = async () => { detached._pageAlive = false; return true }
  await detached.requestExitPractice()
  assert.strictEqual(detached.data.started, true, 'unloaded page cannot reset after async prompt')
  const concurrent = practice()
  let resolvePrompt
  concurrent._showSubmitConfirmPaused = () => new Promise(resolve => { resolvePrompt = resolve })
  const first = concurrent.requestExitPractice()
  await concurrent.requestExitPractice()
  assert.strictEqual(concurrent._questionsRequestSeq, 3)
  resolvePrompt(false)
  await first
  assert.strictEqual(concurrent._exitConfirmInFlight, false)

  let confirmDefinition
  vm.runInNewContext(read('subpackages/study/components/submit-confirm/submit-confirm.js'), { Component: definition => { confirmDefinition = definition } })
  const confirm = Object.assign({ data: {}, setData(patch) { Object.assign(this.data, patch) } }, confirmDefinition.methods)
  const choice = confirm.show({ layout: 'minimal' })
  assert.strictEqual(confirm.data.layout, 'minimal')
  confirm.onConfirm()
  assert.strictEqual(await choice, true)
  const subsequent = confirm.show({ title: '交卷复盘' })
  assert.strictEqual(confirm.data.layout, 'default', 'minimal exit layout does not leak into submission prompts')
  confirm.onCancel()
  assert.strictEqual(await subsequent, false)

  for (const json of ['subpackages/study/wrong-book/wrong-book.json', 'subpackages/study/practice-result/index.json']) {
    assert.strictEqual(JSON.parse(read(json)).usingComponents['wrong-book-empty'], '../components/wrong-book-empty/index')
  }
  assert.ok(read('subpackages/study/wrong-book/wrong-book.wxml').includes('<wrong-book-empty'))
  const result = read('subpackages/study/practice-result/index.wxml')
  assert.ok(result.includes('<wrong-book-empty variant="compact"'))
  assert.ok(result.includes('跳过') && result.includes('全部答对'), 'empty result distinguishes skipped and all-correct attempts')
  assert.ok(fs.existsSync(path.join(root, 'assets/images/wrong-book-empty.png')))
  const home = read('pages/home/home.wxml')
  assert.ok(home.includes('TODAY’S NOTE') || home.includes("TODAY'S NOTE"))
  assert.ok(home.includes('{{dailyBoostText}}'))
  assert.ok(!home.includes('growth-note-line'))
  const recent = read('subpackages/study/practice/practice.wxml')
  assert.ok(!recent.includes('recent-arrow') && recent.includes('recent-subject-icon') && recent.includes('chooseRecentSubject'))
  assert.ok(!recent.includes('recent-card-footer') && !recent.includes('recent-light'), 'single-row subjects omit duplicate copy and decorative pulse')
  assert.ok(read('subpackages/study/components/wrong-book-empty/index.wxss').includes('.empty-compact .empty-image{width:224rpx}'))
  assert.ok(read('subpackages/study/practice/practice.wxss').includes('width:280rpx;height:88rpx'))
  const css = read(runnerDir + 'practice-theme.wxss')
  assert.ok(/prefers-reduced-motion:\s*reduce/.test(css))
  assert.ok(css.includes('question-fade-out') && css.includes('runnerQuestionInLeft'))
  const motion = css.slice(css.indexOf('/* Opaque card, directional content motion;'), css.indexOf('.runner-reference:not(.runner-compact) .runner-bottom-inner'))
  assert.ok(!/opacity:\s*0(?:[;}])/.test(motion), 'question transitions never erase the card or its content')
  assert.ok(motion.includes('.runner-q-wrap{transition:none;animation:none;opacity:1;transform:none}'), 'white card remains stationary and opaque')
  assert.ok(motion.includes('opacity:.88') && motion.includes('.runner-question-motion'), 'only inner content receives a low-contrast transition')
  assert.ok(!read(runnerDir + 'quiz-runner.js').includes("'preparing'"), 'no invisible intermediate phase')
  assert.strictEqual((read(runnerDir + 'quiz-runner.wxml').match(/class="runner-question-motion" bindanimationend="onQuestionAnimationEnd"/g) || []).length, 2, 'animationend is bound directly to the animated inner view in both render paths')
  assert.ok(/prefers-reduced-motion:\s*reduce/.test(read('subpackages/study/practice/practice.wxss')))
  if (process.argv[2]) {
    const compiled = { window: { __webview_engine_version__: 0.02 }, console }
    vm.createContext(compiled)
    vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), compiled)
    const all = node => [node, ...(node.children || []).flatMap(child => child && typeof child === 'object' ? all(child) : [])]
    const byClass = (tree, cls) => all(tree).filter(node => ((node.attr || {}).class || '').split(/\s+/).includes(cls))
    const renderRunner = compiled.$gwx('subpackages/study/components/quiz-runner/quiz-runner.wxml')
    for (const unknown of [false, true]) {
      const tree = renderRunner({ mode: 'practice', _displayQuestion: question(10), _renderUnknownMode: unknown, _qTypeLabel: '单选题', animClass: 'slide-in-left' })
      assert.strictEqual(byClass(tree, 'runner-q-wrap').length, 1)
      assert.strictEqual(byClass(tree, 'runner-question-motion').length, 1, 'normal and fallback renderers isolate content from card paint')
    }
    const renderConfirm = compiled.$gwx('subpackages/study/components/submit-confirm/submit-confirm.wxml')
    const minimal = renderConfirm({ theme: 'mint', visible: true, layout: 'minimal', title: '退出练习？', message: '本组尚未提交', confirmText: '退出', cancelText: '继续作答', scenario: 'info' })
    for (const decoration of ['sc-top-accent', 'sc-icon-circle', 'sc-eyebrow', 'sc-confirm-arrow']) {
      assert.strictEqual(byClass(minimal, decoration).length, 0, 'minimal exit omits ' + decoration)
    }
    assert.strictEqual(byClass(minimal, 'sc-btn').length, 2)
    const standard = renderConfirm({ theme: 'mint', visible: true, layout: 'default', scenario: 'all-done' })
    assert.strictEqual(byClass(standard, 'sc-icon-circle').length, 1, 'submission appearance remains intact')
    const setup = compiled.$gwx('subpackages/study/practice/practice.wxml')({ entryResolved: true, started: false, selectedSubjectId: 42, recentSubjects: [{ subject_id: 42, display_name: '数据结构', icon_src: '/assets/icons/practice-subject/code-xml.svg' }, { subject_id: 43, display_name: '高等数学', mark: 'Σ' }] })
    assert.strictEqual(byClass(setup, 'recent-card').length, 2)
    assert.strictEqual(byClass(setup, 'active').filter(node => (node.attr.class || '').includes('recent-card')).length, 1)
    assert.strictEqual(byClass(setup, 'recent-arrow').length, 2)
    assert.strictEqual(byClass(setup, 'recent-subject-icon').length, 1)
    assert.strictEqual(byClass(setup, 'recent-selected-badge').length, 0)
    assert.strictEqual(byClass(setup, 'recent-card-footer').length, 0)
    const empty = compiled.$gwx('subpackages/study/components/wrong-book-empty/index.wxml')({ variant: 'compact', title: '这里暂时没有错题', description: '新错题会自动进入任务流', secondaryDescription: '' })
    assert.strictEqual(byClass(empty, 'empty-image').length, 1)
    assert.strictEqual(byClass(empty, 'empty-compact').length, 1)
    const defaultEmpty = compiled.$gwx('subpackages/study/components/wrong-book-empty/index.wxml')({ variant: 'default' })
    assert.strictEqual(byClass(defaultEmpty, 'empty-compact').length, 0, 'wrong-book retains original scale')
    assert.strictEqual(byClass(empty, 'empty-desc-line').length, 1, 'optional second line creates no gap')
    const home = compiled.$gwx('pages/home/home.wxml')({ dailyBoostText: '累计12题，连续2天', growthSummaryVisible: true })
    assert.strictEqual(byClass(home, 'growth-note').length, 1)
    assert.strictEqual(byClass(home, 'growth-note-label').length, 1)
    assert.strictEqual(byClass(home, 'growth-note-line').length, 0)
    console.log('Compiled WeChat WXML minimal exit, recent subjects, shared empty and home note passed')
  }
  console.log('Study UI refinements: animation timing, exit safety and shared visual contracts passed')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
