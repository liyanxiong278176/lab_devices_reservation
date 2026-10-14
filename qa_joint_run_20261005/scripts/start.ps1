$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $PSScriptRoot '..\.runtime'
$results = Join-Path $PSScriptRoot '..\results'
$backendPort = 8001
New-Item -ItemType Directory -Force -Path $runtime, $results | Out-Null

foreach ($port in @($backendPort, 5173)) {
  $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($listener) { throw "Port $port is already in use by PID $($listener.OwningProcess); refusing to replace an existing service." }
}

$uv = (Get-Command uv -ErrorAction Stop).Source
$pnpm = Join-Path (Split-Path (Get-Command pnpm -ErrorAction Stop).Source) 'pnpm.cmd'
if (-not (Test-Path -LiteralPath $pnpm)) { throw 'pnpm.cmd was not found beside the pnpm PowerShell shim.' }

$backendOut = Join-Path $results 'backend.out.log'
$backendErr = Join-Path $results 'backend.err.log'
$frontendOut = Join-Path $results 'frontend.out.log'
$frontendErr = Join-Path $results 'frontend.err.log'
$backend = Start-Process -FilePath $uv `
  -ArgumentList @('run', 'uvicorn', 'app.main:app', '--loop', 'app.core.uvicorn_loop:platform_loop_factory', '--reload', '--host', '127.0.0.1', '--port', "$backendPort") `
  -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
$priorProxy = $env:VITE_API_PROXY_TARGET
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$backendPort"
$frontend = Start-Process -FilePath $pnpm `
  -ArgumentList @('dev', '--host', '127.0.0.1') `
  -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr
if ($null -eq $priorProxy) { Remove-Item Env:VITE_API_PROXY_TARGET } else { $env:VITE_API_PROXY_TARGET = $priorProxy }

Set-Content -LiteralPath (Join-Path $runtime 'backend.pid') -Value $backend.Id -Encoding ascii
Set-Content -LiteralPath (Join-Path $runtime 'frontend.pid') -Value $frontend.Id -Encoding ascii

$deadline = (Get-Date).AddSeconds(120)
$healthy = $false
while ((Get-Date) -lt $deadline) {
  try {
    $api = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/api/v2/live" -TimeoutSec 2 -SkipHttpErrorCheck
    $ui = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/login' -TimeoutSec 2 -SkipHttpErrorCheck
    if ($api.StatusCode -eq 200 -and $ui.StatusCode -eq 200) { $healthy = $true; break }
  } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $healthy) {
  Get-Content -LiteralPath $backendErr -Tail 80 -ErrorAction SilentlyContinue
  Get-Content -LiteralPath $frontendErr -Tail 80 -ErrorAction SilentlyContinue
  throw 'The backend/frontend health checks did not pass within 120 seconds.'
}
"backend_port=$backendPort; backend_pid=$($backend.Id); frontend_pid=$($frontend.Id); health=200/200"
