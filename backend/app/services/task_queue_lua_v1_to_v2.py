"""Atomic v1-to-v2 queue migration Lua script.

The migration script validates the oldest v1 task before moving it. Every
state change for one task happens atomically: the v1 ready-list entry is only
removed after the v2 task/idempotency writes succeed or the entry is preserved
as corrupt diagnostic state. A full v2 ready queue leaves the v1 entry in
place.
"""

# MIGRATE_ONE_V1_TO_V2
# KEYS: [
#   v1_queue_key,
#   v1_task_hash_prefix,
#   v2_queue_key,
#   v2_task_hash_prefix,
#   v2_idempotent_prefix,
#   v2_corrupt_key,
# ]
# ARGS: [
#   task_type,
#   idempotent_ttl_sec,
#   max_ready,
#   corrupt_max,
#   terminal_ttl_sec,
# ]
# Returns: {result_code, task_id}
_LUA_DRAIN_ONE_V1_TO_V2 = """
local task_id = redis.call("LINDEX", KEYS[1], 0)
if not task_id then
    return {"empty", ""}
end

local task_type = ARGV[1]
local idem_ttl = tonumber(ARGV[2])
local max_ready = tonumber(ARGV[3])
local corrupt_max = tonumber(ARGV[4])
local terminal_ttl = tonumber(ARGV[5])
local v2_task_key = KEYS[4] .. ":" .. task_id
local v2_idem_key = KEYS[5] .. ":" .. task_id

-- An idempotency guard means v2 already accepted this identity. Remove only
-- the stale v1 ready-list position; never overwrite v2 state.
if redis.call("EXISTS", v2_idem_key) == 1 then
    redis.call("LPOP", KEYS[1])
    return {"duplicate", task_id}
end

-- A hash without the guard can be a partial migration or a manually altered
-- task. Keep the v1 position and surface the conflict for operator review.
if redis.call("EXISTS", v2_task_key) == 1 then
    return {"conflict", task_id}
end

local raw = redis.call("HGET", KEYS[2] .. ":" .. task_id, "data")
local corrupt_error = nil
if not raw then
    corrupt_error = "missing task payload during v1 migration"
else
    local decoded_ok, decoded = pcall(cjson.decode, raw)
    if not decoded_ok or type(decoded) ~= "table" then
        corrupt_error = "invalid task payload during v1 migration"
    elseif tostring(decoded["task_id"] or "") ~= task_id then
        corrupt_error = "task id mismatch during v1 migration"
    elseif tostring(decoded["task_type"] or "") ~= task_type then
        corrupt_error = "task type mismatch during v1 migration"
    end
end

if corrupt_error then
    local now = redis.call("TIME")[1]
    redis.call("LPOP", KEYS[1])
    redis.call("HSET", v2_task_key,
        "status", "corrupt",
        "error", corrupt_error,
        "owner_token", "",
        "lease_expires_at", 0,
        "discovered_at", now)
    if raw then
        redis.call("HSET", v2_task_key, "data", raw)
    end
    redis.call("ZADD", KEYS[6], now, task_id)
    local corrupt_len = redis.call("ZCARD", KEYS[6])
    if corrupt_max > 0 and corrupt_len > corrupt_max then
        redis.call("ZREMRANGEBYRANK", KEYS[6], 0, corrupt_len - corrupt_max - 1)
    end
    redis.call("EXPIRE", KEYS[6], terminal_ttl)
    redis.call("EXPIRE", v2_task_key, terminal_ttl)
    return {"corrupt", task_id}
end

local ready_len = redis.call("LLEN", KEYS[3])
if max_ready > 0 and ready_len >= max_ready then
    return {"queue_full", task_id}
end

-- Keep the v1 position until all v2 writers succeed. If a writer fails, the
-- rollback removes partial v2 state so the next drain retries from the v1
-- ready-list entry rather than stranding it behind a hash-only conflict.
local ok, err = pcall(function()
    redis.call("HSET", v2_task_key,
        "data", raw,
        "status", "pending",
        "owner_token", "",
        "generation", 0,
        "retry_count", 0,
        "error", "",
        "lease_expires_at", 0)
    redis.call("RPUSH", KEYS[3], task_id)
    redis.call("SETEX", v2_idem_key, idem_ttl, "1")
end)
if not ok then
    redis.call("LREM", KEYS[3], 1, task_id)
    redis.call("DEL", v2_idem_key)
    redis.call("DEL", v2_task_key)
    return redis.error_reply(err)
end
redis.call("LPOP", KEYS[1])
return {"migrated", task_id}
"""
