param(
    [string]$RedisContainer = "lab-redis",
    [string]$ZapImage = "ghcr.io/zaproxy/zaproxy:stable"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repoRoot "backend"
$pythonExe = Join-Path $backendRoot ".venv\Scripts\python.exe"
$resultsDir = Join-Path $PSScriptRoot "results"
$runner = Join-Path $PSScriptRoot "run_auth_wstg.py"
$zapName = "qa-owasp-zap-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
$zapPort = 8090
$mainPort = 8002
$ratePort = 8003
$apiProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$redisIsolationEstablished = $false
$environmentNames = @(
    "LAB_ENVIRONMENT", "LAB_REDIS_URL", "LAB_ENABLE_WORKERS", "LAB_CORS_ORIGINS",
    "LAB_COOKIE_SECURE", "LAB_JWT_SECRET", "LAB_RATE_LIMIT_ENABLED",
    "LAB_TRUSTED_PROXY_IPS", "LAB_RATE_LIMIT_LOGIN_IP_CAPACITY",
    "LAB_RATE_LIMIT_LOGIN_IP_REFILL_PER_SECOND", "LAB_RATE_LIMIT_LOGIN_CAPACITY",
    "LAB_RATE_LIMIT_LOGIN_REFILL_PER_SECOND", "QA_OWASP_BASE_URL",
    "QA_OWASP_RATE_BASE_URL", "QA_OWASP_RATE_DIRECT_URL", "QA_OWASP_ORIGIN",
    "QA_OWASP_RATE_ORIGIN",
    "QA_OWASP_ZAP_PROXY", "QA_OWASP_ZAP_API", "QA_OWASP_ZAP_API_KEY",
    "QA_OWASP_JWT_SECRET", "QA_OWASP_RATE_REDIS_URL", "QA_OWASP_RESULTS"
)
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

function Set-ProcessEnvironment([string]$Name, [AllowNull()][string]$Value) {
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Assert-PortFree([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
    } catch {
        throw "Port $Port is already in use. The OWASP runner will not stop or reuse that process."
    } finally {
        $listener.Stop()
    }
}

function Get-RedisDbSize([int]$Database) {
    $output = & docker exec $RedisContainer redis-cli -n $Database DBSIZE
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect Redis database $Database." }
    return [int](($output | Out-String).Trim())
}

function Start-Api([int]$Port, [int]$RedisDb, [int]$IpCapacity, [double]$IpRefill, [int]$UserCapacity, [double]$UserRefill) {
    Set-ProcessEnvironment "LAB_REDIS_URL" "redis://127.0.0.1:6379/$RedisDb"
    Set-ProcessEnvironment "LAB_RATE_LIMIT_LOGIN_IP_CAPACITY" "$IpCapacity"
    Set-ProcessEnvironment "LAB_RATE_LIMIT_LOGIN_IP_REFILL_PER_SECOND" "$IpRefill"
    Set-ProcessEnvironment "LAB_RATE_LIMIT_LOGIN_CAPACITY" "$UserCapacity"
    Set-ProcessEnvironment "LAB_RATE_LIMIT_LOGIN_REFILL_PER_SECOND" "$UserRefill"

    Push-Location $backendRoot
    try {
        $settingsSummary = & $pythonExe -c "from app.core.settings import Settings; s=Settings(); print(f'ip={s.rate_limit_login_ip_capacity}/{s.rate_limit_login_ip_refill_per_second}; username={s.rate_limit_login_capacity}/{s.rate_limit_login_refill_per_second}; trusted_proxies={len(s.trusted_proxy_ips)}')"
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect non-secret rate-limit settings for port $Port." }
    } finally {
        Pop-Location
    }
    Write-Host "API $Port rate-limit settings: $settingsSummary"

    $stdout = Join-Path $resultsDir "api-$Port.stdout.log"
    $stderr = Join-Path $resultsDir "api-$Port.stderr.log"
    $arguments = @(
        "-m", "uvicorn", "app.main:app", "--loop",
        "app.core.uvicorn_loop:platform_loop_factory", "--host", "127.0.0.1",
        "--port", "$Port", "--no-access-log"
    )
    $process = Start-Process -FilePath $pythonExe -ArgumentList $arguments `
        -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $apiProcesses.Add($process)
}

function Wait-Api([int]$Port) {
    $url = "http://127.0.0.1:$Port/api/v2/auth/colleges"
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $url -TimeoutSec 2 -SkipHttpErrorCheck
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 750
    }
    throw "Temporary API on port $Port did not become ready. Check qa_owasp/results/api-$Port.stderr.log."
}

try {
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Backend virtual environment is missing: backend/.venv" }
    New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
    foreach ($port in @($mainPort, $ratePort, $zapPort)) { Assert-PortFree $port }

    $db12Size = Get-RedisDbSize 12
    $db13Size = Get-RedisDbSize 13
    if ($db12Size -ne 0 -or $db13Size -ne 0) {
        throw "Redis DB 12 and 13 must be empty (observed sizes: 12=$db12Size, 13=$db13Size). No keys were changed."
    }
    $redisIsolationEstablished = $true

    $jwtBytes = [byte[]]::new(48)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($jwtBytes)
    $jwtSecret = [Convert]::ToBase64String($jwtBytes)
    $apiKey = [Guid]::NewGuid().ToString("N") + [Guid]::NewGuid().ToString("N")
    $cors = '["http://127.0.0.1:8002","http://127.0.0.1:8003"]'

    Set-ProcessEnvironment "LAB_ENVIRONMENT" "local"
    Set-ProcessEnvironment "LAB_ENABLE_WORKERS" "false"
    Set-ProcessEnvironment "LAB_CORS_ORIGINS" $cors
    Set-ProcessEnvironment "LAB_COOKIE_SECURE" "true"
    Set-ProcessEnvironment "LAB_JWT_SECRET" $jwtSecret
    Set-ProcessEnvironment "LAB_RATE_LIMIT_ENABLED" "true"
    Set-ProcessEnvironment "LAB_TRUSTED_PROXY_IPS" "[]"

    Start-Api $mainPort 12 1000 16.667 1000 16.667
    Start-Api $ratePort 13 30 0.5 5 0.0833333333
    Wait-Api $mainPort
    Wait-Api $ratePort

    Write-Host "Starting OWASP ZAP image $ZapImage"
    & docker run --detach --rm --name $zapName `
        --publish "127.0.0.1:${zapPort}:8090" $ZapImage `
        zap.sh -daemon -host 0.0.0.0 -port 8090 `
        -config "api.addrs.addr.name=.*" `
        -config "api.addrs.addr.regex=true" `
        -config "api.key=$apiKey" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "OWASP ZAP failed to start." }

    $zapReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $zapStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$zapPort/JSON/core/view/version/?apikey=$apiKey" -TimeoutSec 3
            if ($zapStatus.version) { $zapReady = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $zapReady) { throw "OWASP ZAP did not become ready." }

    Set-ProcessEnvironment "QA_OWASP_BASE_URL" "http://host.docker.internal:$mainPort"
    Set-ProcessEnvironment "QA_OWASP_RATE_BASE_URL" "http://host.docker.internal:$ratePort"
    Set-ProcessEnvironment "QA_OWASP_RATE_DIRECT_URL" "http://127.0.0.1:$ratePort"
    Set-ProcessEnvironment "QA_OWASP_ORIGIN" "http://127.0.0.1:$mainPort"
    Set-ProcessEnvironment "QA_OWASP_RATE_ORIGIN" "http://127.0.0.1:$ratePort"
    Set-ProcessEnvironment "QA_OWASP_ZAP_PROXY" "http://127.0.0.1:$zapPort"
    Set-ProcessEnvironment "QA_OWASP_ZAP_API" "http://127.0.0.1:$zapPort"
    Set-ProcessEnvironment "QA_OWASP_ZAP_API_KEY" $apiKey
    Set-ProcessEnvironment "QA_OWASP_JWT_SECRET" $jwtSecret
    Set-ProcessEnvironment "QA_OWASP_RATE_REDIS_URL" "redis://127.0.0.1:6379/13"
    Set-ProcessEnvironment "QA_OWASP_RESULTS" $resultsDir
    Set-ProcessEnvironment "LAB_REDIS_URL" "redis://127.0.0.1:6379/12"

    $proxyProbe = Invoke-WebRequest `
        -Uri "http://host.docker.internal:$mainPort/api/v2/auth/colleges" `
        -Proxy "http://127.0.0.1:$zapPort" -TimeoutSec 15 -SkipHttpErrorCheck
    if ($proxyProbe.StatusCode -ne 200) {
        throw "ZAP could not reach the temporary loopback API through host.docker.internal (HTTP $($proxyProbe.StatusCode))."
    }

    $zapVersion = [string]$zapStatus.version
    Write-Host "OWASP ZAP version: $zapVersion"
    Write-Host "Running the independent WSTG authentication probes through ZAP..."
    & $pythonExe $runner
    $wstgExit = $LASTEXITCODE

    $openApiPath = Join-Path $resultsDir "auth-readonly-openapi.json"
    if (Test-Path -LiteralPath $openApiPath) {
        Write-Host "Running ZAP API scan against the read-only authentication OpenAPI scope..."
        $dockerResults = (Resolve-Path -LiteralPath $resultsDir).Path.Replace("\", "/")
        & docker run --rm --add-host "host.docker.internal:host-gateway" `
            --mount "type=bind,source=$dockerResults,target=/zap/wrk" `
            $ZapImage zap-api-scan.py `
            -t /zap/wrk/auth-readonly-openapi.json -f openapi `
            -J /zap/wrk/zap-api-active.json -r /zap/wrk/zap-api-active.html -I
        $zapScanExit = $LASTEXITCODE
        Write-Host "ZAP API scan exit code: $zapScanExit"

        $reportFile = Get-ChildItem -LiteralPath $resultsDir -Filter "wstg-auth-*.json" |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($reportFile) {
            $wstgReport = Get-Content -LiteralPath $reportFile.FullName -Raw | ConvertFrom-Json
            $activeReportPath = Join-Path $resultsDir "zap-api-active.json"
            $activeAlerts = @()
            if (Test-Path -LiteralPath $activeReportPath) {
                $activeReport = Get-Content -LiteralPath $activeReportPath -Raw | ConvertFrom-Json
                foreach ($site in @($activeReport.site)) {
                    foreach ($alert in @($site.alerts)) {
                        $uris = @($alert.instances | ForEach-Object { $_.uri } | Where-Object { $_ } | Select-Object -Unique)
                        $activeAlerts += [pscustomobject]@{
                            alert = $alert.name
                            risk = $alert.riskdesc
                            confidence = $alert.confidence
                            cweid = $alert.cweid
                            uris = $uris
                            instance_count = @($alert.instances).Count
                        }
                    }
                }
            }
            $wstgReport | Add-Member -Force -NotePropertyName zap_active_scan_exit_code -NotePropertyValue $zapScanExit
            $wstgReport | Add-Member -Force -NotePropertyName zap_active_alerts -NotePropertyValue $activeAlerts
            $wstgReport | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportFile.FullName -Encoding utf8
            $activeAlerts | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $resultsDir "zap-api-active-alerts-sanitized.json") -Encoding utf8
            Write-Host "Merged $($activeAlerts.Count) sanitized ZAP API alerts into $($reportFile.Name)"
        }
    } else {
        Write-Warning "Read-only OpenAPI scope was not generated; the ZAP API scan was skipped."
    }

    if ($wstgExit -ne 0) { exit $wstgExit }
} finally {
    if (docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $zapName }) {
        & docker stop $zapName | Out-Null
    }
    foreach ($process in $apiProcesses) {
        $process.Refresh()
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if ($redisIsolationEstablished) {
        & docker exec $RedisContainer redis-cli -n 12 FLUSHDB | Out-Null
        $flush12Exit = $LASTEXITCODE
        & docker exec $RedisContainer redis-cli -n 13 FLUSHDB | Out-Null
        $flush13Exit = $LASTEXITCODE
        if ($flush12Exit -ne 0) { Write-Warning "Could not restore the reserved OWASP Redis DB 12 to its empty baseline." }
        if ($flush13Exit -ne 0) { Write-Warning "Could not restore the reserved OWASP Redis DB 13 to its empty baseline." }
        if ($flush12Exit -eq 0 -and $flush13Exit -eq 0) {
            Write-Host "Restored reserved OWASP Redis DB 12 and 13 to their empty baseline."
        }
    }
    foreach ($name in $environmentNames) {
        Set-ProcessEnvironment $name $savedEnvironment[$name]
    }
}
