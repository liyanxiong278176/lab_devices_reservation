if redis.call('get', KEYS[1]) == 'HELD' then
    redis.call('set', KEYS[1], 'COMMITTED', 'PX', tonumber(ARGV[1]))
    return 1
end
return 0
