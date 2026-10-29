const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture } = require('./helpers/wrong-book-selection-fixture')
const plain = value => JSON.parse(JSON.stringify(value))
const event = id => ({ currentTarget: { dataset: { id } } })

test('view changes normalize the dataset and call the current selection synchronizer', () => {
  const f = fixture()
  f.page._syncSelectionState = function () {
    assert.equal(this, f.page); f.calls.push(['sync', this.data.activeView])
  }
  for (const view of ['all', 'task', 'invalid', undefined]) {
    assert.equal(f.page.switchView({ currentTarget: { dataset: { view } } }), undefined)
    assert.equal(f.page.data.activeView, view === 'all' ? 'all' : 'task')
  }
  assert.equal(f.page.openAllQuestions(), undefined)
  assert.deepEqual(f.calls.at(-1), ['sync', 'all'])
})

test('batch mode resets selection and closes the filter only on entry with callback-time hooks', () => {
  for (const active of [false, true]) {
    const f = fixture(), callbacks = []
    Object.assign(f.page.data, { batchMode: active, showFilter: true, selectedIds: ['1'],
      selectedIdMap: { 1: true }, selectedCount: 1, allVisibleSelected: true, selectionPulse: true })
    f.page._clearBatchCapsuleIdleTimer = function () { assert.equal(this, f.page); f.calls.push(['clearHook']) }
    f.page.setData = function (patch, cb) { f.calls.push(['setData', patch]); Object.assign(this.data, patch); callbacks.push(cb) }
    f.page.toggleBatchMode()
    assert.equal(f.page.data.batchMode, !active)
    assert.equal(f.page.data.showFilter, active)
    assert.deepEqual(plain(f.page.data.selectedIds), [])
    assert.deepEqual(plain(f.page.data.selectedIdMap), {})
    assert.equal(f.page.data.selectedCount, 0); assert.equal(f.page.data.selectionPulse, false)
    assert.equal(f.calls[0][0], active ? 'clearHook' : 'setData')
    f.page._showBatchCapsuleAndRefreshTimer = function () { assert.equal(this, f.page); f.calls.push(['showHook']) }
    callbacks[0]()
    assert.equal(f.calls.some(call => call[0] === 'showHook'), !active)
  }
})

test('interaction and scroll use current capsule hook without returning its result', () => {
  const f = fixture()
  f.page._showBatchCapsuleAndRefreshTimer = function () { assert.equal(this, f.page); f.calls.push(['show']); return 99 }
  assert.equal(f.page.onPageInteraction(), undefined)
  assert.equal(f.page.onPageScroll(), undefined)
  assert.deepEqual(f.calls, [['show'], ['show']])
})

test('capsule timer clear keeps a falsey handle and clears a truthy handle before nulling it', () => {
  const f = fixture()
  f.page._batchCapsuleIdleTimer = 0
  f.page._clearBatchCapsuleIdleTimer()
  assert.equal(f.page._batchCapsuleIdleTimer, 0)
  f.page._batchCapsuleIdleTimer = 12
  f.context.clearTimeout = id => { assert.equal(f.page._batchCapsuleIdleTimer, 12); f.cleared.push(id) }
  f.page._clearBatchCapsuleIdleTimer()
  assert.deepEqual(f.cleared, [12]); assert.equal(f.page._batchCapsuleIdleTimer, null)
})

test('capsule scheduling clears first and callback reads current alive mode and visibility', () => {
  for (const alive of [false, true]) for (const mode of [false, true]) {
    const f = fixture()
    f.page._alive = alive; f.page.data.batchMode = mode
    f.page._batchCapsuleIdleTimer = 40
    f.page._scheduleBatchCapsuleAutoHide()
    assert.deepEqual(f.cleared, [40]); assert.equal(f.timers.size, alive && mode ? 1 : 0)
  }
  for (const state of [{ _alive: false }, { batchMode: false }, { batchCapsuleVisible: false }, {}]) {
    const f = fixture()
    f.page.data.batchMode = true
    f.page._scheduleBatchCapsuleAutoHide()
    const id = f.page._batchCapsuleIdleTimer
    assert.equal(f.timers.get(id).delay, 5000)
    if ('_alive' in state) f.page._alive = state._alive
    else Object.assign(f.page.data, state)
    f.calls.length = 0; f.fire(id)
    assert.equal(f.page._batchCapsuleIdleTimer, null)
    assert.equal(f.calls.length, Object.keys(state).length ? 0 : 1)
    if (!Object.keys(state).length) assert.equal(f.page.data.batchCapsuleVisible, false)
  }
})

test('capsule show does nothing outside mode, refreshes visible state and resolves delayed hook live', () => {
  const f = fixture()
  f.page._showBatchCapsuleAndRefreshTimer(); assert.equal(f.calls.length, 0)
  f.page.data.batchMode = true
  f.page._scheduleBatchCapsuleAutoHide = function () { assert.equal(this, f.page); f.calls.push(['schedule']) }
  f.page._showBatchCapsuleAndRefreshTimer()
  assert.deepEqual(f.calls, [['schedule']])
  f.page.data.batchCapsuleVisible = false
  let callback
  f.page.setData = (patch, cb) => { f.calls.push(['setData', patch]); callback = cb }
  f.page._showBatchCapsuleAndRefreshTimer()
  f.page._scheduleBatchCapsuleAutoHide = () => f.calls.push(['lateSchedule'])
  callback(); assert.deepEqual(f.calls.at(-1), ['lateSchedule'])
})

test('question taps honor strict suppression time and route using current mode and raw ID', () => {
  const f = fixture(), id = { raw: true }
  f.page._toggleQuestionSelection = function (value) { assert.equal(this, f.page); assert.equal(value, id); f.calls.push(['select']) }
  f.page._navigateToDetail = function (value) { assert.equal(this, f.page); assert.equal(value, id); f.calls.push(['navigate']) }
  f.page._suppressQuestionTapUntil = 1001
  f.page.onQuestionTap(event(id)); assert.equal(f.calls.length, 0)
  f.setNow(1001); f.page.onQuestionTap(event(id))
  f.page.data.batchMode = true; f.page.onQuestionTap(event(id))
  assert.deepEqual(f.calls, [['navigate'], ['select']])
})

test('select controls enter mode and select before a deferred show callback', () => {
  const f = fixture()
  f.page._suppressQuestionTapUntil = 1001
  f.page.onSelectControlTap(event(5)); assert.equal(f.calls.length, 0)
  f.setNow(1001)
  let callback
  f.page.setData = function (patch, cb) { f.calls.push(['setData', patch]); Object.assign(this.data, patch); callback = cb }
  f.page._toggleQuestionSelection = function (id) { assert.equal(this, f.page); f.calls.push(['select', id]) }
  f.page.onSelectControlTap(event(5))
  assert.deepEqual(f.calls.map(c => c[0]), ['setData', 'select'])
  assert.deepEqual(plain(f.calls[0][1]), { batchMode: true, batchCapsuleVisible: true, showFilter: false })
  f.page._showBatchCapsuleAndRefreshTimer = () => f.calls.push(['lateShow'])
  callback(); assert.deepEqual(f.calls.at(-1), ['lateShow'])
  f.calls.length = 0; f.page.onSelectControlTap(event(7))
  assert.deepEqual(f.calls, [['select', 7]])
})

test('long press records 700ms suppression, catches platform failures and still selects', () => {
  for (const platform of ['normal', 'throw', 'missing']) {
    const f = fixture()
    f.page._showBatchCapsuleAndRefreshTimer = () => f.calls.push(['show'])
    f.page._toggleQuestionSelection = id => f.calls.push(['select', id])
    f.context.wx = platform === 'missing' ? undefined : {
      vibrateShort(options) {
        assert.equal(this, f.context.wx); assert.deepEqual(plain(options), { type: 'light' })
        f.calls.push(['vibrate']); if (platform === 'throw') throw Error('vibration')
      },
    }
    f.page.onQuestionLongPress(event(9))
    assert.equal(f.page._suppressQuestionTapUntil, 1700)
    assert.equal(f.page.data.batchMode, true)
    assert.deepEqual(f.calls.at(-1), ['select', 9])
    assert.equal(f.calls[0][0], 'setData')
  }
})

test('selection toggles copy maps, keep truthy semantics, synchronize before a new-selection pulse', () => {
  const f = fixture(), original = { 7: true, 3: false, old: true }
  f.page.data.selectedIdMap = original
  f.page._syncSelectionState = function () { assert.equal(this, f.page); f.calls.push(['sync']); this._pulseSelectionBadge = () => f.calls.push(['latePulse']) }
  f.page._toggleQuestionSelection(3)
  assert.equal(original[3], false); assert.notEqual(f.page.data.selectedIdMap, original)
  assert.deepEqual(plain(f.page.data.selectedIds), ['3', '7', 'old'])
  assert.equal(f.page.data.selectedCount, 3)
  assert.deepEqual(f.calls.map(c => c[0]), ['setData', 'sync', 'latePulse'])
  f.calls.length = 0; f.page._toggleQuestionSelection('7')
  assert.deepEqual(f.calls.map(c => c[0]), ['setData', 'sync'])
  assert.deepEqual(plain(f.page.data.selectedIds), ['3', 'old'])
})

test('selection pulse keeps the untracked first delay and current alive checks on both callbacks', () => {
  for (const alive of [false, true]) {
    const f = fixture()
    f.page._selectionPulseTimer = 90
    f.page._pulseSelectionBadge()
    assert.deepEqual(f.cleared, [90]); assert.equal(f.page._selectionPulseTimer, 90)
    const first = [...f.timers.keys()][0]
    assert.equal(f.timers.get(first).delay, 16)
    f.page._alive = alive; f.fire(first)
    assert.equal(f.page.data.selectionPulse, alive)
    if (alive) {
      const second = f.page._selectionPulseTimer
      assert.equal(f.timers.get(second).delay, 260)
      f.page._alive = false; f.fire(second)
      assert.equal(f.page.data.selectionPulse, true)
      assert.equal(f.page._selectionPulseTimer, second)
    }
  }
  const f = fixture()
  f.page._pulseSelectionBadge(); f.fire([...f.timers.keys()][0]); f.fire(f.page._selectionPulseTimer)
  assert.equal(f.page.data.selectionPulse, false)
})

test('visible IDs preserve list duplicates but task view deduplicates strings in encounter order', () => {
  const f = fixture()
  f.page.data.list = [{ id: 2 }, { id: '2' }, { id: 1 }]
  f.page.data.taskGroups = [{ items: [{ id: 3 }, { id: '3' }, { id: 2 }] }, {}, { items: [{ id: 4 }] }]
  assert.deepEqual(plain(f.page._getVisibleIds()), ['3', '2', '4'])
  f.page.data.activeView = 'all'
  assert.deepEqual(plain(f.page._getVisibleIds()), ['2', '2', '1'])
  f.page.data.list = null; assert.deepEqual(plain(f.page._getVisibleIds()), [])
})

test('select-all only changes visible IDs, retains offscreen keys and does not synchronize', () => {
  for (const allSelected of [false, true]) {
    const f = fixture(), original = { outside: true, 2: true }
    if (allSelected) original[1] = true
    f.page.data.selectedIdMap = original
    f.page._getVisibleIds = () => ['2', '1']
    f.page._syncSelectionState = () => assert.fail('unexpected sync')
    f.page._pulseSelectionBadge = () => f.calls.push(['pulse'])
    f.page.toggleSelectAll()
    assert.equal(f.page.data.selectedIdMap.outside, true)
    assert.equal(f.page.data.allVisibleSelected, !allSelected)
    assert.equal(f.page.data.selectedCount, allSelected ? 1 : 3)
    assert.equal(f.calls.some(c => c[0] === 'pulse'), !allSelected)
    assert.equal(original[2], true)
  }
  const f = fixture()
  f.page._getVisibleIds = () => []; f.page.toggleSelectAll()
  assert.equal(f.calls.length, 0)
})

test('selection synchronization keeps valid keys from list and task groups regardless of old values', () => {
  const f = fixture(), old = { 1: false, 2: true, stale: true, 3: null }
  f.page.data.list = [{ id: 1 }, { id: 2 }]
  f.page.data.taskGroups = [{ items: [{ id: 3 }] }, {}]
  f.page.data.selectedIdMap = old
  f.page._getVisibleIds = function () { assert.equal(this, f.page); return ['3', '1'] }
  f.page._syncSelectionState()
  assert.deepEqual(plain(f.page.data.selectedIdMap), { 1: true, 2: true, 3: true })
  assert.deepEqual(plain(f.page.data.selectedIds), ['1', '2', '3'])
  assert.equal(f.page.data.allVisibleSelected, true); assert.equal(old[1], false)
  f.page._getVisibleIds = () => []
  f.page._syncSelectionState(); assert.equal(f.page.data.allVisibleSelected, false)
})

test('selection error propagation preserves partial writes and try boundaries', () => {
  const f = fixture(), error = Error('hook')
  f.page._syncSelectionState = () => { throw error }
  assert.throws(() => f.page._toggleQuestionSelection(8), value => value === error)
  assert.equal(f.page.data.selectedCount, 1); assert.equal(f.timers.size, 0)
  f.page._clearBatchCapsuleIdleTimer = () => { throw error }
  assert.throws(() => f.page._scheduleBatchCapsuleAutoHide(), value => value === error)
  f.page.data.batchMode = false
  f.page.setData = () => { throw error }
  assert.throws(() => f.page.onQuestionLongPress(event(3)), value => value === error)
  assert.equal(f.page._suppressQuestionTapUntil, 1700)
  assert.equal(f.calls.some(c => c[0] === 'vibrate'), false)
})
