param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('load', 'stairs', 'stress', 'spike', 'soak')]
    [string]$Profile,
    [int]$Users = 25,
    [int]$DurationSeconds = 60,
    [int]$StageSeconds = 60,
    [string]$HostUrl = $env:QA_BASE_URL
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$locust = Join-Path $PSScriptRoot '.venv\Scripts\locust.exe'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$locustFile = Join-Path $PSScriptRoot 'locustfile.py'
$results = Join-Path $PSScriptRoot 'results'

if (-not (Test-Path -LiteralPath $locust)) { throw 'Locust is missing; install qa_eval/requirements.txt first.' }
if (-not (Test-Path -LiteralPath $python)) { throw 'QA virtual environment is missing; install qa_eval/requirements.txt first.' }
if ([string]::IsNullOrWhiteSpace($HostUrl)) { $HostUrl = 'http://127.0.0.1:8000' }
if ([string]::IsNullOrWhiteSpace($env:QA_MYSQL_DSN)) { throw 'Set QA_MYSQL_DSN in this PowerShell process.' }
if (-not (Test-Path -LiteralPath (Join-Path $results 'fixture.json'))) { throw 'Create the isolated QA fixture before load testing.' }
if ($Users -lt 1 -or $DurationSeconds -lt 1 -or $StageSeconds -lt 1) { throw 'User and duration values must be positive.' }

$env:QA_BASE_URL = $HostUrl.TrimEnd('/')
$env:QA_PROFILE = $Profile
$env:QA_USERS = [string]$Users
$env:QA_DURATION_SECONDS = [string]$DurationSeconds
$env:QA_STAGE_SECONDS = [string]$StageSeconds
$env:QA_SPAWN_RATE = '5'

$runtimeSeconds = switch ($Profile) {
    'load' { $DurationSeconds }
    'stairs' { 5 * $StageSeconds }
    'stress' { 6 * $StageSeconds }
    'spike' { 165 }
    'soak' { [Math]::Max(1800, $DurationSeconds) }
}

$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$prefix = Join-Path $results "$Profile-$Users-$runStamp"
$resourceOutput = "$prefix-resources.jsonl"
$collectorOut = "$prefix-collector.log"
$collectorErr = "$prefix-collector.err.log"
$locustLog = "$prefix-locust.log"
$htmlReport = "$prefix.html"

$serverPort = ([Uri]$env:QA_BASE_URL).Port
$apiPid = Get-NetTCPConnection -State Listen -LocalPort $serverPort -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::1', '::') } |
    Select-Object -First 1 -ExpandProperty OwningProcess
$collectorArgs = @($PSScriptRoot + '\telemetry_collector.py', '--seconds', [string]$runtimeSeconds, '--interval', '2', '--output', $resourceOutput)
if ($apiPid) { $collectorArgs += @('--api-pid', [string]$apiPid) }
$collector = Start-Process -FilePath $python -ArgumentList $collectorArgs -WorkingDirectory $root `
    -WindowStyle Hidden -PassThru -RedirectStandardOutput $collectorOut -RedirectStandardError $collectorErr

try {
    $locustArgs = @('-f', $locustFile, '--headless', '--host', $env:QA_BASE_URL,
        '--csv', $prefix, '--csv-full-history', '--stop-timeout', '10',
        '--html', $htmlReport, '--logfile', $locustLog, '--exit-code-on-error', '1')
    if ($Profile -in @('load', 'soak')) {
        $locustArgs += @('--users', [string]$Users, '--spawn-rate', '5')
    }
    & $locust @locustArgs
    $locustExit = $LASTEXITCODE
}
finally {
    if (-not $collector.HasExited) {
        Wait-Process -Id $collector.Id -Timeout 10 -ErrorAction SilentlyContinue
        if (-not $collector.HasExited) { Stop-Process -Id $collector.Id -Force }
    }
}

Write-Output "Locust profile: $Profile; samples: $resourceOutput; csv prefix: $prefix"
exit $locustExit
