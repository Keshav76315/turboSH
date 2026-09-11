# Keshav's Role in turboSH

You are the **Backend Systems Engineer** and **ML Systems Engineer** for the project **turboSH**, an AI‑powered middleware designed to:

- Optimize server performance
- Detect anomalous traffic
- Mitigate potential attacks

The system acts as an intelligent middleware layer between clients and backend servers.

**Your responsibilities include:**

- Backend infrastructure algorithms & reverse proxy architecture
- Concurrency scheduling and queue management
- Rule-based traffic control (token-bucket rate limiting, burst & endpoint abuse rules)
- Machine learning model training and hyperparameter optimization
- Real-time in-process ONNX inference engine in Go
- Decision engine mitigation logic
- Containerization and multi-architecture Docker deployment

**You work in close coordination with Anzal**, who is responsible for:

- High-speed LRU response caching with TTL & singleflight stampede collapse
- Traffic logging & canonical HMAC-SHA-256 IP extraction
- Feature extraction pipelines & CSV dataset generation
- Exploratory data analysis & attack profiling
- Full-stack observability (Prometheus metrics & Real-Time Dashboard UI)

---

## System Architecture Context

The full request flow is:

```
Client
  ↓
Reverse Proxy (Keshav)
  ↓
Dashboard Telemetry Recorder (Anzal)
  ↓
Prometheus Metrics (Anzal)
  ↓
Canonical Client Identity & IP Hasher (Anzal)
  ↓
Scheduler / Concurrency Control (Keshav)
  ↓
Traffic Logger & ML Response Feedback (Anzal)
  ↓
Rate Limiter: Token Bucket (Keshav)
  ↓
Traffic Rules: Burst & Abuse Detection (Keshav)
  ↓
Real-Time ML Inference: In-Process ONNX (Keshav)
  ↓
Decision Engine: Block / Throttle / Allow (Keshav)
  ↓
LRU Cache & Stampede Collapse (Anzal)
  ↓ (on cache miss)
Backend Origin Server
```

**Your systems operate primarily in:**

- `/core/proxy/`
- `/core/scheduler/`
- `/core/security/`
- `/core/inference/`
- `/core/decision/`
- `/ml/`
- `/models/`

**Anzal operates mainly in:**

- `/core/cache/`
- `/pipeline/`
- `/monitoring/`
- `/ui/`
- `/datasets/`
- `/notebooks/`

---

## Part 1 — Reverse Proxy Middleware

You built the primary middleware server responsible for handling client traffic.

**Responsibilities:**

- Request routing and connection pooling
- Concurrency management and middleware assembly
- Upstream `Host` header rewrite (`req.Host = target.Host`)
- Forwarding requests to backend services via `httputil.ReverseProxy`
- Graceful shutdown handling (`SIGINT`/`SIGTERM`) and resource lifecycle management

**Libraries:**

- `net/http`
- `net/http/httputil`
- `github.com/gin-gonic/gin`

**Deliverables:**

- `/core/proxy/proxy.go`
- `/core/proxy/middleware.go`
- `/core/proxy/proxy_test.go`
- `/core/proxy/components_test.go`

---

## Part 2 — Request Scheduler

Controls load on the backend server via bounded concurrency.

**Architecture:**

- **Semaphore-based Concurrency Limiter** (`core/scheduler/scheduler.go`)
- Bounded channel queue capacity (`MaxConcurrent`, default 100)
- Configurable request wait timeout (`QueueTimeout`, default 10s)
- Fast-failure HTTP 503 (`Service Unavailable`) on queue saturation
- Live queue telemetry: `ActiveCount()` and `WaitingCount()` exposed to Prometheus gauges and the real-time dashboard

**Deliverables:**

- `/core/scheduler/scheduler.go`

---

## Part 3 — Traffic Control Algorithms

Rule‑based protections that function deterministically even when ML is disabled or warming up.

**Components:**

| Rule | Behavior | Implementation |
| :--- | :--- | :--- |
| **Rate Limiting** | Token-bucket per client IP (`RateLimitCapacity`, `RateLimitRate`) | `core/security/rate_limiter.go` |
| **Burst Detection** | Sliding-window threshold within configurable duration (`BurstThreshold`, `BurstWindow`) | `core/security/traffic_rules.go` |
| **Endpoint Abuse** | Detects excessive requests targeted at a single endpoint per IP (`EndpointAbuseThreshold`, `EndpointAbuseWindow`) | `core/security/traffic_rules.go` |

Both security modules feature background cleanup managers (`StartCleanupManager`) that periodically evict inactive client IPs to prevent unbounded memory growth.

**Deliverables:**

- `/core/security/rate_limiter.go`
- `/core/security/traffic_rules.go`
- `/core/security/security_test.go`

---

## Part 4 — Cache Management Integration

Integrates the in-memory response caching layer built by Anzal into the middleware pipeline.

**Characteristics:**

- Placed downstream of ML Inference so all incoming requests are evaluated by security models before cache short-circuiting
- Intercepts GET/HEAD requests, serving hits with `X-Cache: HIT` without touching the backend
- Request collapsing via `singleflight` prevents backend stampedes when popular keys expire

**Deliverables:**

- `/core/cache/` (owned by Anzal; integrated in `/core/proxy/middleware.go`)

---

## Part 5 — Metrics and Observability

Prometheus instrumentation and administrative isolation.

**Prometheus Metrics:**

- `turbosh_requests_total{method, status}`: Request counter
- `turbosh_request_latency_ms{method}`: Sub-millisecond latency distribution histogram
- `turbosh_scheduler_active_requests`: Active concurrent request gauge
- `turbosh_scheduler_waiting_requests`: Queued request gauge
- `turbosh_scheduler_capacity`: Maximum concurrency capacity gauge
- `turbosh_cache_operations_total{result="hit"|"miss"}`: Cache efficiency counter
- `turbosh_anomaly_alerts_total{action="block"|"rate_limit"|"allow"}`: ML threat counter

**Port Isolation:**
- Metrics (`/metrics`), live status (`/api/v1/status`), and the web dashboard (`/dashboard`) are hosted on an isolated internal administrative port (`:9090`, configurable via `TURBOSH_METRICS_PORT`), distinct from the public proxy port (`:8080`).

---

## Part 6 — Machine Learning Model Lifecycle

Responsible for training, evaluating, and deploying the anomaly detection models.

### 6-Dimensional Feature Vector

The ML models consume 6 normalized behavioral features:

| Index | Feature | Range | Description |
| :---: | :------ | :---- | :---------- |
| 0 | `requests_per_ip_10s` | $\ge 0$ | Request count in the last 10s |
| 1 | `requests_per_ip_60s` | $\ge 0$ | Request count in the last 60s |
| 2 | `endpoint_entropy` | $[0.0, 1.0]$ | Normalized Shannon entropy of endpoints |
| 3 | `latency_spike` | `0.0` or `1.0` | Max latency $> 1.5\times$ avg and $> 100\text{ ms}$ |
| 4 | `error_rate` | $[0.0, 1.0]$ | Ratio of 4xx/5xx responses |
| 5 | `request_variance` | $\ge 0$ | Variance of request inter-arrival times |

### Model Training & Selection

- **Synthetic Generator:** `ml/data/generate_synthetic_data.py` (CLI flags `--output`, `--num-normal`, `--num-attack`)
- **GridSearchCV:** `ml/training/train_model.py` across Isolation Forest, One-Class SVM, and Local Outlier Factor (LOF)
- **Winner:** **Isolation Forest** (`n_estimators=200`, `max_samples=256`, `contamination=0.091`), achieving Validation F1 ~0.983, Detection Rate 91.2%, and False Positive Rate 3.3%.
- **Report:** `docs/model_evaluation_report.md`
- **Model Export:** `ml/export/export_onnx.py` → `models/anomaly_model.onnx`

### Real-Time In-Process Inference Engine

turboSH embeds the ONNX Runtime directly into the Go middleware process using CGO bindings (`yalue/onnxruntime_go`):

- **Zero Microservice Overhead:** No external Python server or HTTP round-trips; inference runs in-process in $< 1\text{ ms}$.
- **Non-CGO Fallback:** Stubs in `core/inference/inference_nocgo.go` enable compilation and test execution on machines without CGO toolchains.
- **Sliding Ring Buffers:** `core/inference/middleware.go` maintains per-IP ring buffers of the last 60 seconds of traffic to construct live feature vectors on each request.
- **Continuous Anomaly Scoring:** Extracts a continuous decision score in $[0.0, 1.0]$ rather than binary classification.

### Decision Engine

Translates the continuous anomaly score into deterministic mitigation:

| Anomaly Score | Action | HTTP Response |
| :------------ | :----- | :------------ |
| `score > 0.85` | **BLOCK** | `403 Forbidden` (`{"error":"forbidden","reason":"anomalous_traffic"}`) |
| `score > 0.65` | **RATE LIMIT** | `429 Too Many Requests` (`{"error":"rate_limited","reason":"anomalous_traffic"}`) |
| `score <= 0.65` | **ALLOW** | Forwarded to Cache / Origin Backend |

Configurable at runtime via `TURBOSH_BLOCK_THRESHOLD` and `TURBOSH_RATE_LIMIT_THRESHOLD`.

**Deliverables:**

- `/core/inference/inference.go` (CGO ONNX runtime engine)
- `/core/inference/inference_nocgo.go` (graceful non-CGO fallback)
- `/core/inference/features.go` (normalized Shannon entropy & feature extraction)
- `/core/inference/middleware.go` (live windowed inference middleware)
- `/core/decision/decision_engine.go` (threshold evaluation policy)
- `/core/decision/decision_engine_test.go` (decision policy unit tests)

---

## Collaboration Rules

- **Keshav owns:** `/core/proxy/`, `/core/scheduler/`, `/core/security/`, `/core/inference/`, `/core/decision/`, `/ml/`, `/models/`
- **Anzal owns:** `/core/cache/`, `/pipeline/`, `/monitoring/`, `/ui/`, `/datasets/`, `/notebooks/`, `/docs/`
- Shared interaction occurs via well-defined Go interfaces (`RequestFeatures`, `DashboardState`, `Cache`, `Scheduler`).
