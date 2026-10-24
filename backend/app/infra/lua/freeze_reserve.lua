--[[
  三元库存预占 Lua 脚本（M0.5 spike / SRS-D04.03 FreezeService::reserve 原型）
  契约（SRS-D04.02 §5.2）：available = store − freeze − defective − locked_safe
  KEY[1] = 库存 hash key: inv:{branch_id}:{bm_id}:{owner_id}  字段: store/freeze/defective/safe_locked
  ARGV[1] = 预占数量 num
  ARGV[2] = 幂等键 idempotent_key（预占台账已存在则直接返回成功，防重复预占）
  ARGV[3] = 幂等记录 key 前缀（inv:freeze:{idempotent_key}）
  ARGV[4] = 预占有效期秒数（台账 TTL，过期回收任务兜底 D04.03 §5.4）
  返回: {code, available_after}
    code=1 成功；code=-1 可用不足；code=0 幂等命中（此前已预占成功）
]]
-- 幂等：SETNX 台账标记，已存在则视为此前成功
local added = redis.call('SET', ARGV[3], ARGV[1], 'NX', 'EX', tonumber(ARGV[4]))
if not added then
  local freeze = tonumber(redis.call('HGET', KEYS[1], 'freeze') or '0')
  return {0, freeze}
end

local store     = tonumber(redis.call('HGET', KEYS[1], 'store') or '0')
local freeze    = tonumber(redis.call('HGET', KEYS[1], 'freeze') or '0')
local defective = tonumber(redis.call('HGET', KEYS[1], 'defective') or '0')
local safe      = tonumber(redis.call('HGET', KEYS[1], 'safe_locked') or '0')

local num = tonumber(ARGV[1])
local available = store - freeze - defective - safe
if available < num then
  redis.call('DEL', ARGV[3])          -- 预占失败回滚幂等标记
  return {-1, available}
end

redis.call('HINCRBY', KEYS[1], 'freeze', num)
return {1, available - num}
