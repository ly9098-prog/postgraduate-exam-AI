/**
 * 隐私协议版本管理
 *
 * 用于：
 * 1. 记录用户已同意的协议版本
 * 2. 协议版本升级后要求用户重新确认
 * 3. 退出登录时清除同意记录
 */

const storage = require('./storage')

// 当前协议版本号（更新协议后修改此值）
const CURRENT_PRIVACY_VERSION = '1.0'

const AGREEMENT_ITEMS = [
  'user_agreement',
  'privacy_policy',
  'ai_service',
]

const PRIVACY_KEY = 'privacy_acceptance'

/**
 * 获取当前协议版本号
 */
function getCurrentPrivacyVersion() {
  return CURRENT_PRIVACY_VERSION
}

/**
 * 获取已存储的协议同意记录
 */
function _getStored() {
  try {
    return storage.get(PRIVACY_KEY) || {}
  } catch (_) {
    return {}
  }
}

/**
 * 检查用户是否已同意当前版本的全部协议
 */
function hasAcceptedCurrentPrivacy() {
  const stored = _getStored()
  return stored.privacy_version === CURRENT_PRIVACY_VERSION &&
    Array.isArray(stored.accepted_items) &&
    AGREEMENT_ITEMS.every(function (item) {
      return stored.accepted_items.indexOf(item) >= 0
    })
}

/**
 * 保存协议同意记录
 * @param {string[]} [items] - 用户同意的协议项列表，默认为全部
 */
function savePrivacyAcceptance(items) {
  const accepted = items || AGREEMENT_ITEMS.slice()
  storage.set(PRIVACY_KEY, {
    privacy_version: CURRENT_PRIVACY_VERSION,
    accepted_at: Date.now(),
    accepted_items: accepted,
  })
}

/**
 * 清除协议同意记录（退出登录时调用）
 */
function clearPrivacyAcceptance() {
  storage.remove(PRIVACY_KEY)
}

module.exports = {
  getCurrentPrivacyVersion,
  hasAcceptedCurrentPrivacy,
  savePrivacyAcceptance,
  clearPrivacyAcceptance,
  AGREEMENT_ITEMS,
}
