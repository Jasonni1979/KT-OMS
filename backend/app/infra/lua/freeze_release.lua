--[[
  预占释放 Lua（SRS-D04.03 FreezeService::release）
  KEY[1] = 库存 hash key
  ARGV[1] = 释放数量
  ARGV[2] = 幂等键 key（inv:freeze:{key}）——释放后删除台账标记
  返回: {code, freeze_after}  code=1 成功 / code=0 台账不存在（已释放或已 settle，幂等返回成功）
]]
if redis.call('EXISTS', ARGV[2]) == 0 then
  local freeze = tonumber(redis.call('HGET', KEYS[1], 'freeze') or '0')
  return {0, freeze}
end
redis.call('DEL', ARGV[2])
local freeze = redis.call('HINCRBY', KEYS[1], 'freeze', -tonumber(ARGV[1]))
if freeze < 0 then redis.call('HSET', KEYS[1], 'freeze', 0); freeze = 0 end
return {1, freeze}
