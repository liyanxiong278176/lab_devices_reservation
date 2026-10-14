$ErrorActionPreference = 'Stop'
$backendPort = 8001
$api = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/api/v2/live" -TimeoutSec 5 -SkipHttpErrorCheck
$ui = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/login' -TimeoutSec 5 -SkipHttpErrorCheck
if ($api.StatusCode -ne 200) { throw "Backend health returned $($api.StatusCode)." }
if ($ui.StatusCode -ne 200 -or $ui.Content -notmatch 'id="app"') { throw "Frontend login shell returned $($ui.StatusCode)." }

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location (Join-Path $root 'backend')
try {
  $alembic = & (Get-Command uv).Source run alembic current 2>&1
  if ($LASTEXITCODE -ne 0) { throw 'MySQL/Alembic connectivity check failed.' }
  $redisScript = @'
from app.core.settings import get_settings
from redis import Redis
settings = get_settings()
client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
try:
    client.ping()
    print('redis=PING')
finally:
    client.close()
'@
  $redis = $redisScript | & (Get-Command uv).Source run python -
  if ($LASTEXITCODE -ne 0 -or ($redis -join "`n") -notmatch 'redis=PING') { throw 'Redis connectivity check failed.' }
} finally {
  Pop-Location
}
$qdrant = Invoke-WebRequest -Uri 'http://127.0.0.1:6333/readyz' -TimeoutSec 5 -SkipHttpErrorCheck
if ($qdrant.StatusCode -ne 200) { throw "Qdrant readiness returned $($qdrant.StatusCode)." }
"backend=$($api.StatusCode); frontend=$($ui.StatusCode); mysql=connected; redis=PING; qdrant=$($qdrant.StatusCode)"
