const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../subpackages/productivity/pomodoro-stats')
const FACTORIES = {
  "./duration-animation-controller": "createDurationAnimationController",
  "./pie-tap-controller": "createPieTapController",
  "./start-animations-controller": "createStartAnimationsController",
  "./distribution-commit-controller": "createDistributionCommitController",
  "./save-day-start-controller": "createSaveDayStartController",
  "./settings-controller": "createSettingsController",
  "./select-date-controller": "createSelectDateController",
  "./cumulative-refresh-controller": "createCumulativeRefreshController",
  "./cumulative-start-controller": "createCumulativeStartController",
  "./distribution-load-controller": "createDistributionLoadController",
  "./distribution-entry-controller": "createDistributionEntryController",
  "./close-detail-controller": "createCloseDetailController",
  "./day-start-entry-controller": "createDayStartEntryController",
  "./subject-meta-controller": "createSubjectMetaController",
  "./trend-animation-controller": "createTrendAnimationController",
  "./pie-animation-controller": "createPieAnimationController",
  "./pie-label-reveal-controller": "createPieLabelRevealController",
  "./cancel-work-controller": "createCancelWorkController",
  "./canvas-init-controller": "createStatsCanvasInitController",
  "./theme-sync-controller": "createThemeSyncController",
  "./deferred-history-controller": "createDeferredHistoryController",
  "./load-commit-controller": "createLoadCommitController",
  "./date-commit-controller": "createDateCommitController",
  "./load-failure-controller": "createLoadFailureController",
  "./date-failure-controller": "createDateFailureController",
  "./date-request-controller": "createDateRequestController",
  "./date-navigation-controller": "createDateNavigationController",
  "./chart-mode-controller": "createChartModeController",
  "./dynamic-refresh-controller": "createDynamicRefreshController",
  "./load-request-controller": "createLoadRequestController",
  "./page-init-controller": "createPageInitController",
  "./lifecycle-controller": "createLifecycleController"
}

function fixture(sourcePath = process.env.STATS_PAGE_SOURCE) {
  const calls = [], instances = [], cache = new Map()
  let definition
  const api = { now: () => 1234, createTraceId: () => 'trace' }
  const config = { DEV: false, enableMathImage: false }
  const stubs = {
    '../../../utils/api': api, '../../../config': config,
    '../../../utils/storage': {}, '../utils/pomodoro-theme': {}, '../utils/china-time': {},
  }
  const platform = new Proxy({}, { get: (object, key) => key in object ? object[key] : (...args) => { calls.push([key, ...args]); return undefined } })
  const context = vm.createContext({ Page: value => { definition = value }, wx: platform,
    console: { warn: (...args) => calls.push(['warn', ...args]), error: (...args) => calls.push(['error', ...args]), log: (...args) => calls.push(['log', ...args]) },
    Date: { now: () => 1000 }, Math, Promise, getCurrentPages: () => [],
    setTimeout: (fn, delay) => { calls.push(['timeout', fn, delay]); return 11 },
    clearTimeout: id => calls.push(['clearTimeout', id]), setInterval, clearInterval,
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }; cache.set(filename, module)
    const required = request => {
      if (Object.hasOwn(stubs, request)) return stubs[request]
      if (Object.hasOwn(FACTORIES, request)) return { [FACTORIES[request]]: options => {
        const instance = { type: FACTORIES[request], options }; instances.push(instance); return instance
      } }
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      if (!resolved.startsWith(root + path.sep)) throw Error('Unexpected dependency: ' + request)
      return load(resolved)
    }
    const input = filename === path.join(root, 'index.js') && sourcePath ? sourcePath : filename
    vm.runInContext('(function(require,module,exports) {\n' + fs.readFileSync(input, 'utf8') + '\n})', context, { filename })(required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'index.js'))
  const page = Object.assign({}, definition, { data: JSON.parse(JSON.stringify(definition.data)),
    setData(patch, callback) { calls.push(['setData', patch]); Object.assign(this.data, patch); if (callback) callback() },
  })
  return { page, methods: definition, calls, instances, stubs, api, config, context, platform }
}

module.exports = { fixture, FACTORIES }
