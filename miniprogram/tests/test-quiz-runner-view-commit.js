const assert = require('node:assert/strict')
const { test } = require('node:test')
const { runner, question, plain } = require('./quiz-runner-component-support')

for (const pkg of ['study', 'exam']) {
  for (const layout of ['normal', 'flowLayout', 'compactReviewMode']) {
    test(`${pkg}: ${layout} viewport and motion join the same setData`, () => {
      const r = runner(pkg, { data: layout === 'normal' ? {} : { [layout]: true } })
      r.observe(question(1), null)
      r.target._lastQuestionScrollTop = 200
      r.target._switchTargetIndex = 1
      r.target._switchDirection = 'right'
      const q = question(2)
      const options = [{ key: 'B' }]
      r.observe(q, { questionId: 2, optionList: options })
      const patch = r.writes[1].patch
      assert.equal(patch._displayQuestion, q)
      assert.equal(patch._optionList, options)
      assert.equal(patch.animClass, 'slide-in-right')
      assert.equal(Object.hasOwn(patch, 'questionScrollIntoView'), layout === 'normal')
      assert.equal(r.target._switchTargetIndex, null)
      assert.equal(r.target._switchPhase, 'enter')
      r.clock.tick(0)
      assert.equal(r.writes.length, layout === 'normal' ? 3 : 2)
      if (layout === 'normal') assert.equal(r.writes[2].patch.questionScrollIntoView, '')
      r.clock.tick(299)
      assert.equal(r.target._switchPhase, 'enter')
      r.clock.tick(1)
      assert.equal(r.target._switchPhase, '')
      assert.equal(r.target.data._animating, false)
      assert.equal(r.clock.jobs.size, 0)
    })
  }

  for (const scroll of [0, 1, 1.1, '10', 'invalid']) {
    test(`${pkg}: viewport threshold ${scroll} is applied only after first render`, () => {
      const r = runner(pkg)
      r.target._lastQuestionScrollTop = scroll
      r.observe(question(1), null)
      assert.equal(Object.hasOwn(r.writes[0].patch, 'questionScrollIntoView'), false)
      r.observe(question(2), null)
      assert.equal(Object.hasOwn(r.writes[1].patch, 'questionScrollIntoView'), Number(scroll) > 1)
      r.detach()
    })
  }

  test(`${pkg}: deferred setData callback observes detach and phase changes`, () => {
    const r = runner(pkg, { deferCommit: true })
    r.observe(question(1), null)
    r.callbacks.shift()()
    r.target._lastQuestionScrollTop = 200
    r.target._switchTargetIndex = 1
    r.observe(question(2), null)
    r.target._switchPhase = ''
    r.callbacks.shift()()
    assert.equal(r.clock.jobs.size, 1)
    r.detach()
    assert.equal(r.clock.jobs.size, 0)
    r.target._switchTargetIndex = 2
    r.observe(question(3), null)
    r.callbacks.shift()()
    assert.equal(r.clock.jobs.size, 0)
  })

  test(`${pkg}: switching callback dispatches the current finish method`, () => {
    const r = runner(pkg)
    r.observe(question(1), null)
    r.target._switchTargetIndex = 1
    r.observe(question(2), null)
    let called = 0
    r.target._finishQuestionSwitch = () => { called++ }
    r.clock.tick(300)
    assert.equal(called, 1)
  })

  test(`${pkg}: navigation delay, rejected-switch fallback and detach remain bounded`, () => {
    const r = runner(pkg)
    r.target.goNext()
    assert.equal(r.target.data._animating, true)
    assert.equal(r.events.length, 0)
    r.clock.tick(99)
    assert.equal(r.events.length, 0)
    r.clock.tick(1)
    assert.deepEqual(plain(r.events), [{ name: 'next', detail: { index: 1 } }])
    r.clock.tick(799)
    assert.equal(r.target.data._animating, true)
    r.clock.tick(1)
    assert.equal(r.target.data._animating, false)
    r.target.goNext()
    r.detach()
    r.clock.tick(1000)
    assert.equal(r.events.length, 1)
    assert.equal(r.clock.jobs.size, 0)
  })
}
