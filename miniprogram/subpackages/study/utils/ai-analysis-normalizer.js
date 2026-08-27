/**
 * AI 分析数据标准化工具
 * 纯函数，无外部依赖，无副作用。
 * 将各种异常后端结构统一为 { mistake_diagnosis, knowledge_patch, review_task, formatError }
 */

var MAX_DEPTH = 6

var WRAPPER_KEYS = ['content', 'data', 'result', 'analysis', 'ai_analysis', 'payload']

var DIAGNOSIS_KEYS = [
  'mistake_diagnosis', 'error_analysis', 'diagnosis',
  'mistakeDiagnosis', 'mistakediagnosis', '错因诊断',
]
var KNOWLEDGE_KEYS = [
  'knowledge_patch', 'knowledge_weakness', 'knowledge',
  'knowledgePatch', 'knowledgepatch', '补漏重点',
]
var TASK_KEYS = [
  'review_task', 'suggestion', 'task',
  'reviewTask', 'reviewtask', 'reviewask', '复练任务',
]

var ALL_KNOWN_KEYS = []
  .concat(DIAGNOSIS_KEYS)
  .concat(KNOWLEDGE_KEYS)
  .concat(TASK_KEYS)

var TEXT_SUB_KEYS = ['text', 'content', 'value', 'description']

/**
 * 安全 JSON 字符串解析，不抛异常
 */
function _safeParse(str) {
  try { return JSON.parse(str) } catch (_) { return null }
}

/**
 * 判断字符串是否"看起来像 JSON"
 */
function _looksLikeJson(str) {
  if (typeof str !== 'string' || !str) return false
  var t = str.trim()
  if (!t) return false
  if (/^```(?:json|javascript|js)?/i.test(t)) return true
  // 以 { 或 [ 开头，或出现带引号的已知 JSON 字段。不要仅凭 task /
  // knowledge 等普通英文单词判断，避免误伤正常 AI 文本。
  if (t.charAt(0) === '{' || t.charAt(0) === '[') return true
  for (var i = 0; i < ALL_KNOWN_KEYS.length; i++) {
    var escaped = ALL_KNOWN_KEYS[i].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    var re = new RegExp("[\"']" + escaped + "[\"']\\s*:", 'i')
    if (re.test(t)) return true
  }
  return false
}

/**
 * 去除 Markdown 代码围栏
 */
function _stripFence(str) {
  var value = String(str || '').trim()
  var m = value.match(/```(?:json|javascript|js)?\s*\n?([\s\S]*?)\n?```/i)
  if (m) return m[1].trim()
  // 网络中断时可能只有开围栏没有闭围栏；先移除围栏，后续按结构化
  // 内容处理，绝不把 ```json / { ... } 作为普通正文展示。
  value = value.replace(/^```(?:json|javascript|js)?\s*/i, '')
  value = value.replace(/\s*```$/, '')
  return value.trim()
}

/**
 * 递归解包 wrapper 字段 (content/data/result/...)
 */
function _unwrapWrapper(obj, depth) {
  if (depth >= MAX_DEPTH) return obj
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return obj
  for (var i = 0; i < WRAPPER_KEYS.length; i++) {
    var val = obj[WRAPPER_KEYS[i]]
    if (val !== undefined && val !== null) {
      if (typeof val === 'string') {
        var parsed = _tryParseStructuredString(val)
        if (parsed && typeof parsed === 'object') return _unwrapWrapper(parsed, depth + 1)
      } else if (typeof val === 'object' && !Array.isArray(val)) {
        return _unwrapWrapper(val, depth + 1)
      }
    }
  }
  return obj
}

/**
 * 安全顶层 JSON 分割器：按 {}[] 深度在顶层切分
 * 正确处理字符串中的花括号和转义引号
 */
function _splitTopLevelJson(text) {
  var results = []
  var depth = 0
  var braceDepth = 0
  var bracketDepth = 0
  var inString = false
  var start = -1
  var i = 0

  for (i = 0; i < text.length; i++) {
    var ch = text.charAt(i)
    var prev = i > 0 ? text.charAt(i - 1) : ''

    if (inString) {
      if (ch === '"' && prev !== '\\') inString = false
      continue
    }

    if (ch === '"') {
      inString = true
      continue
    }

    if (ch === '{') {
      if (start === -1) start = i
      braceDepth++
      depth++
    } else if (ch === '}') {
      braceDepth--
      depth--
      if (depth === 0 && start !== -1) {
        results.push(text.substring(start, i + 1))
        start = -1
      }
    } else if (ch === '[') {
      if (start === -1) start = i
      bracketDepth++
      depth++
    } else if (ch === ']') {
      bracketDepth--
      depth--
      if (depth === 0 && start !== -1) {
        results.push(text.substring(start, i + 1))
        start = -1
      }
    }
  }

  return results
}

function _tryParseStructuredString(value) {
  if (typeof value !== 'string') return null
  var stripped = _stripFence(value)
  if (!stripped) return null
  var parsed = _safeParse(stripped)
  if (parsed && typeof parsed === 'object') return parsed

  // 兼容模型输出前后说明文字或连续多个 JSON 对象。
  var parts = _splitTopLevelJson(stripped)
  if (!parts.length) return null
  var candidates = []
  for (var i = 0; i < parts.length; i++) {
    var item = _safeParse(parts[i])
    if (item && typeof item === 'object') candidates.push(item)
  }
  if (!candidates.length) return null
  if (candidates.length === 1) return candidates[0]
  return _pickBestObject(candidates) || candidates[0]
}

/**
 * 从数组中选字段最完整的对象
 */
function _pickBestObject(arr) {
  if (!arr || !arr.length) return null
  var best = null
  var bestScore = -1
  for (var i = 0; i < arr.length; i++) {
    var item = arr[i]
    if (!item || typeof item !== 'object') continue
    var score = 0
    if (item.mistake_diagnosis || item.error_analysis || item.diagnosis) score += 3
    if (item.knowledge_patch || item.knowledge_weakness || item.knowledge) score += 2
    if (item.review_task || item.suggestion || item.task) score += 2
    if (item.mistakeDiagnosis) score += 2
    if (item.knowledgePatch) score += 1
    if (item.reviewTask) score += 1
    if (score > bestScore) { bestScore = score; best = item }
  }
  return best
}

/**
 * 从对象中提取字段值，支持别名链
 */
function _extractField(obj, keys) {
  for (var i = 0; i < keys.length; i++) {
    var val = obj[keys[i]]
    if (val !== undefined && val !== null) return val
  }
  return ''
}

/**
 * 标准化字段值：处理字符串/对象/数组等
 */
function _normalizeFieldValue(raw) {
  if (raw === null || raw === undefined) return ''
  if (typeof raw === 'number') return String(raw)
  if (typeof raw === 'string') {
    var trimmed = raw.trim()
    if (!trimmed) return ''
    // 尝试递归解析 JSON 字符串
    var result = _tryParseStructuredString(trimmed)
    if (result !== null && typeof result === 'object') {
      return _extractTextFromObject(result)
    }
    // 结构化内容解析失败时返回空值，让上层进入 formatError / 重试态，
    // 避免原始 JSON 被当成“错因诊断”正文直接显示。
    if (_looksLikeJson(_stripFence(trimmed))) return ''
    return trimmed
  }
  if (typeof raw === 'object') {
    if (Array.isArray(raw)) {
      // 字符串数组，去空去重后用换行连接
      var strs = []
      for (var i = 0; i < raw.length; i++) {
        var v = raw[i]
        if (typeof v === 'string' && v.trim()) {
          var clean = v.trim()
          if (!_looksLikeJson(_stripFence(clean)) && strs.indexOf(clean) === -1) strs.push(clean)
        } else if (typeof v === 'object' && v !== null) {
          var t = _extractTextFromObject(v)
          if (t && strs.indexOf(t) === -1) strs.push(t)
        }
      }
      return strs.join('\n')
    }
    // 对象 → 提取 text/content/value/description
    return _extractTextFromObject(raw)
  }
  return String(raw)
}

/**
 * 递归解析 JSON 字符串（处理双重编码）
 */
function _recursiveParseString(str, depth) {
  if (depth >= MAX_DEPTH) return str
  var trimmed = str.trim()
  if (!trimmed) return str
  if ((trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[')) {
    var parsed = _safeParse(trimmed)
    if (parsed && typeof parsed === 'object') return parsed
  }
  return str
}

/**
 * 从对象中提取文本（递归查找 text/content/value/description）
 */
function _extractTextFromObject(obj) {
  if (!obj || typeof obj !== 'object') return String(obj || '')
  for (var i = 0; i < TEXT_SUB_KEYS.length; i++) {
    var val = obj[TEXT_SUB_KEYS[i]]
    if (val !== undefined && val !== null) {
      if (typeof val === 'string') {
        var t = val.trim()
        if (t) return t
      } else if (typeof val === 'object') {
        var r = _extractTextFromObject(val)
        if (r) return r
      }
    }
  }
  return ''
}

/**
 * 检测三个字段是否全部为空
 */
function _isEmptyResult(result) {
  return !(
    (result.mistake_diagnosis && String(result.mistake_diagnosis).trim()) ||
    (result.knowledge_patch && String(result.knowledge_patch).trim()) ||
    (result.review_task && String(result.review_task).trim())
  )
}

/**
 * 标准化 AI 分析 Payload
 *
 * @param {*} input - 后端返回的原始数据结构
 * @returns {{ mistake_diagnosis: string, knowledge_patch: string, review_task: string, formatError?: boolean }}
 */
function normalizeAiAnalysisPayload(input) {
  // 第一步：处理空值
  if (input === null || input === undefined) return EMPTY
  if (typeof input === 'string' && !input.trim()) return EMPTY
  if (typeof input === 'object' && !Array.isArray(input) && Object.keys(input).length === 0) return EMPTY
  if (Array.isArray(input) && input.length === 0) return EMPTY

  var obj = input

  // 字符串 → 处理
  if (typeof obj === 'string') {
    var trimmed = obj.trim()
    // 尝试去围栏
    var unfenced = _stripFence(trimmed)
    // 尝试解析 JSON
    var parsed = _safeParse(unfenced)
    if (parsed && typeof parsed === 'object') {
      obj = parsed
    } else {
      // 处理连续 JSON 对象
      var parts = _splitTopLevelJson(unfenced)
      if (parts.length > 0) {
        var best = null
        var bestScore = -1
        for (var pi = 0; pi < parts.length; pi++) {
          var p = _safeParse(parts[pi])
          if (p && typeof p === 'object' && !Array.isArray(p)) {
            var score = 0
            if (p.mistake_diagnosis || p.error_analysis) score += 3
            if (p.knowledge_patch || p.knowledge_weakness) score += 2
            if (p.review_task || p.suggestion) score += 2
            if (score > bestScore) { bestScore = score; best = p }
          }
        }
        if (best) {
          obj = best
        } else {
          // 检查是否看起来像 JSON
          if (_looksLikeJson(trimmed)) {
            return { mistake_diagnosis: '', knowledge_patch: '', review_task: '', formatError: true }
          }
          // 普通文本 → 作为错因诊断
          return { mistake_diagnosis: trimmed, knowledge_patch: '', review_task: '' }
        }
      } else {
        // 检查是否看起来像 JSON
        if (_looksLikeJson(trimmed)) {
          return { mistake_diagnosis: '', knowledge_patch: '', review_task: '', formatError: true }
        }
        return { mistake_diagnosis: trimmed, knowledge_patch: '', review_task: '' }
      }
    }
  }

  // 数组 → 选最完整对象
  if (Array.isArray(obj)) {
    var bestObj = _pickBestObject(obj)
    if (bestObj) {
      obj = bestObj
    } else {
      // 数组但无可用对象
      var arrText = []
      var arrayFormatError = false
      for (var ai = 0; ai < obj.length; ai++) {
        if (typeof obj[ai] === 'string' && obj[ai].trim()) {
          var arrayItem = obj[ai].trim()
          if (_looksLikeJson(_stripFence(arrayItem))) {
            arrayFormatError = true
            continue
          }
          if (arrText.indexOf(arrayItem) === -1) arrText.push(arrayItem)
        }
      }
      if (arrText.length) return { mistake_diagnosis: arrText.join('\n'), knowledge_patch: '', review_task: '' }
      return arrayFormatError
        ? { mistake_diagnosis: '', knowledge_patch: '', review_task: '', formatError: true }
        : EMPTY
    }
  }

  // 对象 → 递归解包 wrapper
  obj = _unwrapWrapper(obj, 0)
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return EMPTY

  // 部分模型/网关会把完整 JSON 再塞进 mistake_diagnosis 等字段。
  // 先提升这类嵌套结构，再提取普通字符串字段，防止 raw JSON 泄漏。
  for (var eki = 0; eki < ALL_KNOWN_KEYS.length; eki++) {
    var embeddedRaw = obj[ALL_KNOWN_KEYS[eki]]
    if (typeof embeddedRaw !== 'string') continue
    var embeddedClean = _stripFence(embeddedRaw)
    if (!_looksLikeJson(embeddedClean)) continue
    var embeddedObj = _tryParseStructuredString(embeddedRaw)
    if (!embeddedObj || typeof embeddedObj !== 'object') continue
    var embeddedResult = normalizeAiAnalysisPayload(embeddedObj)
    if (hasAiAnalysisContent(embeddedResult)) return embeddedResult
  }

  // 提取三个字段
  var rawDiagnosis = _extractField(obj, DIAGNOSIS_KEYS)
  var rawKnowledge = _extractField(obj, KNOWLEDGE_KEYS)
  var rawTask = _extractField(obj, TASK_KEYS)

  // 标准化字段值
  var diagnosis = _normalizeFieldValue(rawDiagnosis)
  var knowledge = _normalizeFieldValue(rawKnowledge)
  var task = _normalizeFieldValue(rawTask)

  // 去除常见标题前缀
  diagnosis = diagnosis.replace(/^错因诊断[：:]\s*/, '')
  knowledge = knowledge.replace(/^补漏重点[：:]\s*/, '')
  task = task.replace(/^复练任务[：:]\s*/, '')

  var result = {
    mistake_diagnosis: diagnosis,
    knowledge_patch: knowledge,
    review_task: task,
  }

  // 如果三个字段全空，但输入看起来像结构化 JSON，标记格式错误
  if (_isEmptyResult(result) && _looksLikeJson(JSON.stringify(input))) {
    result.formatError = true
  }

  return result
}

var EMPTY = { mistake_diagnosis: '', knowledge_patch: '', review_task: '' }

/**
 * 检查标准化结果是否包含有效正文
 */
function hasAiAnalysisContent(result) {
  if (!result || typeof result !== 'object') return false
  return !!(
    (result.mistake_diagnosis && String(result.mistake_diagnosis).trim()) ||
    (result.knowledge_patch && String(result.knowledge_patch).trim()) ||
    (result.review_task && String(result.review_task).trim())
  )
}

module.exports = {
  normalizeAiAnalysisPayload: normalizeAiAnalysisPayload,
  hasAiAnalysisContent: hasAiAnalysisContent,
}
