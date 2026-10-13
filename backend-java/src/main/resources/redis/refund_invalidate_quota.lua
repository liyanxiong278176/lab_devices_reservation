local marker = KEYS[#KEYS]
if redis.call('get', marker) ~= 'HELD' then
    return 0
end
local day_count = (#KEYS - 1) / 2
for day = 1, day_count do
    redis.call('del', KEYS[day])
    redis.call('del', KEYS[day_count + day])
end
redis.call('set', marker, 'REFUNDED', 'PX', tonumber(ARGV[1]))
return 1
