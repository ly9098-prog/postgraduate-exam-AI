const assert = require('node:assert/strict')
const { test } = require('node:test')
const { runner, question, plain } = require('./quiz-runner-component-support')

for (const pkg of ['study', 'exam']) {
  for (const mode of ['SEGMENTS', 'RICH_TEXT', 'CODE', 'LATEX', 'MIXED', '', 'NEW']) {
    test(`${pkg}: ${mode || 'missing'} render mode has one atomic projection`, () => {
      const r = runner(pkg)
      const q = question(8, mode)
      const textBlock = { type: 'TEXT', value: 'keep' }
      q._renderModel.rawText = '  return;'
      q._renderModel.blocks = [textBlock, { type: 'CODE', rawText: '  x++;' }]
      q.content = { text: 'fallback' }
      r.observe(q, { questionId: 8, optionList: [{ key: 'B' }] })
      assert.equal(r.writes.length, 1)
      const patch = r.writes[0].patch
      assert.equal(patch._displayQuestion, q)
      assert.equal(patch._qTypeLabel, '单选题')
      assert.equal(patch._renderUnknownMode, mode === '' || mode === 'NEW')
      assert.equal(patch._renderFallbackText, mode === '' || mode === 'NEW' ? 'fallback' : '')
      assert.deepEqual(plain(patch._codeLines), mode === 'CODE' ? [{ no: 1, text: '  return;' }] : [])
      assert.equal(patch._mixedBlocks.length, mode === 'MIXED' ? 2 : 0)
      if (mode === 'MIXED') {
        assert.equal(patch._mixedBlocks[0], textBlock)
        assert.equal(patch._mixedBlocks[1]._codeLines[0].text, '  x++;')
      }
      assert.equal(patch._optionList[0].key, 'B')
      assert.equal(r.clock.jobs.size, 0)
    })
  }

  test(`${pkg}: unchanged model updates answers without rebuilding stem`, () => {
    const r = runner(pkg)
    const q = question()
    r.observe(q, null)
    const options = [{ key: 'A', selected: true }]
    q._typeLabel = 'must not re-read'
    r.observe(q, { questionId: '1', optionList: options })
    const patch = r.writes[1].patch
    assert.equal(patch._displayQuestion, q)
    assert.equal(patch._optionList, options)
    assert.equal(Object.hasOwn(patch, '_qTypeLabel'), false)
    assert.equal(Object.hasOwn(patch, '_questionImages'), false)
    assert.equal(r.target.data._qTypeLabel, '单选题')
  })

  test(`${pkg}: null clears render state without touching outstanding timers`, () => {
    const r = runner(pkg)
    r.observe(question(), null)
    r.target._switchTimer = r.clock.setTimeout(() => {}, 100)
    r.observe(null, null)
    assert.equal(r.target._lastRenderModel, null)
    assert.equal(r.target._lastQuestionId, null)
    assert.equal(r.target._hasRenderedQuestion, false)
    assert.equal(r.target.data._displayQuestion, null)
    assert.deepEqual(plain(r.target.data._optionList), [])
    assert.equal(r.clock.jobs.size, 1)
    r.detach()
    assert.equal(r.clock.jobs.size, 0)
  })

  for (const source of ['compute', 'get', 'array', 'content']) {
    test(`${pkg}: image source precedence ${source}`, () => {
      const calls = []
      const adapter = source === 'compute'
        ? { computeExtraImages(q) { calls.push(q); return ['computed'] }, getQuestionImages() { throw Error() } }
        : source === 'get' ? { getQuestionImages(q) { calls.push(q); return ['get'] } } : {}
      const r = runner(pkg, { adapter: () => adapter })
      const q = question()
      q.image_url = source === 'content' ? 'ignored' : ['', 3, 'question']
      q.content = { image_url: ['content', null] }
      r.observe(q, null)
      assert.deepEqual(plain(r.target.data._questionImages),
        [source === 'compute' ? 'computed' : source === 'get' ? 'get' : source === 'array' ? 'question' : 'content'])
      assert.equal(calls.length, source === 'compute' || source === 'get' ? 1 : 0)
      if (calls.length) assert.equal(calls[0], q)
    })
  }

  test(`${pkg}: failed initial adapter stays absent for answers but render lookup retries`, () => {
    let lookups = 0
    const r = runner(pkg, { adapter() {
      if (++lookups === 1) throw Error('optional adapter absent')
      return { computeExtraImages: () => ['late'], buildOptionListFromFlags() { throw Error() } }
    } })
    r.observe(question(), null)
    assert.equal(lookups, 2)
    assert.deepEqual(plain(r.target.data._questionImages), ['late'])
    assert.deepEqual(plain(r.target.data._optionList), [])
  })

  test(`${pkg}: render adapter exceptions propagate before setData`, () => {
    const error = new Error('image failure')
    const r = runner(pkg, { adapter: () => ({ computeExtraImages() { throw error } }) })
    assert.throws(() => r.observe(question(), null), value => value === error)
    assert.equal(r.writes.length, 0)
    assert.equal(r.target._hasRenderedQuestion, true)
    assert.equal(r.target._lastQuestionId, 'id:1')
  })

  test(`${pkg}: index identity and unknown-mode text fallbacks remain exact`, () => {
    const r = runner(pkg, { data: { currentIndex: 3 } })
    const q = { content: { stem: 'stem fallback' } }
    r.observe(q, null)
    assert.equal(r.target._lastQuestionId, 'index:3')
    assert.equal(r.target.data._renderFallbackText, 'stem fallback')
    r.observe({ id: 0 }, null)
    assert.equal(r.target._lastQuestionId, 'id:0')
    assert.equal(r.target.data._renderFallbackText, '该题内容暂时无法显示')
  })
}
