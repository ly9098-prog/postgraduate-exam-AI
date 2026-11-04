function readStorage(storage, key, context = '') {
  try {
    const value = storage.getStorageSync(key)
    if (key === 'pomodoro_running_state' && value) {
      const owner = currentOwner(storage)
      if (!owner) return { ok: true, value: null }
      if (String(value.ownerId || '') !== owner) {
        storage.removeStorageSync(key)
        return { ok: true, value: null }
      }
    }
    return { ok: true, value }
  } catch (error) {
    console.error(`pomodoro storage read failed${context ? ` (${context})` : ''}: ${key}`, error)
    return { ok: false, value: null }
  }
}

function writeStorage(storage, key, value, context = '') {
  try {
    const owner = key === 'pomodoro_running_state' ? currentOwner(storage) : ''
    if (key === 'pomodoro_running_state' && !owner) return false
    const owned = key === 'pomodoro_running_state' ? { ...value, ownerId: owner } : value
    storage.setStorageSync(key, owned)
    return true
  } catch (error) {
    console.error(`pomodoro storage write failed${context ? ` (${context})` : ''}: ${key}`, error)
    return false
  }
}

function removeStorage(storage, key, context = '') {
  try {
    storage.removeStorageSync(key)
    return true
  } catch (error) {
    console.warn(`pomodoro storage remove failed${context ? ` (${context})` : ''}: ${key}`, error)
    return false
  }
}

function currentOwner(storage) {
  const user = storage.getStorageSync('user') || {}
  return String(user.id || user.user_id || user.openid || '')
}

module.exports = { readStorage, writeStorage, removeStorage }
