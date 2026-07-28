/**
 * Preview temporary-file lifecycle manager.
 *
 * WeChat mini programs cannot run a reliable background cron job after the
 * app process is suspended. This module therefore combines:
 * 1) a seven-day foreground interval while the app is alive; and
 * 2) a due-check on every app launch/show.
 *
 * Downloaded preview files are tracked in local storage. Files that have not
 * been used for seven days are unlinked when cleanup runs. Missing files are
 * treated as already cleaned because the host may remove temp files itself.
 */

const STORAGE_KEY = '__preview_temp_files_v1__'
const LAST_CLEANUP_KEY = '__preview_temp_files_last_cleanup_v1__'
const FILE_TTL_MS = 7 * 24 * 60 * 60 * 1000
const CLEANUP_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000
const MAX_TRACKED_FILES = 100

function now() {
  return Date.now()
}

function readRecords() {
  try {
    const value = wx.getStorageSync(STORAGE_KEY)
    if (!Array.isArray(value)) return []
    return value.filter(function(item) {
      return item && typeof item.path === 'string' && item.path
    })
  } catch (_) {
    return []
  }
}

function writeRecords(records) {
  try {
    wx.setStorageSync(STORAGE_KEY, records.slice(-MAX_TRACKED_FILES))
  } catch (_) {}
}

function getLastCleanupAt() {
  try {
    return Number(wx.getStorageSync(LAST_CLEANUP_KEY)) || 0
  } catch (_) {
    return 0
  }
}

function setLastCleanupAt(timestamp) {
  try {
    wx.setStorageSync(LAST_CLEANUP_KEY, Number(timestamp) || now())
  } catch (_) {}
}

function unlinkFile(filePath) {
  return new Promise(function(resolve) {
    const fs = wx.getFileSystemManager && wx.getFileSystemManager()
    if (!fs || typeof fs.unlink !== 'function' || !filePath) {
      resolve(false)
      return
    }
    fs.unlink({
      filePath: filePath,
      success: function() { resolve(true) },
      // The host may already have removed a temp file. That still counts as a
      // successful cleanup from the application's perspective.
      fail: function() { resolve(false) },
    })
  })
}

function register(filePath, metadata) {
  if (!filePath) return
  const meta = metadata || {}
  const timestamp = now()
  const records = readRecords().filter(function(item) {
    return item.path !== filePath && (!meta.cacheKey || item.cacheKey !== meta.cacheKey)
  })
  records.push({
    path: filePath,
    cacheKey: meta.cacheKey ? String(meta.cacheKey) : '',
    taskId: meta.taskId == null ? null : Number(meta.taskId),
    createdAt: timestamp,
    lastAccessAt: timestamp,
  })
  writeRecords(records)
}

function touch(filePath) {
  if (!filePath) return
  const timestamp = now()
  const records = readRecords()
  var changed = false
  records.forEach(function(item) {
    if (item.path === filePath) {
      item.lastAccessAt = timestamp
      changed = true
    }
  })
  if (changed) writeRecords(records)
}

function findByCacheKey(cacheKey) {
  if (!cacheKey) return ''
  const key = String(cacheKey)
  const records = readRecords()
  for (var i = records.length - 1; i >= 0; i -= 1) {
    if (records[i].cacheKey === key) return records[i].path
  }
  return ''
}

function forget(filePath) {
  if (!filePath) return
  writeRecords(readRecords().filter(function(item) {
    return item.path !== filePath
  }))
}

async function remove(filePath, options) {
  if (!filePath) return
  forget(filePath)
  if (!options || options.unlink !== false) {
    await unlinkFile(filePath)
  }
}

async function removeByTaskId(taskId) {
  const numericTaskId = Number(taskId)
  if (!numericTaskId) return
  const records = readRecords()
  const removed = []
  const kept = []
  records.forEach(function(item) {
    if (Number(item.taskId) === numericTaskId) removed.push(item)
    else kept.push(item)
  })
  writeRecords(kept)
  await Promise.all(removed.map(function(item) {
    return unlinkFile(item.path)
  }))
}

async function cleanupIfDue(options) {
  const opts = options || {}
  const timestamp = now()
  const lastCleanupAt = getLastCleanupAt()
  if (!opts.force && lastCleanupAt && timestamp - lastCleanupAt < CLEANUP_INTERVAL_MS) {
    return { skipped: true, removed: 0, kept: readRecords().length }
  }

  const records = readRecords()
  const expired = []
  const kept = []
  records.forEach(function(item) {
    const lastUsedAt = Number(item.lastAccessAt || item.createdAt || 0)
    if (!lastUsedAt || timestamp - lastUsedAt >= FILE_TTL_MS) expired.push(item)
    else kept.push(item)
  })

  writeRecords(kept)
  setLastCleanupAt(timestamp)
  await Promise.all(expired.map(function(item) {
    return unlinkFile(item.path)
  }))

  return {
    skipped: false,
    removed: expired.length,
    kept: kept.length,
  }
}

module.exports = {
  FILE_TTL_MS: FILE_TTL_MS,
  CLEANUP_INTERVAL_MS: CLEANUP_INTERVAL_MS,
  register: register,
  touch: touch,
  findByCacheKey: findByCacheKey,
  forget: forget,
  remove: remove,
  removeByTaskId: removeByTaskId,
  cleanupIfDue: cleanupIfDue,
}
