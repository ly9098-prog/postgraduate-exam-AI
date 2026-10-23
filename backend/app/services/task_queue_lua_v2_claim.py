"""v2 queue admission and claim Lua scripts.

Generation counters are allocated with ``HINCRBY`` and are never reset. Lease
expiry and retry eligibility use Redis server time. The task hash and fencing
home remain authoritative for owner/generation checks in the transition
scripts.
"""

# ENQUEUE_V2 with idempotency and capacity limit (v2 keys)
# KEYS: [queue_key, task_hash_prefix, idempotent_prefix]
# ARGS: [task_id, task_json, idempotent_ttl_sec, max_ready]
_LUA_ENQUEUE_V2 = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local idem_ttl = tonumber(ARGV[3])
local max_ready = tonumber(ARGV[4])

local exists = redis.call("EXISTS", KEYS[3] .. ":" .. task_id)
if exists == 1 then
    return "__duplicate__"
end

local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

redis.call("SETEX", KEYS[3] .. ":" .. task_id, idem_ttl, "1")

redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending",
    "owner_token", "",
    "generation", 0,
    "retry_count", 0)

redis.call("RPUSH", KEYS[1], task_id)
return task_id
"""

# ENQUEUE_NON_IDEMPOTENT_V2 (v2 keys)
# KEYS: [queue_key, task_hash_prefix]
# ARGS: [task_id, task_json, max_ready]
_LUA_ENQUEUE_NON_IDEMPOTENT_V2 = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local max_ready = tonumber(ARGV[3])

local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending")
redis.call("RPUSH", KEYS[1], task_id)
return task_id
"""

# CLAIM_V2 — HINCRBY generation, NEVER reset.
# KEYS: [queue_key, processing_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [task_id_placeholder_not_used, lease_expiry_abs, lease_ttl_rel, owner_token]
# The task_id comes from RPOP of the queue (not ARGV).
# Returns: {raw_payload, owner_token, generation} or nil.
_LUA_CLAIM_V2 = """
local lease_ttl = tonumber(ARGV[1])
local owner_token = ARGV[2]
local corrupt_max = tonumber(ARGV[3]) or 100
local corrupt_ttl = tonumber(ARGV[4]) or 604800
local now = tonumber(redis.call("TIME")[1])
local lease_expiry = now + lease_ttl

for _ = 1, 100 do
    local task_id = redis.call("LPOP", KEYS[1])
    if not task_id then
        return nil
    end

    local raw = redis.call("HGET", KEYS[4] .. ":" .. task_id, "data")
    local status = redis.call("HGET", KEYS[4] .. ":" .. task_id, "status")
    if not raw then
        redis.call("HSET", KEYS[4] .. ":" .. task_id,
            "status", "corrupt", "error", "missing task payload")
        redis.call("ZADD", KEYS[6], now, task_id)
        local corrupt_len = redis.call("ZCARD", KEYS[6])
        if corrupt_max > 0 and corrupt_len > corrupt_max then
            redis.call("ZREMRANGEBYRANK", KEYS[6], 0, corrupt_len - corrupt_max - 1)
        end
        redis.call("EXPIRE", KEYS[6], corrupt_ttl)
        redis.call("EXPIRE", KEYS[4] .. ":" .. task_id, corrupt_ttl)
    elseif status == "completed" or status == "dead" or status == "corrupt" or status == "cancelled" then
        -- Stale ready entry. Drop it and continue to the next task id.
    elseif status == "cancel_requested" then
        redis.call("HSET", KEYS[4] .. ":" .. task_id,
            "status", "cancelled", "owner_token", "", "lease_expires_at", 0)
        redis.call("EXPIRE", KEYS[4] .. ":" .. task_id, corrupt_ttl)
    else
        local generation = redis.call("HINCRBY", KEYS[5] .. ":" .. task_id, "gen", 1)
        redis.call("ZADD", KEYS[2], lease_expiry, task_id)
        redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)
        redis.call("HSET", KEYS[4] .. ":" .. task_id,
            "owner_token", owner_token,
            "generation", generation,
            "status", "processing",
            "lease_expires_at", lease_expiry)
        return {task_id, raw, owner_token, tostring(generation), tostring(lease_expiry)}
    end
end
return nil
"""

# HEARTBEAT_V2 — verify BOTH owner_token AND generation
# Uses Redis TIME instead of client-provided timestamps to prevent clock skew.
# KEYS: [processing_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [task_id, lease_ttl, owner_token]
# Returns: 1 on success, 0 on owner mismatch, -1 on generation mismatch
_LUA_HEARTBEAT_V2 = """
local task_id = ARGV[1]
local lease_ttl = tonumber(ARGV[2])
local owner_token = ARGV[3]
local redis_now = redis.call("TIME")
local new_expiry = tonumber(redis_now[1]) + lease_ttl
local stored = redis.call("GET", KEYS[2] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

local stored_gen = redis.call("HGET", KEYS[3] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[4] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then
    return -1
end

local status = redis.call("HGET", KEYS[3] .. ":" .. task_id, "status")
if status ~= "processing" and status ~= "cancel_requested" then
    return 0
end
redis.call("ZADD", KEYS[1], new_expiry, task_id)
redis.call("SETEX", KEYS[2] .. ":" .. task_id, lease_ttl, owner_token)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "lease_expires_at", new_expiry)
return 1
"""

# REAPER_V2 — reclaim expired tasks using Redis server time
# Uses ``redis.call("TIME")`` instead of client-provided timestamps
# so that all workers agree on lease expiry regardless of clock skew.
# KEYS: [processing_key, queue_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [batch_size, max_ready]
# Returns: count of reclaimed tasks (tasks that exceeded capacity are skipped)
_LUA_REAPER_V2 = """
local now = tonumber(redis.call("TIME")[1])
local limit = tonumber(ARGV[1]) or 100
local max_ready = tonumber(ARGV[2]) or 0
local corrupt_max = tonumber(ARGV[3]) or 100
local terminal_ttl = tonumber(ARGV[4]) or 604800
local expired = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, limit)
local count = 0
for _, task_id in ipairs(expired) do
    if redis.call("EXISTS", KEYS[3] .. ":" .. task_id) == 0 then
        local task_key = KEYS[4] .. ":" .. task_id
        local status = redis.call("HGET", task_key, "status")
        if status == "completed" or status == "dead" or status == "corrupt" or status == "cancelled" then
            redis.call("ZREM", KEYS[1], task_id)
        elseif status == "cancel_requested" then
            redis.call("ZREM", KEYS[1], task_id)
            redis.call("HSET", task_key,
                "status", "cancelled", "owner_token", "", "lease_expires_at", 0)
            redis.call("HDEL", task_key, "cancel_requested")
            redis.call("EXPIRE", task_key, terminal_ttl)
            redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, terminal_ttl)
        elseif redis.call("HEXISTS", task_key, "data") == 1 then
            local ready_len = redis.call("LLEN", KEYS[2])
            if max_ready > 0 and ready_len >= max_ready then
                break
            end
            redis.call("ZREM", KEYS[1], task_id)
            redis.call("HSET", task_key,
                "status", "pending", "owner_token", "", "lease_expires_at", 0)
            redis.call("HDEL", task_key, "cancel_requested", "cancel_reason")
            redis.call("RPUSH", KEYS[2], task_id)
            count = count + 1
        else
            redis.call("ZREM", KEYS[1], task_id)
            redis.call("HSET", task_key,
                "status", "corrupt", "error", "missing task payload",
                "owner_token", "", "lease_expires_at", 0)
            redis.call("ZADD", KEYS[5], now, task_id)
            local corrupt_len = redis.call("ZCARD", KEYS[5])
            if corrupt_max > 0 and corrupt_len > corrupt_max then
                redis.call("ZREMRANGEBYRANK", KEYS[5], 0, corrupt_len - corrupt_max - 1)
            end
            redis.call("EXPIRE", KEYS[5], terminal_ttl)
            redis.call("EXPIRE", task_key, terminal_ttl)
            redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, terminal_ttl)
        end
    end
end
return count
"""

# RETRY_CLAIM_V2 — HINCRBY generation from retry ZSET
# KEYS: [retry_key, processing_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [now_timestamp, lease_expiry_abs, lease_ttl_rel, owner_token, execution_generation_unused]
# Returns: {task_id, owner_token, generation, raw_payload} or nil
_LUA_RETRY_CLAIM_V2 = """
local lease_ttl = tonumber(ARGV[1])
local owner_token = ARGV[2]
local corrupt_max = tonumber(ARGV[3]) or 100
local terminal_ttl = tonumber(ARGV[4]) or 604800
local now = tonumber(redis.call("TIME")[1])
local lease_expiry = now + lease_ttl
for _ = 1, 100 do
    local candidates = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, 1)
    if #candidates == 0 then return nil end
    local task_id = candidates[1]
    redis.call("ZREM", KEYS[1], task_id)
    local task_key = KEYS[4] .. ":" .. task_id
    local raw = redis.call("HGET", task_key, "data")
    local status = redis.call("HGET", task_key, "status")
    if not raw then
        redis.call("HSET", task_key, "status", "corrupt", "error", "missing task payload")
        redis.call("ZADD", KEYS[6], now, task_id)
        local corrupt_len = redis.call("ZCARD", KEYS[6])
        if corrupt_max > 0 and corrupt_len > corrupt_max then
            redis.call("ZREMRANGEBYRANK", KEYS[6], 0, corrupt_len - corrupt_max - 1)
        end
        redis.call("EXPIRE", KEYS[6], terminal_ttl)
        redis.call("EXPIRE", task_key, terminal_ttl)
    elseif status == "completed" or status == "dead" or status == "corrupt" or status == "cancelled" then
        -- stale retry entry; discard
    elseif status == "cancel_requested" then
        redis.call("HSET", task_key, "status", "cancelled", "owner_token", "", "lease_expires_at", 0)
        redis.call("EXPIRE", task_key, terminal_ttl)
    else
        local generation = redis.call("HINCRBY", KEYS[5] .. ":" .. task_id, "gen", 1)
        redis.call("ZADD", KEYS[2], lease_expiry, task_id)
        redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)
        redis.call("HSET", task_key,
            "owner_token", owner_token, "generation", generation,
            "status", "processing", "lease_expires_at", lease_expiry)
        return {task_id, raw, owner_token, tostring(generation), tostring(lease_expiry)}
    end
end
return nil
"""
