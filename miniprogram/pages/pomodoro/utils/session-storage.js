function readStorage(storage, key, context = '') {
  try {
    return { ok: true, value: storage.getStorageSync(key) }
  } catch (error) {
    console.error(`pomodoro storage read failed${context ? ` (${context})` : ''}: ${key}`, error)
    return { ok: false, value: null }
  }
}

function writeStorage(storage, key, value, context = '') {
  try {
    storage.setStorageSync(key, value)
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

module.exports = { readStorage, writeStorage, removeStorage }
