"""Legacy v1 queue lifecycle Lua scripts.

These scripts write only the legacy ``taskq:*`` namespace. They remain for
migration compatibility; production workers claim and transition tasks through
the v2 namespace in ``task_queue_lua_v2_claim`` and
``task_queue_lua_v2_transitions``.
"""

# ENQUEUE with idempotency check AND ready queue capacity limit.
# KEYS: [queue_key, task_hash_prefix, idempotent_prefix]
# ARGS: [task_id, task_json, idempotent_ttl_sec, max_ready]
# Returns: task_id on success, "__duplicate__" if idempotent exists,
#          "__queue_full__" if at capacity, nil on error
_LUA_ENQUEUE = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local idem_ttl = tonumber(ARGV[3])
local max_ready = tonumber(ARGV[4])

-- 1. Check idempotent key
local exists = redis.call("EXISTS", KEYS[3] .. ":" .. task_id)
if exists == 1 then
    return "__duplicate__"
end

-- 2. Check ready queue capacity
local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

-- 3. Set idempotent guard first (prevents races on concurrent enqueue)
redis.call("SETEX", KEYS[3] .. ":" .. task_id, idem_ttl, "1")

-- 4. Write task payload + authoritative fields
redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending",
    "owner_token", "",
    "generation", 0,
    "retry_count", 0)

-- 5. Push to ready queue
redis.call("RPUSH", KEYS[1], task_id)

return task_id
"""

# ENQUEUE_NON_IDEMPOTENT: HSET payload → RPUSH ready (no idempotency check)
# KEYS: [queue_key, task_hash_prefix]
# ARGS: [task_id, task_json]
_LUA_ENQUEUE_NON_IDEMPOTENT = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local max_ready = tonumber(ARGV[3])

-- Check ready queue capacity
local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending")
redis.call("RPUSH", KEYS[1], task_id)

return task_id
"""

# CLAIM: RPOP ready → ZADD processing → HGET payload → SETEX heartbeat + update hash
# Returns payload, owner_token, and generation.
# KEYS: [queue_key, processing_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [lease_expiry_abs, lease_ttl_rel, owner_token, execution_generation]
# Returns: {raw_payload, owner_token, generation} or nil
_LUA_CLAIM = """
local task_id = redis.call("RPOP", KEYS[1])
if not task_id then
    return nil
end

local owner_token = ARGV[3]
local generation = tonumber(ARGV[4]) or 1
local lease_expiry = tonumber(ARGV[1])
local lease_ttl = tonumber(ARGV[2])

-- Read payload
local raw = redis.call("HGET", KEYS[4] .. ":" .. task_id, "data")
if not raw then
    -- Payload missing — don't requeue, mark as corrupt
    redis.call("HSET", KEYS[4] .. ":" .. task_id, "status", "corrupt")
    return nil
end

-- Add to processing ZSET with absolute lease expiry
redis.call("ZADD", KEYS[2], lease_expiry, task_id)

-- Set heartbeat key with relative TTL and owner_token as value
redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)

-- Update authoritative state fields in task hash
redis.call("HSET", KEYS[4] .. ":" .. task_id,
    "owner_token", owner_token,
    "generation", generation,
    "status", "processing",
    "lease_expires_at", lease_expiry)

return {raw, owner_token, tostring(generation)}
"""

# HEARTBEAT: verify owner_token → update processing ZSET score → extend heartbeat TTL
# KEYS: [processing_key, heartbeat_prefix]
# ARGS: [task_id, new_lease_expiry, lease_ttl, owner_token]
# Returns: 1 on success, 0 on owner mismatch
_LUA_HEARTBEAT = """
local task_id = ARGV[1]
local new_expiry = tonumber(ARGV[2])
local lease_ttl = tonumber(ARGV[3])
local owner_token = ARGV[4]

-- Verify owner
local stored = redis.call("GET", KEYS[2] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Update processing ZSET lease score
redis.call("ZADD", KEYS[1], new_expiry, task_id)

-- Extend heartbeat key TTL
redis.call("EXPIRE", KEYS[2] .. ":" .. task_id, lease_ttl)

return 1
"""

# COMPLETE: verify owner_token → ZREM processing → ZREM retry → HSET completed → DEL heartbeat
# KEYS: [processing_key, retry_key, task_hash_prefix, heartbeat_prefix]
# ARGS: [task_id, owner_token, completed_ttl]
_LUA_COMPLETE = """
local task_id = ARGV[1]
local owner_token = ARGV[2]
local ttl = tonumber(ARGV[3])

-- Verify owner via heartbeat key
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Remove from processing
redis.call("ZREM", KEYS[1], task_id)

-- Clean up retry ZSET (in case it was re-enqueued)
redis.call("ZREM", KEYS[2], task_id)

-- Set authoritative status to completed
redis.call("HSET", KEYS[3] .. ":" .. task_id, "status", "completed")
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, ttl)

-- Delete heartbeat only (idempotent key preserved for dedup)
redis.call("DEL", KEYS[4] .. ":" .. task_id)

return 1
"""
