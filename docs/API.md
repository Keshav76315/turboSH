# turboSH — Internal API Definitions

> Defines the internal Go interfaces, Prometheus metrics, and administrative APIs between turboSH components.

---

## 1. Middleware APIs (Go)

### 1.1 Reverse Proxy (`core/proxy/`)

The reverse proxy is the primary entry point for client HTTP traffic.

| Setting | Config Field | Default | Description |
| :--- | :--- | :--- | :--- |
| Listen Port | `ListenPort` | `:8080` | Public port the proxy listens on |
| Backend URL | `BackendURL` | `http://localhost:9092` | Upstream origin server |
| Trusted Proxies | `TrustedProxies` | `nil` | Upstream CIDRs/IPs trusted for `X-Forwarded-For` verification |
| TLS Termination | `TLSEnabled` | `false` | In-process HTTPS termination via certificate & key |

The proxy wraps `net/http/httputil.ReverseProxy` with Gin:
```go
func New(targetURL string) (*ReverseProxy, error)
func (p *ReverseProxy) Handler() gin.HandlerFunc
func (p *ReverseProxy) TargetURL() string
```

---

### 1.2 Scheduler (`core/scheduler/`)

Controls incoming concurrency to prevent upstream backend saturation.

```go
type Scheduler struct { /* unexported fields */ }

// New creates a semaphore-based concurrency limiter.
func New(maxConcurrent int, timeout time.Duration) *Scheduler

// Middleware provides Gin integration enforcing concurrency bounds.
func (s *Scheduler) Middleware() gin.HandlerFunc

// Telemetry accessors
func (s *Scheduler) ActiveCount() int64
func (s *Scheduler) WaitingCount() int64
```

Requests that exceed `maxConcurrent` are placed in a waiting queue for up to `timeout` duration before being rejected with `503 Service Unavailable`.

---

### 1.3 Cache (`core/cache/`)

Thread-safe LRU response cache with byte-level memory tracking and TTL management.

```go
type Cache interface {
    Get(key string) (*CachedResponse, bool)
    Set(key string, response *CachedResponse, ttl time.Duration)
    Delete(key string) bool
    CurrentMemory() int
    Len() int
    Clear()
}

type CachedResponse struct {
    StatusCode int
    Headers    http.Header
    Body       []byte
}
```

- **Admission**: Caches successful `GET` and `HEAD` requests satisfying HTTP caching headers.
- **Stampede Collapse**: Uses `singleflight.Group` (`core/cache/stampede.go`) to coalesce concurrent misses on the same URI.
- **Deep-Copy Isolation**: All reads and writes perform full copies of headers and body buffers to prevent cross-goroutine mutation.

---

### 1.4 Decision Engine (`core/decision/`)

Translates continuous anomaly scores into deterministic mitigation actions.

```go
type Action int

const (
    ActionBlock Action = iota  // 0 -> 403 Forbidden
    ActionRateLimit            // 1 -> 429 Too Many Requests
    ActionAllow                // 2 -> Forward to Origin
)

type DecisionEngine interface {
    Evaluate(score float64) Action
}

// NewThresholdPolicy configures explicit threshold boundaries.
func NewThresholdPolicy(blockThreshold, rateLimitThreshold float64) *ThresholdPolicy

// NewDefaultThresholdPolicy sets standard defaults (0.85, 0.65).
func NewDefaultThresholdPolicy() *ThresholdPolicy
```

---

## 2. ML Inference Architecture & API (`core/inference/`)

turboSH embeds the ML inference engine directly into the Go process via in-process ONNX Runtime CGO bindings (`yalue/onnxruntime_go`). No external Python microservice is required for runtime operation. Python is utilized strictly offline for dataset generation, model training, and ONNX model export.

### 2.1 In-Process Go Inference Interface

```go
type MLProtection interface {
    // Predict runs model inference on a normalized 6-dimensional feature vector.
    // Returns a continuous anomaly score in [0.0, 1.0].
    Predict(features []float32) (float64, error)
    
    // Middleware wraps Gin request contexts to extract features and enforce actions.
    Middleware() gin.HandlerFunc

    // RecordBackendResponse updates latency and status ring buffers from downstream logs.
    RecordBackendResponse(ipHash string, statusCode int, latencyMs float64)
}
```

### 2.2 Feature Vector Schema

The feature vector passed to `Predict` contains 6 float32 values extracted across active 10s and 60s sliding windows:

| Index | Feature | Range / Type | Description |
| :---: | :------ | :----------- | :---------- |
| 0 | `requests_per_ip_10s` | `float32 >= 0` | Request count from the canonical IP in the last 10s window |
| 1 | `requests_per_ip_60s` | `float32 >= 0` | Request count from the canonical IP in the last 60s window |
| 2 | `endpoint_entropy` | `[0.0, 1.0]` | Normalized Shannon entropy of accessed endpoints ($H / \log_2(N)$) |
| 3 | `latency_spike` | `0.0` or `1.0` | Boolean indicator (1.0 if max > 1.5x avg and max > 100ms) |
| 4 | `error_rate` | `[0.0, 1.0]` | Fraction of 4xx/5xx responses in the active 60s window |
| 5 | `request_variance` | `float32 >= 0` | Variance of request inter-arrival intervals |

### 2.3 Middleware Execution

1. Extracts live windowed features per IP via an in-memory ring buffer.
2. The in-process ONNX session scores the feature vector and returns a continuous anomaly score in $[0.0, 1.0]$.
3. The `DecisionEngine` evaluates the score against configured thresholds (`score > 0.85` Block, `score > 0.65` Rate Limit).
4. If anomalous, the request is terminated early (`403` or `429`) with a mitigation event emitted to the real-time threat feed.

---

## 3. Observability & Monitoring APIs

Administrative endpoints are isolated on a dedicated internal port (`:9090`, configurable via `TURBOSH_METRICS_PORT`), ensuring monitoring endpoints are never exposed on the public proxy port (`:8080`).

### 3.1 Prometheus Metrics Endpoint

```
GET http://localhost:9090/metrics
```

Returns standard Prometheus-formatted metrics:

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `turbosh_requests_total` | Counter | `method`, `status` | Total HTTP requests processed by turboSH |
| `turbosh_request_latency_ms` | Histogram | `method` | Sub-millisecond latency distribution (buckets 1ms–5000ms) |
| `turbosh_scheduler_active_requests` | Gauge | — | Requests currently holding a concurrency slot |
| `turbosh_scheduler_waiting_requests` | Gauge | — | Requests queued waiting for a concurrency slot |
| `turbosh_scheduler_capacity` | Gauge | — | Maximum configured concurrency capacity |
| `turbosh_cache_operations_total` | Counter | `result` (`hit` or `miss`) | Total cache lookup operations |
| `turbosh_anomaly_alerts_total` | Counter | `action` (`block`, `rate_limit`, `allow`) | Total ML threat mitigation decisions |

---

### 3.2 Real-Time Dashboard Status API

```
GET http://localhost:9090/api/v1/status
```

Returns a compact, thread-safe JSON snapshot consumed by the frontend dashboards every 1,000 ms. Wildcard CORS is omitted as same-origin access from the administrative dashboard on `:9090` is sufficient.

**Response Schema:**

```json
{
  "uptime_seconds": 124.5,
  "backend_url": "http://localhost:9092",
  "proxy_port": ":8080",
  "go_version": "go1.24+",
  "scheduler": {
    "active": 4,
    "waiting": 0,
    "capacity": 100
  },
  "cache": {
    "hits": 340,
    "misses": 52,
    "evictions": 0,
    "hit_rate": 0.867,
    "current_memory_bytes": 45812,
    "max_memory_bytes": 536870912,
    "entry_count": 48,
    "entry_capacity": 1000
  },
  "requests": {
    "total": 392,
    "by_status": {
      "200": 340,
      "429": 42,
      "503": 10
    },
    "recent_rps": 24.6,
    "avg_latency_ms": 8.4,
    "p99_latency_ms": 32.1
  },
  "rate_limiter": {
    "capacity_per_ip": 10,
    "refill_rate": 2.0
  },
  "recent_events": [
    {
      "timestamp": "2026-09-09T10:38:35Z",
      "type": "RATE_LIMIT",
      "ip_hash": "a1b2c3d4",
      "path": "/api/login",
      "score": 0.72,
      "detail": "Rate limit exceeded (token bucket / burst)",
      "status": 429
    }
  ]
}
```

### 3.3 Dashboard Web UI Endpoints

| URL | Theme | File Served |
| :--- | :--- | :--- |
| `http://localhost:9090/dashboard` | Dark (Default) | `ui/dark_desktop_ui.html` |
| `http://localhost:9090/dashboard/dark` | Dark | `ui/dark_desktop_ui.html` |
| `http://localhost:9090/dashboard/light` | Light | `ui/light_desktop_ui.html` |

---

## 4. Traffic Logger Output

The logger writes structured JSON Lines to `logs/traffic.jsonl` (buffered in 4 KB blocks with periodic automatic flushing on timer and on graceful shutdown).

**Log entry example:**
```json
{
  "timestamp": "2026-03-05T12:00:00Z",
  "ip_hash": "a1b2c3d4e5f67890",
  "endpoint": "/api/login",
  "method": "POST",
  "status_code": 200,
  "response_time": 45.2,
  "request_size": 512
}
```
