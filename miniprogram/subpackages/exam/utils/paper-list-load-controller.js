function createPaperListLoadController(options) {
  const state = { loadPromise: null }
  return {
    load: loadImpl.bind(null, options, state),
  }
}

async function loadImpl(options, state, requestOptions = {}) {
  const silent = !!requestOptions.silent
  const force = !!requestOptions.force
  const suppressErrorToast = !!requestOptions.suppressErrorToast
  if (state.loadPromise && !force) return state.loadPromise

  if (!silent && !options.wasLoadedOnce()) {
    options.setData({ loading: true, errorText: '' })
  }

  // A cancellation can happen while an onShow refresh is still in flight.
  // Allow the post-cancel force refresh to overtake it, and only let the
  // newest generation commit. This prevents stale responses from restoring
  // a just-cancelled "continue" state.
  const generation = options.nextGeneration()
  const request = runLoad(options, generation, { silent, suppressErrorToast })

  state.loadPromise = request
  try {
    await request
  } finally {
    if (state.loadPromise === request) state.loadPromise = null
  }
}

async function runLoad(options, generation, context) {
  try {
    const rows = await options.getPapers()
    const papers = options.buildPapers(rows)
    if (!options.isPageAlive() || generation !== options.getGeneration()) return
    const wasLoaded = options.wasLoadedOnce()
    options.markLoadedOnce()
    options.commitPapers(papers, { silent: context.silent || wasLoaded })
  } catch (error) {
    if (!options.isPageAlive() || generation !== options.getGeneration()) return
    const message = options.getErrorMessage(error)
    if ((context.silent || options.wasLoadedOnce()) && !options.getErrorText()) {
      if (!context.suppressErrorToast) options.showToast({ title: message, icon: 'none' })
      return
    }
    options.setData({ loading: false, errorText: message })
  }
}

module.exports = {
  createPaperListLoadController,
}
