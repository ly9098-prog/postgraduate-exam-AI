const store = require('./launch-session-store')
const storage = require('./storage-core')
const api = require('./api')
const apiAuth = require('./api-auth')
const { recordResumeEvent } = require('./launch-resume-diagnostics')

const HOME = '/pages/home/home'
const PRACTICE = '/subpackages/study/practice/practice?resume=1'
const REVIEW = '/subpackages/study/review-today/review-today?autostart=1'
const POMODORO = '/pages/pomodoro/pomodoro'
const TIMEOUT_MS = 1500
const DEFAULT_ENTRY_SCENES = new Set([1001, 1005, 1006, 1017, 1023, 1027, 1089, 1090, 1103, 1104])
let coldEntryHandled = false
let consumedAuthInvalidationSeq = 0

function isDefaultEntry(entry) {
  if (!entry) return false
  const path = String(entry.path || '').replace(/^\//, '')
  if (path && path !== 'pages/login/login') return false
  if (Object.keys(entry.query || {}).length) return false
  return entry.scene == null || DEFAULT_ENTRY_SCENES.has(Number(entry.scene))
}

function resolvedTarget(event, target) {
  recordResumeEvent(event, { target })
  return target
}

function runningSession(session) {
  return Boolean(session && ['running', 'paused'].includes(session.status))
}

function localPomodoro() {
  const local = storage.get('pomodoro_running_state')
  return Boolean(local && String(local.ownerId || '') === store.userId() &&
    local.sessionId && Number(local.sessionStartTime) > 0 &&
    !storage.get('pomodoro_completion') && !storage.get('pomodoro_break'))
}

async function resolveLaunchTarget(options = {}) {
  if (!storage.get(storage.KEYS.TOKEN) || !store.userId()) return resolvedTarget('auth_missing', HOME)
  const owner = store.userId()
  const now = options.now == null ? Date.now() : options.now
  if (store.readPending(now)) return resolvedTarget('target_pending', PRACTICE)
  const active = store.readActive(now)
  if (active) return active.kind === 'practice'
    ? resolvedTarget('target_practice', PRACTICE) : resolvedTarget('target_review', REVIEW)
  if (storage.get('pomodoro_break') || storage.get('pomodoro_completion')) {
    return resolvedTarget('pomodoro_terminal', HOME)
  }
  let timer
  try {
    const response = await Promise.race([
      Promise.resolve().then(() => (options.getActive || (() =>
        api.get('/pomodoro/active', {}, { timeout: TIMEOUT_MS, suppressNetworkToast: true })))()),
      new Promise((resolve, reject) => {
        timer = setTimeout(() => reject(new Error('launch_resume_timeout')), TIMEOUT_MS)
      }),
    ])
    if (owner !== store.userId() || !storage.get(storage.KEYS.TOKEN)) {
      return resolvedTarget('auth_changed', HOME)
    }
    return runningSession(response)
      ? resolvedTarget('target_pomodoro', POMODORO) : resolvedTarget('pomodoro_inactive', HOME)
  } catch (_) {
    if (owner !== store.userId() || !storage.get(storage.KEYS.TOKEN)) {
      return resolvedTarget('auth_changed', HOME)
    }
    return localPomodoro()
      ? resolvedTarget('pomodoro_local', POMODORO) : resolvedTarget('pomodoro_unavailable', HOME)
  } finally {
    clearTimeout(timer)
  }
}

function createLoginResume(platform = wx) {
  const launch = typeof platform.getLaunchOptionsSync === 'function'
    ? platform.getLaunchOptionsSync() : null
  const authInvalidationSeq = typeof apiAuth.getAuthInvalidationSeq === 'function'
    ? apiAuth.getAuthInvalidationSeq() : 0
  let eligible = isDefaultEntry(launch) && (!coldEntryHandled ||
    authInvalidationSeq > consumedAuthInvalidationSeq)
  recordResumeEvent(eligible ? 'entry_eligible' : 'entry_skipped', { entry: launch })
  let lastTarget
  return {
    async resolve() {
      const target = eligible ? await resolveLaunchTarget() : HOME
      const entry = typeof platform.getEnterOptionsSync === 'function'
        ? platform.getEnterOptionsSync() : launch
      if (eligible && !isDefaultEntry(entry)) {
        eligible = false
        coldEntryHandled = true
        recordResumeEvent('entry_changed', { entry })
        return null
      }
      lastTarget = target
      return target
    },
    complete() {
      eligible = false
      coldEntryHandled = true
      consumedAuthInvalidationSeq = typeof apiAuth.getAuthInvalidationSeq === 'function'
        ? apiAuth.getAuthInvalidationSeq() : 0
      recordResumeEvent('navigation_success', { target: lastTarget })
    },
  }
}

module.exports = { resolveLaunchTarget, createLoginResume, isDefaultEntry }
