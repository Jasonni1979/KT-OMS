-- 令牌桶限流（D02.01 §5.2，Redis + Lua 原子执行）
-- KEYS[1] = 限流键
-- ARGV[1] = capacity（突发容量）
-- ARGV[2] = rate（每秒补充速率）
-- ARGV[3] = now_ms（当前毫秒，由调用方传入，保证同一次计算的时间一致）
-- 返回 {allowed(0/1), wait_ms（预估等待毫秒）}
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then tokens = capacity end
if ts == nil then ts = now end

-- 按经过时间补充令牌（不足 1 个的时间余量保留，不丢精度）
local delta_ms = now - ts
if delta_ms < 0 then delta_ms = 0 end
tokens = math.min(capacity, tokens + (delta_ms / 1000.0) * rate)

local allowed = 0
local wait_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  if rate > 0 then
    wait_ms = math.ceil(((1 - tokens) / rate) * 1000)
  else
    wait_ms = 1000
  end
end

redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], 3600)
return {allowed, wait_ms}
