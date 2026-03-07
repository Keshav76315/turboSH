# turboSH — Data Schema

> Defines the structure of traffic logs, feature vectors, and datasets used throughout the system.

---

## 1. Traffic Log Schema

Produced by the **Traffic Logger** (`pipeline/logging/`).

Each log entry is a single JSON object per line (JSON Lines format).
_For architectural details regarding how the ML models were trained, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)._

### Fields

| Field           | Type     | Description                   | Example                |
| --------------- | -------- | ----------------------------- | ---------------------- |
| `timestamp`     | ISO 8601 | Request arrival time (UTC)    | `2026-03-05T12:00:00Z` |
| `ip_hash`       | string   | SHA-256 hash of client IP     | `a1b2c3d4e5f6...`      |
| `endpoint`      | string   | Requested URL path            | `/api/login`           |
| `method`        | string   | HTTP method                   | `POST`                 |
| `status_code`   | int      | Response status code          | `200`                  |
| `response_time` | float    | Backend response latency (ms) | `45.2`                 |
| `request_size`  | int      | Request body size (bytes)     | `512`                  |

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

Produced by the **Feature Extraction Pipeline** (`pipeline/feature_extraction/`). Consumed by the **ML Inference Engine**.

### Fields

| Feature               | Type   | Description                                      | Range / Example |
| --------------------- | ------ | ------------------------------------------------ | --------------- |
| `ip_hash`             | string | Identifies the client (carried from log)         | `a1b2c3d4...`   |
| `requests_per_ip_10s` | int    | Request count for this IP in the last 10 seconds | `0–1000+`       |
| `requests_per_ip_60s` | int    | Request count for this IP in the last 60 seconds | `0–5000+`       |
| `endpoint_entropy`    | float  | Entropy of endpoint distribution for this IP     | `0.0–1.0`       |
| `latency_spike`       | bool   | Max response time > 1.5x avg (and > 100ms)       | `true/false`    |
| `error_rate`          | float  | Ratio of 4xx/5xx responses for this IP           | `0.0–1.0`       |
| `request_variance`    | float  | Variance of response latencies (jitter)          | `0.0+`          |

### Example

```json
{
  "ip_hash": "a1b2c3d4e5f67890",
  "requests_per_ip_10s": 25,
  "requests_per_ip_60s": 80,
  "endpoint_entropy": 0.3,
  "latency_spike": true,
  "error_rate": 0.15,
  "request_variance": 12.5
}
```

---

## 3. ML Prediction Schema

Produced by the **ML Inference Engine**. Consumed by the **Decision Engine**.

### Fields

| Field                | Type   | Description                              | Values                             |
| -------------------- | ------ | ---------------------------------------- | ---------------------------------- |
| `ip_hash`            | string | Client identifier                        | `a1b2c3d4...`                      |
| `anomaly_score`      | float  | Anomaly confidence score                 | `0.0` (normal) – `1.0` (anomalous) |
| `risk_level`         | string | Categorized risk                         | `LOW`, `MEDIUM`, `HIGH`            |
| `recommended_action` | string | Suggested action for the Decision Engine | `ALLOW`, `RATE_LIMIT`, `BLOCK`     |

### Example

```json
{
  "ip_hash": "a1b2c3d4e5f67890",
  "anomaly_score": 0.87,
  "risk_level": "HIGH",
  "recommended_action": "BLOCK"
}
```

---

## 4. Dataset Schema

Generated datasets for ML training and evaluation. Stored in `datasets/`.

### `normal_traffic.csv` / `attack_traffic.csv`

| Column                | Type   | Description                   |
| --------------------- | ------ | ----------------------------- |
| `timestamp`           | string | ISO 8601 timestamp            |
| `requests_per_ip_10s` | int    | Request count (10s window)    |
| `requests_per_ip_60s` | int    | Request count (60s window)    |
| `endpoint_entropy`    | float  | Endpoint distribution entropy |
| `latency_spike`       | int    | 1 = spike, 0 = normal         |
| `error_rate`          | float  | 4xx/5xx ratio                 |
| `request_variance`    | float  | Latency variance (jitter)     |
| `label`               | int    | `0` = normal, `1` = anomalous |

### Attack Types

| Label | Attack Type       |
| ----- | ----------------- |
| 0     | Normal traffic    |
| 1     | DDoS burst        |
| 1     | Brute force login |
| 1     | Endpoint scanning |
| 1     | Request flooding  |
