"""Legacy v1 queue recovery Lua scripts.

The scripts here handle retry, dead-letter, and expired-lease recovery without
generation fencing. New production work must not depend on this API surface.
"""

# FAIL_RETRY: verify owner_token → ZREM processing → ZADD retry → update status fields → DEL heartbeat
# KEYS: [processing_key, retry_key, task_hash_prefix, heartbeat_prefix]
# ARGS: [task_id, retry_at, task_json, owner_token, retry_count, error]
_LUA_FAIL_RETRY = """
local task_id = ARGV[1]
local retry_at = tonumber(ARGV[2])
local task_json = ARGV[3]
local owner_token = ARGV[4]
local retry_count = tonumber(ARGV[5]) or 1
local error_msg = ARGV[6] or ""

-- Verify owner
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Remove from processing
redis.call("ZREM", KEYS[1], task_id)

-- Add to retry ZSET
redis.call("ZADD", KEYS[2], retry_at, task_id)

-- Update task hash (JSON data for backward compat + authoritative fields)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "data", task_json,
    "status", "failed",
    "retry_count", retry_count,
    "error", error_msg)

-- Delete heartbeat (idempotent stays for dedup)
redis.call("DEL", KEYS[4] .. ":" .. task_id)

return 1
"""

# FAIL_DEAD: verify owner → ZREM processing → LPUSH dead → LTRIM → HSET status=dead + TTL → DEL heartbeat
# KEYS: [processing_key, dead_key, task_hash_prefix, heartbeat_prefix]
# ARGS: [task_id, task_json, owner_token, dead_max]
_LUA_FAIL_DEAD = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local owner_token = ARGV[3]
local dead_max = tonumber(ARGV[4]) or 1000

-- Verify owner
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Remove from processing
redis.call("ZREM", KEYS[1], task_id)

-- Add to dead list (trim prevents unbounded growth)
redis.call("LPUSH", KEYS[2], task_id)
redis.call("LTRIM", KEYS[2], 0, dead_max - 1)

-- Update task hash (data + authoritative status = dead)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "data", task_json)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "status", "dead")
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, 604800)

-- Delete heartbeat only (idempotent key preserved for dedup)
redis.call("DEL", KEYS[4] .. ":" .. task_id)

return 1
"""

# REAPER: scan processing ZSET → heartbeat alive? → check status/payload → reclaim or mark corrupt
# KEYS: [processing_key, queue_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [now_timestamp, batch_size]
# Returns: count of reclaimed tasks
_LUA_REAPER = """
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2]) or 100
local expired = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, limit)
local count = 0
for _, task_id in ipairs(expired) do
    -- Check if worker is still alive via heartbeat key
    local hb_exists = redis.call("EXISTS", KEYS[3] .. ":" .. task_id)
    if hb_exists == 0 then
        -- Check task hash status — skip if terminal (stale ZSET entry)
        local status = redis.call("HGET", KEYS[4] .. ":" .. task_id, "status")
        if status and (status == "completed" or status == "dead" or status == "corrupt") then
            redis.call("ZREM", KEYS[1], task_id)
        else
            -- Check payload exists before reclaiming
            local payload_exists = redis.call("HEXISTS", KEYS[4] .. ":" .. task_id, "data")
            if payload_exists == 1 then
                redis.call("ZREM", KEYS[1], task_id)
                redis.call("RPUSH", KEYS[2], task_id)
                count = count + 1
            else
                redis.call("ZREM", KEYS[1], task_id)
                redis.call("HSET", KEYS[4] .. ":" .. task_id, "status", "corrupt")
            end
        end
    end
end
return count
"""

# RETRY_CLAIM: ZRANGEBYSCORE retry → validate payload/status → ZADD processing + heartbeat
# Returns payload inline — no separate HGET needed.
# KEYS: [retry_key, processing_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [now_timestamp, lease_expiry_abs, lease_ttl_rel, owner_token, execution_generation]
# Returns: {task_id, owner_token, generation, raw_payload} or nil
_LUA_RETRY_CLAIM = """
local now = tonumber(ARGV[1])
local lease_expiry = tonumber(ARGV[2])
local lease_ttl = tonumber(ARGV[3])
local owner_token = ARGV[4]
local generation = tonumber(ARGV[5]) or 1

local candidates = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, 1)
if #candidates == 0 then
    return nil
end

local task_id = candidates[1]

-- Validate payload exists before moving
local raw = redis.call("HGET", KEYS[4] .. ":" .. task_id, "data")
if not raw then
    redis.call("ZREM", KEYS[1], task_id)
    redis.call("HSET", KEYS[4] .. ":" .. task_id, "status", "corrupt")
    return nil
end

-- Check if task is in terminal state (stale retry entry)
local status = redis.call("HGET", KEYS[4] .. ":" .. task_id, "status")
if status and (status == "completed" or status == "dead") then
    redis.call("ZREM", KEYS[1], task_id)
    return nil
end

redis.call("ZREM", KEYS[1], task_id)
redis.call("ZADD", KEYS[2], lease_expiry, task_id)
redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)

-- Update authoritative state fields
redis.call("HSET", KEYS[4] .. ":" .. task_id,
    "owner_token", owner_token,
    "generation", generation,
    "status", "processing",
    "lease_expires_at", lease_expiry)

return {task_id, owner_token, tostring(generation), raw}
"""
