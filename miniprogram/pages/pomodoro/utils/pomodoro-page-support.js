// Constants and pure helpers shared by the pomodoro page and its capability adapters.

const { parseServerUtc } = require('../../../utils/china-time')

const PHASE = { IDLE: 'idle', RUNNING: 'running', BREAK: 'break', CEREMONY: 'ceremony' }

const PRESETS = [
  { key: 'standard', label: '标准', work: 25, break: 5 },
  { key: 'long', label: '长时间', work: 50, break: 10 },
  { key: 'custom', label: '自定义', work: 25, break: 5 },
  { key: 'free', label: '自由计时', work: 0, break: 0 },
]

const MOTTOES = [
  '击败了昨天的自己',
  '每一步都算数',
  '坚持就是胜利',
  '离上岸又近一步',
  '今天的你比昨天更强',
  '积少成多，聚沙成塔',
  '专注是最好的努力',
  '为梦想全力以赴',
]

const FREE_TIMER_MAX_MS = 5 * 60 * 60 * 1000 // 5 hours max for free timer

const POMODORO_UNKNOWN_START_KEY = 'pomodoro_unknown_start'

const POMODORO_TERMINAL_CONFLICT_KEY = 'pomodoro_terminal_conflict'

const POMODORO_PAUSE_TOGGLE_COOLDOWN_MS = 500

function parseServerTime(value) {
  return parseServerUtc(value)
}

module.exports = {
  PHASE,
  PRESETS,
  MOTTOES,
  FREE_TIMER_MAX_MS,
  POMODORO_UNKNOWN_START_KEY,
  POMODORO_TERMINAL_CONFLICT_KEY,
  POMODORO_PAUSE_TOGGLE_COOLDOWN_MS,
  parseServerTime,
}
