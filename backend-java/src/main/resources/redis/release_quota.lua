local marker = KEYS[#KEYS]
if redis.call('exists', marker) == 1 then
    return 0
end
local device_count = tonumber(ARGV[1])
local day_count = (#KEYS - 1) / 2
for day = 1, day_count do
    if redis.call('get', KEYS[day_count + day]) ~= '1' then
        return -1
    end
    if redis.call('exists', KEYS[day]) == 0 then
        return -1
    end
    for index = 1, device_count do
        local device_id = ARGV[index + 1]
        if not redis.call('hget', KEYS[day], device_id) then
            return -1
        end
    end
end
for day = 1, day_count do
    for index = 1, device_count do
        redis.call('hset', KEYS[day], ARGV[index + 1], '1')
    end
    redis.call('pexpire', KEYS[day], tonumber(ARGV[2 + device_count + day]))
end
redis.call('set', marker, 'RELEASED', 'PX', tonumber(ARGV[2 + device_count]))
return 1
