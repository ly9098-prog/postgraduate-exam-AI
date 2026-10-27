const assert = require('node:assert/strict')
const { test } = require('node:test')
const { runner, question, plain } = require('./quiz-runner-component-support')

for (const pkg of ['study', 'exam']) {
  test(`${pkg}: image adapter is live while answer adapter remains captured`, () => {
    const groups = [{ options: [{ _text: 'captured' }] }]
    const captured = { getBlankOptionGroups() { return groups } }
    const live = { computeExtraImages() { return ['live'] } }
    let lookups = 0
    const r = runner(pkg, { adapter: () => ++lookups === 1 ? captured : live })
    r.observe(question(), null)
    assert.equal(lookups, 2)
    assert.equal(r.target.data._blankOptionGroups, groups)
    assert.deepEqual(plain(r.target.data._questionImages), ['live'])
  })

  test(`${pkg}: code preparation precedes live image and answer projection`, () => {
    const order = []
    const q = question(1, 'CODE')
    const options = [{ key: 'new' }]
    const adapter = { computeExtraImages(value) {
      order.push('images')
      value._optionList = options
      return []
    } }
    const r = runner(pkg, { adapter: () => adapter })
    q._typeLabel = 'original-label'
    r.target._splitCodeLines = function () {
      order.push('code')
      assert.equal(this._lastRenderModel, q._renderModel)
      q._typeLabel = 'changed-label'
      return []
    }
    r.observe(q, null)
    assert.deepEqual(order, ['code', 'images'])
    assert.equal(r.target.data._qTypeLabel, 'original-label')
    assert.equal(r.target.data._optionList, options)
  })

  for (const property of ['getBlankOptionGroups', 'buildOptionListFromFlags']) {
    test(`${pkg}: ${property} capability getter errors remain outside fallback catches`, () => {
      const error = new Error('capability access')
      const adapter = {}
      Object.defineProperty(adapter, property, { get() { throw error } })
      const r = runner(pkg, { adapter: () => adapter })
      assert.throws(() => r.observe(question(), null), value => value === error)
      assert.equal(r.writes.length, 0)
      assert.equal(r.target._hasRenderedQuestion, true)
    })
  }

  for (const property of ['enrichBlankOptionGroups', 'getQuestionOptions']) {
    test(`${pkg}: ${property} getter errors retain optional fallback`, () => {
      const adapter = {
        getBlankOptionGroups() { return [{ options: [] }] },
        buildOptionListFromFlags() { throw Error('must not build') },
      }
      if (property === 'getQuestionOptions') adapter.getBlankOptionGroups = () => []
      Object.defineProperty(adapter, property, { get() { throw Error('optional getter') } })
      const r = runner(pkg, { adapter: () => adapter })
      r.observe(question(), null)
      assert.equal(r.writes.length, 1)
      assert.deepEqual(plain(r.target.data._optionList), [])
    })
  }

  test(`${pkg}: empty question identity can match a null answer identity`, () => {
    const r = runner(pkg)
    const q = question(null)
    const optionList = [{ key: 'A' }]
    r.observe(q, { questionId: null, optionList })
    assert.equal(r.target.data._optionList, optionList)
    assert.equal(r.target._lastQuestionId, 'index:0')
  })

  test(`${pkg}: failed setData leaves the original precommit identity mutations`, () => {
    const r = runner(pkg)
    const q = question(8)
    const error = new Error('view write failed')
    r.target.setData = () => { throw error }
    assert.throws(() => r.observe(q, null), value => value === error)
    assert.equal(r.target._lastRenderModel, q._renderModel)
    assert.equal(r.target._lastQuestionId, 'id:8')
    assert.equal(r.target._hasRenderedQuestion, true)
    assert.equal(r.clock.jobs.size, 0)
  })
}
