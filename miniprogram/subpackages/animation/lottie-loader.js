// 分包共享 Lottie 加载器
// 所有 Lottie 动画数据和 lottie-miniprogram 模块统一从此入口加载，
// 确保文件位于分包中，不占用主包体积。

var MODULE_CACHE = undefined
var LOADING_CACHE = null
var REWARD_CACHE = null

function getModule() {
  if (MODULE_CACHE !== undefined) return MODULE_CACHE
  var mod = null
  try { mod = require('./lottie-vendor/index') } catch (_) {}
  MODULE_CACHE = mod || null
  return MODULE_CACHE
}

function getLoadingData() {
  if (LOADING_CACHE !== null) return LOADING_CACHE
  var mod = null
  try { mod = require('./lottie/loading/loading.js') } catch (_) {}
  LOADING_CACHE = mod || false
  return LOADING_CACHE
}

function getRewardData() {
  if (REWARD_CACHE !== null) return REWARD_CACHE

  var map = {}
  var trophyMod, successMod
  var awardMod, thumbsUpMod

  try { trophyMod = require('./lottie/reward/trophy.js') } catch (_) {}
  try { successMod = require('./lottie/success/success-check.js') } catch (_) {}
  try { awardMod = require('./lottie/reward/award.js') } catch (_) {}
  try { thumbsUpMod = require('./lottie/reward/thumbs-up.js') } catch (_) {}

  if (trophyMod) map.excellent = trophyMod
  if (successMod) { map.practice = successMod; map.steady = successMod }
  if (awardMod) map.award = awardMod
  if (thumbsUpMod) map.thumbsUp = thumbsUpMod

  REWARD_CACHE = Object.keys(map).length ? map : false
  return REWARD_CACHE
}

module.exports = { getModule: getModule, getLoadingData: getLoadingData, getRewardData: getRewardData }
