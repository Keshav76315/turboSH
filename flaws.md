# turboSH — Exhaustive Flaw Analysis & Technical Audit

> **Scope:** Every source file, configuration, script, and documentation in the repository, verified against [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).  
> **Status:** Audited & Updated (2026-09-03)

---

## Table of Contents

1. [Resolved Items](#1-resolved-items)
2. [Retracted / False Positive Claims](#2-retracted--false-positive-claims)
3. [Critical Runtime Bugs & Panics](#3-critical-runtime-bugs--panics)
4. [Architecture & Pipeline Disconnects](#4-architecture--pipeline-disconnects)
5. [Security & Privacy Vulnerabilities](#5-security--privacy-vulnerabilities)
6. [Mathematical & ML Feature Inconsistencies](#6-mathematical--ml-feature-inconsistencies)
7. [Memory Leaks & Concurrency Issues](#7-memory-leaks--concurrency-issues)
8. [Monitoring, Metrics & Grafana Conflicts](#8-monitoring-metrics--grafana-conflicts)
9. [Cache & Resource Management Flaws](#9-cache--resource-management-flaws)
10. [Docker, Deployment & Network Issues](#10-docker-deployment--network-issues)
11. [Test & Tooling Flaws](#11-test--tooling-flaws)
12. [Documentation & Code Quality Deficiencies](#12-documentation--code-quality-deficiencies)
13. [Audit Summary Statistics](#13-audit-summary-statistics)

---

## 1. Resolved Items

The following issues have been addressed and verified in the codebase:

- ✅ **Fixed:** `config/config 2.51.45 PM.go` restored to [`config/config.go`](config/config.go).
- ✅ **Fixed:** `Dockerfile 2.51.50 PM` restored to [`Dockerfile`](Dockerfile).
- ✅ **Verified:** [`go.mod`](go.mod) and dependencies tidied via `go mod tidy`. `go build ./...` and `go test ./...` pass cleanly.

---

## 2. Retracted / False Positive Claims

The following items from the initial audit were verified as **false positives or misunderstandings** of the system mechanics:

1. **Claim: "`go 1.25.0` does not exist"**
   - _Status:_ **Retracted.** The local environment runs Go 1.26, and Go 1.25 is fully supported by the Go toolchain.
2. **Claim: "Singleflight winners should execute `c.Next()` for all waiter goroutines"**
   - _Status:_ **Retracted.** `c.Next()` executes the downstream backend proxy. Invoking `c.Next()` for waiters would trigger duplicate backend requests, defeating singleflight cache-stampede collapse. (The true issue is the relative ordering of Cache vs Traffic Logger).
3. **Claim: "`docs/ANZAL.md` references SentinelEdge and Kevin"**
   - _Status:_ **Retracted.** `docs/ANZAL.md` does not exist in the repository tree.
4. **Claim: "`docker-compose.yml` fails without `.env`"**
   - _Status:_ **Retracted.** A default [`.env`](.env) file is committed in the root repository.
5. **Claim: "Decision Engine uses `>` instead of `>=`"**
   - _Status:_ **Retracted.** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#L40) specifies `score > 0.85` and `score > 0.65`. The implementation adheres to the architectural specification.

---

## 3. Critical Runtime Bugs & Panics

### 3.1 — `string(rune(status))` produces corrupted Unicode glyphs in Prometheus metrics

- **File:** [`pipeline/monitoring/metrics.go:L63`](pipeline/monitoring/metrics.go#L63)
- **Code:** `RequestsTotal.WithLabelValues(method, string(rune(status))).Inc()`
- **Bug:** `rune(200)` converts integer HTTP 200 to Unicode character `È` (`U+00C8`). Status 404 converts to `ǔ`, and 500 converts to `Ǵ`.
- **Impact:** Corrupts metric labels in Prometheus, breaking PromQL queries and Grafana dashboards.
- **Fix:** Replace `string(rune(status))` with `strconv.Itoa(status)`.

### 3.2 — Dual Prometheus metric registrations cause runtime panic on startup

- **Files:** [`monitoring/metrics.go:L12`](monitoring/metrics.go#L12) and [`pipeline/monitoring/metrics.go:L13`](pipeline/monitoring/metrics.go#L13)
- **Bug:** Both packages define `turbosh_requests_total` with incompatible label schemas (`["status"]` vs `["method", "status"]`).
- **Impact:** Calling `monitoring.Register()` while importing `pipeline/monitoring` causes a runtime panic on `prometheus.DefaultRegisterer` initialization.
- **Fix:** Consolidate metric definitions into a single monitoring package.

### 3.3 — `NormalizeScore()` returns binary 0.0/1.0, rendering `RATE_LIMIT` action unreachable

- **File:** [`core/inference/features.go:L37-L41`](core/inference/features.go#L37-L41)
- **Code:** Returns `1.0` if `rawScore == -1`, else `0.0`.
- **Impact:** Decision Engine thresholds (`block > 0.85`, `rate_limit > 0.65`) only receive 0.0 or 1.0. The intermediate `RATE_LIMIT` tier is completely unreachable, collapsing the three-tier defense into binary allow/block.
- **Fix:** Extract continuous decision-function output or anomaly probabilities from the ONNX session.

### 3.4 — `cmd/loadtest/main.go` nil pointer dereference panic

- **File:** [`cmd/loadtest/main.go:L41-L47`](cmd/loadtest/main.go#L41-L47)
- **Code:** `resp, requestErr := client.Do(req)` executes even if `http.NewRequest` returns an error (`req == nil`).
- **Impact:** Panics with nil pointer dereference on invalid URL paths or request creation errors.
- **Fix:** Check `if err != nil { return Result{Err: err} }` before calling `client.Do`.

### 3.5 — Integer truncation of sub-millisecond request latencies

- **File:** [`pipeline/monitoring/metrics.go:L59`](pipeline/monitoring/metrics.go#L59)
- **Code:** `elapsed := float64(time.Since(start).Milliseconds())`
- **Impact:** Cached responses and sub-millisecond proxy round-trips are recorded as `0.0 ms`, distorting latency histograms.
- **Fix:** Use `float64(time.Since(start).Microseconds()) / 1000.0` or `time.Since(start).Seconds()`.

---

## 4. Architecture & Pipeline Disconnects

### 4.1 — Middleware execution order contradicts system architecture

- **Architecture §2:** Client → Proxy → Scheduler → Cache → Traffic Logger → Feature Extraction → ML Inference → Decision Engine
- **Implementation:** [`core/proxy/middleware.go:L114-L153`](core/proxy/middleware.go#L114-L153) sets order: `Metrics → Scheduler → RateLimiter → TrafficRules → ML Inference → Cache → Traffic Logger → Proxy`.
- **Impact:** ML evaluation occurs prior to the Cache layer. While this allows the ML engine to observe all raw requests, it deviates from the documented pipeline flow.

### 4.2 — Cache hits bypass Traffic Logger and ML backend feedback

- **Files:** [`core/proxy/middleware.go:L144-L152`](core/proxy/middleware.go#L144-L152) and [`core/cache/cache_middleware.go:L131`](core/cache/cache_middleware.go#L131)
- **Issue:** `CacheMiddleware` short-circuits on cache hits with `serveCachedResponse(c, cachedResp); return`. Because `TrafficLogger` is registered _after_ `Cache`, all cache hits are invisible to the traffic logger and never written to `traffic.jsonl`.
- **Impact:** Log datasets are biased, missing all cache-hit traffic.

### 4.3 — Implemented Priority Queue is dead code

- **Files:** [`core/scheduler/queue.go`](core/scheduler/queue.go) vs [`core/scheduler/scheduler.go`](core/scheduler/scheduler.go)
- **Issue:** A heap-based `PriorityQueue` with client reputation weighting exists in `queue.go`, but `scheduler.go` relies solely on a simple buffered-channel semaphore.
- **Impact:** Priority scheduling described in Architecture §3.2 is non-functional.

### 4.4 — Offline training dataset ignored by model training

- **Files:** [`pipeline/dataset_builder/build_dataset.py`](pipeline/dataset_builder/build_dataset.py) vs [`ml/training/train_model.py:L16`](ml/training/train_model.py#L16)
- **Issue:** `build_dataset.py` generates `datasets/traffic_dataset.csv` from real logs, but `train_model.py` hardcodes `datasets/synthetic_traffic_dataset.csv`.
- **Impact:** Production models are trained solely on synthetic distributions and never on observed traffic logs.

### 4.5 — ONNX export script hardcodes Isolation Forest model path

- **File:** [`ml/export/export_onnx.py:L8`](ml/export/export_onnx.py#L8)
- **Issue:** `MODEL_PATH = "models/best_isolationforest.pkl"`. If `train_model.py` selects `OneClassSVM` or `LocalOutlierFactor` as the best estimator, the export script fails or exports an obsolete model.

### 4.6 — Missing `core/inference/` from architecture module ownership tree

- **File:** [`docs/ARCHITECTURE.md §6`](docs/ARCHITECTURE.md#L6)
- **Issue:** The module tree lists `core/proxy/`, `core/scheduler/`, `core/cache/`, `core/security/`, and `core/decision/`, but omits `core/inference/`.

### 4.7 — Hardcoded decision thresholds and model path in proxy setup

- **File:** [`core/proxy/middleware.go:L65-L68`](core/proxy/middleware.go#L65-L68)
- **Issue:** `modelPath := "models/anomaly_model.onnx"` and `decision.NewThresholdPolicy(0.85, 0.65)` are hardcoded, ignoring `cfg.BlockThreshold` and `cfg.RateLimitThreshold`.

---

## 5. Security & Privacy Vulnerabilities

### 5.1 — Hardcoded fallback IP salt for PII hashing

- **File:** [`pipeline/logging/ip_extractor.go:L19-L21`](pipeline/logging/ip_extractor.go#L19-L21)
- **Default salt:** `"turboSH_default_salt"`
- **Impact:** Without `TURBOSH_IP_SALT`, all client IP hashes are deterministic and vulnerable to precomputed rainbow-table attacks across the IPv4 space.

### 5.2 — Truncated 8-byte IP hash increases collision probability

- **File:** [`pipeline/logging/ip_extractor.go:L30`](pipeline/logging/ip_extractor.go#L30)
- **Code:** `hex.EncodeToString(hash[:8])`
- **Impact:** Truncation to 64 bits reduces birthday collision resistance to ~2³² (~65,000 distinct IPs), risking distinct clients colliding into the same ML bucket.

### 5.3 — Inconsistent client IP extraction between security modules

- **Files:** [`core/security/rate_limiter.go:L83`](core/security/rate_limiter.go#L83), [`core/security/traffic_rules.go:L109`](core/security/traffic_rules.go#L109) vs [`core/inference/middleware.go:L202`](core/inference/middleware.go#L202)
- **Issue:** Security middlewares use Gin's `c.ClientIP()`, while ML and logging middlewares use `logging.GetClientIP(r, cfg)`.
- **Impact:** If upstream proxy configurations differ, rate limiters and anomaly detection track different IP strings for the same client.

### 5.4 — Client-controlled `X-Forwarded-For` spoofing via `ips[0]`

- **File:** [`pipeline/logging/ip_extractor.go:L46-L48`](pipeline/logging/ip_extractor.go#L46-L48)
- **Code:** `strings.TrimSpace(ips[0])`
- **Impact:** An attacker prepending spoofed headers (`X-Forwarded-For: 1.1.1.1`) through a trusted reverse proxy has their spoofed IP selected rather than the verified client IP.

### 5.5 — Missing authentication and rate limiting on `/metrics` endpoint

- **File:** [`cmd/turbosh/main.go:L50`](cmd/turbosh/main.go#L50)
- **Issue:** `/metrics` is exposed publicly on the main router without authentication or IP allowlisting.
- **Impact:** Exposes internal throughput, cache statistics, and detection state to unauthorized scrapers.

### 5.6 — Lack of TLS/HTTPS termination configuration

- **Issue:** No TLS configuration is available in `cmd/turbosh/main.go` or `config/config.go`. All proxy operations assume plaintext HTTP.

### 5.7 — Unchecked `w.Write` error in reverse proxy error handler

- **File:** [`core/proxy/proxy.go:L32`](core/proxy/proxy.go#L32)
- **Code:** Error returned from `w.Write(...)` is discarded without logging or handling.

### 5.8 — Docker container runs as root user

- **File:** [`Dockerfile`](Dockerfile)
- **Issue:** Missing `USER` directive in runtime stage; container runs with root privileges.

---

## 6. Mathematical & ML Feature Inconsistencies

### 6.1 — Incompatible Shannon entropy computation between Python and Go

- **Python:** [`pipeline/feature_extraction/feature_extractor.py:L88-L89`](pipeline/feature_extraction/feature_extractor.py#L88-L89) divides entropy by $\log_2(N)$ to normalize to `[0.0, 1.0]`.
- **Go:** [`core/inference/features.go:L46-L67`](core/inference/features.go#L46-L67) computes raw unnormalized Shannon entropy.
- **Impact:** Inference receives values with a different scale and distribution than what the model observed during training.

### 6.2 — Synthetic data entropy distribution does not match any extractor

- **File:** [`ml/data/generate_synthetic_data.py:L37`](ml/data/generate_synthetic_data.py#L37)
- **Code:** `np.clip(np.random.normal(1.5, 0.5), 0.0, 3.0)`
- **Impact:** Synthetic normal traffic is centered at 1.5, whereas normalized Python features are strictly $\le 1.0$.

### 6.3 — Latency spike detection threshold divergence

- **Python:** [`pipeline/feature_extraction/feature_extractor.py:L138`](pipeline/feature_extraction/feature_extractor.py#L138) uses `max(baseline * 3, 500.0)`.
- **Go:** [`core/inference/middleware.go:L169`](core/inference/middleware.go#L169) uses `avgLatency * 1.5` and `> 100.0`.
- **Impact:** Divergent spike definitions between offline training features and real-time inference features.

### 6.4 — Batch feature extractor averages over entire log duration rather than sliding windows

- **File:** [`pipeline/feature_extraction/feature_extractor.py:L163-L166`](pipeline/feature_extraction/feature_extractor.py#L163-L166)
- **Code:** `requests_per_10s = round(total_requests / max(1, span_seconds / 10))`
- **Impact:** Bursts are smoothed out over the entire log duration. An attack sending 100 requests in 5 seconds over a 1-hour log file calculates as ~0 requests/10s.

### 6.5 — `NewThresholdPolicy` overrides valid zero thresholds

- **File:** [`core/decision/decision_engine.go:L51-L56`](core/decision/decision_engine.go#L51-L56)
- **Code:** `if blockThreshold == 0 { blockThreshold = 0.85 }`
- **Impact:** A threshold of `0.0` (block all) cannot be configured because it is mistaken for uninitialized state.

---

## 7. Memory Leaks & Concurrency Issues

### 7.1 — TTL cache manager does not decrement memory on entry expiration

- **File:** [`core/cache/ttl_manager.go:L42-L46`](core/cache/ttl_manager.go#L42-L46)
- **Code:** Expired elements are removed via `c.order.Remove(element)` and `delete(c.items, key)`, but `c.currentMemory -= entry.size` and `c.metrics.RecordEviction()` are never called.
- **Impact:** `currentMemory` permanently drifts upward, eventually triggering continuous premature LRU evictions.

### 7.2 — `RateLimiter.Cleanup()` is never invoked

- **File:** [`core/security/rate_limiter.go:L99-L109`](core/security/rate_limiter.go#L99-L109)
- **Issue:** No background ticker or caller invokes `Cleanup(maxAge)`.
- **Impact:** `rl.buckets` map grows indefinitely as new client IPs connect.

### 7.3 — `TrafficRules.Cleanup()` is never invoked

- **File:** [`core/security/traffic_rules.go:L135-L154`](core/security/traffic_rules.go#L135-L154)
- **Issue:** `tr.burstTracker` and `tr.endpointTracker` maps are never cleaned periodically, leaking memory under distributed IP scans.

### 7.4 — `MLProtection` map accumulation on abandoned IPs

- **File:** [`core/inference/middleware.go:L61-L88`](core/inference/middleware.go#L61-L88)
- **Issue:** `prune()` is only invoked for the active client IP on an incoming request. Abandoned IPs that send a single request remain in `requestTimes`, `endpoints`, and `ipStats` indefinitely.
- **Issue 2:** `endpoints[ip]` counts are never decremented or windowed, accumulating lifetime endpoint counters.

### 7.5 — Background metric poller goroutine leaks on shutdown

- **File:** [`core/proxy/middleware.go:L90-L96`](core/proxy/middleware.go#L90-L96)
- **Code:** An infinite `for { time.Sleep(1 * time.Second) }` goroutine runs without a termination channel or context.

### 7.6 — Double-locking contention in `LRUCache.Get()`

- **File:** [`core/cache/lru_cache.go:L98-L109`](core/cache/lru_cache.go#L98-L109)
- **Issue:** `Get()` acquires `RLock()`, releases it, then acquires `Lock()` to perform `MoveToFront`. Under high concurrent read load, this causes lock bouncing and extra lookups.

### 7.7 — Shallow copy in `LRUCache.Set()`

- **File:** [`core/cache/lru_cache.go:L123`](core/cache/lru_cache.go#L123)
- **Code:** `valCopy := *value` performs a shallow struct copy. `Headers` map and `Body` byte slice share backing arrays with the caller.

---

## 8. Monitoring, Metrics & Grafana Conflicts

### 8.1 — Grafana dashboard PromQL queries reference non-existent metric names

- **File:** [`monitoring/grafana/dashboards/turbosh.json`](monitoring/grafana/dashboards/turbosh.json)
- **Mismatches:**
  - Latency panel queries `turbosh_request_duration_seconds_bucket` (pipeline defines `turbosh_request_latency_ms`).
  - Cache panel queries `turbosh_cache_hits_total` (pipeline uses `turbosh_cache_operations_total{result="hit"}`).
  - Scheduler panel queries `turbosh_scheduler_active` (pipeline defines `turbosh_scheduler_active_requests`).
  - ML panel queries `turbosh_ml_blocks_total` (pipeline defines `turbosh_anomaly_alerts_total{action="block"}`).
- **Impact:** Grafana dashboard panels fail to render data.

### 8.2 — Duplicate Grafana dashboard provisioning files

- **Files:** [`monitoring/grafana/provisioning/dashboards/dashboards.yaml`](monitoring/grafana/provisioning/dashboards/dashboards.yaml) and [`dashboards.yml`](monitoring/grafana/provisioning/dashboards/dashboards.yml)
- **Issue:** Both files configure the dashboard provider with conflicting settings (`foldersFromFilesStructure: true` vs `false`), causing Grafana to register duplicate dashboard providers.

### 8.3 — Duplicate Grafana datasource provisioning files

- **Files:** [`monitoring/grafana/provisioning/datasources/prometheus.yaml`](monitoring/grafana/provisioning/datasources/prometheus.yaml) and [`prometheus.yml`](monitoring/grafana/provisioning/datasources/prometheus.yml)
- **Issue:** Both files configure the Prometheus datasource with conflicting `editable` flags.

### 8.4 — Duplicate Prometheus scrape configurations

- **Files:** [`monitoring/prometheus.yml`](monitoring/prometheus.yml) and [`monitoring/prometheus/prometheus.yml`](monitoring/prometheus/prometheus.yml)
- **Issue:** Two configuration files exist with slightly different scrape targets and parameters.

---

## 9. Cache & Resource Management Flaws

### 9.1 — `CacheStop` channel never closed on application shutdown

- **Files:** [`core/proxy/middleware.go:L103`](core/proxy/middleware.go#L103) and [`cmd/turbosh/main.go`](cmd/turbosh/main.go)
- **Issue:** `components.CacheStop` channel is created by `StartTTLManager` but never closed in `main.go`.

### 9.2 — Missing graceful shutdown in `cmd/turbosh/main.go`

- **File:** [`cmd/turbosh/main.go:L69`](cmd/turbosh/main.go#L69)
- **Issue:** Server executes `router.Run(...)` directly without trapping `SIGINT`/`SIGTERM`.
- **Impact:** On termination, `TrafficLogger.Close()` is not called (losing up to 4KB buffered logs), and ONNX runtime sessions are not cleanly released via `inference.Destroy()`.

### 9.3 — Missing automatic periodic flush in `TrafficLogger`

- **File:** [`pipeline/logging/traffic_logger.go:L156`](pipeline/logging/traffic_logger.go#L156)
- **Comment:** `// Removed: tl.writer.Flush() - logs are now flushed periodically or on close`
- **Issue:** No periodic flush goroutine exists. Low-volume traffic can sit in the 4KB buffer indefinitely.

---

## 10. Docker, Deployment & Network Issues

### 10.1 — Default backend port inconsistency

- **`Dockerfile` L49:** `ENV TURBOSH_BACKEND="http://localhost:9090"`
- **`PLAYBOOK.md` L58:** Default documented as `http://localhost:9090`
- **[`config/config.go:L89`](config/config.go#L89):** Default is `"http://localhost:9092"`
- **[`cmd/dummy_backend/main.go:L28`](cmd/dummy_backend/main.go#L28):** Backend listens on `:9092`
- **Impact:** Docker container points to port 9090 by default, failing to connect to dummy backend on 9092.

### 10.2 — Dockerfile hardcodes x86_64 architecture

- **File:** [`Dockerfile`](Dockerfile)
- **Lines:** Downloads `onnxruntime-linux-x64-1.17.1.tgz` and sets `GOARCH=amd64`.
- **Impact:** Image build fails on ARM64 architectures (e.g. Apple Silicon, AWS Graviton).

### 10.3 — `.dockerignore` omits large datasets and build artifacts

- **File:** [`.dockerignore`](.dockerignore)
- **Issue:** Does not ignore `datasets/`, `models/*.pkl`, `notebooks/`, or `*.csv`, unnecessarily bloating the Docker build context.

### 10.4 — Missing `Host` header rewrite in reverse proxy

- **File:** [`core/proxy/proxy.go:L26`](core/proxy/proxy.go#L26)
- **Issue:** `httputil.NewSingleHostReverseProxy` retains the incoming client `Host` header. Upstream backends requiring virtual host matching may reject or misroute requests.

---

## 11. Test & Tooling Flaws

### 11.1 — `accuracy_test` counts HTTP 503 (Queue Full) as allowed traffic

- **File:** [`cmd/accuracy_test/main.go:L118`](cmd/accuracy_test/main.go#L118)
- **Code:** `blocked := r.StatusCode == 403 || r.StatusCode == 429`
- **Impact:** HTTP 503 responses returned when the scheduler queue is saturated are categorized as "allowed", artificially depressing detection recall during high-load attacks.

### 11.2 — Socket exhaustion from HTTP client recreation in test scripts

- **Files:** [`cmd/attacker/main.go:L36`](cmd/attacker/main.go#L36), [`cmd/loadtest/main.go:L40`](cmd/loadtest/main.go#L40), [`cmd/accuracy_test/main.go:L22`](cmd/accuracy_test/main.go#L22)
- **Issue:** A new `&http.Client{}` is instantiated per request, disabling TCP connection reuse and exhausting ephemeral ports under high concurrency.

### 11.3 — Test tools omit response body draining before close

- **Files:** All `cmd/*/main.go` test tools.
- **Issue:** `resp.Body.Close()` is called without `io.Copy(io.Discard, resp.Body)`, preventing HTTP keep-alive connection reuse.

### 11.4 — `loadtest` fails if `docs/` directory is absent

- **File:** [`cmd/loadtest/main.go:L330`](cmd/loadtest/main.go#L330)
- **Issue:** `os.WriteFile("docs/benchmark_report.md", ...)` does not invoke `os.MkdirAll("docs", 0755)` first.

### 11.5 — Hardcoded backend server configuration in `dummy_backend`

- **File:** [`cmd/dummy_backend/main.go:L28-L29`](cmd/dummy_backend/main.go#L28-L29)
- **Issue:** Port `:9092` is hardcoded with no timeout configurations on `http.Server`.

---

## 12. Documentation & Code Quality Deficiencies

### 12.1 — `.gitignore` syntax error on line 2

- **File:** [`.gitignore:L2`](.gitignore#L2)
- **Issue:** Missing `#` prefix on comment line ` ============================================`, causing Git to treat it as an active pattern.

### 12.2 — Dead comment and stub in `traffic_logger.go`

- **File:** [`pipeline/logging/traffic_logger.go:L88`](pipeline/logging/traffic_logger.go#L88)
- **Content:** `// dirOf returns the directory portion of a file path.` with no implementation.

### 12.3 — Undecided architecture options in `API.md`

- **File:** [`docs/API.md §2`](docs/API.md#L2)
- **Issue:** Retains unresolved notes ("Two possible architectures... once decided") rather than documenting the finalized ONNX CGO architecture.

### 12.4 — Outdated status in `AGENT.md`

- **File:** [`docs/AGENT.md`](docs/AGENT.md)
- **Issue:** Lists project status as "Phase 1" despite all components being implemented.

### 12.5 — Missing CLI arguments for `generate_synthetic_data.py`

- **File:** [`ml/data/generate_synthetic_data.py`](ml/data/generate_synthetic_data.py)
- **Issue:** Hardcoded row counts and file paths without `argparse` support.

---

## 13. Audit Summary Statistics

| Category                                      | Verified Count |
| :-------------------------------------------- | :------------: |
| **Resolved Issues**                           |       3        |
| **Retracted / False Positives**               |       5        |
| **Critical Runtime Bugs & Panics**            |       5        |
| **Architecture & Pipeline Disconnects**       |       7        |
| **Security & Privacy Vulnerabilities**        |       8        |
| **Mathematical & ML Feature Inconsistencies** |       5        |
| **Memory Leaks & Concurrency Issues**         |       7        |
| **Monitoring, Metrics & Grafana Conflicts**   |       4        |
| **Cache & Resource Management Flaws**         |       3        |
| **Docker, Deployment & Network Issues**       |       4        |
| **Test & Tooling Flaws**                      |       5        |
| **Documentation & Code Quality Deficiencies** |       5        |
| **Total Active Verified Flaws**               |     **53**     |
