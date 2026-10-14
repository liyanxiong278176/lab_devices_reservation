param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('Stop', 'Start')]
  [string]$Action
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $PSScriptRoot '..\.runtime'
$results = Join-Path $PSScriptRoot '..\results'
$pidFile = Join-Path $runtime 'backend.pid'
$port = 8001

function Test-BackendHealth {
  $request = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$port/api/v2/live")
  $request.Proxy = $null
  $request.Timeout = 2000
  $response = $null
  try {
    $response = $request.GetResponse()
    return $response.StatusCode -eq [System.Net.HttpStatusCode]::OK
  } catch {
    return $false
  } finally {
    if ($response) { $response.Close() }
  }
}

if ($Action -eq 'Stop') {
  if (-not (Test-Path -LiteralPath $pidFile)) { throw 'Managed backend PID file is missing.' }
  $pidValue = [int](Get-Content -LiteralPath $pidFile -Raw)
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue"
  if ($process) {
    $commandLine = [string]$process.CommandLine
    if ($commandLine -notmatch 'uvicorn app\.main:app' -or $commandLine -notmatch '--port 8001') {
      throw "PID $pidValue no longer identifies the qa_joint FastAPI process; refusing to stop it."
    }
    & taskkill.exe /PID $pidValue /T /F | Out-Null
  }
  Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
  $deadline = (Get-Date).AddSeconds(15)
  while ((Get-Date) -lt $deadline) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if (-not $listener) { 'backend_stopped=true'; exit 0 }
    Start-Sleep -Milliseconds 250
  }
  throw 'Managed backend did not release port 8001 after stop.'
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
  $commandLine = [string]$existing.CommandLine
  if ($commandLine -notmatch 'uvicorn(\.exe)?"?\s+app\.main:app' -or $commandLine -notmatch '--port 8001') {
    throw "Port $port is occupied by PID $($listener.OwningProcess); refusing to replace it."
  }
  $existingDeadline = (Get-Date).AddSeconds(180)
  while ((Get-Date) -lt $existingDeadline) {
    if (Test-BackendHealth) { 'backend_already_healthy=true'; exit 0 }
    Start-Sleep -Milliseconds 500
  }
  throw 'Managed backend is listening but did not become healthy within 180 seconds.'
}
New-Item -ItemType Directory -Force -Path $runtime, $results | Out-Null
$uv = (Get-Command uv -ErrorAction Stop).Source
$backendOut = Join-Path $results 'backend.out.log'
$backendErr = Join-Path $results 'backend.err.log'
$process = Start-Process -FilePath $uv -ArgumentList @('run', 'uvicorn', 'app.main:app', '--loop', 'app.core.uvicorn_loop:platform_loop_factory', '--reload', '--host', '127.0.0.1', '--port', "$port") -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

$deadline = (Get-Date).AddSeconds(180)
while ((Get-Date) -lt $deadline) {
  if (Test-BackendHealth) { "backend_started=true; pid=$($process.Id)"; exit 0 }
  Start-Sleep -Milliseconds 500
}
Get-Content -LiteralPath $backendErr -Tail 80 -ErrorAction SilentlyContinue
throw 'Managed backend did not become healthy after restart within 180 seconds.'
