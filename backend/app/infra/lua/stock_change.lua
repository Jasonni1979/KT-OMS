--[[
  通用库存口径变更 Lua（SRS-D04.02 FR-02 五口径记账核心）
  原子完成「读当前值 → 判负库存下限 → 写回」，保证同一三元键的并发记账串行化。

  KEY[1] = 库存 hash key: inv:{branch_id}:{bm_id}:{owner_id}
           字段: store(实际) / freeze(锁定) / arrive(在途) / defective(次品) / safe_locked(锁定安全库存)
  ARGV[1] = 口径字段名（store/freeze/arrive/defective）
  ARGV[2] = 变动数量 delta（±整数）
  ARGV[3] = 是否允许负数（0=禁止, 1=允许）——FR-02c 负卖开关
  ARGV[4] = 该口径下限（store 默认 0；freeze/arrive/defective 恒 >=0）

  返回: {code, after}
    code=1  成功（after = 变更后余额）
    code=0  key 不存在（miss）→ 应用层走 DB 行锁路径并回填 Redis（FR-05b 降级）
    code=-1 触达下限且不允许负数 → 记账失败（余额不足）
]]
if redis.call('EXISTS', KEYS[1]) == 0 then
  return {0, 0}
end

local field = ARGV[1]
local delta = tonumber(ARGV[2])
local allow_negative = ARGV[3]
local min_allowed = tonumber(ARGV[4])

local current = tonumber(redis.call('HGET', KEYS[1], field) or '0')
local after = current + delta

if after < min_allowed and allow_negative ~= '1' then
  return {-1, current}
end

redis.call('HSET', KEYS[1], field, after)
return {1, after}
