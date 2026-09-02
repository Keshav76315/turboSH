# turboSH — Exhaustive Flaw Analysis

> **Scope:** Every source file in the repository, cross-referenced against [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
> **Date:** 2026-09-03

---

## Table of Contents

1. [Critical Build-Breaking Issues](#1-critical-build-breaking-issues)
2. [Architecture Mismatches](#2-architecture-mismatches)
3. [Critical Bugs](#3-critical-bugs)
4. [Security Vulnerabilities](#4-security-vulnerabilities)
5. [Logical Flaws](#5-logical-flaws)
6. [Integration Issues](#6-integration-issues)
7. [Concurrency & Resource Leaks](#7-concurrency--resource-leaks)
8. [ML Pipeline Mismatches](#8-ml-pipeline-mismatches)
9. [Monitoring & Metrics Conflicts](#9-monitoring--metrics-conflicts)
10. [Docker & Deployment Issues](#10-docker--deployment-issues)
11. [Documentation Inconsistencies](#11-documentation-inconsistencies)
12. [Test & Tooling Issues](#12-test--tooling-issues)
13. [Code Quality & Typos](#13-code-quality--typos)

---

## 1. Critical Build-Breaking Issues

### 1.1 — Config file has invalid filename (CANNOT BE IMPORTED)
- **File:** `config/config 2.51.45 PM.go`
- **Issue:** The filename contains spaces and a macOS Finder timestamp. Go's toolchain cannot import a package from a directory containing a file with spaces in its name. This file defines the `config` package that every other package imports. The build will fail on any machine that doesn't have macOS's special handling of this duplicate naming.
- **Impact:** **Build-breaking.** The entire project is unbuildable if Go encounters this filename.
- **Fix:** Rename to `config/config.go`.

### 1.2 — Dockerfile has invalid filename
- **File:** `Dockerfile 2.51.50 PM`
- **Issue:** Same macOS Finder duplicate naming. `docker build .` looks for a file literally named `Dockerfile` — this file will never be found.
- **Impact:** **Docker build completely broken.** All Docker instructions in README.md and PLAYBOOK.md are non-functional.
- **Fix:** Rename to `Dockerfile`.

### 1.3 — `go.mod` declares non-existent Go version
- **File:** `go.mod` line 3
- **Issue:** `go 1.25.0` — Go 1.25 does not exist. As of the project date, the latest Go release is 1.24.x.
- **Impact:** `go mod tidy` and `go build` may fail or produce warnings on real Go toolchains.
- **Fix:** Change to `go 1.24.0` or the actual version used.

---

## 2. Architecture Mismatches

### 2.1 — Middleware pipeline order contradicts architecture flow
- **Architecture §2 says:** Client → Proxy → Scheduler → Cache → Traffic Logger → Feature Extraction → ML Inference → Decision Engine
- **Actual order in `core/proxy/middleware.go` `SetupMiddleware()` (L114–153):** Metrics → Scheduler → RateLimiter → TrafficRules → **ML Inference** → **Cache** → Logger
- **Mismatch:** ML Inference runs BEFORE Cache, not after Feature Extraction. The architecture diagram shows Cache before the ML pipeline; the implementation inverts this. The comment on L139 even acknowledges: "MUST run before cache so the ML engine sees all requests, even repetitive ones" — this is a deliberate deviation from the architecture document that was never reflected back into the spec.

### 2.2 — Feature extraction is not the Python pipeline described in architecture
- **Architecture §3.5** says Feature Extraction is Python (`pipeline/feature_extraction/`), operating on structured logs from the Traffic Logger.
- **Reality:** The live system does feature extraction inline in Go via `core/inference/middleware.go` (`recordRequest()` method, L109-195). The Python `feature_extractor.py` is a batch offline tool, not the live pipeline component the architecture describes.
- **Impact:** The entire architecture's data flow (Logger → Feature Extraction → ML Inference) does not exist as a live pipeline.

### 2.3 — Traffic Logger feeds ML backwards
- **Architecture §3.4** says Traffic Logger output feeds Feature Extraction.
- **Reality:** The Traffic Logger (`pipeline/logging/traffic_logger.go`) feeds metrics BACK to `MLProtection.RecordBackendResponse()` (L118–120) — this is a reverse feedback direction. The Logger runs AFTER ML inference in the middleware chain, so ML inference happens before the logger even sees the request.

### 2.4 — Priority Queue is implemented but never used
- **Architecture §3.2** specifies "Priority Scheduling — weighted by client reputation / request type."
- **File:** `core/scheduler/queue.go` — A full `PriorityQueue` with heap implementation exists (114 lines).
- **File:** `core/scheduler/scheduler.go` — The actual `Scheduler` uses a simple buffered-channel semaphore with no priority.
- **Impact:** The priority scheduling described in the architecture is dead code.

### 2.5 — `core/inference/` directory not listed in architecture module tree
- **Architecture §6** (Module Ownership tree) lists: `core/proxy/`, `core/scheduler/`, `core/cache/`, `core/security/`, `core/decision/`.
- **Missing:** `core/inference/` is not mentioned anywhere in the architecture module ownership tree, despite being the most critical component (ML inference middleware).

### 2.6 — Architecture says ML models include ensemble; only Isolation Forest supported
- **Architecture §3.6** lists: Isolation Forest, One-Class SVM, Local Outlier Factor, LSTM Autoencoder.
- **Reality:** `ml/export/export_onnx.py` hardcodes `best_isolationforest.pkl` (L8). Even though `train_model.py` trains multiple models and saves the best, the export script only knows about Isolation Forest. No ensemble, no model selection in the inference pipeline.

### 2.7 — `ml/evaluation/` directory missing
- **Architecture §6** lists `ml/evaluation/` in the module tree.
- **Reality:** This directory does not exist or is empty. No model evaluation reports or scripts are present.

---

## 3. Critical Bugs

### 3.1 — `string(rune(status))` produces Unicode garbage instead of status code strings
- **File:** `pipeline/monitoring/metrics.go` L63
- **Code:** `RequestsTotal.WithLabelValues(method, string(rune(status))).Inc()`
- **Bug:** `string(rune(200))` converts HTTP status code 200 to Unicode character `È` (U+00C8), not the string `"200"`. Status 404 → `ǔ` (U+0194). Status 500 → `Ǵ` (U+01F4).
- **Impact:** All Prometheus metrics for `turbosh_requests_total` have corrupted, unreadable label values. Grafana dashboards and alerts are completely broken.
- **Note:** The comment on the same line says "I will use strconv.Itoa" — but the author never actually applied the fix.
- **Fix:** `strconv.Itoa(status)`.

### 3.2 — `NormalizeScore` returns binary 0.0/1.0, making RATE_LIMIT action unreachable
- **File:** `core/inference/features.go` L37-41
- **Code:** Returns only `0.0` (normal) or `1.0` (anomalous) — a binary output.
- **Architecture §3.6** specifies `anomaly_score` as a continuous range "0.0 (normal) – 1.0 (anomalous)".
- **Impact:** The Decision Engine thresholds (block > 0.85, rate_limit > 0.65) receive only 0.0 or 1.0. Score 1.0 > 0.85 → BLOCK. Score 0.0 → ALLOW. The RATE_LIMIT action (0.65 < score < 0.85) can **NEVER** trigger. The three-tier defense is reduced to a binary block/allow.

### 3.3 — TTL Manager does not update `currentMemory` when removing expired entries
- **File:** `core/cache/ttl_manager.go` L42-44
- **Code:**
  ```go
  c.order.Remove(element)
  delete(c.items, entry.key)
  // Missing: c.currentMemory -= entry.size
  // Missing: c.metrics.RecordEviction()
  ```
- **Impact:** `currentMemory` drifts permanently upward over time. Once enough entries expire without being accounted for, `currentMemory` exceeds `maxMemory` and causes premature eviction of valid cache entries. The longer the system runs, the worse it gets.

### 3.4 — Singleflight winners run `c.Next()` for all waiters' contexts
- **File:** `core/cache/cache_middleware.go` L159
- **Issue:** `c.Next()` is called inside the singleflight function, running in the context of the first goroutine. For `shared=true` goroutines (waiters), their `gin.Context`'s `c.Next()` is never called, which means their subsequent middleware (traffic logger) never executes for those requests.
- **Impact:** Under stampede conditions, only 1 out of N concurrent requests for the same cache key will have its traffic logged. The other N-1 requests are invisible to the logging and ML pipeline.

### 3.5 — `loadtest/main.go` nil pointer dereference panic
- **File:** `cmd/loadtest/main.go` L41-47
- **Code:**
  ```go
  req, err := http.NewRequest("GET", targetURL+path, nil)
  if err == nil && clientIP != "" {
      req.Header.Set("X-Forwarded-For", clientIP)
  }
  resp, requestErr := client.Do(req)  // req is nil if err != nil!
  ```
- **Impact:** If `http.NewRequest` returns an error, `req` is nil, and `client.Do(nil)` causes a **nil pointer dereference panic**.

### 3.6 — Sub-millisecond latency truncation in pipeline metrics
- **File:** `pipeline/monitoring/metrics.go` L59
- **Code:** `elapsed := float64(time.Since(start).Milliseconds())` — uses integer milliseconds then casts to float.
- **Impact:** All sub-millisecond latencies (common for cached responses) are recorded as `0.0 ms`, destroying histogram accuracy.

---

## 4. Security Vulnerabilities

### 4.1 — Hardcoded default IP salt
- **File:** `pipeline/logging/ip_extractor.go` L19-21
- **Default salt:** `"turboSH_default_salt"` (publicly visible in source code)
- **Impact:** In production without `TURBOSH_IP_SALT` env var, all IP hashes are deterministic. The entire IPv4 space (~4.3B addresses) can be rainbow-tabled in minutes. IP anonymization is effectively non-existent.

### 4.2 — IP hash truncation increases collision risk
- **File:** `pipeline/logging/ip_extractor.go` L30
- **Code:** `hash[:8]` — only first 8 bytes (16 hex chars) of SHA-256.
- **Impact:** Birthday collision resistance drops to 2³², meaning ~65,000 distinct IPs could produce a collision. Different IPs may be treated as the same entity by the ML pipeline.

### 4.3 — Inconsistent IP extraction across security components
- **Files:**
  - `core/security/rate_limiter.go` and `traffic_rules.go` use `c.ClientIP()` (Gin's built-in)
  - `core/inference/middleware.go` and `pipeline/logging/traffic_logger.go` use `logging.GetClientIP()` (custom extractor)
- **Impact:** An attacker behind a proxy could be identified as different IPs by different middleware layers. The ML engine and logger see one IP, but the rate limiter and traffic rules see another. Security controls can be bypassed.

### 4.4 — RateLimiter `Cleanup()` is never called — unbounded memory growth
- **File:** `core/security/rate_limiter.go`
- **Issue:** `Cleanup(maxAge)` method exists but is never called anywhere — no goroutine, timer, or scheduler invokes it.
- **Impact:** The `buckets` map grows without bound as new client IPs arrive. Under a distributed attack with many source IPs, this is a memory leak that will eventually OOM the process.

### 4.5 — TrafficRules `Cleanup()` is never called — same issue
- **File:** `core/security/traffic_rules.go`
- **Same issue as 4.4.** The `ipBursts` and `endpointAbuse` maps grow unboundedly.

### 4.6 — MLProtection maps have no maximum size cap
- **File:** `core/inference/middleware.go`
- **Issue:** `requestTimes`, `endpoints`, `ipStats` maps: `prune()` only removes entries older than 60s, but under a distributed attack with many unique IPs, these maps grow unboundedly before the 60s window even starts to help.

### 4.7 — No authentication on `/metrics` endpoint
- **File:** `cmd/turbosh/main.go` L51
- **Issue:** `router.GET("/metrics", gin.WrapH(promhttp.Handler()))` — Prometheus metrics are exposed to any client with no authentication, rate limiting, or access control.
- **Impact:** Attackers can learn about internal system state, queue lengths, cache hit rates, and ML decision distributions.

### 4.8 — No TLS/HTTPS configuration
- **Impact:** All traffic between clients, the proxy, and the backend is plaintext HTTP. No TLS termination is configured anywhere.

### 4.9 — Proxy error handler ignores `Write` error
- **File:** `core/proxy/proxy.go` L32
- **Code:** `w.Write([]byte(...))` — error from `Write` is silently ignored.

### 4.10 — X-Forwarded-For uses ips[0] which can be attacker-controlled
- **File:** `pipeline/logging/ip_extractor.go` L47
- **Issue:** When a trusted proxy is detected, `ips[0]` from `X-Forwarded-For` is used. An attacker can inject `X-Forwarded-For: spoofed-ip` and the proxy appends the real IP, making the header `spoofed-ip, real-ip`. The code picks `ips[0]` (the spoofed one).
- **Fix:** Use the rightmost untrusted IP (ips[len(ips)-1] before the trusted proxy hop).

### 4.11 — Docker container runs as root
- **File:** `Dockerfile 2.51.50 PM`
- **Issue:** No `USER` directive. The container runs as root.

### 4.12 — Global mutable state for IP salt
- **File:** `pipeline/logging/ip_extractor.go` L15-23
- **Issue:** `ipSalt` is a package-level var set in `init()`. Cannot be updated per-tenant or at runtime.

---

## 5. Logical Flaws

### 5.1 — `NewThresholdPolicy` treats 0.0 as "use default"
- **File:** `core/decision/decision_engine.go` L51-56
- **Code:** `if blockThreshold == 0 { blockThreshold = 0.85 }`
- **Issue:** `0.0` is a valid threshold meaning "block everything." Using `== 0` to detect "not provided" silently overrides intentional zero values.
- **Fix:** Use pointer types (`*float64`) or a sentinel value like `-1`.

### 5.2 — Shannon entropy implementations are incompatible between Python and Go
- **Python** (`feature_extractor.py` L88-89): Entropy is **normalized** (divided by `log2(num_endpoints)`) to the range [0.0, 1.0].
- **Go** (`features.go` L46-66): Returns **raw** (unnormalized) Shannon entropy.
- **Impact:** Training data uses normalized entropy, but inference uses raw entropy. The model was trained on a different feature distribution than what it sees in production.

### 5.3 — Latency spike thresholds differ between Python and Go
- **Python** (`feature_extractor.py` L138): Spike threshold = `max(latency_baseline * 3, 500.0)` (3x baseline, minimum 500ms).
- **Go** (`inference/middleware.go` L169): Spike threshold = `avgLatency * 1.5` AND `> 100.0` (1.5x average, minimum 100ms).
- **Impact:** A latency of 200ms would be a spike in Go (200 > 100 and 200 > avg * 1.5) but not in Python (200 < 500). Features extracted at training time vs inference time are computed differently.

### 5.4 — Synthetic data entropy range doesn't match any extractor
- **File:** `ml/data/generate_synthetic_data.py` L37
- **Normal traffic entropy:** `np.random.normal(1.5, 0.5)` clipped to [0.0, 3.0].
- **Python feature extractor** normalizes entropy to [0.0, 1.0].
- **Go inference** computes raw entropy (can be > 1.0).
- **Impact:** The model was trained on entropy values centered around 1.5, but real normal traffic (via normalized Python extraction) would have entropy ≤ 1.0, causing massive false positives. Via Go's raw extraction, the domain might roughly match, but the distributions are still different.

### 5.5 — Decision Engine uses `>` instead of `>=`
- **File:** `core/decision/decision_engine.go` L68
- **Code:** `if prediction.AnomalyScore > tp.BlockThreshold`
- **Issue:** With a threshold of 0.85, a score of exactly 0.85 falls through to RATE_LIMIT, not BLOCK. The architecture says `score > 0.85` → BLOCK, which is consistent, but `score > 0.65` → RATE_LIMIT means a score of exactly 0.65 falls through to ALLOW. Whether this is intentional is unclear.

### 5.6 — `Scheduler` uses channel semaphore which doesn't guarantee FIFO
- **File:** `core/scheduler/scheduler.go`
- **Issue:** Go channel `select` does not guarantee FIFO ordering among blocked goroutines. Under heavy load, some requests may be starved while others proceed.

### 5.7 — Missing `Host` header rewrite in reverse proxy
- **File:** `core/proxy/proxy.go`
- **Issue:** `httputil.NewSingleHostReverseProxy` does not rewrite `req.Host` to the target host by default. If the backend uses virtual hosting, requests will be routed incorrectly.

---

## 6. Integration Issues

### 6.1 — Double metrics middleware registration
- **File:** `cmd/turbosh/main.go` L52 and `core/proxy/middleware.go` L121
- **Flow:**
  1. `main.go` L52: `router.Use(monitoring.MetricsMiddleware())` — imports from root `monitoring` package.
  2. `main.go` L63: `proxy.SetupMiddleware(router, components)` → `middleware.go` L121: `router.Use(monitoring.MetricsMiddleware())` — imports from `pipeline/monitoring` package.
- **Impact:** Every request passes through TWO metrics middleware handlers from two different packages. Metrics are double-counted.

### 6.2 — Two `monitoring` packages with conflicting Prometheus registrations
- **Root `monitoring/metrics.go`:** Defines `turbosh_requests_total` with label `status` using `prometheus.NewCounterVec`.
- **`pipeline/monitoring/metrics.go`:** Defines `turbosh_requests_total` with labels `method, status` using `promauto.NewCounterVec`.
- **Impact:** Both register with the default Prometheus registry. Registering the same metric name with different label sets causes a **runtime panic** on startup.

### 6.3 — Overlapping metric names with different schemas
- Root `monitoring`: `turbosh_cache_hits_total`, `turbosh_cache_misses_total` (simple counters)
- Pipeline `monitoring`: `turbosh_cache_operations_total` with label `result` (counter vec)
- Root: `turbosh_scheduler_active` (gauge) / `turbosh_scheduler_capacity` (gauge)
- Pipeline: `turbosh_scheduler_active_requests` (gauge) / `turbosh_scheduler_waiting_requests` (gauge)
- **Grafana dashboard** references `turbosh_scheduler_active` and `turbosh_scheduler_capacity` but the pipeline registers `turbosh_scheduler_active_requests`.
- **Impact:** Grafana panels show no data because the metric names don't match.

### 6.4 — Import path confusion across packages
- `core/proxy/middleware.go` imports `pipeline/monitoring` for metrics.
- `core/inference/middleware.go` imports root `monitoring` for `RecordMLBlock`, `RecordMLThrottle`, `RecordMLAllow`.
- `core/cache/cache_middleware.go` imports `pipeline/monitoring` for `CacheOps`.
- **Impact:** Two different metric packages are used interchangeably. Functions that exist in one package are called from the other's import context.

### 6.5 — `build_dataset.py` output is ignored by `train_model.py`
- `pipeline/dataset_builder/build_dataset.py` produces `datasets/traffic_dataset.csv`.
- `ml/training/train_model.py` L16 loads `datasets/synthetic_traffic_dataset.csv`.
- **Impact:** The real data pipeline (`logs → features → labeled dataset`) is never connected to model training. Training uses only synthetic data.

### 6.6 — `export_onnx.py` hardcodes `best_isolationforest.pkl`
- **File:** `ml/export/export_onnx.py` L8
- **Issue:** `train_model.py` L127 saves the best model as `best_{model_name}.pkl` (e.g., `best_oneclasssvm.pkl`). But the export script hardcodes `best_isolationforest.pkl`.
- **Impact:** If OneClassSVM or LOF wins the GridSearch, the export script loads the wrong (or missing) model file.

### 6.7 — `middleware.go` hardcodes thresholds instead of using config
- **File:** `core/proxy/middleware.go` L68
- **Code:** `decision.NewThresholdPolicy(0.85, 0.65)` — hardcoded.
- **Config has:** `cfg.BlockThreshold` and `cfg.RateLimitThreshold` (loaded from env vars).
- **Impact:** Environment variable overrides for `TURBOSH_BLOCK_THRESHOLD` and `TURBOSH_RATE_LIMIT_THRESHOLD` are silently ignored.

### 6.8 — `middleware.go` hardcodes model path
- **File:** `core/proxy/middleware.go` L65
- **Code:** `modelPath := "models/anomaly_model.onnx"` — hardcoded.
- **Impact:** No way to configure the model path via environment variables.

---

## 7. Concurrency & Resource Leaks

### 7.1 — No graceful shutdown in `main.go`
- **File:** `cmd/turbosh/main.go`
- **Issue:** `router.Run()` blocks until termination. No `http.Server` with signal handling (`SIGTERM`, `SIGINT`). On container restart:
  - `TrafficLogger.Close()` is never called → buffered logs lost.
  - `inference.Destroy()` is never called → ONNX runtime resources leaked.
  - `CacheStop` channel is never closed → TTL manager goroutine leaked.
  - Background gauge poller goroutine runs forever with no stop mechanism.

### 7.2 — Background gauge poller goroutine leaks
- **File:** `core/proxy/middleware.go` L90-96
- **Code:**
  ```go
  go func() {
      for {
          monitoring.SchedulerActive.Set(...)
          monitoring.SchedulerWaiting.Set(...)
          time.Sleep(1 * time.Second)
      }
  }()
  ```
- **Issue:** No stop channel, no context cancellation. This goroutine runs forever even if the server shuts down.

### 7.3 — `CacheStop` channel is never used in `main.go`
- **File:** `core/proxy/middleware.go` L32 defines `CacheStop chan struct{}`.
- **File:** `cmd/turbosh/main.go` — never calls `close(components.CacheStop)`.
- **Impact:** TTL manager goroutine leaks on shutdown.

### 7.4 — HTTP client re-instantiation causes socket exhaustion in test tools
- **Files:** `cmd/attacker/main.go` L36, `cmd/loadtest/main.go` L40, `cmd/accuracy_test/main.go` L22
- **Issue:** `client := &http.Client{Timeout: ...}` is created inside each request function. Each new client creates a new `http.Transport`, bypassing connection pooling. Under high concurrency (500 goroutines in loadtest), this exhausts ephemeral ports and file descriptors.

### 7.5 — Response bodies not drained before closing in test tools
- **Files:** All `cmd/*/main.go` files
- **Issue:** `resp.Body.Close()` is called without `io.Copy(io.Discard, resp.Body)`. The underlying TCP connection cannot be reused by the transport pool.

### 7.6 — `LRUCache.Get()` has lock escalation pattern
- **File:** `core/cache/lru_cache.go`
- **Issue:** `Get()` acquires `RLock`, releases it, then acquires `Lock` for `MoveToFront`. Under read-heavy workloads, this double-lock pattern creates contention and TOCTOU windows.

### 7.7 — Timer allocation overhead in scheduler
- **File:** `core/scheduler/scheduler.go` L34
- **Issue:** `time.NewTimer(s.timeout)` is allocated per request. Under high throughput, this creates significant GC pressure.

---

## 8. ML Pipeline Mismatches

### 8.1 — Training data never comes from real traffic
- **Pipeline as designed:** `traffic.jsonl` → `feature_extractor.py` → `features.csv` → `build_dataset.py` → `traffic_dataset.csv` → `train_model.py`
- **Actual pipeline:** `generate_synthetic_data.py` → `synthetic_traffic_dataset.csv` → `train_model.py`
- **Impact:** The ML model has never seen real traffic patterns.

### 8.2 — ONNX export hardcodes 6 input features
- **File:** `ml/export/export_onnx.py` L24
- **Issue:** Hardcodes `initial_types` with 6 float features. If the feature set changes, this breaks silently.

### 8.3 — Go inference engine hardcodes ONNX tensor names
- **File:** `core/inference/inference.go`
- **Issue:** Input and output tensor names are hardcoded. If the ONNX model is exported with different names, inference fails.

### 8.4 — Predict test is commented out
- **File:** `core/inference/inference_test.go`
- **Issue:** The actual `Predict` test is commented out. Only `ShannonEntropy` is tested.

### 8.5 — `feature_extractor.py` has dead code
- **File:** `pipeline/feature_extraction/feature_extractor.py` L100-108
- **Function:** `compute_inter_arrival_times()` is defined but never called.

---

## 9. Monitoring & Metrics Conflicts

### 9.1 — Grafana dashboard queries reference wrong metric names
- **Dashboard file:** `monitoring/grafana/dashboards/turbosh.json`
- **Issues:**
  - **Latency panel** (L35-45): Queries `turbosh_request_duration_seconds_bucket` — this metric does not exist. Root `monitoring` defines `turbosh_request_duration_ms` (histogram). Pipeline `monitoring` defines `turbosh_request_latency_ms`. Neither uses `_seconds`.
  - **Cache panels** (L64, L91-96): Query `turbosh_cache_hits_total` and `turbosh_cache_misses_total` — these are from root `monitoring`. Pipeline `monitoring` uses `turbosh_cache_operations_total{result="hit"}`.
  - **Scheduler panel** (L115): Queries `turbosh_scheduler_active` / `turbosh_scheduler_capacity` — root `monitoring` names. Pipeline uses `turbosh_scheduler_active_requests`.
  - **ML panels** (L142-154): Query `turbosh_ml_blocks_total`, `turbosh_ml_throttles_total`, `turbosh_ml_allows_total` — these are from root `monitoring`. Pipeline `monitoring` uses `turbosh_anomaly_alerts_total{action="..."}`.
- **Impact:** At least half the Grafana dashboard panels show no data due to metric name mismatches.

### 9.2 — Duplicate Grafana provisioning configs
- **Files:** `monitoring/grafana/provisioning/dashboards/dashboards.yaml` AND `dashboards.yml`
- **Issue:** Both exist with conflicting settings (`foldersFromFilesStructure: true` vs `false`). Grafana loads all `.yaml`/`.yml` files, creating duplicate providers.

### 9.3 — Duplicate Grafana datasource configs
- **Files:** `monitoring/grafana/provisioning/datasources/prometheus.yaml` AND `prometheus.yml`
- **Issue:** One sets `editable: true`, the other `editable: false`. Duplicate datasource registration on startup.

### 9.4 — Duplicate Prometheus config files
- **Files:** `monitoring/prometheus.yml` AND `monitoring/prometheus/prometheus.yml`
- **Issue:** `docker-compose.yml` mounts `monitoring/prometheus.yml`, but a second copy exists at `monitoring/prometheus/prometheus.yml` with slightly different content (`metrics_path` specified vs not).

---

## 10. Docker & Deployment Issues

### 10.1 — Dockerfile backend URL default doesn't match config
- **Dockerfile** L49: `ENV TURBOSH_BACKEND="http://localhost:9090"`
- **`config.go`** default: `"http://localhost:9092"`
- **`dummy_backend/main.go`** listens on: `:9092`
- **Impact:** Docker container points to wrong port by default.

### 10.2 — Dockerfile uses hardcoded x86_64 architecture
- **Dockerfile** L10: Downloads `onnxruntime-linux-x64-1.17.1.tgz`
- **Dockerfile** L25: Compiles with `GOARCH=amd64`
- **Impact:** Cannot build or run on ARM64 hosts (Apple Silicon Macs, ARM EC2 instances).

### 10.3 — `docker-compose.yml` requires mandatory env var
- **Line 19:** `${GRAFANA_ADMIN_PASSWORD:?Set GRAFANA_ADMIN_PASSWORD in .env}`
- **Impact:** `docker-compose up` fails immediately without a `.env` file. No `.env.example` is provided.

### 10.4 — `docker-compose.yml` missing turboSH and backend services
- **Issue:** Only defines Prometheus and Grafana services. Does not include `turbosh` proxy or `dummy_backend` services.
- **Impact:** Users cannot spin up the full stack with `docker-compose up`.

### 10.5 — `.dockerignore` doesn't ignore large files
- **Issue:** Does not ignore `datasets/`, `notebooks/`, `models/`, or `*.csv`. Docker build context includes potentially hundreds of MB of CSV data files.

### 10.6 — `localhost` in Docker container doesn't reach host
- **Dockerfile** L49: `TURBOSH_BACKEND="http://localhost:9090"` — inside a container, `localhost` refers to the container itself, not the host machine.

---

## 11. Documentation Inconsistencies

### 11.1 — `ANZAL.md` refers to project as "SentinelEdge" and developer as "Kevin"
- **File:** `docs/ANZAL.md` L3: "SentinelEdge"
- **File:** `docs/ANZAL.md` L7: "Kevin" (should be "Keshav")
- **Impact:** Project name inconsistency. Developer name mismatch.

### 11.2 — `PLAYBOOK.md` default backend URL is wrong
- **Line 58:** Lists `TURBOSH_BACKEND` default as `http://localhost:9090`.
- **`config.go`** actual default: `http://localhost:9092`.

### 11.3 — `README.md` Docker build command will fail
- **Line 26:** `docker build -t turbosh-proxy .` — Dockerfile has the wrong filename.

### 11.4 — `README.md` Windows activation script casing
- **Line 98:** `.venv/Scripts/Activate` — capital `A`. Standard Windows uses lowercase `activate`.

### 11.5 — `README.md` architecture diagram doesn't match implementation
- **Line 43:** Shows `Client → Reverse Proxy → Scheduler → Cache → Traffic Logger` → ML. Actual order has ML before Cache.

### 11.6 — `API.md` shows undecided architecture choice
- **Section 2:** "Two possible architectures. The chosen approach will be documented here once decided." — Still lists both FastAPI and ONNX options. Should document the chosen ONNX approach.

### 11.7 — `AGENT.md` lists status as "Phase 1" but system is fully implemented
- **Line under Current Status:** "Phase: 1 — Project Foundation & Documentation" — outdated.

### 11.8 — `DATA_SCHEMA.md` and `log_schema.md` don't mention salted hashing
- Only say "SHA-256 hash of client IP" without mentioning the salt or truncation to 16 hex chars.

### 11.9 — `ANZAL.md` specifies `user_agent_hash` and `server_latency` fields not in actual schema
- The log entry example in `ANZAL.md` includes fields (`user_agent_hash`, `server_latency`, `response_time_ms`) that don't exist in the actual `TrafficLogEntry` struct.

### 11.10 — `PLAN.md` references `pipeline/feature_extractor.py` not `pipeline/feature_extraction/feature_extractor.py`
- **Story 4.2 Deliverables:** Lists `/pipeline/feature_extractor.py` — actual location is `pipeline/feature_extraction/feature_extractor.py`.

### 11.11 — `KESHAV.md` references `/core/cache/cache_manager.go`
- **Part 4 Deliverables:** Lists `/core/cache/cache_manager.go` — this file does not exist. Actual files are `cache.go`, `lru_cache.go`, etc.

---

## 12. Test & Tooling Issues

### 12.1 — `accuracy_test` treats 503 as "allowed"
- **File:** `cmd/accuracy_test/main.go` L118
- **Code:** `blocked := r.StatusCode == 403 || r.StatusCode == 429`
- **Issue:** 503 (Service Unavailable from scheduler queue full) is not counted as "blocked." Under DDoS load, many attack requests may receive 503 and be counted as False Negatives (missed attacks), making detection rates appear artificially low.

### 12.2 — All test tools use hardcoded `localhost:8080`
- **Files:** `cmd/attacker/main.go` L10, `cmd/loadtest/main.go` L15, `cmd/accuracy_test/main.go` L13
- **Impact:** Cannot test against non-local environments without modifying source code.

### 12.3 — `dummy_backend` has no server timeouts
- **File:** `cmd/dummy_backend/main.go` L29
- **Code:** `http.ListenAndServe(":9092", nil)` — no `ReadTimeout`, `WriteTimeout`, or `IdleTimeout`.
- **Impact:** Susceptible to slowloris and hung connection attacks during testing.

### 12.4 — `dummy_backend` port is hardcoded
- **File:** `cmd/dummy_backend/main.go` L28
- **Impact:** Cannot run multiple instances or configure via env var.

### 12.5 — `lru_cache_test.go` directly accesses `cache.mu` and `cache.items`
- **File:** `core/cache/lru_cache_test.go` L113-115
- **Code:** `cache.mu.RLock()` then `cache.items["expire-soon"]`
- **Issue:** Tests access unexported fields, which is only possible because they're in the same package. This couples tests to implementation details.

### 12.6 — `loadtest` does not create output directory
- **File:** `cmd/loadtest/main.go` L330
- **Code:** `os.WriteFile("docs/benchmark_report.md", ...)` — doesn't call `os.MkdirAll("docs/", ...)` first.
- **Impact:** Fails if run from a directory without a `docs/` subdirectory.

---

## 13. Code Quality & Typos

### 13.1 — `.gitignore` has syntax error on line 2
- **File:** `.gitignore` L2
- **Content:** ` ============================================` (no `#` prefix)
- **Impact:** Git interprets this as an active ignore pattern rather than a comment.

### 13.2 — `cache_demo/main.go` has duplicate section numbers
- **File:** `core/cache/cmd/cache_demo/main.go` L40 and L45
- **Content:** Both say `// ---------- 3.` — should be 3 and 4.

### 13.3 — Dead comment/function stub in `traffic_logger.go`
- **File:** `pipeline/logging/traffic_logger.go` L88
- **Content:** `// dirOf returns the directory portion of a file path.` — no implementation follows.
- **File:** `pipeline/logging/traffic_logger.go` L188
- **Content:** `// ---------- helpers ----------` — empty section at end of file.

### 13.4 — Comment says "removed flush" but no periodic flush was added
- **File:** `pipeline/logging/traffic_logger.go` L156
- **Comment:** `// Removed: tl.writer.Flush() - logs are now flushed periodically or on close`
- **Issue:** No periodic flush goroutine or ticker was ever created. Up to 4KB of log data can be lost.

### 13.5 — `Close()` swallows file close error
- **File:** `pipeline/logging/traffic_logger.go` L181-184
- **Issue:** If `Flush()` fails, `tl.file.Close()` error is discarded.

### 13.6 — `feature_extractor.py` has potential `NoneType` crash
- **File:** `pipeline/feature_extraction/feature_extractor.py` L134, L175
- **Issue:** If any log entry has `response_time: None` instead of a number, `max()` and `statistics.median()` will raise `TypeError`.

### 13.7 — `generate_synthetic_data.py` has no CLI interface
- **File:** `ml/data/generate_synthetic_data.py`
- **Issue:** No `argparse` for output path or row counts. Everything is hardcoded.

### 13.8 — `main.go` log output formatting
- **File:** `cmd/turbosh/main.go` L68
- **Code:** `log.Printf("Prometheus metrics available at %s/metrics", cfg.ListenPort)`
- **Output:** `:8080/metrics` — no scheme or host. Should be `http://localhost:8080/metrics`.

### 13.9 — `README.md` says "Go: 1.24+" but `go.mod` says `1.25.0`
- Inconsistency between prerequisite documentation and module definition.

### 13.10 — `ANZAL.md` deliverable paths don't match actual structure
- Lists `/pipeline/log_parser.py` — does not exist.
- Lists `/pipeline/feature_extractor.py` — actual path is `pipeline/feature_extraction/feature_extractor.py`.
- Lists `/pipeline/dataset_builder.py` — actual path is `pipeline/dataset_builder/build_dataset.py`.

### 13.11 — `LRUCache.Set()` does shallow copy of `CachedResponse`
- **File:** `core/cache/lru_cache.go` L123
- **Code:** `valCopy := *value` — shallow struct copy. `Headers` map and `Body` slice still reference the original data. Concurrent modifications to the original will corrupt the cached copy.

### 13.12 — Unused imports and blank identifier suppression in `accuracy_test`
- **File:** `cmd/accuracy_test/main.go` L187-188, L199-200
- **Code:** `_ = ntp; _ = nfn` — computed metrics are thrown away rather than being used in the report.

---

## Summary Statistics

| Category | Count |
|:---|---:|
| Critical Build-Breaking | 3 |
| Architecture Mismatches | 7 |
| Critical Bugs | 6 |
| Security Vulnerabilities | 12 |
| Logical Flaws | 7 |
| Integration Issues | 8 |
| Concurrency & Resource Leaks | 7 |
| ML Pipeline Mismatches | 5 |
| Monitoring & Metrics Conflicts | 4 |
| Docker & Deployment Issues | 6 |
| Documentation Inconsistencies | 11 |
| Test & Tooling Issues | 6 |
| Code Quality & Typos | 12 |
| **Total** | **94** |
