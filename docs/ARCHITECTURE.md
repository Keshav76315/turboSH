# turboSH — System Architecture

**Version:** 0.1
**Last Updated:** 2026-03-05

---

## 1. Overview

turboSH is an AI‑powered middleware system that sits between clients and backend servers. It intercepts every request, applies scheduling and caching, logs traffic data, and runs ML‑based anomaly detection to automatically mitigate threats.

The system is designed to run on commodity hardware (4 GB RAM, 2 CPU cores, no GPU).

---

## 2. High-Level Request Flow

```
                    ┌──────────────────────────────────────────────────┐
                    │              turboSH Middleware                  │
                    │                                                  │
  Client ──────►    │  Reverse Proxy                                   │
                    │       │                                          │
                    │       ▼                                          │
                    │  Scheduler / Rate Limiter                        │
                    │       │                                          │
                    │       ▼                                          │
                    │  Cache Layer ──── hit ──► Response to Client     │
                    │       │ miss                                     │
                    │       ▼                                          │
                    │  Traffic Logger ──────► Log Store                │
                    │       │                                          │
                    │       ▼                                          │
                    │  Feature Extraction                              │
                    │       │                                          │
                    │       ▼                                          │
                    │  ML Inference Engine                             │
                    │       │                                          │
                    │       ▼                                          │
                    │  Decision Engine ─── BLOCK / RATE LIMIT / ALLOW  │
                    │       │ (if ALLOW)                               │
                    │       ▼                                          │
                    │  Forward to Backend ──► Backend Server           │
                    │                                                  │
                    └──────────────────────────────────────────────────┘
```

---

## 3. Component Architecture

### 3.1 Reverse Proxy (`core/proxy/`)

The entry point for all client traffic.

| Aspect    | Detail                                               |
| --------- | ---------------------------------------------------- |
| Language  | Go                                                   |
| Libraries | `net/http`, `httputil.ReverseProxy`, `gin-gonic/gin` |
| Owner     | Keshav                                                |

**Responsibilities:**

- Accept incoming HTTP requests
- Route requests through the middleware pipeline
- Forward allowed requests to the backend
- Return responses to clients

**Interfaces:**

- **Incoming:** HTTP requests from clients
- **Outgoing:** Passes request context to Scheduler

---

### 3.2 Request Scheduler (`core/scheduler/`)

Controls request flow to prevent backend overload.

| Aspect   | Detail |
| -------- | ------ |
| Language | Go     |
| Owner    | Keshav  |

**Algorithms:**

- **Request Queue** — buffered channel or priority queue
- **Priority Scheduling** — weighted by client reputation / request type
- **Burst Detection** — sliding window counter per IP
- **Rate Limiting** — token bucket per IP

**Interfaces:**

- **Input:** Request context from Reverse Proxy
- **Output:** Approved requests → Cache Layer

---

### 3.3 Cache Layer (`core/cache/`)

Reduces backend load by serving cached responses.

| Aspect   | Detail       |
| -------- | ------------ |
| Language | Go           |
| Type     | LRU with TTL |
| Owner    | Anzal        |

**Behavior:**

- On **cache hit** → return cached response directly (skip backend)
- On **cache miss** → forward request downstream, cache the response on return

**Metrics exposed:**

- `cache_hit_rate`, `cache_miss_rate`, `cache_evictions`

**Interfaces:**

- **Input:** Approved requests from Scheduler
- **Output (hit):** Response directly to client
- **Output (miss):** Request → Traffic Logger → Backend

---

### 3.4 Traffic Logger (`pipeline/logging/`)

Captures structured request metadata for the data pipeline.

| Aspect   | Detail |
| -------- | ------ |
| Language | Go     |
| Owner    | Anzal  |

**Log Schema:**

| Field           | Type     | Description                   |
| --------------- | -------- | ----------------------------- |
| `timestamp`     | datetime | Request arrival time          |
| `ip_hash`       | string   | Anonymized client IP          |
| `endpoint`      | string   | Requested URL path            |
| `method`        | string   | HTTP method (GET, POST, etc)  |
| `status_code`   | int      | Response status code          |
| `response_time` | float    | Backend response latency (ms) |
| `request_size`  | int      | Request body size (bytes)     |

**Interfaces:**

- **Input:** Request/response metadata from Cache Layer
- **Output:** Structured logs → Log Store (file / buffer)

---

### 3.5 Feature Extraction (`pipeline/feature_extraction/`)

Transforms raw logs into ML‑ready feature vectors.

| Aspect   | Detail |
| -------- | ------ |
| Language | Python |
| Owner    | Anzal  |

**Computed Features:**

| Feature               | Description                             |
| --------------------- | --------------------------------------- |
| `requests_per_ip_10s` | Request count per IP in 10s window      |
| `requests_per_ip_60s` | Request count per IP in 60s window      |
| `endpoint_entropy`    | Entropy of endpoint distribution per IP |
| `latency_spike`       | Boolean: response time exceeds baseline |
| `error_rate`          | Ratio of 4xx/5xx responses              |
| `request_variance`    | Variance in request timing              |

**Interfaces:**

- **Input:** Structured logs from Traffic Logger
- **Output:** Feature vectors → ML Inference Engine

---

### 3.6 ML Inference Engine (`ml/`)

Loads trained anomaly detection models and scores incoming traffic.

| Aspect         | Detail                              |
| -------------- | ----------------------------------- |
| Training       | Python (scikit-learn)               |
| Inference      | ONNX Runtime (Go or Python FastAPI) |
| Model Format   | ONNX                                |
| Model Location | `models/anomaly_model.onnx`         |
| Owner          | Keshav                               |

**Models:**

- Isolation Forest
- One‑Class SVM
- Local Outlier Factor
- _(Optional)_ LSTM Autoencoder

**Output:**

| Field                | Type   | Description                    |
| -------------------- | ------ | ------------------------------ |
| `anomaly_score`      | float  | 0.0 (normal) – 1.0 (anomalous) |
| `risk_level`         | string | LOW / MEDIUM / HIGH            |
| `recommended_action` | string | ALLOW / RATE_LIMIT / BLOCK     |

**Interfaces:**

- **Input:** Feature vectors from Feature Extraction
- **Output:** Anomaly scores → Decision Engine

---

### 3.7 Decision Engine (`core/decision/`)

Translates ML predictions into concrete system actions.

| Aspect   | Detail |
| -------- | ------ |
| Language | Go     |
| Owner    | Keshav  |

**Policy Rules:**

| Condition      | Action     |
| -------------- | ---------- |
| `score > 0.85` | BLOCK IP   |
| `score > 0.65` | RATE LIMIT |
| `score < 0.65` | ALLOW      |

**Interfaces:**

- **Input:** Anomaly score from ML Inference Engine
- **Output:** Action applied to request (block / throttle / forward)

---

### 3.8 Monitoring (`monitoring/`)

System observability via metrics and dashboards.

| Aspect   | Detail               |
| -------- | -------------------- |
| Language | Go                   |
| Stack    | Prometheus + Grafana |
| Endpoint | `/metrics`           |
| Owner    | Keshav                |

**Metrics:**

- Request throughput (req/s)
- Scheduler queue length
- Cache hit rate
- Anomaly alerts count
- ML inference latency

---

## 4. Data Flow Diagram

```
  ┌─────────────┐
  │   Clients   │
  └──────┬──────┘
         │ HTTP
         ▼
  ┌─────────────┐     ┌──────────────┐
  │ Reverse     │     │  Prometheus  │
  │ Proxy       │────►│  /metrics    │
  └──────┬──────┘     └──────┬───────┘
         │                    │
         ▼                    ▼
  ┌─────────────┐     ┌──────────────┐
  │ Scheduler   │     │   Grafana    │
  └──────┬──────┘     │  Dashboard   │
         │            └──────────────┘
         ▼
  ┌─────────────┐  hit  ┌──────────┐
  │ Cache Layer ├──────►│ Response │
  └──────┬──────┘       └──────────┘
         │ miss
         ▼
  ┌─────────────┐       ┌──────────────┐
  │  Traffic    │──────►│  Log Store   │
  │  Logger     │       └──────┬───────┘
  └──────┬──────┘              │
         │                     ▼
         │              ┌──────────────┐
         │              │  Feature     │
         │              │  Extraction  │
         │              └──────┬───────┘
         │                     │
         │                     ▼
         │              ┌──────────────┐
         │              │ ML Inference │
         │              └──────┬───────┘
         │                     │
         ▼                     ▼
  ┌─────────────┐       ┌──────────────┐
  │  Backend    │◄──────│  Decision    │
  │  Server     │ ALLOW │  Engine      │
  └─────────────┘       └──────────────┘
```

---

## 5. Technology Stack

| Layer              | Technology                  |
| ------------------ | --------------------------- |
| Reverse Proxy      | Go (`net/http`, `gin`)      |
| Scheduler          | Go (channels, goroutines)   |
| Cache              | Go (in-memory LRU)          |
| Traffic Logging    | Go (structured JSON logs)   |
| Feature Extraction | Python (pandas, numpy)      |
| ML Training        | Python (scikit-learn)       |
| ML Inference       | ONNX Runtime (Go or Python) |
| Model Format       | ONNX                        |
| Monitoring         | Prometheus + Grafana        |
| API (optional)     | FastAPI (Python)            |

---

## 6. Module Ownership

```
turboSH/
│
├── core/                    ← Keshav
│   ├── proxy/               │  Reverse proxy server
│   ├── scheduler/           │  Request scheduling & rate limiting
│   ├── cache/               │  LRU cache (Anzal)
│   ├── security/            │  Traffic control rules
│   └── decision/            │  ML score → action mapping
│
├── pipeline/                ← Anzal
│   ├── logging/             │  Traffic log capture
│   ├── feature_extraction/  │  Log → feature vectors
│   └── dataset_builder/     │  Feature vectors → CSV datasets
│
├── ml/                      ← Keshav
│   ├── training/            │  Model training scripts
│   └── evaluation/          │  Model evaluation & reports
│
├── models/                  ← Keshav (generated artifacts)
├── monitoring/              ← Keshav
├── datasets/                ← Anzal (generated artifacts)
├── notebooks/               ← Anzal
└── docs/                    ← Shared
```

---

## 7. Interface Contracts

Components communicate through well‑defined interfaces. This ensures Keshav and Anzal can develop independently.

### 7.1 Traffic Logger → Feature Extraction

**Format:** JSON lines (one JSON object per log entry)

```json
{
  "timestamp": "2026-03-05T12:00:00Z",
  "ip_hash": "a1b2c3d4",
  "endpoint": "/api/login",
  "method": "POST",
  "status_code": 200,
  "response_time": 45.2,
  "request_size": 512
}
```

### 7.2 Feature Extraction → ML Inference

**Format:** Feature vector (JSON or binary)

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

### 7.3 ML Inference → Decision Engine

**Format:** Prediction result

```json
{
  "ip_hash": "a1b2c3d4",
  "anomaly_score": 0.87,
  "risk_level": "HIGH",
  "recommended_action": "BLOCK"
}
```

---

## 8. Performance Targets

| Metric                 | Target  |
| ---------------------- | ------- |
| ML inference latency   | < 50 ms |
| Anomaly detection rate | > 70%   |
| False positive rate    | < 5%    |

---

## 9. Hardware Requirements

| Resource | Minimum |
| -------- | ------- |
| RAM      | 4 GB    |
| CPU      | 2 cores |
| GPU      | None    |
| OS       | Linux   |
