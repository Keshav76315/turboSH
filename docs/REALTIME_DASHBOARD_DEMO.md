# Real-Time Monitoring Dashboard & Live Demo Guide

This document explains the real-time monitoring system and live demo workflow built into **turboSH**. It details how the proxy, backend, and dashboard interact across different ports, how metrics are captured and aggregated, and how the frontend updates live in the browser.

---

## ⚡ Quick Start: Launch Live Demo Session

To turn on the complete end-to-end live demo session in one command:

### macOS / Linux:
```bash
./scripts/demo.sh
```

### Windows (PowerShell or CMD):
```powershell
# In PowerShell:
.\scripts\demo.ps1

# Or in Command Prompt / Explorer:
scripts\demo.bat
```

This single command:
1. Compiles the binaries (`bin/dummy_backend` and `bin/turbosh` on Unix, `.exe` on Windows)
2. Starts the Dummy Backend on **`:9092`**
3. Starts the turboSH Proxy on **`:8080`** (with metrics & status API on **`:9090`**)
4. Opens the real-time Monitoring Dashboard in your default web browser at **`http://localhost:9090/dashboard`**
5. Generates simulated live traffic (normal traffic, repeated cache hits, and burst attacks)
6. Displays live throughput, cache stats, and threat detections both in your terminal and on the web UI

> **Theme & Headless Options:**
> - **macOS/Linux**:
>   - Light Theme: `./scripts/demo.sh --light`
>   - Headless (no browser): `./scripts/demo.sh --no-browser`
> - **Windows (PowerShell)**:
>   - Light Theme: `.\scripts\demo.ps1 -Light` (or `--light`)
>   - Headless (no browser): `.\scripts\demo.ps1 -NoBrowser` (or `--no-browser`)
> - **Windows (Command Prompt / CMD)**:
>   - Light Theme: `scripts\demo.bat -Light`
>   - Headless (no browser): `scripts\demo.bat -NoBrowser`
> - To cleanly exit and shut down all servers: press **`Ctrl+C`**

---

## 1. High-Level Architecture & Port Allocation

The demo runs three isolated network layers:

```
                      +-------------------------------------------------------------+
                      |                    Client / Browser                         |
                      +-------------------------------------------------------------+
                                     |                               |
                        HTTP Requests|                  Live Polling | (Every 1s)
                        (Normal/Burst|                  & Web UI     |
                                     v                               v
                      +-----------------------------+ +-----------------------------+
                      |    turboSH Reverse Proxy    | |    turboSH Internal Server  |
                      |         Port :8080          | |         Port :9090          |
                      +-----------------------------+ +-----------------------------+
                      | - Pipeline Middleware:      | | - GET /dashboard (Dark UI)  |
                      |   * Dashboard Recorder      | | - GET /dashboard/light (UI) |
                      |   * Concurrency Scheduler   | | - GET /api/v1/status (JSON) |
                      |   * Client Identity (IP)    | | - GET /metrics (Prometheus) |
                      |   * Traffic Logger          | +-----------------------------+
                      |   * Token Bucket Limiter    |                ^
                      |   * Burst / Abuse Rules     |                | Read Snapshot
                      |   * In-Memory LRU Cache     |                |
                      +-----------------------------+ +-----------------------------+
                                     |                |       DashboardState        |
                             Forward | Valid Requests |   (Thread-Safe Aggregator)  |
                                     v                +-----------------------------+
                      +-----------------------------+
                      |     Dummy Backend Server    |
                      |         Port :9092          |
                      +-----------------------------+
```
### Port Responsibilities

| Port | Service | Visibility | Purpose |
| :--- | :--- | :--- | :--- |
| **`:9092`** | **Dummy Backend** | Internal | Simulates an upstream origin service. Returns HTTP `200 OK` (with occasional 500 errors and latency spikes for realistic behavior). |
| **`:8080`** | **turboSH Proxy** | Public | Main entry point for all client traffic. Executes security rules, token-bucket rate limiting, concurrency scheduling, and response caching before forwarding requests to `:9092`. |
| **`:9090`** | **Internal Metrics & Dashboard** | Admin / Internal | Isolated administrative server. Serves Prometheus metrics (`/metrics`), the live JSON status API (`/api/v1/status`), and the self-contained dashboard interfaces (`/dashboard` and `/dashboard/light`). |

> **Security Note:** Keeping the dashboard and metrics on `:9090` ensures that administrative endpoints, metrics scraping, and monitoring APIs are not exposed on the public proxy port (`:8080`).

---

## 2. What We Built & Modified

### A. Backend Aggregator: `monitoring/dashboard_state.go`
A thread-safe, lock-free/low-contention aggregator that holds the live state of the entire system:
- **Request Counters**: Atomic total request count and per-status-code distribution map (`200`, `429`, `500`, etc.).
- **Latency Tracker**: Ring buffer holding the last 1,000 request durations to calculate rolling average and p99 latency without memory allocation overhead.
- **Throughput Calculator**: 60-second sliding time window calculating current requests-per-second (RPS).
- **Subsystem Adapters**: Direct read access to:
  - Concurrency Scheduler: Active worker count, waiting queue length, and max capacity.
  - LRU Cache: Hits, misses, hit rate, memory consumed in bytes, and current entry count.
  - Rate Limiter & Security: Configured capacity and refill rates.
- **Threat Feed Ring Buffer**: Stores the last 50 mitigation events (timestamp, truncated client IP hash, targeted path, status code, and reason).

### B. Status API & UI Server: `monitoring/dashboard_api.go`
- `GET /api/v1/status`: Returns the complete metrics snapshot as a compact JSON object.
- Wildcard CORS is omitted as same-origin access from the administrative dashboard on `:9090` is sufficient.
- Embedded HTML delivery (`/dashboard` for dark theme, `/dashboard/light` for light theme).

### C. Pipeline Middleware Hooks: `core/proxy/middleware.go`
- **Dashboard Recorder**: Placed at the very start of the middleware chain to record true end-to-end latency and final HTTP status codes.
- **Event Emitter**: When a request is throttled (HTTP `429`) or blocked (HTTP `403`), it automatically logs a `MitigationEvent` into the dashboard threat feed ring buffer with the client's hashed IP.

### D. Desktop Frontend Polling Engine: `ui/dark_desktop_ui.html` & `ui/light_desktop_ui.html`
- A zero-dependency JavaScript polling engine running at a 1-second interval (`1000ms`).
- Translates raw API numbers into formatted metrics (`toLocaleString()`, `%`, bytes formatted as `KB`/`MB`, and milliseconds).

### E. One-Command Demo Runners
- **macOS / Linux (`scripts/demo.sh`)**: Bash script with ANSI colors, `lsof` port sanitization, and background `curl` jobs.
- **Windows (`scripts/demo.ps1` & `scripts/demo.bat`)**: Native PowerShell script leveraging `Get-NetTCPConnection` / `netstat` for port validation, `Start-Process` for background daemon management, and high-performance .NET `HttpClient` for async non-blocking traffic generation. Includes `scripts/demo.bat` for CMD / one-click Explorer launch.

---

## 3. How the Dashboard Updates in Real Time

### The Polling Flow
Every **1,000 ms**, the browser runs an asynchronous `fetch()` to `http://localhost:9090/api/v1/status`:

```javascript
fetch('http://localhost:9090/api/v1/status')
  .then(res => res.json())
  .then(data => updateDashboard(data))
```

### Sample `/api/v1/status` JSON Response
```json
{
  "uptime_seconds": 34.2,
  "backend_url": "http://localhost:9092",
  "proxy_port": ":8080",
  "go_version": "go1.24+",
  "scheduler": {
    "active": 2,
    "waiting": 0,
    "capacity": 100
  },
  "cache": {
    "hits": 18,
    "misses": 24,
    "evictions": 0,
    "hit_rate": 0.428,
    "current_memory_bytes": 1420,
    "max_memory_bytes": 536870912,
    "entry_count": 8,
    "entry_capacity": 1000
  },
  "requests": {
    "total": 65,
    "by_status": {
      "200": 42,
      "429": 18,
      "500": 5
    },
    "recent_rps": 6.4,
    "avg_latency_ms": 14.8,
    "p99_latency_ms": 48.2
  },
  "rate_limiter": {
    "capacity_per_ip": 10,
    "refill_rate": 2
  },
  "recent_events": [
    {
      "timestamp": "2026-09-09T10:38:35Z",
      "type": "RATE_LIMIT",
      "ip_hash": "1c57742a",
      "path": "/api/login",
      "score": 0,
      "detail": "Rate limit exceeded (token bucket / burst)",
      "status": 429
    }
  ]
}
```

### How Each UI Component Reacts

1. **Telemetry Banner**:
   - **Success / Error %**: Calculated live from `requests.by_status` (ratio of $2xx$ vs $\ge 400$).
   - **Throughput**: Shows live `recent_rps` (`req/s`) and tracks session peak RPS.
   - **Cache Memory**: Formats `cache.current_memory_bytes` into dynamic `KB` or `MB`.

2. **KPI Metrics Cards**:
   - **Cache Hit Rate**: Updates both the percentage text and the progress bar width based on `cache.hit_rate`.
   - **p99 Latency**: Displays calculated 99th-percentile latency in milliseconds.
   - **Decision Actions**: Aggregates total throttled (`429`) and blocked (`403`) requests.
   - **Anomaly Score**: Updates with the latest security score.

3. **Scheduler & Cache Sidebar**:
   - Updates active workers against capacity (`scheduler.active / scheduler.capacity`).
   - Updates LRU cache entry count against maximum capacity (`cache.entry_count / cache.entry_capacity`).

4. **Live Threat Feed**:
   - Renders cards for the latest mitigation events.
   - Displays event badges (`RATE_LIMIT` / `BLOCK`), sanitized client IP hashes (`1c57742a`), targeted HTTP paths, and dynamic relative timestamps ("just now", "12s ago").

5. **SVG Waveform Chart**:
   - Maintains a 60-point sliding window of recent values.
   - Dynamically recalculates the SVG `<polyline>` coordinate points and updates the SVG path on every poll tick.

---

## 4. How the Demo Scripts Work

### macOS / Linux (`scripts/demo.sh`)
When you run `./scripts/demo.sh`, the script automatically executes the following sequence:
1. **Port Sanitation**: Checks ports `9092`, `8080`, and `9090` using `lsof -ti:$PORT`. If any stale processes occupy them, they are cleanly terminated.
2. **Binary Compilation**: Builds `bin/dummy_backend` and `bin/turbosh` using `go build`.
3. **Backend Startup**: Launches the dummy server on `:9092` and verifies health via `curl`.
4. **Proxy Startup**: Launches turboSH on `:8080` (forwarding to `:9092`, metrics on `:9090`) with rate limiting and burst protection active.
5. **Browser Launch**: Opens `http://localhost:9090/dashboard` in the default browser using macOS `open` or Linux `xdg-open`.
6. **Traffic Simulation Loop**: Generates high-volume steady traffic, cache exercises, and periodic bursts to trigger live rate limiting.
7. **Graceful Shutdown**: Traps `SIGINT` (`Ctrl+C`) to cleanly terminate all processes and release ports.

---

### Windows (`scripts/demo.ps1` & `scripts/demo.bat`)
Designed specifically to solve Windows compatibility hurdles without requiring external Unix tools or WSL:

| Unix Issue in Bash | Windows PowerShell Solution (`scripts/demo.ps1`) |
| :--- | :--- |
| **Shebang `#!/bin/bash`** | Native `.ps1` script, runnable directly or via `scripts\demo.bat`. |
| **Bash Variable Expansion (`BASH_SOURCE`)** | `$MyInvocation.MyCommand.Definition` & `Split-Path` to robustly resolve repo root. |
| **`lsof -ti:$PORT`** | Native `Get-NetTCPConnection -LocalPort $Port` (with automatic fallback to `netstat -ano`). |
| **Path Slashes & `.exe` Binaries** | `Join-Path` resolves Windows paths and builds `bin\dummy_backend.exe` & `bin\turbosh.exe`. |
| **External `curl` / Job Control (`&`)** | Uses high-performance asynchronous .NET `[System.Net.Http.HttpClient]` tasks (`WaitAll`), avoiding heavy process spawning overhead on Windows. |
| **`open` / `xdg-open`** | Native `Start-Process $dashboardUrl` opens your default Windows web browser (Edge, Chrome, Firefox). |
| **Job Signals / Traps** | PowerShell `try { ... } finally { Cleanup-Processes }` block cleanly stops background processes on `Ctrl+C`. |

---

## 5. Running the Demo

### macOS / Linux:
```bash
# Start default (Dark Theme)
./scripts/demo.sh

# Start with Light Theme
./scripts/demo.sh --light

# Start in Headless Mode (no browser auto-open)
./scripts/demo.sh --no-browser
```

### Windows (PowerShell):
```powershell
# Start default (Dark Theme)
.\scripts\demo.ps1

# Start with Light Theme
.\scripts\demo.ps1 -Light

# Start in Headless Mode (no browser auto-open)
.\scripts\demo.ps1 -NoBrowser

# (Note: Standard execution policy bypass if scripts are restricted on your laptop)
powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1
```

### Windows (Command Prompt / CMD / Double-Click):
```cmd
:: Start default (Dark Theme)
scripts\demo.bat

:: Start with Light Theme
scripts\demo.bat -Light

:: Start in Headless Mode
scripts\demo.bat -NoBrowser
```

---

### Direct URLs
- **Dark Dashboard**: [http://localhost:9090/dashboard](http://localhost:9090/dashboard)
- **Light Dashboard**: [http://localhost:9090/dashboard/light](http://localhost:9090/dashboard/light)
- **Raw Status JSON**: [http://localhost:9090/api/v1/status](http://localhost:9090/api/v1/status)
- **Prometheus Metrics**: [http://localhost:9090/metrics](http://localhost:9090/metrics)
- **Proxy Endpoint**: [http://localhost:8080/](http://localhost:8080/)

