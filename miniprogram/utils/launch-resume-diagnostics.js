const storage = require('./storage-core')

const KEY = 'debug_snapshot:launch_resume:v1'
const MAX_EVENTS = 20
const EVENTS = new Set([
  'entry_eligible', 'entry_skipped', 'entry_changed', 'navigation_success',
  'target_pending', 'target_practice', 'target_review', 'target_pomodoro', 'target_home',
  'auth_missing', 'auth_changed', 'pomodoro_inactive', 'pomodoro_local', 'pomodoro_unavailable',
  'pomodoro_terminal', 'practice_saved', 'practice_invalid', 'practice_save_failed',
  'practice_restored', 'practice_restore_failed', 'practice_missing',
])
const ROUTES = new Set([
  'pages/login/login', 'pages/home/home', 'pages/pomodoro/pomodoro',
  'subpackages/study/practice/practice?resume=1',
  'subpackages/study/review-today/review-today?autostart=1',
])

function safeRoute(route) {
  if (!route) return ''
  const normalized = String(route).replace(/^\//, '')
  return ROUTES.has(normalized) ? normalized : 'other'
}

function recordResumeEvent(event, options = {}) {
  if (!EVENTS.has(event)) return
  const entry = options.entry || {}
  const scene = Number(entry.scene)
  const record = {
    version: 1,
    event,
    at: Date.now(),
    path: safeRoute(entry.path),
    scene: entry.scene != null && Number.isFinite(scene) ? scene : null,
    queryCount: Object.keys(entry.query || {}).length,
    target: safeRoute(options.target),
  }
  try {
    const previous = storage.get(KEY)
    const history = Array.isArray(previous) ? previous.slice(-(MAX_EVENTS - 1)) : []
    storage.setStrict(KEY, history.concat(record))
  } catch (_) {
    console.warn('[LAUNCH_RESUME] diagnostics unavailable')
  }
}

module.exports = { recordResumeEvent }
