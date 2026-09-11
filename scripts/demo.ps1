<#
==============================================================================
 turboSH Real-Time Monitoring Dashboard Demo (Windows PowerShell)
==============================================================================
 Workflow:
   1. Checks ports (:9092, :8080, :9090) for conflicts
   2. Compiles Windows binaries (bin\dummy_backend.exe, bin\turbosh.exe)
   3. Starts Dummy Backend server on :9092
   4. Starts turboSH Proxy on :8080 (metrics & dashboard on :9090)
   5. Opens the real-time dashboard in your default Windows browser
   6. Generates live traffic (steady requests + bursts + cache hits)
   7. Real-time stats display in terminal and dashboard UI

 Press Ctrl+C at any time to cleanly stop all servers.
==============================================================================
#>

[CmdletBinding()]
param (
    [switch]$Light,
    [switch]$NoBrowser
)

# Parse additional command-line string arguments if passed as --light, --no-browser
foreach ($arg in $args) {
    if ($arg -match '^--light$|^-l$') { $Light = $true }
    if ($arg -match '^--no-browser$|^-n$') { $NoBrowser = $true }
}

$ErrorActionPreference = "Stop"

# Determine repository root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $ScriptDir) { $ScriptDir = (Get-Location).Path }
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $RootDir

$BinDir = Join-Path $RootDir "bin"
$LogDir = Join-Path $RootDir "logs"

if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$backendProc = $null
$turboshProc = $null

function Cleanup-Processes {
    Write-Host ""
    Write-Host "[demo] Shutting down demo processes..." -ForegroundColor Yellow

    if ($turboshProc -and -not $turboshProc.HasExited) {
        try {
            Stop-Process -Id $turboshProc.Id -Force -ErrorAction SilentlyContinue
        } catch {}
    }

    if ($backendProc -and -not $backendProc.HasExited) {
        try {
            Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
        } catch {}
    }

    Write-Host "[demo] All servers stopped cleanly. Goodbye!" -ForegroundColor Green
}

# Banner
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "          🚀 turboSH Real-Time Dashboard Demo (Windows)     " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ── 1. Check for stale processes on required ports ───────────────────────
function Test-PortAvailable {
    param([int]$Port)
    $occupied = $false
    $pids = @()

    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            if ($pids) { $occupied = $true }
        }
    } else {
        $lines = netstat -ano | Select-String ":$Port\s+.*LISTENING"
        foreach ($l in $lines) {
            if ($l -match 'LISTENING\s+(\d+)') {
                $pids += [int]$matches[1]
                $occupied = $true
            }
        }
    }

    if ($occupied) {
        $pidStr = ($pids | Select-Object -Unique) -join ', '
        Write-Host "[ERROR] Port :$Port is already occupied by PID(s): $pidStr." -ForegroundColor Red
        Write-Host "Please terminate the conflicting process or choose another port before starting the demo." -ForegroundColor Red
        exit 1
    }
}

foreach ($p in @(9092, 8080, 9090)) {
    Test-PortAvailable -Port $p
}

try {
    # ── 2. Build binaries ───────────────────────────────────────────────────
    Write-Host "[1/4] Building Windows binaries..." -ForegroundColor Cyan

    $dummyBin = Join-Path $BinDir "dummy_backend.exe"
    $turboshBin = Join-Path $BinDir "turbosh.exe"

    & go build -o $dummyBin ./cmd/dummy_backend
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to compile dummy_backend." -ForegroundColor Red
        exit 1
    }
    Write-Host "  ✔ Built bin\dummy_backend.exe" -ForegroundColor Green

    & go build -o $turboshBin ./cmd/turbosh
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to compile turbosh." -ForegroundColor Red
        exit 1
    }
    Write-Host "  ✔ Built bin\turbosh.exe" -ForegroundColor Green

    # ── 3. Start Dummy Backend on :9092 ─────────────────────────────────────
    Write-Host "[2/4] Starting Dummy Backend on :9092..." -ForegroundColor Cyan

    $env:PORT = ":9092"
    $backendLog = Join-Path $LogDir "dummy_backend.log"
    $backendErr = Join-Path $LogDir "dummy_backend_err.log"

    $backendProc = Start-Process -FilePath $dummyBin `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErr `
        -PassThru -NoNewWindow

    # Wait for backend to be ready
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:9092/" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            # Retry after delay
        }
        Start-Sleep -Milliseconds 200
    }

    if (-not $ready) {
        Write-Host "[ERROR] Dummy Backend failed to start. See logs\dummy_backend.log" -ForegroundColor Red
        exit 1
    }
    Write-Host "  ✔ Dummy Backend is listening on http://localhost:9092" -ForegroundColor Green

    # ── 4. Start turboSH Proxy on :8080 ─────────────────────────────────────
    Write-Host "[3/4] Starting turboSH Proxy (:8080 -> :9092, metrics/dashboard :9090)..." -ForegroundColor Cyan

    $turboshLog = Join-Path $LogDir "turbosh.log"
    $turboshErr = Join-Path $LogDir "turbosh_err.log"

    $env:TURBOSH_PORT = "8080"
    $env:TURBOSH_BACKEND = "http://localhost:9092"
    $env:TURBOSH_METRICS_PORT = ":9090"
    $env:TURBOSH_METRICS_ENABLED = "true"
    $env:TURBOSH_RATE_LIMIT_CAPACITY = "500"
    $env:TURBOSH_RATE_LIMIT_RATE = "250.0"
    $env:TURBOSH_BURST_THRESHOLD = "300"

    $turboshProc = Start-Process -FilePath $turboshBin `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $turboshLog `
        -RedirectStandardError $turboshErr `
        -PassThru -NoNewWindow

    # Wait for proxy and dashboard status API to be ready
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:9090/api/v1/status" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            # Retry after delay
        }
        Start-Sleep -Milliseconds 200
    }

    if (-not $ready) {
        Write-Host "[ERROR] turboSH failed to start. See logs\turbosh.log" -ForegroundColor Red
        exit 1
    }

    Write-Host "  ✔ turboSH Proxy is listening on http://localhost:8080" -ForegroundColor Green
    Write-Host "  ✔ Real-Time Status API on   http://localhost:9090/api/v1/status" -ForegroundColor Green
    Write-Host "  ✔ Monitoring Dashboard on  http://localhost:9090/dashboard" -ForegroundColor Green
    Write-Host "  ✔ Light Monitoring UI on   http://localhost:9090/dashboard/light" -ForegroundColor Green

    # ── 5. Open browser ──────────────────────────────────────────────────────
    $dashboardUrl = if ($Light) { "http://localhost:9090/dashboard/light" } else { "http://localhost:9090/dashboard" }

    if (-not $NoBrowser) {
        Write-Host "[4/4] Opening dashboard in browser..." -ForegroundColor Cyan
        Start-Process $dashboardUrl
    } else {
        Write-Host "[demo] Skipping browser launch (-NoBrowser). Visit: $dashboardUrl" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  ✨ DEMO RUNNING — LIVE TRAFFIC SIMULATION ACTIVE          " -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "Watch the browser dashboard at: $dashboardUrl" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to terminate demo." -ForegroundColor Yellow
    Write-Host ""

    # ── 6. Traffic Generator Loop ───────────────────────────────────────────
    $endpoints = @(
        "/api/users",
        "/api/products",
        "/api/orders",
        "/api/search?q=test",
        "/api/dashboard/stats",
        "/health"
    )

    # Initialize high-performance .NET HttpClient for non-blocking concurrent requests
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object System.Net.Http.HttpClientHandler
    $httpClient = New-Object System.Net.Http.HttpClient($handler)
    $httpClient.Timeout = [System.TimeSpan]::FromSeconds(3)

    $totalSent = 0
    $cycle = 0
    $concurrentNormal = 160
    $concurrentCache = 200
    $concurrentBurst = 240

    while ($true) {
        $cycle++

        # High-volume normal request mix
        $tasks = New-Object 'System.Collections.Generic.List[System.Threading.Tasks.Task]'
        for ($i = 0; $i -lt $concurrentNormal; $i++) {
            $ep = $endpoints[(Get-Random -Maximum $endpoints.Count)]
            $url = "http://localhost:8080$ep"
            $tasks.Add($httpClient.GetAsync($url))
            $totalSent++
        }
        try {
            [System.Threading.Tasks.Task]::WaitAll($tasks.ToArray(), 2000) | Out-Null
        } catch {}

        # Repeated cache hits
        $cacheTasks = New-Object 'System.Collections.Generic.List[System.Threading.Tasks.Task]'
        for ($i = 0; $i -lt $concurrentCache; $i++) {
            $cacheTasks.Add($httpClient.GetAsync("http://localhost:8080/api/static/cached-catalog"))
            $totalSent++
        }
        try {
            [System.Threading.Tasks.Task]::WaitAll($cacheTasks.ToArray(), 2000) | Out-Null
        } catch {}

        # Burst simulation every 3 cycles
        if ($cycle % 3 -eq 0) {
            Write-Host "  ⚡ SIMULATING HIGH-VOLUME BURST ($totalSent total reqs) -> $concurrentBurst concurrent hits on /api/login ..." -ForegroundColor Yellow
            $burstTasks = New-Object 'System.Collections.Generic.List[System.Threading.Tasks.Task]'
            for ($b = 0; $b -lt $concurrentBurst; $b++) {
                $burstTasks.Add($httpClient.GetAsync("http://localhost:8080/api/login"))
                $totalSent++
            }
            try {
                [System.Threading.Tasks.Task]::WaitAll($burstTasks.ToArray(), 2000) | Out-Null
            } catch {}
            Write-Host "  ✔ High-volume burst finished. Dashboard should now show elevated RPS and threat counters." -ForegroundColor Magenta
        }

        # Query latest status snapshot and print live summary
        try {
            $statusJson = $httpClient.GetStringAsync("http://localhost:9090/api/v1/status").Result
            $stats = $statusJson | ConvertFrom-Json
            $rps = $stats.requests.recent_rps
            $hits = $stats.cache.hits
            $misses = $stats.cache.misses
            $hitRate = if ($stats.cache.hit_rate -ne $null) { ("{0:P1}" -f [double]$stats.cache.hit_rate) } else { "0%" }
            $active = $stats.scheduler.active

            Write-Host "  ── LIVE STATS ── Throughput: $rps req/s | Cache Hits: $hits / Misses: $misses (Hit Rate: $hitRate) | Sched Active: $active" -ForegroundColor Cyan
        } catch {
            # Ignore transient reporting hiccups
        }

        Start-Sleep -Milliseconds 250
    }
}
finally {
    Cleanup-Processes
}
