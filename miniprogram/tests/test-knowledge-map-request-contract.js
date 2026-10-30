const assert = require('node:assert/strict')
const { test } = require('node:test')

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

async function withPage(kind, run) {
  const names = ['wx', 'Page', 'setTimeout', 'clearTimeout']
  const globals = names.map(name => [name, Object.getOwnPropertyDescriptor(global, name)])
  const path = require.resolve(`../subpackages/knowledge/knowledge-${kind}/index.js`)
  const cached = require.cache[path]
  const timers = new Map()
  const calls = { get: [], patches: [], titles: [], removed: [], toasts: [] }
  let definition
  let timerId = 0
  let api
  let sync
  let originals
  try {
    global.wx = {
      setNavigationBarTitle: value => calls.titles.push(value.title),
      showToast: value => calls.toasts.push(value.title),
      pageScrollTo() {},
      nextTick: callback => callback(),
    }
    global.Page = value => { definition = value }
    global.setTimeout = (callback, delay) => {
      const id = ++timerId
      timers.set(id, { callback, delay })
      return id
    }
    global.clearTimeout = id => timers.delete(id)
    api = require('../utils/api')
    sync = require('../utils/storage').knowledgePracticeSync
    originals = [api.get, api.getErrorMessage, sync.getForSubject, sync.resolveReceipt, sync.remove]
    api.get = url => { calls.get.push(url); return Promise.resolve({}) }
    api.getErrorMessage = error => error.message
    sync.getForSubject = () => []
    sync.resolveReceipt = () => false
    sync.remove = receipts => calls.removed.push(receipts)
    delete require.cache[path]
    require(path)
    const page = {
      ...definition,
      data: structuredClone(definition.data),
      setData(patch, callback) {
        calls.patches.push(patch)
        Object.assign(this.data, patch)
        if (callback) callback()
      },
    }
    if (kind === 'subject') {
      Object.assign(page, { subjectId: 10, _pageVisible: true, _expandedNodeIds: new Set() })
      page.applyView = (_reset, _fit, done) => done()
      page.enterPage = () => {}
    } else {
      Object.assign(page, {
        knowledgePointId: 1, _detailCache: Object.create(null),
        _detailRequests: Object.create(null), _switchToken: 0,
      })
    }
    await run({ page, api, sync, calls, timers })
  } finally {
    if (originals) {
      ;[api.get, api.getErrorMessage, sync.getForSubject, sync.resolveReceipt, sync.remove] = originals
    }
    if (cached) require.cache[path] = cached
    else delete require.cache[path]
    globals.forEach(([name, descriptor]) => {
      if (descriptor) Object.defineProperty(global, name, descriptor)
      else delete global[name]
    })
  }
}

const mapPayload = name => ({
  subject: { subject_id: 10, subject_name: name },
  nodes: [],
})

test('subject request publishes only the newest response', async () => {
  await withPage('subject', async ({ page, api, calls }) => {
    const first = deferred()
    const second = deferred()
    api.get = url => { calls.get.push(url); return calls.get.length === 1 ? first.promise : second.promise }
    const earlier = page.loadMap()
    const later = page.loadMap()
    second.resolve(mapPayload('newest'))
    await later
    first.resolve(mapPayload('stale'))
    await earlier
    assert.deepEqual(calls.get, ['/knowledge-map/subjects/10', '/knowledge-map/subjects/10'])
    assert.equal(page.data.subject.subject_name, 'newest')
    assert.deepEqual(calls.titles, ['newest · 知识图谱'])
  })
})

test('subject hide invalidates an in-flight response', async () => {
  await withPage('subject', async ({ page, api, calls }) => {
    const pending = deferred()
    api.get = () => pending.promise
    const request = page.loadMap()
    page.onHide()
    const patchCount = calls.patches.length
    pending.resolve(mapPayload('hidden'))
    await request
    assert.equal(calls.patches.length, patchCount)
    assert.equal(calls.titles.length, 0)
  })
})

test('subject initial and background errors use distinct fields', async () => {
  await withPage('subject', async ({ page, api }) => {
    api.get = () => Promise.reject(new Error('offline'))
    await page.loadMap()
    assert.equal(page.data.error, 'offline')
    const subject = { subject_id: 10 }
    page.data.subject = subject
    page.data.error = ''
    await page.loadMap(false)
    assert.equal(page.data.subject, subject)
    assert.equal(page.data.error, '')
    assert.equal(page.data.refreshError, 'offline')
  })
})

test('subject pending receipts clear only when the direct counter resolves them', async () => {
  await withPage('subject', async ({ page, sync, calls }) => {
    const receipt = { knowledgePointId: 2, correctCount: 1, wrongCount: 1, expectedMinAttemptCount: 7 }
    sync.getForSubject = id => { assert.equal(id, 10); return [receipt] }
    sync.resolveReceipt = (value, count) => {
      assert.equal(value, receipt)
      return count >= 7
    }
    const payload = count => ({
      nodes: [{ knowledge_point_id: 2, status: 'mastered', attempt_count: count }],
    })
    const pending = page._buildMapNodes(payload(6))[0]
    assert.equal(pending.pendingSync, true)
    assert.equal(pending.status, 'insufficient')
    assert.equal(pending.attempt_count, 7)
    assert.equal(pending.accuracyText, '50%')
    assert.equal(calls.removed.length, 0)
    const current = page._buildMapNodes(payload(7))[0]
    assert.equal(current.pendingSync, false)
    assert.equal(current.status, 'mastered')
    assert.deepEqual(calls.removed, [[receipt]])
  })
})

test('detail request shares in-flight and cached results; force bypasses both', async () => {
  await withPage('detail', async ({ page, api, calls }) => {
    const pending = deferred()
    const fresh = deferred()
    api.get = url => { calls.get.push(url); return calls.get.length === 1 ? pending.promise : fresh.promise }
    const first = page._fetchDetail(2)
    assert.equal(page._fetchDetail(2), first)
    const forced = page._fetchDetail(2, true)
    assert.notEqual(forced, first)
    assert.equal(calls.get.length, 2)
    const detail = { knowledge_point_id: 2 }
    pending.resolve(detail)
    assert.equal(await first, detail)
    assert.equal(await page._fetchDetail(2), detail)
    fresh.resolve({ knowledge_point_id: 2, fresh: true })
    assert.equal((await forced).fresh, true)
    assert.equal((await page._fetchDetail(2)).fresh, true)
    assert.equal(calls.get.length, 2)
    assert.equal(page._detailRequests['2'], undefined)
  })
})

test('detail rejection removes the single-flight entry for retry', async () => {
  await withPage('detail', async ({ page, api }) => {
    api.get = () => Promise.reject(new Error('offline'))
    await assert.rejects(page._fetchDetail(2), /offline/)
    assert.equal(page._detailRequests['2'], undefined)
    api.get = () => Promise.resolve({ knowledge_point_id: 2 })
    assert.equal((await page._fetchDetail(2)).knowledge_point_id, 2)
  })
})

test('detail keeps parent subtree display and relation priority without merging scopes', async () => {
  await withPage('detail', async ({ page }) => {
    const raw = {
      knowledge_point_id: 1, status: 'mastered', mastery_score: 99, confidence: 1,
      direct_children: [{ knowledge_point_id: 2 }], subtree_status: 'weak',
      subtree_mastery_score: 23, subtree_confidence: 0.4, subtree_coverage_ratio: 1.2,
      subtree_trainable_knowledge_points: 1, trainable_question_count: 0,
      prerequisites: [{ knowledge_point_id: 3 }, { knowledge_point_id: 1 }],
      next_nodes: [{ knowledge_point_id: 3 }, { knowledge_point_id: 4 }],
      related_nodes: [{ knowledge_point_id: 4 }, { knowledge_point_id: 5 }],
      practice_route_params: { subject_id: 10, knowledge_point_id: 1 },
    }
    const result = page._normalizeDetail(raw)
    assert.equal(result.detail.display_status, 'weak')
    assert.equal(result.scoreText, '23%')
    assert.equal(result.confidenceText, '40%')
    assert.equal(result.accuracyText, '100%')
    assert.equal(result.practiceDisabled, false)
    assert.equal(result.relationCount, 6)
    assert.deepEqual(result.relationItems.map(item => [item.knowledge_point_id, item.relation_type]), [
      [3, 'prerequisite'], [4, 'next'], [5, 'related'],
    ])
    assert.equal(raw.display_status, undefined)
  })
})

test('unloaded detail relation switch cannot publish its late result', async () => {
  await withPage('detail', async ({ page, api, calls, timers }) => {
    const pending = deferred()
    api.get = () => pending.promise
    page.openRelation({ currentTarget: { dataset: { id: 2 } } })
    page.onUnload()
    const patchCount = calls.patches.length
    pending.resolve({ knowledge_point_id: 2 })
    await Promise.resolve()
    await Promise.resolve()
    assert.equal(calls.patches.length, patchCount)
    assert.equal(page.knowledgePointId, 1)
    assert.equal(timers.size, 0)
  })
})

test('legacy ordinary detail load can overwrite a later relation switch result', async () => {
  await withPage('detail', async ({ page, api, timers }) => {
    const first = deferred()
    api.get = url => url.endsWith('/1')
      ? first.promise
      : Promise.resolve({ knowledge_point_id: 2, name: 'related' })
    const initialLoad = page.loadDetail()
    page.openRelation({ currentTarget: { dataset: { id: 2 } } })
    await Promise.resolve()
    await Promise.resolve()
    const transition = [...timers.values()][0]
    assert.ok(transition)
    transition.callback()
    assert.equal(page.knowledgePointId, 2)
    assert.equal(page.data.detail.knowledge_point_id, 2)
    first.resolve({ knowledge_point_id: 1, name: 'original' })
    await initialLoad
    assert.equal(page.knowledgePointId, 2)
    assert.equal(page.data.detail.knowledge_point_id, 1)
    page.onUnload()
  })
})
