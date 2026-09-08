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

## 2. ML Inference Architecture & API

turboSH embeds the ML inference engine directly into the Go process via in-process ONNX Runtime CGO bindings (`yalue/onnxruntime_go`). No external Python service or HTTP microservice is required for runtime operation. Python is utilized strictly offline for dataset generation, model training, and ONNX model export.

### 2.1 In-Process Go Inference Interface

The Go inference engine implements an in-memory scoring function:

```go
type MLProtection interface {
    // Predict runs model inference on a normalized 6-dimensional feature vector.
    // Returns a continuous anomaly score in [0.0, 1.0].
    Predict(features []float32) (float64, error)
}
```

### 2.2 Feature Vector Schema

The feature vector passed to `Predict` contains 6 float32 values:

| Index | Feature | Range / Type | Description |
| :---: | :------ | :----------- | :---------- |
| 0 | `requests_per_ip_10s` | `float32 >= 0` | Request count from the canonical IP in the last 10s window |
| 1 | `requests_per_ip_60s` | `float32 >= 0` | Request count from the canonical IP in the last 60s window |
| 2 | `endpoint_entropy` | `[0.0, 1.0]` | Normalized Shannon entropy of accessed endpoints |
| 3 | `latency_spike` | `0.0` or `1.0` | Boolean indicator (1.0 if max > 1.5x avg and max > 100ms) |
| 4 | `error_rate` | `[0.0, 1.0]` | Fraction of 4xx/5xx responses in the active window |
| 5 | `request_variance` | `float32 >= 0` | Variance of request inter-arrival intervals |

### 2.3 Middleware Integration

1. The ML middleware extracts live windowed features per IP via an in-memory sliding window ring buffer.
2. The in-process ONNX session evaluates the feature vector and returns a continuous anomaly score in `[0.0, 1.0]`.
3. The `DecisionEngine` evaluates the score against configured thresholds (`block > 0.85`, `rate_limit > 0.65`) and returns `ActionAllow`, `ActionRateLimit`, or `ActionBlock`.

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
