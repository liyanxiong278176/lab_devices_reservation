local marker = KEYS[#KEYS]
local previous_state = redis.call('get', marker)
if previous_state and previous_state ~= 'UNKNOWN' and previous_state ~= 'DIRTY' then
    return {2}
end
if previous_state then
    redis.call('del', marker)
end
local quantity = tonumber(ARGV[1])
local marker_ttl = tonumber(ARGV[2])
local device_count = tonumber(ARGV[3])
local day_count = (#KEYS - 1) / 2
for day = 1, day_count do
    if redis.call('get', KEYS[day_count + day]) ~= '1' then
        return {-1}
    end
end
local available_by_day = {}
for day = 1, day_count do
    available_by_day[day] = 0
end
local selected = {}
for index = 1, device_count do
    local device_id = ARGV[index + 3]
    local available_for_all_days = true
    for day = 1, day_count do
        local value = redis.call('hget', KEYS[day], device_id)
        if not value or (value ~= '0' and value ~= '1') then
            return {-1}
        end
        if value == '1' then
            available_by_day[day] = available_by_day[day] + 1
        else
            available_for_all_days = false
        end
    end
    if available_for_all_days and #selected < quantity then
        selected[#selected + 1] = device_id
    end
end
if #selected < quantity then
    local each_day_has_capacity = true
    for day = 1, day_count do
        if available_by_day[day] < quantity then
            each_day_has_capacity = false
            break
        end
    end
    if each_day_has_capacity then
        return {3}
    end
    return {0}
end
for day = 1, day_count do
    for index = 1, #selected do
        redis.call('hset', KEYS[day], selected[index], '0')
    end
    redis.call('pexpire', KEYS[day], tonumber(ARGV[3 + device_count + day]))
end
redis.call('set', marker, 'HELD', 'PX', marker_ttl)
local result = {1}
for index = 1, #selected do
    result[#result + 1] = selected[index]
end
return result
