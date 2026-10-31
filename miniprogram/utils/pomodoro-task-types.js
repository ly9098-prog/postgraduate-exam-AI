const { get, set } = require('./storage-core')

const POMODORO_TASK_RECORDS_STORAGE_KEY = 'pomodoro_task_type_records_v1'
const SELECTION_KEY = 'pomodoro_task_type_selection_v1'
const MAX_RECORDS = 600
const DEFAULT_TYPE = 'new_questions'
const TYPES = [
  { value: 'lecture', label: '听课', shortLabel: '听课' },
  { value: 'textbook', label: '教材', shortLabel: '教材' },
  { value: 'new_questions', label: '新题', shortLabel: '新题' },
  { value: 'wrong_questions', label: '错题', shortLabel: '错题' },
  { value: 'review', label: '复习', shortLabel: '复习' },
  { value: 'exam', label: '真题', shortLabel: '真题' },
]
const TYPE_MAP = TYPES.reduce((map, item) => { map[item.value] = item; return map }, {})

function normalize(type) {
  return TYPE_MAP[type] ? type : DEFAULT_TYPE
}

function label(type) {
  return TYPE_MAP[normalize(type)].label
}

function getSelected() {
  return normalize(get(SELECTION_KEY))
}

function setSelected(type) {
  const normalized = normalize(type)
  set(SELECTION_KEY, normalized)
  return normalized
}

function loadRecords() {
  const raw = get(POMODORO_TASK_RECORDS_STORAGE_KEY)
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { version: 1, records: {} }
  return { version: 1, records: raw.records && typeof raw.records === 'object' ? raw.records : {} }
}

function saveRecords(payload) {
  set(POMODORO_TASK_RECORDS_STORAGE_KEY, payload)
}

function recordSession(session, type) {
  if (!session) return
  // An invalid/empty type never overwrites an existing attribution and never
  // creates a new default-classified record.
  if (!TYPE_MAP[type]) return
  const id = session.id != null ? String(session.id) : ''
  const clientId = String(session.client_start_id || session.clientStartId || '')
  if (!id && !clientId) return
  const data = loadRecords()
  const key = id ? `id:${id}` : `client:${clientId}`
  data.records[key] = { type: normalize(type), savedAt: Date.now(), clientId }
  if (id && clientId) data.records[`client:${clientId}`] = { type: normalize(type), savedAt: Date.now(), sessionId: id }
  const entries = Object.keys(data.records).map(keyName => ({ key: keyName, ...data.records[keyName] }))
  entries.sort((a, b) => Number(b.savedAt || 0) - Number(a.savedAt || 0))
  if (entries.length > MAX_RECORDS) {
    const keep = new Set(entries.slice(0, MAX_RECORDS).map(item => item.key))
    Object.keys(data.records).forEach(keyName => { if (!keep.has(keyName)) delete data.records[keyName] })
  }
  saveRecords(data)
}

function typeForSession(session) {
  if (!session) return ''
  // Only a valid type is classified. Invalid/legacy sessions stay unclassified
  // instead of inheriting whatever the current default happens to be.
  if (TYPE_MAP[session.task_type]) return session.task_type
  const data = loadRecords()
  const id = session.id != null ? String(session.id) : ''
  const clientId = String(session.client_start_id || session.clientStartId || '')
  const byId = id && data.records[`id:${id}`]
  const byClient = clientId && data.records[`client:${clientId}`]
  const found = byId || byClient
  const foundType = found && found.type
  return TYPE_MAP[foundType] ? foundType : ''
}

function labelForSession(session) {
  const type = typeForSession(session)
  return type ? label(type) : ''
}

const pomodoroTaskTypes = { STORAGE_KEY: POMODORO_TASK_RECORDS_STORAGE_KEY, SELECTION_KEY, TYPES, TYPE_MAP, DEFAULT_TYPE, normalize, label, getSelected, setSelected, recordSession, typeForSession, labelForSession }

module.exports = { pomodoroTaskTypes }
