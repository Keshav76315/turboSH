# turboSH — System Architecture

**Version: 1.0.0**  
**Status: Production Ready (EPICs 1–9 Finished, Flaw Audit Remediation Verified)**

---

## 1. Overview

turboSH is a high-performance, AI‑powered middleware system positioned between clients and backend servers. It intercepts HTTP traffic, enforces concurrency limits and token-bucket rate limiting, caches frequent responses, logs traffic with privacy-preserving IP hashing, computes sliding-window behavioral features, and applies real-time ML anomaly detection to automatically mitigate threats (blocking or throttling malicious traffic).

The system runs efficiently on commodity hardware (4 GB RAM, 2 CPU cores, no GPU required) with in-process ML inference executing in under 1 millisecond.

---

## 2. High-Level Request Flow

The middleware pipeline is assembled in [`core/proxy/middleware.go`](../core/proxy/middleware.go) in a verified, hardened execution order:

```
                      ┌─────────────────────────────────────────────────────────────┐
                      │                     turboSH Middleware                      │
                      │                                                             │
  Client Request ───► │  1. Dashboard Recorder (Telemetry & End-to-End Latency)     │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  2. Prometheus Base Metrics (/metrics on :9090)             │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  3. Canonical Client Identity (Trusted Proxies & HMAC-SHA)  │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  4. Concurrency Scheduler (Semaphore Limiter & Queue)       │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  5. Traffic Logger (Wraps downstream; feeds live ML stats)  │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  6. Token Bucket Rate Limiter (Per-IP Capacity & Refill)    │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  7. Traffic Rules (Sliding Burst & Endpoint Abuse Guards)   │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  8. Live Feature Extraction & In-Process ONNX ML Inference  │
                      │       │                                                     │
                      │       ▼                                                     │
                      │  9. Decision Engine ─── BLOCK (403) / RATE LIMIT (429)      │
                      │       │ (if ALLOW)                                          │
                      │       ▼                                                     │
                      │ 10. LRU Cache & Stampede Collapse ── hit ──► Direct Return  │
                      │       │ (on cache miss)                                     │
                      │       ▼                                                     │
                      │ 11. Upstream Reverse Proxy (req.Host Rewrite)               │
                      └───────┼─────────────────────────────────────────────────────┘
                              │
                              ▼
                     Backend Origin Server (:9092)
```

### Architectural Design Invariants

1. **ML Inference Precedes Cache:**
   Evaluating ML anomaly detection *before* the cache ensures that repeated request bursts, credential stuffing, and scraping attacks cannot hide behind cache hits. Every incoming request is subjected to behavioral security analysis.
2. **Traffic Logger Wraps Downstream Handlers:**
   The Traffic Logger middleware wraps all downstream execution. This ensures that downstream requests admitted by the Scheduler — cache hits, normal origin responses, token-bucket throttles, and ML-blocked requests (excluding scheduler-generated 503 queue timeout rejections) — are captured in `logs/traffic.jsonl` and fed back to ML latency ring buffers in real time.
3. **Canonical Client Identity Established Early:**
   IP extraction resolves trusted reverse proxies (`TURBOSH_TRUSTED_PROXIES`) and applies HMAC-SHA-256 salting before any rate limiter or ML component runs, guaranteeing that all layers reference the exact same client identity.

---

## 3. Component Architecture

### 3.1 Reverse Proxy (`core/proxy/`)

The primary HTTP gateway.

| Aspect | Detail |
| :--- | :--- |
| Language | Go 1.24+ |
| Libraries | `net/http`, `net/http/httputil`, `github.com/gin-gonic/gin` |
| Owner | Keshav |

**Responsibilities:**
- Accepts incoming client requests on `TURBOSH_PORT` (default `:8080`)
- Rewrites `req.Host = target.Host` to maintain backend routing integrity
- Configures connection pooling (`Transport` with idle connection reuse)
- Manages graceful shutdown on `SIGINT`/`SIGTERM`, safely draining open requests within 10 seconds

---

### 3.2 Request Scheduler (`core/scheduler/`)

Controls concurrent request execution to protect origin backends from saturation.

| Aspect | Detail |
| :--- | :--- |
| Language | Go |
| Implementation | Semaphore channel (`core/scheduler/scheduler.go`) |
| Owner | Keshav |

**Behavior:**
- Bounded concurrency (`MaxConcurrent`, default 100 slots)
- Configurable waiting queue timeout (`QueueTimeout`, default 10s)
- Fast failure: if the queue timeout expires, the request is terminated with `503 Service Unavailable`
- Exposes atomic `ActiveCount()` and `WaitingCount()` to Prometheus and the dashboard

---

### 3.3 Cache Layer (`core/cache/`)

In-memory caching layer that eliminates redundant backend requests.

| Aspect | Detail |
| :--- | :--- |
| Language | Go |
| Type | Doubly linked list + hashmap LRU with TTL & byte bounds |
| Owner | Anzal |

**Behavior:**
- **Cache Hit:** Serves response immediately with `X-Cache: HIT` header (bypasses backend)
- **Cache Miss:** Forwards request downstream, captures response via response recorder, and stores copy
- **Stampede Protection:** Coalesces concurrent misses on the same URI using `singleflight`
- **Memory Safety:** Enforces byte-level capacity limit (default 512 MB) and uses deep copies of headers/body to guarantee zero data races across goroutines
- **TTL Eviction:** Lazy expiration on `Get()` combined with a background eviction manager (`StartTTLManager`)

---

### 3.4 Traffic Control & Security Rules (`core/security/`)

Deterministic, rule-based traffic enforcement.

| Component | Behavior |
| :--- | :--- |
| **Rate Limiter** (`rate_limiter.go`) | Per-IP token-bucket algorithm (`RateLimitCapacity`, `RateLimitRate`) |
| **Burst Detection** (`traffic_rules.go`) | Flags clients exceeding `BurstThreshold` requests within `BurstWindow` |
| **Endpoint Abuse** (`traffic_rules.go`) | Flags clients targeting a single path more than `EndpointAbuseThreshold` times |

Both modules employ automated background cleanup managers (`StartCleanupManager`) that evict inactive IP buckets, keeping memory usage strictly bounded.

---

### 3.5 Traffic Logging System (`pipeline/logging/`)

Captures structured request telemetry for analysis, training datasets, and live ML feedback.

| Aspect | Detail |
| :--- | :--- |
| Language | Go |
| Storage | JSON Lines (`logs/traffic.jsonl`) |
| Owner | Anzal |

**Key Features:**
- Buffered I/O (4 KB buffer) with periodic timer-based flushing and flush-on-shutdown
- Canonical IP resolution with untrusted header striping and HMAC-SHA-256 anonymization
- Real-time feedback loop: calls `MLProtection.RecordBackendResponse(ipHash, statusCode, latencyMs)` to maintain live sliding-window statistics for incoming ML evaluation

---

### 3.6 ML Inference Engine (`core/inference/`, `ml/`)

Detects anomalous and malicious traffic patterns using machine learning.

| Aspect | Detail |
| :--- | :--- |
| Offline Training | Python (`scikit-learn`, `GridSearchCV`) in `ml/training/train_model.py` |
| Model Format | ONNX (`models/anomaly_model.onnx`, exported via `skl2onnx`) |
| Online Inference | In-process Go via CGO (`yalue/onnxruntime_go`) in `core/inference/inference.go` |
| Fallback | Non-CGO stub in `core/inference/inference_nocgo.go` for non-CGO builds |
| Owner | Keshav |

**6-Dimensional Feature Vector:**
1. `requests_per_ip_10s`: 10-second window request count
2. `requests_per_ip_60s`: 60-second window request count
3. `endpoint_entropy`: Normalized Shannon entropy of visited paths ($[0.0, 1.0]$)
4. `latency_spike`: Binary flag ($1$ if max latency $> 1.5\times$ average and $> 100\text{ ms}$)
5. `error_rate`: 4xx/5xx error ratio in active window ($[0.0, 1.0]$)
6. `request_variance`: Variance of inter-arrival durations

Inference runs in $< 1\text{ ms}$ per request and outputs a continuous anomaly score in $[0.0, 1.0]$.

---

### 3.7 Decision Engine (`core/decision/`)

Maps continuous ML anomaly scores to system actions.

| Anomaly Score | Action | HTTP Response |
| :--- | :--- | :--- |
| `score > 0.85` | **BLOCK** | `403 Forbidden` (`{"error":"forbidden","reason":"anomalous_traffic"}`) |
| `score > 0.65` | **RATE LIMIT** | `429 Too Many Requests` (`{"error":"rate_limited","reason":"anomalous_traffic"}`) |
| `score <= 0.65` | **ALLOW** | Forwarded to cache / origin |

Thresholds are configurable at startup via `TURBOSH_BLOCK_THRESHOLD` and `TURBOSH_RATE_LIMIT_THRESHOLD`.

---

### 3.8 Observability & Real-Time Dashboard (`monitoring/`, `ui/`)

Full-stack observability isolated on administrative port `:9090`.

| Aspect | Detail |
| :--- | :--- |
| Prometheus | Exposed at `GET :9090/metrics` |
| Status API | Exposed at `GET :9090/api/v1/status` (compact JSON snapshot) |
| Web Dashboard | `GET :9090/dashboard` (Dark theme) and `/dashboard/light` (Light theme) |
| Owner | Anzal |

**Dashboard Capabilities:**
- Real-time requests-per-second (RPS) throughput calculator
- 1,000-request rolling latency tracker (average and p99 latency)
- Cache memory consumption and hit-rate gauge
- Live threat feed displaying the last 50 mitigation events with sanitized IP hashes and trigger details
- 60-second animated SVG throughput waveform chart

---

## 4. System Data Flow Diagram

```
                             +------------------------+
                             |    External Clients    |
                             +------------------------+
                                         |
                                         | HTTP Requests
                                         v
+---------------------------------------------------------------------------------+
|                              turboSH Reverse Proxy                              |
|                                                                                 |
|   +-------------------------------------------------------------------------+   |
|   | 1. Dashboard Recorder & 2. Prometheus Base Metrics                      |   |
|   +-------------------------------------------------------------------------+   |
|                                        |                                        |
|   +------------------------------------+------------------------------------+   |
|   | 3. Client Identity: Resolves Trusted Proxies & Computes HMAC IP Hash    |   |
|   +-------------------------------------------------------------------------+   |
|                                        |                                        |
|   +------------------------------------+------------------------------------+   |
|   | 4. Concurrency Scheduler (Semaphore Channel Limiter)                    |   |
|   +-------------------------------------------------------------------------+   |
|                                        |                                        |
|   +------------------------------------+------------------------------------+   |
|   | 5. Traffic Logger: Logs Request & Feeds Response Metrics to ML Engine   |   |
|   +-------------------------------------------------------------------------+   |
|                                        |                                        |
|   +------------------------------------+------------------------------------+   |
|   | 6. Rate Limiter (Token Bucket) & 7. Traffic Rules (Burst/Abuse)         |   |
|   +-------------------------------------------------------------------------+   |
|                                        |                                        |
|   +------------------------------------+------------------------------------+   |
|   | 8. In-Process ONNX ML Inference Engine (6D Live Feature Vector)         |   |
|   +-------------------------------------------------------------------------+   |
|                                        |                                        |
|   +------------------------------------+------------------------------------+   |
|   | 9. Decision Engine: Evaluates Continuous Anomaly Score                  |   |
|   +-------------------------------------------------------------------------+   |
|                    | Block (>0.85)     | Throttle (>0.65)   | Allow (<=0.65)    |
|                    v                   v                    v                   |
|              403 Forbidden     429 Too Many Reqs     +----------------------+   |
|                                                      | 10. LRU Cache Layer  |   |
|                                                      +----------------------+   |
|                                                                 | Miss          |
|                                                                 v               |
|                                                      +----------------------+   |
|                                                      | 11. Backend Forward  |   |
|                                                      +----------------------+   |
+-----------------------------------------------------------------|---------------+
                                                                  | Forward
                                                                  v
                                                     +------------------------+
                                                     |  Origin Backend :9092  |
                                                     +------------------------+
```

---

## 5. Technology Stack

| Layer | Technology | Rationale |
| :--- | :--- | :--- |
| **Reverse Proxy** | Go (`net/http`, `gin-gonic/gin`) | Low overhead, predictable garbage collection, high concurrency |
| **Concurrency Control** | Go buffered channels | Non-blocking semaphore pattern with zero deadlocks |
| **Cache** | In-memory doubly linked list + hashmap (`golang.org/x/sync/singleflight`) | $O(1)$ read/write with singleflight stampede collapse |
| **Traffic Logging** | Go buffered I/O with HMAC-SHA-256 | High-throughput logging without disk thrashing |
| **Feature Extraction** | Go (real-time) & Python (batch) | Mathematically unified sliding window algorithms |
| **ML Training** | Python (`scikit-learn`) | Rapid experimentation with Isolation Forest & GridSearchCV |
| **ML Inference** | Go CGO (`yalue/onnxruntime_go`) | Zero-latency in-process evaluation ($<1\text{ ms}$) |
| **Observability** | Prometheus + Grafana | Industry-standard metric scraping and dashboarding |
| **Real-Time UI** | Vanilla HTML / CSS / JS | Zero-dependency responsive interface polling `/api/v1/status` |
| **Deployment** | Multi-arch Docker (`amd64`/`arm64`) | Portable, reproducible production deployment |

---

## 6. Module Ownership

```
turboSH/
├── cmd/                     ← Shared
│   ├── turbosh/             Keshav (Main proxy entrypoint)
│   ├── dummy_backend/       Keshav (Test backend)
│   ├── loadtest/            Keshav + Anzal (Performance benchmarking)
│   └── accuracy_test/       Keshav + Anzal (Detection accuracy evaluation)
├── core/
│   ├── proxy/               Keshav
│   ├── scheduler/           Keshav
│   ├── security/            Keshav
│   ├── inference/           Keshav (In-process ONNX engine & ML middleware)
│   ├── decision/            Keshav
│   └── cache/               Anzal (LRU Cache, TTL manager, singleflight)
├── pipeline/
│   ├── logging/             Anzal (Traffic logger & IP extractor)
│   ├── monitoring/          Anzal (Canonical Prometheus metrics)
│   ├── feature_extraction/  Anzal (Sliding-window feature extractor)
│   └── dataset_builder/     Anzal (Training CSV generation)
├── ml/                      ← Keshav
│   ├── data/                Synthetic dataset generator
│   ├── training/            Model training & hyperparameter search
│   ├── export/              ONNX export scripts
│   └── evaluation/          Model performance reporting
├── monitoring/              ← Anzal (DashboardState, Dashboard API, Prometheus)
├── ui/                      ← Anzal (Desktop & Mobile Web Dashboards)
├── scripts/                 ← Shared (demo.sh live runner)
├── datasets/                ← Anzal (Generated datasets)
├── notebooks/               ← Anzal (Traffic analysis notebooks)
└── docs/                    ← Shared
```

---

## 7. Performance Targets & Validation Results

| Metric | Target | Verified Value | Status |
| :--- | :--- | :--- | :--- |
| **Inference Latency** | $< 50\text{ ms}$ | **$< 1\text{ ms}$** (in-process ONNX) | **PASS** |
| **Detection Rate (Recall)** | $> 70\%$ | **$91.2\%$** | **PASS** |
| **False Positive Rate** | $< 5\%$ | **$3.3\%$** | **PASS** |
| **Max Ramp Concurrency** | $> 500\text{ req/s}$ | **$613.2\text{ req/s}$** | **PASS** |
| **Active Codebase Flaws** | $0$ | **$0$** (53 audited flaws closed) | **PASS** |

---

## 8. Network Architecture & Port Allocation

turboSH enforces a clean, three-tier network isolation model:

```
[Public Network]                   [Private Container Network]
Client Requests (8080) ───────► turboSH Proxy (:8080)
                                      │
                                      ▼
                               Origin Backend (:9092)

[Internal Admin Network]
Prometheus / Dashboards ──────► turboSH Admin Server (:9090)
                                - GET /metrics
                                - GET /api/v1/status
                                - GET /dashboard
```

| Port | Service | Exposure | Responsibility |
| :--- | :--- | :--- | :--- |
| **`:8080`** | **turboSH Proxy** | Public | Reverse proxy handling client traffic, scheduling, security rules, ML inference, and caching |
| **`:9092`** | **Dummy / Origin Backend**| Internal | Upstream origin server servicing cache misses |
| **`:9090`** | **Admin & Telemetry** | Internal | Isolated administrative server hosting `/metrics`, `/api/v1/status`, and `/dashboard` |

### TLS / HTTPS Termination

turboSH supports two deployment configurations:
- **Direct TLS Termination:** Enable `TURBOSH_TLS_ENABLED=true` and configure `TURBOSH_TLS_CERT` and `TURBOSH_TLS_KEY`.
- **Edge Reverse Proxy Termination (Recommended):** Place an edge load balancer (Nginx, AWS ALB, Cloudflare) in front of turboSH. Upstream proxies are specified in `TURBOSH_TRUSTED_PROXIES` so client IP extraction remains spoof-resistant.
