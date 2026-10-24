--[[
  预占转实扣 Lua（SRS-D04.03 FreezeService::settle，出库回传触发 D09.02）
  KEY[1] = 库存 hash key
  ARGV[1] = 实扣数量（=出库确认量）
  ARGV[2] = 幂等键 key——settle 后删除，防重复扣减
  返回: {code, store_after, freeze_after}  code=1 成功 / code=0 台账不存在（幂等）
  语义：store -= num AND freeze -= num（预占与实存同时减，available 不变——预占时已扣过 available）
]]
if redis.call('EXISTS', ARGV[2]) == 0 then
  local s = tonumber(redis.call('HGET', KEYS[1], 'store') or '0')
  local f = tonumber(redis.call('HGET', KEYS[1], 'freeze') or '0')
  return {0, s, f}
end
redis.call('DEL', ARGV[2])
local num = tonumber(ARGV[1])
local store  = redis.call('HINCRBY', KEYS[1], 'store', -num)
local freeze = redis.call('HINCRBY', KEYS[1], 'freeze', -num)
if freeze < 0 then redis.call('HSET', KEYS[1], 'freeze', 0); freeze = 0 end
return {1, store, freeze}
