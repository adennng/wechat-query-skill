$ErrorActionPreference = "Stop"

$BaseDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ServiceDir = Join-Path $BaseDir "services\wechat-download-api"

function Resolve-BaseUrl {
    if ($env:WECHAT_QUERY_BASE_URL) {
        return $env:WECHAT_QUERY_BASE_URL
    }

    if ($env:WECHAT_WATCH_BASE_URL) {
        return $env:WECHAT_WATCH_BASE_URL
    }

    $envFile = Join-Path $ServiceDir ".env"
    if (Test-Path $envFile) {
        $siteLine = Select-String -Path $envFile -Pattern '^SITE_URL=' -ErrorAction SilentlyContinue | Select-Object -Last 1
        if ($siteLine) {
            return ($siteLine.Line -replace '^SITE_URL=', '')
        }

        $portLine = Select-String -Path $envFile -Pattern '^PORT=' -ErrorAction SilentlyContinue | Select-Object -Last 1
        if ($portLine) {
            $port = ($portLine.Line -replace '^PORT=', '')
            if ($port) {
                return "http://localhost:$port"
            }
        }
    }

    return "http://localhost:5000"
}

$BaseUrl = Resolve-BaseUrl
$HealthUrl = "$BaseUrl/api/health"
$StatusUrl = "$BaseUrl/api/admin/status"
$HealthRetries = if ($env:HEALTH_RETRIES) { [int]$env:HEALTH_RETRIES } else { 3 }
$HealthRetryDelay = if ($env:HEALTH_RETRY_DELAY) { [int]$env:HEALTH_RETRY_DELAY } else { 3 }
$ComposeCmd = if ($env:WECHAT_QUERY_COMPOSE_CMD) { $env:WECHAT_QUERY_COMPOSE_CMD } elseif ($env:WECHAT_WATCH_COMPOSE_CMD) { $env:WECHAT_WATCH_COMPOSE_CMD } else { "" }

function Write-Result {
    param(
        [bool]$Ok,
        [bool]$ServiceHealthy,
        [bool]$ServiceRestarted,
        [bool]$StatusChecked,
        [string]$LoginState,
        [bool]$Authenticated,
        [bool]$IsExpired,
        [string]$Action,
        [string]$Message
    )

    $result = [ordered]@{
        ok = $Ok
        service_healthy = $ServiceHealthy
        service_restarted = $ServiceRestarted
        status_checked = $StatusChecked
        login_state = $LoginState
        authenticated = $Authenticated
        is_expired = $IsExpired
        action = $Action
        message = $Message
    }
    $result | ConvertTo-Json -Depth 3
}

function Test-Health {
    try {
        Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 10 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-StatusJson {
    try {
        return Invoke-RestMethod -Uri $StatusUrl -Method Get -TimeoutSec 10
    } catch {
        return $null
    }
}

function Resolve-ComposeCommand {
    if ($ComposeCmd) {
        return $ComposeCmd
    }

    try {
        docker compose version *> $null
        return "docker compose"
    } catch {}

    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        return "docker-compose"
    }

    throw "No docker compose command found"
}

function Wait-ForHealth {
    for ($i = 0; $i -lt $HealthRetries; $i++) {
        if (Test-Health) {
            return $true
        }
        Start-Sleep -Seconds $HealthRetryDelay
    }
    return $false
}

function Restart-ServiceContainer {
    if (-not (Test-Path $ServiceDir)) {
        return $false
    }

    try {
        $compose = Resolve-ComposeCommand
        Push-Location $ServiceDir
        try {
            if ($compose -eq "docker compose") {
                docker compose up -d *> $null
            } else {
                docker-compose up -d *> $null
            }
        } finally {
            Pop-Location
        }
        return $true
    } catch {
        return $false
    }
}

$serviceHealthy = $false
$serviceRestarted = $false
$statusChecked = $false
$loginState = "unknown"
$authenticated = $false
$isExpired = $false

if (Test-Health) {
    $serviceHealthy = $true
} else {
    if ((Restart-ServiceContainer) -and (Wait-ForHealth)) {
        $serviceHealthy = $true
        $serviceRestarted = $true
    } else {
        Write-Result `
            -Ok $false `
            -ServiceHealthy $false `
            -ServiceRestarted $serviceRestarted `
            -StatusChecked $false `
            -LoginState $loginState `
            -Authenticated $authenticated `
            -IsExpired $isExpired `
            -Action "notify_service_down" `
            -Message "service health check failed and auto restart did not recover it"
        exit 0
    }
}

$status = Get-StatusJson
if ($null -eq $status) {
    Write-Result `
        -Ok $false `
        -ServiceHealthy $serviceHealthy `
        -ServiceRestarted $serviceRestarted `
        -StatusChecked $false `
        -LoginState $loginState `
        -Authenticated $authenticated `
        -IsExpired $isExpired `
        -Action "notify_service_down" `
        -Message "service is healthy but admin status endpoint is unavailable"
    exit 0
}

$statusChecked = $true
$loginState = if ($status.loginState) { [string]$status.loginState } else { "unknown" }
$authenticated = [bool]$status.authenticated
$isExpired = [bool]$status.isExpired

if ($loginState -eq "invalid") {
    Write-Result `
        -Ok $false `
        -ServiceHealthy $serviceHealthy `
        -ServiceRestarted $serviceRestarted `
        -StatusChecked $statusChecked `
        -LoginState $loginState `
        -Authenticated $authenticated `
        -IsExpired $isExpired `
        -Action "notify_login_invalid" `
        -Message "service is healthy but wechat login is invalid"
    exit 0
}

if (-not $authenticated) {
    Write-Result `
        -Ok $false `
        -ServiceHealthy $serviceHealthy `
        -ServiceRestarted $serviceRestarted `
        -StatusChecked $statusChecked `
        -LoginState $loginState `
        -Authenticated $authenticated `
        -IsExpired $isExpired `
        -Action "notify_not_logged_in" `
        -Message "service is healthy but no active wechat login was found"
    exit 0
}

if ($isExpired) {
    Write-Result `
        -Ok $true `
        -ServiceHealthy $serviceHealthy `
        -ServiceRestarted $serviceRestarted `
        -StatusChecked $statusChecked `
        -LoginState $loginState `
        -Authenticated $authenticated `
        -IsExpired $isExpired `
        -Action "warn_login_expiring" `
        -Message "service is healthy and login still exists, but it is estimated to be expired"
    exit 0
}

Write-Result `
    -Ok $true `
    -ServiceHealthy $serviceHealthy `
    -ServiceRestarted $serviceRestarted `
    -StatusChecked $statusChecked `
    -LoginState $loginState `
    -Authenticated $authenticated `
    -IsExpired $isExpired `
    -Action "none" `
    -Message "service and login are healthy"
