# turboSH — Data Schema

> Defines the structure of traffic logs, feature vectors, datasets, and API schemas used throughout turboSH.

---

## 1. Traffic Log Schema

Produced by the **Traffic Logger** (`pipeline/logging/traffic_logger.go`). Stored in `logs/traffic.jsonl`.

Each log entry is written as a single JSON object per line (JSON Lines format) using buffered I/O.

### Fields

| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `timestamp` | string (ISO 8601) | Request arrival time (UTC) | `"2026-03-05T12:00:00Z"` |
| `ip_hash` | string | HMAC-SHA-256 hash of canonical client IP | `"a1b2c3d4e5f67890"` |
| `endpoint` | string | Requested URL path | `"/api/login"` |
| `method` | string | HTTP method | `"POST"` |
| `status_code` | int | HTTP response status code | `200` |
| `response_time`| float | End-to-end processing/backend latency in ms | `45.2` |
| `request_size` | int | Request body size in bytes | `512` |

### Example

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

---

## 2. Feature Vector Schema

Computed from request sliding windows by `pipeline/feature_extraction/feature_extractor.py` (offline batch) and `core/inference/middleware.go` (real-time in-process Go ring buffers).

### 6-Dimensional Feature Specification

| Index | Feature | Type | Range | Description |
| :---: | :------ | :--- | :---- | :---------- |
| 0 | `requests_per_ip_10s` | float32 / int | $\ge 0$ | Total requests from this client IP in the last 10 seconds |
| 1 | `requests_per_ip_60s` | float32 / int | $\ge 0$ | Total requests from this client IP in the last 60 seconds |
| 2 | `endpoint_entropy` | float32 | $[0.0, 1.0]$ | Normalized Shannon entropy of paths accessed: $H / \log_2(N)$ ($0.0$ when $N \le 1$) |
| 3 | `latency_spike` | float32 / int | $0$ or $1$ | Indicator: $1$ if max latency $> 1.5\times$ avg and $> 100\text{ ms}$, else $0$ |
| 4 | `error_rate` | float32 | $[0.0, 1.0]$ | Ratio of 4xx and 5xx status codes in the active 60s window |
| 5 | `request_variance` | float32 | $\ge 0$ | Variance of inter-arrival durations between consecutive requests |

### JSON Representation (Features Contract)

```json
{
  "ip_hash": "a1b2c3d4e5f67890",
  "requests_per_ip_10s": 25,
  "requests_per_ip_60s": 80,
  "endpoint_entropy": 0.35,
  "latency_spike": 1,
  "error_rate": 0.15,
  "request_variance": 12.5
}
```

---

## 3. ML Prediction Schema

Produced by `core/inference/` and consumed by `core/decision/decision_engine.go`.

### Fields

| Field | Type | Description | Values |
| :--- | :--- | :--- | :--- |
| `ip_hash` | string | Sanitized client identifier | `"a1b2c3d4"` |
| `anomaly_score` | float64 | Continuous anomaly score | `0.0` (normal) to `1.0` (anomalous) |
| `risk_level` | string | Categorized risk band | `"LOW"`, `"MEDIUM"`, `"HIGH"` |
| `recommended_action` | string | Enforcement action | `"ALLOW"`, `"RATE_LIMIT"`, `"BLOCK"` |

### Example

```json
{
  "ip_hash": "a1b2c3d4",
  "anomaly_score": 0.88,
  "risk_level": "HIGH",
  "recommended_action": "BLOCK"
}
```

---

## 4. Dataset Schemas (`datasets/`)

Used for offline training, GridSearchCV evaluation, and detection accuracy benchmarking.

### Labeled Training Datasets

- `datasets/synthetic_traffic_dataset.csv` (22,000 records)
- `datasets/traffic_dataset.csv`
- `datasets/attack_dataset.csv`

**Columns (7):**

```csv
requests_per_ip_10s,requests_per_ip_60s,endpoint_entropy,latency_spike,error_rate,request_variance,label
```

| Column | Type | Range | Description |
| :--- | :--- | :--- | :--- |
| `requests_per_ip_10s` | int | $\ge 0$ | Windowed request count (10s) |
| `requests_per_ip_60s` | int | $\ge 0$ | Windowed request count (60s) |
| `endpoint_entropy` | float | $[0.0, 1.0]$ | Normalized endpoint Shannon entropy |
| `latency_spike` | int | `0` or `1` | Latency spike indicator |
| `error_rate` | float | $[0.0, 1.0]$ | 4xx/5xx error ratio |
| `request_variance` | float | $\ge 0$ | Inter-arrival variance |
| `label` | int | `0` or `1` | `0` = Normal traffic, `1` = Attack traffic |

### Extracted Unlabeled Features Dataset

- `datasets/features.csv`

**Columns (7):**

```csv
ip_hash,requests_per_ip_10s,requests_per_ip_60s,endpoint_entropy,latency_spike,error_rate,request_variance
```

### Simulated Attack Profiles

| Attack Type | Simulated Characteristics in Features |
| :--- | :--- |
| **Normal Browsing** | High endpoint entropy (~0.7), low error rate (<0.05), moderate request rates, zero latency spikes |
| **DDoS Burst** | Extremely high 10s/60s request counts (50–200+), near-zero entropy (targeting single URL), high variance |
| **Brute Force Login** | High error rate (0.4–0.9), near-zero entropy (repeated hits to `/api/login`), tight request spacing |
| **Request Flooding** | Moderate entropy, high request rates (30–90 in 60s), elevated error rate |
| **Latency Attack** | Latency spike indicator = 1, high inter-arrival variance, lower overall request rate |

---

## 5. Real-Time Dashboard Status Schema (`GET /api/v1/status`)

Exposed by `monitoring/dashboard_api.go` on port `:9090` for the web UI polling engine.

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
    "refill_rate": 2.0
  },
  "recent_events": [
    {
      "timestamp": "2026-09-09T10:38:35Z",
      "type": "RATE_LIMIT",
      "ip_hash": "1c57742a",
      "path": "/api/login",
      "score": 0.74,
      "detail": "Rate limit exceeded (token bucket / burst)",
      "status": 429
    }
  ]
}
```
