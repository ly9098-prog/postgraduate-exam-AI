"""v2 queue terminal-transition Lua scripts.

Every completion, failure, dead-letter, corruption, and cancellation transition
must verify both owner token and monotonic fencing generation before changing
authoritative queue state.
"""

# COMPLETE_V2 — verify owner_token AND generation
# KEYS: [processing_key, retry_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, owner_token, task_json, completed_ttl, fencing_tombstone_ttl]
# Returns: 1 on success, 0 on owner mismatch, -1 on generation mismatch
_LUA_COMPLETE_V2 = """
local task_id = ARGV[1]
local owner_token = ARGV[2]
local task_json = ARGV[3]
local ttl = tonumber(ARGV[4])
local fence_ttl = tonumber(ARGV[5])
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end
local stored_gen = redis.call("HGET", KEYS[3] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[5] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then
    return -1
end
redis.call("ZREM", KEYS[1], task_id)
redis.call("ZREM", KEYS[2], task_id)
redis.call("HSET", KEYS[3] .. ":" .. task_id,
    "data", task_json, "status", "completed",
    "owner_token", "", "lease_expires_at", 0, "error", "")
redis.call("HDEL", KEYS[3] .. ":" .. task_id, "cancel_requested", "cancel_reason")
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, ttl)
redis.call("DEL", KEYS[4] .. ":" .. task_id)
redis.call("EXPIRE", KEYS[5] .. ":" .. task_id, fence_ttl)
return 1
"""

# FAIL_RETRY_V2 — verify owner+generation, retry-full atomic → dead-letter.
# KEYS: [processing_key, retry_key, dead_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, retry_at, task_json, owner_token, retry_count, error, retry_max, dead_max]
# Returns: 1 (retry), 2 (dead-letter due to full), 0 (owner mismatch), -1 (gen mismatch)
_LUA_FAIL_RETRY_V2 = """
local task_id = ARGV[1]
local retry_delay = tonumber(ARGV[2]) or 0
local task_json = ARGV[3]
local owner_token = ARGV[4]
local retry_count = tonumber(ARGV[5]) or 1
local error_msg = ARGV[6] or ""
local retry_max = tonumber(ARGV[7]) or 500
local dead_max = tonumber(ARGV[8]) or 1000
local fence_ttl = tonumber(ARGV[9]) or 604800
local now = tonumber(redis.call("TIME")[1])
local retry_at = now + retry_delay
local stored = redis.call("GET", KEYS[5] .. ":" .. task_id)
if not stored or stored ~= owner_token then return 0 end
local stored_gen = redis.call("HGET", KEYS[4] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[6] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then return -1 end
redis.call("ZREM", KEYS[1], task_id)
redis.call("DEL", KEYS[5] .. ":" .. task_id)

if retry_max > 0 and redis.call("ZCARD", KEYS[2]) >= retry_max then
    redis.call("LPUSH", KEYS[3], task_id)
    redis.call("LTRIM", KEYS[3], 0, dead_max - 1)
    redis.call("EXPIRE", KEYS[3], fence_ttl)
    local dead_json = task_json
    local decoded_ok, decoded = pcall(cjson.decode, task_json)
    if decoded_ok and type(decoded) == "table" then
        decoded["status"] = "dead"
        decoded["owner_token"] = ""
        decoded["lease_expires_at"] = 0
        dead_json = cjson.encode(decoded)
    end
    redis.call("HSET", KEYS[4] .. ":" .. task_id,
        "data", dead_json, "status", "dead", "retry_count", retry_count,
        "error", error_msg, "owner_token", "", "lease_expires_at", 0)
    redis.call("EXPIRE", KEYS[4] .. ":" .. task_id, fence_ttl)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, fence_ttl)
    return 2
end

redis.call("ZADD", KEYS[2], retry_at, task_id)
redis.call("HSET", KEYS[4] .. ":" .. task_id,
    "data", task_json, "status", "failed", "retry_count", retry_count,
    "error", error_msg, "owner_token", "", "lease_expires_at", 0)
return 1
"""

# FAIL_DEAD_V2 — verify owner+generation → ZREM processing → LPUSH dead → HSET status=dead
# KEYS: [processing_key, dead_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, task_json, owner_token, dead_max, fencing_tombstone_ttl]
# Returns: 1 on success, 0 on owner mismatch, -1 on generation mismatch
_LUA_FAIL_DEAD_V2 = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local owner_token = ARGV[3]
local dead_max = tonumber(ARGV[4]) or 1000
local fence_ttl = tonumber(ARGV[5])
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then return 0 end
local stored_gen = redis.call("HGET", KEYS[3] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[5] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then return -1 end
local retry_count = 0
local last_error = ""
local decoded_ok, decoded = pcall(cjson.decode, task_json)
if decoded_ok and type(decoded) == "table" then
    retry_count = tonumber(decoded["retry_count"]) or 0
    last_error = tostring(decoded["error"] or "")
end
redis.call("ZREM", KEYS[1], task_id)
redis.call("LPUSH", KEYS[2], task_id)
redis.call("LTRIM", KEYS[2], 0, dead_max - 1)
redis.call("EXPIRE", KEYS[2], fence_ttl)
redis.call("HSET", KEYS[3] .. ":" .. task_id,
    "data", task_json, "status", "dead", "owner_token", "", "lease_expires_at", 0,
    "retry_count", retry_count, "error", string.sub(last_error, 1, 500))
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, fence_ttl)
redis.call("DEL", KEYS[4] .. ":" .. task_id)
redis.call("EXPIRE", KEYS[5] .. ":" .. task_id, fence_ttl)
return 1
"""

# MARK_CORRUPT_V2 — atomically remove from processing, add to corrupt ZSET
# KEYS: [processing_key, corrupt_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, error_summary, corrupt_max, fencing_tombstone_ttl]
_LUA_MARK_CORRUPT_V2 = """
local task_id = ARGV[1]
local error_summary = ARGV[2] or ""
local corrupt_max = tonumber(ARGV[3]) or 100
local fence_ttl = tonumber(ARGV[4])

redis.call("ZREM", KEYS[1], task_id)
redis.call("ZADD", KEYS[2], redis.call("TIME")[1], task_id)
local corrupt_len = redis.call("ZCARD", KEYS[2])
if corrupt_max > 0 and corrupt_len > corrupt_max then
    redis.call("ZREMRANGEBYRANK", KEYS[2], 0, corrupt_len - corrupt_max - 1)
end
redis.call("HSET", KEYS[3] .. ":" .. task_id,
    "status", "corrupt",
    "error", error_summary,
    "owner_token", "",
    "lease_expires_at", 0,
    "discovered_at", redis.call("TIME")[1])
redis.call("EXPIRE", KEYS[2], fence_ttl)
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, fence_ttl)
redis.call("DEL", KEYS[4] .. ":" .. task_id)
redis.call("EXPIRE", KEYS[5] .. ":" .. task_id, fence_ttl)
return 1
"""

# CANCEL_V2 — atomic cancel with status-dependent behavior
# KEYS: [queue_key, processing_key, retry_key, dead_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [task_id, reason, fencing_tombstone_ttl]
# Returns:
#   0 — already terminal or not found (idempotent)
#   1 — pending → cancelled (removed from ready)
#   2 — processing → cancel_requested (flag set on task hash)
#   3 — retrying → cancelled (removed from retry ZSET)
#   4 — in dead-letter → cancelled (removed from dead list)
_LUA_CANCEL_V2 = """
local task_id = ARGV[1]
local reason = ARGV[2] or "cancelled by admin"
local fence_ttl = tonumber(ARGV[3])

-- Check task exists
local status = redis.call("HGET", KEYS[6] .. ":" .. task_id, "status")
if not status then
    return 0  -- not found
end

-- Already terminal
if status == "completed" or status == "cancelled" or status == "corrupt" then
    return 0
end

if status == "pending" then
    -- Remove from ready queue, set cancelled
    redis.call("LREM", KEYS[1], 0, task_id)
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "status", "cancelled", "error", reason)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, 86400)
    return 1
end

if status == "processing" then
    -- Set cancel_requested flag — worker will check at heartbeat boundary
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "cancel_requested", "1", "cancel_reason", reason)
    return 2
end

if status == "failed" then
    -- Remove from retry ZSET, set cancelled
    redis.call("ZREM", KEYS[3], task_id)
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "status", "cancelled", "error", reason)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, 86400)
    return 3
end

if status == "dead" then
    redis.call("LREM", KEYS[4], 0, task_id)
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "status", "cancelled", "error", reason)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, 86400)
    redis.call("DEL", KEYS[5] .. ":" .. task_id)
    return 4
end

return 0
"""
