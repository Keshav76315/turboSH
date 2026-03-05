# turboSH — Internal API Definitions

> Defines the internal APIs and communication interfaces between turboSH components.

---

## 1. Middleware APIs (Go)

### 1.1 Reverse Proxy

The proxy is the entry point. No internal API — it listens on a configurable port and forwards traffic through the middleware pipeline.

| Setting     | Default      |
| ----------- | ------------ |
| Listen Port | `:8080`      |
| Backend URL | configurable |

---

### 1.2 Scheduler

The scheduler exposes an internal Go interface consumed by the proxy.

```go
type Scheduler interface {
    // Enqueue adds a request to the scheduling queue.
    // Returns an error if the request is rejected (e.g., rate limited).
    Enqueue(ctx context.Context, req *http.Request) error

    // SetRateLimit configures the rate limit for a given IP.
    SetRateLimit(ipHash string, maxRequests int, window time.Duration)
}
```

---

### 1.3 Cache

```go
type Cache interface {
    // Get retrieves a cached response. Returns nil if not found.
    Get(key string) (*CachedResponse, bool)

    // Set stores a response in the cache with a TTL.
    Set(key string, response *CachedResponse, ttl time.Duration)

    // Stats returns cache hit/miss/eviction counters.
    Stats() CacheStats
}

type CachedResponse struct {
    StatusCode int
    Headers    http.Header
    Body       []byte
}

type CacheStats struct {
    Hits       int64
    Misses     int64
    Evictions  int64
}
```

---

### 1.4 Decision Engine

```go
type DecisionEngine interface {
    // Evaluate takes an anomaly prediction and returns the action to take.
    Evaluate(prediction Prediction) Action
}

type Prediction struct {
    IPHash          string  `json:"ip_hash"`
    AnomalyScore    float64 `json:"anomaly_score"`
    RiskLevel       string  `json:"risk_level"`
    RecommendedAction string `json:"recommended_action"`
}

type Action int

const (
    ActionAllow     Action = iota
    ActionRateLimit
    ActionBlock
)
```

---

## 2. ML Inference API

Two possible architectures. The chosen approach will be documented here once decided.

### Option A — FastAPI Service (Python)

```
POST /predict
Content-Type: application/json
```

**Request:**

```json
{
  "ip_hash": "a1b2c3d4",
  "requests_per_ip_10s": 25,
  "requests_per_ip_60s": 80,
  "endpoint_entropy": 0.3,
  "latency_spike": true,
  "error_rate": 0.15,
  "request_variance": 12.5
}
```

**Response:**

```json
{
  "ip_hash": "a1b2c3d4",
  "anomaly_score": 0.87,
  "risk_level": "HIGH",
  "recommended_action": "BLOCK"
}
```

### Option B — Embedded ONNX Runtime (Go)

No HTTP API. The ML model is loaded directly into the Go process via ONNX Runtime bindings. The inference function matches the `DecisionEngine` interface above.

---

## 3. Monitoring API

### Prometheus Metrics Endpoint

```
GET /metrics
```

Returns Prometheus-formatted metrics.

**Exposed Metrics:**

| Metric Name                     | Type      | Description                    |
| ------------------------------- | --------- | ------------------------------ |
| `turbosh_requests_total`        | counter   | Total requests received        |
| `turbosh_requests_blocked`      | counter   | Requests blocked by decision   |
| `turbosh_requests_rate_limited` | counter   | Requests rate limited          |
| `turbosh_scheduler_queue_len`   | gauge     | Current scheduler queue size   |
| `turbosh_cache_hit_total`       | counter   | Cache hits                     |
| `turbosh_cache_miss_total`      | counter   | Cache misses                   |
| `turbosh_ml_inference_seconds`  | histogram | ML inference latency           |
| `turbosh_anomaly_score`         | histogram | Distribution of anomaly scores |

---

## 4. Traffic Logger Output

Not an API — the logger writes structured JSON lines to a configurable output (file or stdout).

**Output format:** See [DATA_SCHEMA.md](DATA_SCHEMA.md) § 1.

---

## 5. Feature Pipeline Interface

The feature extraction pipeline reads log files and produces feature vectors.

**Input:** JSON lines from Traffic Logger
**Output:** Feature vectors as JSON (see [DATA_SCHEMA.md](DATA_SCHEMA.md) § 2)

This can operate in two modes:

- **Batch:** Process log files offline for training data generation
- **Streaming:** Process logs in real-time for live inference
