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
13. [SIH (Smart India Hackathon) Alignment & Deficiencies](#13-sih-smart-india-hackathon-alignment--deficiencies)
14. [Audit Summary Statistics](#14-audit-summary-statistics)

---

## 1. Resolved Items

The following issues have been addressed and verified in the codebase:

- ✅ **Fixed:** `config/config 2.51.45 PM.go` restored to [`config/config.go`](config/config.go).
- ✅ **Fixed:** `Dockerfile 2.51.50 PM` restored to [`Dockerfile`](Dockerfile).
- ✅ **Verified:** [`go.mod`](go.mod) and dependencies tidied via `go mod tidy`. `go build ./...` and `go test ./...` pass cleanly.
- ✅ **Closed (Section 3):** Critical Runtime Bugs & Panics (§3.1 – §3.5 fixed and verified).
- ✅ **Closed (Section 4):** Architecture & Pipeline Disconnects (§4.1 – §4.7 fixed, verified, and reconciled).
- ✅ **Closed (Section 5):** Security & Privacy Vulnerabilities (§5.1 – §5.8 fixed, audited, and tested).
- ✅ **Closed (Section 6):** Mathematical & ML Feature Inconsistencies (§6.1 – §6.5 fixed, entropy normalized, latency spikes unified, sliding windows implemented, 0.0 threshold enabled, datasets regenerated, model retrained/exported, and unit tested).
- ✅ **Closed (Section 7):** Memory Leaks & Concurrency Issues (§7.1 – §7.7 fixed, unit tested, race-detector verified).
- ✅ **Closed (Section 8):** Monitoring, Metrics & Grafana Conflicts (§8.1 – §8.4 fixed, PromQL aligned, duplicate configs pruned, metrics consolidated).
- ✅ **Closed (Section 9):** Cache & Resource Management Flaws (§9.1 – §9.3 fixed, graceful shutdown, CacheStop closing, and automatic log flushing).

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

- **Status:** Closed
- **File:** [`pipeline/monitoring/metrics.go:L63`](pipeline/monitoring/metrics.go#L63)
- **Code:** `RequestsTotal.WithLabelValues(method, string(rune(status))).Inc()`
- **Bug:** `rune(200)` converts integer HTTP 200 to Unicode character `È` (`U+00C8`). Status 404 converts to `ǔ`, and 500 converts to `Ǵ`.
- **Impact:** Corrupts metric labels in Prometheus, breaking PromQL queries and Grafana dashboards.
- **Fix:** Replace `string(rune(status))` with `strconv.Itoa(status)`.

### 3.2 — Dual Prometheus metric registrations cause runtime panic on startup

- **Status:** Closed
- **Files:** [`monitoring/metrics.go:L12`](monitoring/metrics.go#L12) and [`pipeline/monitoring/metrics.go:L13`](pipeline/monitoring/metrics.go#L13)
- **Bug:** Both packages define `turbosh_requests_total` with incompatible label schemas (`["status"]` vs `["method", "status"]`).
- **Impact:** Calling `monitoring.Register()` while importing `pipeline/monitoring` causes a runtime panic on `prometheus.DefaultRegisterer` initialization.
- **Fix:** Consolidate metric definitions into a single monitoring package.

### 3.3 — `NormalizeScore()` returns binary 0.0/1.0, rendering `RATE_LIMIT` action unreachable

- **Status:** Closed
- **File:** [`core/inference/features.go:L37-L41`](core/inference/features.go#L37-L41)
- **Code:** Returns `1.0` if `rawScore == -1`, else `0.0`.
- **Impact:** Decision Engine thresholds (`block > 0.85`, `rate_limit > 0.65`) only receive 0.0 or 1.0. The intermediate `RATE_LIMIT` tier is completely unreachable, collapsing the three-tier defense into binary allow/block.
- **Fix:** Extract continuous decision-function output or anomaly probabilities from the ONNX session.

### 3.4 — `cmd/loadtest/main.go` nil pointer dereference panic

- **Status:** Closed
- **File:** [`cmd/loadtest/main.go:L41-L47`](cmd/loadtest/main.go#L41-L47)
- **Code:** `resp, requestErr := client.Do(req)` executes even if `http.NewRequest` returns an error (`req == nil`).
- **Impact:** Panics with nil pointer dereference on invalid URL paths or request creation errors.
- **Fix:** Check `if err != nil { return Result{Err: err} }` before calling `client.Do`.

### 3.5 — Integer truncation of sub-millisecond request latencies

- **Status:** Closed
- **File:** [`pipeline/monitoring/metrics.go:L59`](pipeline/monitoring/metrics.go#L59)
- **Code:** `elapsed := float64(time.Since(start).Milliseconds())`
- **Impact:** Cached responses and sub-millisecond proxy round-trips are recorded as `0.0 ms`, distorting latency histograms.
- **Fix:** Use `float64(time.Since(start).Microseconds()) / 1000.0` or `time.Since(start).Seconds()`.

---

## 4. Architecture & Pipeline Disconnects

### 4.1 — Middleware execution order contradicts system architecture

- **Status:** Closed
- **Architecture §2:** Client → Proxy → Scheduler → Cache → Traffic Logger → Feature Extraction → ML Inference → Decision Engine
- **Implementation:** [`core/proxy/middleware.go:L114-L153`](core/proxy/middleware.go#L114-L153) sets order: `Metrics → Scheduler → RateLimiter → TrafficRules → ML Inference → Cache → Traffic Logger → Proxy`.
- **Impact:** ML evaluation occurs prior to the Cache layer. While this allows the ML engine to observe all raw requests, it deviates from the documented pipeline flow.

### 4.2 — Cache hits bypass Traffic Logger and ML backend feedback

- **Status:** Closed
- **Files:** [`core/proxy/middleware.go:L144-L152`](core/proxy/middleware.go#L144-L152) and [`core/cache/cache_middleware.go:L131`](core/cache/cache_middleware.go#L131)
- **Issue:** `CacheMiddleware` short-circuits on cache hits with `serveCachedResponse(c, cachedResp); return`. Because `TrafficLogger` is registered _after_ `Cache`, all cache hits are invisible to the traffic logger and never written to `traffic.jsonl`.
- **Impact:** Log datasets are biased, missing all cache-hit traffic.

### 4.3 — Implemented Priority Queue is dead code

- **Status:** Closed
- **Files:** [`core/scheduler/queue.go`](core/scheduler/queue.go) vs [`core/scheduler/scheduler.go`](core/scheduler/scheduler.go)
- **Issue:** A heap-based `PriorityQueue` with client reputation weighting exists in `queue.go`, but `scheduler.go` relies solely on a simple buffered-channel semaphore.
- **Impact:** Priority scheduling described in Architecture §3.2 is non-functional.

### 4.4 — Offline training dataset ignored by model training

- **Status:** Closed
- **Files:** [`pipeline/dataset_builder/build_dataset.py`](pipeline/dataset_builder/build_dataset.py) vs [`ml/training/train_model.py:L16`](ml/training/train_model.py#L16)
- **Issue:** `build_dataset.py` generates `datasets/traffic_dataset.csv` from real logs, but `train_model.py` hardcodes `datasets/synthetic_traffic_dataset.csv`.
- **Impact:** Production models are trained solely on synthetic distributions and never on observed traffic logs.

### 4.5 — ONNX export script hardcodes Isolation Forest model path

- **Status:** Closed
- **File:** [`ml/export/export_onnx.py:L8`](ml/export/export_onnx.py#L8)
- **Issue:** `MODEL_PATH = "models/best_isolationforest.pkl"`. If `train_model.py` selects `OneClassSVM` or `LocalOutlierFactor` as the best estimator, the export script fails or exports an obsolete model.

### 4.6 — Missing `core/inference/` from architecture module ownership tree

- **Status:** Closed
- **File:** [`docs/ARCHITECTURE.md §6`](docs/ARCHITECTURE.md#L6)
- **Issue:** The module tree lists `core/proxy/`, `core/scheduler/`, `core/cache/`, `core/security/`, and `core/decision/`, but omits `core/inference/`.

### 4.7 — Hardcoded decision thresholds and model path in proxy setup

- **Status:** Closed
- **File:** [`core/proxy/middleware.go:L65-L68`](core/proxy/middleware.go#L65-L68)
- **Issue:** `modelPath := "models/anomaly_model.onnx"` and `decision.NewThresholdPolicy(0.85, 0.65)` are hardcoded, ignoring `cfg.BlockThreshold` and `cfg.RateLimitThreshold`.

---

## 5. Security & Privacy Vulnerabilities

### 5.1 — Hardcoded fallback IP salt for PII hashing

- **Status:** Closed
- **File:** [`pipeline/logging/ip_extractor.go:L19-L21`](pipeline/logging/ip_extractor.go#L19-L21)
- **Default salt:** `"turboSH_default_salt"`
- **Impact:** Without `TURBOSH_IP_SALT`, all client IP hashes are deterministic and vulnerable to precomputed rainbow-table attacks across the IPv4 space.

### 5.2 — Truncated 8-byte IP hash increases collision probability

- **Status:** Closed
- **File:** [`pipeline/logging/ip_extractor.go:L30`](pipeline/logging/ip_extractor.go#L30)
- **Code:** `hex.EncodeToString(hash[:8])`
- **Impact:** Truncation to 64 bits reduces birthday collision resistance to ~2³² (~65,000 distinct IPs), risking distinct clients colliding into the same ML bucket.

### 5.3 — Inconsistent client IP extraction between security modules

- **Status:** Closed
- **Files:** [`core/security/rate_limiter.go:L83`](core/security/rate_limiter.go#L83), [`core/security/traffic_rules.go:L109`](core/security/traffic_rules.go#L109) vs [`core/inference/middleware.go:L202`](core/inference/middleware.go#L202)
- **Issue:** Security middlewares use Gin's `c.ClientIP()`, while ML and logging middlewares use `logging.GetClientIP(r, cfg)`.
- **Impact:** If upstream proxy configurations differ, rate limiters and anomaly detection track different IP strings for the same client.

### 5.4 — Client-controlled `X-Forwarded-For` spoofing via `ips[0]`

- **Status:** Closed
- **File:** [`pipeline/logging/ip_extractor.go:L46-L48`](pipeline/logging/ip_extractor.go#L46-L48)
- **Code:** `strings.TrimSpace(ips[0])`
- **Impact:** An attacker prepending spoofed headers (`X-Forwarded-For: 1.1.1.1`) through a trusted reverse proxy has their spoofed IP selected rather than the verified client IP.

### 5.5 — Missing authentication and rate limiting on `/metrics` endpoint

- **Status:** Closed
- **File:** [`cmd/turbosh/main.go:L50`](cmd/turbosh/main.go#L50)
- **Issue:** `/metrics` is exposed publicly on the main router without authentication or IP allowlisting.
- **Impact:** Exposes internal throughput, cache statistics, and detection state to unauthorized scrapers.

### 5.6 — Lack of TLS/HTTPS termination configuration

- **Status:** Closed
- **Issue:** No TLS configuration is available in `cmd/turbosh/main.go` or `config/config.go`. All proxy operations assume plaintext HTTP.

### 5.7 — Unchecked `w.Write` error in reverse proxy error handler

- **Status:** Closed
- **File:** [`core/proxy/proxy.go:L32`](core/proxy/proxy.go#L32)
- **Code:** Error returned from `w.Write(...)` is discarded without logging or handling.

### 5.8 — Docker container runs as root user

- **Status:** Closed
- **File:** [`Dockerfile`](Dockerfile)
- **Issue:** Missing `USER` directive in runtime stage; container runs with root privileges.

---

## 6. Mathematical & ML Feature Inconsistencies

### 6.1 — Incompatible Shannon entropy computation between Python and Go

- **Status:** Closed
- **Python:** [`pipeline/feature_extraction/feature_extractor.py:L88-L89`](pipeline/feature_extraction/feature_extractor.py#L88-L89) divides entropy by $\log_2(N)$ to normalize to `[0.0, 1.0]`.
- **Go:** [`core/inference/features.go`](core/inference/features.go) was computing raw unnormalized Shannon entropy.
- **Fix:** Standardized Go `ShannonEntropy` to normalize by `math.Log2(float64(nonZeroCount))` so both Go inference and Python pipeline return values strictly in `[0.0, 1.0]`. Unit tested across edge cases in `core/inference/inference_test.go`.

### 6.2 — Synthetic data entropy distribution does not match any extractor

- **Status:** Closed
- **File:** [`ml/data/generate_synthetic_data.py`](ml/data/generate_synthetic_data.py)
- **Fix:** Bounded all synthetic entropy generation to `[0.0, 1.0]` across all traffic profiles (normal centered at ~0.7, DDoS and brute force near 0.0, flooding at 0.4–0.9, latency attacks at 0.1–0.6). Added `argparse` support. Regenerated `datasets/synthetic_traffic_dataset.csv`, retrained Isolation Forest with GridSearchCV (F1 score 0.9827), and exported to `models/anomaly_model.onnx`.

### 6.3 — Latency spike detection threshold divergence

- **Status:** Closed
- **Python:** [`pipeline/feature_extraction/feature_extractor.py`](pipeline/feature_extraction/feature_extractor.py) used `max(baseline * 3, 500.0)`.
- **Go:** [`core/inference/middleware.go`](core/inference/middleware.go) and [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) use `maxLatency > (avgLatency * 1.5) && maxLatency > 100.0`.
- **Fix:** Unified Python `extract_features` to use `max_latency > (avg_latency * 1.5) and max_latency > 100.0`. Unit tested in `pipeline/feature_extraction/test_feature_extractor.py`.

### 6.4 — Batch feature extractor averages over entire log duration rather than sliding windows

- **Status:** Closed
- **File:** [`pipeline/feature_extraction/feature_extractor.py`](pipeline/feature_extraction/feature_extractor.py)
- **Fix:** Replaced whole-log duration averaging with true sliding window extraction over active 60-second windows with 10-second sub-windows. Emits accurate windowed feature records without burst smoothing. Unit tested in `pipeline/feature_extraction/test_feature_extractor.py`.

### 6.5 — `NewThresholdPolicy` overrides valid zero thresholds

- **Status:** Closed
- **File:** [`core/decision/decision_engine.go`](core/decision/decision_engine.go)
- **Fix:** Removed zero overrides (`if blockThreshold == 0`) from `NewThresholdPolicy` so that `0.0` can be configured explicitly. Added `NewDefaultThresholdPolicy()` for callers wanting defaults (0.85, 0.65). Verified with unit tests in `core/decision/decision_engine_test.go`.

---

## 7. Memory Leaks & Concurrency Issues

### 7.1 — TTL cache manager does not decrement memory on entry expiration

- **Status:** Closed
- **File:** [`core/cache/ttl_manager.go:L42-L46`](core/cache/ttl_manager.go#L42-L46)
- **Code:** Expired elements are removed via `c.order.Remove(element)` and `delete(c.items, key)`, but `c.currentMemory -= entry.size` and `c.metrics.RecordEviction()` are never called.
- **Impact:** `currentMemory` permanently drifts upward, eventually triggering continuous premature LRU evictions.

### 7.2 — `RateLimiter.Cleanup()` is never invoked

- **Status:** Closed
- **File:** [`core/security/rate_limiter.go:L99-L109`](core/security/rate_limiter.go#L99-L109)
- **Issue:** No background ticker or caller invokes `Cleanup(maxAge)`.
- **Impact:** `rl.buckets` map grows indefinitely as new client IPs connect.

### 7.3 — `TrafficRules.Cleanup()` is never invoked

- **Status:** Closed
- **File:** [`core/security/traffic_rules.go:L135-L154`](core/security/traffic_rules.go#L135-L154)
- **Issue:** `tr.burstTracker` and `tr.endpointTracker` maps are never cleaned periodically, leaking memory under distributed IP scans.

### 7.4 — `MLProtection` map accumulation on abandoned IPs

- **Status:** Closed
- **File:** [`core/inference/middleware.go:L61-L88`](core/inference/middleware.go#L61-L88)
- **Issue:** `prune()` is only invoked for the active client IP on an incoming request. Abandoned IPs that send a single request remain in `requestTimes`, `endpoints`, and `ipStats` indefinitely.
- **Issue 2:** `endpoints[ip]` counts are never decremented or windowed, accumulating lifetime endpoint counters.

### 7.5 — Background metric poller goroutine leaks on shutdown

- **Status:** Closed
- **File:** [`core/proxy/middleware.go:L90-L96`](core/proxy/middleware.go#L90-L96)
- **Code:** An infinite `for { time.Sleep(1 * time.Second) }` goroutine runs without a termination channel or context.

### 7.6 — Double-locking contention in `LRUCache.Get()`

- **Status:** Closed
- **File:** [`core/cache/lru_cache.go:L98-L109`](core/cache/lru_cache.go#L98-L109)
- **Issue:** `Get()` acquires `RLock()`, releases it, then acquires `Lock()` to perform `MoveToFront`. Under high concurrent read load, this causes lock bouncing and extra lookups.

### 7.7 — Shallow copy in `LRUCache.Set()`

- **Status:** Closed
- **File:** [`core/cache/lru_cache.go:L123`](core/cache/lru_cache.go#L123)
- **Code:** `valCopy := *value` performs a shallow struct copy. `Headers` map and `Body` byte slice share backing arrays with the caller.

---

## 8. Monitoring, Metrics & Grafana Conflicts

### 8.1 — Grafana dashboard PromQL queries reference non-existent metric names

- **Status:** Closed
- **File:** [`monitoring/grafana/dashboards/turbosh.json`](monitoring/grafana/dashboards/turbosh.json)
- **Mismatches:**
  - Latency panel queries `turbosh_request_duration_seconds_bucket` (pipeline defines `turbosh_request_latency_ms`).
  - Cache panel queries `turbosh_cache_hits_total` (pipeline uses `turbosh_cache_operations_total{result="hit"}`).
  - Scheduler panel queries `turbosh_scheduler_active` (pipeline defines `turbosh_scheduler_active_requests`).
  - ML panel queries `turbosh_ml_blocks_total` (pipeline defines `turbosh_anomaly_alerts_total{action="block"}`).
- **Impact:** Grafana dashboard panels fail to render data.

### 8.2 — Duplicate Grafana dashboard provisioning files

- **Status:** Closed
- **Files:** [`monitoring/grafana/provisioning/dashboards/dashboards.yaml`](monitoring/grafana/provisioning/dashboards/dashboards.yaml) and [`dashboards.yml`](monitoring/grafana/provisioning/dashboards/dashboards.yml)
- **Issue:** Both files configure the dashboard provider with conflicting settings (`foldersFromFilesStructure: true` vs `false`), causing Grafana to register duplicate dashboard providers.

### 8.3 — Duplicate Grafana datasource provisioning files

- **Status:** Closed
- **Files:** [`monitoring/grafana/provisioning/datasources/prometheus.yaml`](monitoring/grafana/provisioning/datasources/prometheus.yaml) and [`prometheus.yml`](monitoring/grafana/provisioning/datasources/prometheus.yml)
- **Issue:** Both files configure the Prometheus datasource with conflicting `editable` flags.

### 8.4 — Duplicate Prometheus scrape configurations

- **Status:** Closed
- **Files:** [`monitoring/prometheus.yml`](monitoring/prometheus.yml) and [`monitoring/prometheus/prometheus.yml`](monitoring/prometheus/prometheus.yml)
- **Issue:** Two configuration files exist with slightly different scrape targets and parameters.

---

## 9. Cache & Resource Management Flaws

### 9.1 — `CacheStop` channel never closed on application shutdown

- **Status:** Closed
- **Files:** [`core/proxy/middleware.go:L103`](core/proxy/middleware.go#L103) and [`cmd/turbosh/main.go`](cmd/turbosh/main.go)
- **Issue:** `components.CacheStop` channel is created by `StartTTLManager` but never closed in `main.go`.

### 9.2 — Missing graceful shutdown in `cmd/turbosh/main.go`

- **Status:** Closed
- **File:** [`cmd/turbosh/main.go:L69`](cmd/turbosh/main.go#L69)
- **Issue:** Server executes `router.Run(...)` directly without trapping `SIGINT`/`SIGTERM`.
- **Impact:** On termination, `TrafficLogger.Close()` is not called (losing up to 4KB buffered logs), and ONNX runtime sessions are not cleanly released via `inference.Destroy()`.

### 9.3 — Missing automatic periodic flush in `TrafficLogger`

- **Status:** Closed
- **File:** [`pipeline/logging/traffic_logger.go:L156`](pipeline/logging/traffic_logger.go#L156)
- **Comment:** `// Removed: tl.writer.Flush() - logs are now flushed periodically or on close`
- **Issue:** No periodic flush goroutine exists. Low-volume traffic can sit in the 4KB buffer indefinitely.

---

## 10. Docker, Deployment & Network Issues

### 10.1 — Default backend port inconsistency

- **Status:** Closed
- **`Dockerfile` L56:** `ENV TURBOSH_BACKEND="http://localhost:9092"`
- **`PLAYBOOK.md` L58:** Corrected default documentation from `http://localhost:9090` to `http://localhost:9092`.
- **[`config/config.go:L100`](config/config.go#L100):** Default is `"http://localhost:9092"`.
- **[`cmd/dummy_backend/main.go`](cmd/dummy_backend/main.go):** Backend listens on `:9092` by default.
- **Fix:** Standardized backend port to 9092 across code, docker configuration, and operator playbook, eliminating port collision with Prometheus (`:9090`).

### 10.2 — Dockerfile hardcodes x86_64 architecture

- **Status:** Closed
- **File:** [`Dockerfile`](Dockerfile)
- **Fix:** Parameterized build using `ARG TARGETARCH`. Added dynamic ONNX Runtime architecture resolution (`x64` for `amd64`, `aarch64` for `arm64`) and configured `GOARCH=${TARGETARCH:-amd64}` for cross-platform Docker multi-arch builds.

### 10.3 — `.dockerignore` omits large datasets and build artifacts

- **Status:** Closed
- **File:** [`.dockerignore`](.dockerignore)
- **Fix:** Appended `datasets/`, `models/*.pkl`, `notebooks/`, `*.csv`, `turbosh`, and `turbosh.exe` to `.dockerignore`, preventing unnecessary image context bloat.

### 10.4 — Missing `Host` header rewrite in reverse proxy

- **Status:** Closed
- **File:** [`core/proxy/proxy.go:L26`](core/proxy/proxy.go#L26)
- **Fix:** Wrapped `proxy.Director` to explicitly rewrite `req.Host = target.Host` after default director processing. Verified with unit test in `core/proxy/proxy_test.go`.

---

## 11. Test & Tooling Flaws

### 11.1 — `accuracy_test` counts HTTP 503 (Queue Full) as allowed traffic

- **Status:** Closed
- **File:** [`cmd/accuracy_test/main.go:L118`](cmd/accuracy_test/main.go#L118)
- **Fix:** Updated `blocked := r.StatusCode == 403 || r.StatusCode == 429 || r.StatusCode == 503`. Added queue-full tracking and reporting in `runDDoSAttack()`.

### 11.2 — Socket exhaustion from HTTP client recreation in test scripts

- **Status:** Closed
- **Files:** [`cmd/attacker/main.go`](cmd/attacker/main.go), [`cmd/loadtest/main.go`](cmd/loadtest/main.go), [`cmd/accuracy_test/main.go`](cmd/accuracy_test/main.go)
- **Fix:** Replaced per-request `&http.Client{}` instantiations with shared package-level `httpClient` configured with high-capacity connection pooling (`MaxIdleConns: 1000`, `MaxIdleConnsPerHost: 1000`).

### 11.3 — Test tools omit response body draining before close

- **Status:** Closed
- **Files:** [`cmd/attacker/main.go`](cmd/attacker/main.go), [`cmd/loadtest/main.go`](cmd/loadtest/main.go), [`cmd/accuracy_test/main.go`](cmd/accuracy_test/main.go)
- **Fix:** Added `_, _ = io.Copy(io.Discard, resp.Body)` prior to `resp.Body.Close()` across all test utilities to enable HTTP keep-alive connection reuse.

### 11.4 — `loadtest` fails if `docs/` directory is absent

- **Status:** Closed
- **File:** [`cmd/loadtest/main.go`](cmd/loadtest/main.go)
- **Fix:** Added `_ = os.MkdirAll("docs", 0755)` before writing `docs/benchmark_report.md` (and in `cmd/accuracy_test/main.go` before writing `docs/detection_accuracy_report.md`).

### 11.5 — Hardcoded backend server configuration in `dummy_backend`

- **Status:** Closed
- **File:** [`cmd/dummy_backend/main.go`](cmd/dummy_backend/main.go)
- **Fix:** Added environment variable port configuration (`PORT` or `BACKEND_PORT`, defaulting to `:9092`), dedicated `http.NewServeMux()`, and explicit `http.Server` timeouts (`ReadTimeout: 10s`, `WriteTimeout: 10s`, `IdleTimeout: 60s`).

---

## 12. Documentation & Code Quality Deficiencies

### 12.1 — `.gitignore` syntax error on line 2

- **Status:** Closed
- **File:** [`.gitignore:L2`](.gitignore#L2)
- **Fix:** Added `#` comment prefix to line 2 (`# ============================================`).

### 12.2 — Dead comment and stub in `traffic_logger.go`

- **Status:** Closed
- **File:** [`pipeline/logging/traffic_logger.go:L100`](pipeline/logging/traffic_logger.go#L100)
- **Fix:** Removed dangling unused comment `// dirOf returns the directory portion of a file path.`

### 12.3 — Undecided architecture options in `API.md`

- **Status:** Closed
- **File:** [`docs/API.md §2`](docs/API.md)
- **Fix:** Replaced speculative text with finalized documentation for the in-process Go CGO ONNX runtime architecture and 6-dimensional feature vector specification.

### 12.4 — Outdated status in `AGENT.md`

- **Status:** Closed
- **File:** [`docs/AGENT.md`](docs/AGENT.md)
- **Fix:** Updated project status to reflect completion of all 9 EPICs and verified flaw remediation.

### 12.5 — Missing CLI arguments for `generate_synthetic_data.py`

- **Status:** Closed
- **File:** [`ml/data/generate_synthetic_data.py`](ml/data/generate_synthetic_data.py)
- **Fix:** Implemented `argparse` with configurable `--output`, `--num-normal`, and `--num-attack` parameters, with safe directory creation and full profile entropy bounds `[0.0, 1.0]`.

---

## 13. SIH (Smart India Hackathon) Alignment & Deficiencies

> **Scope:** Verification of turboSH against official SIH problem statement requirements, comparing documentation claims against actual codebase implementation, with technical specifications for required additions.  
> **Status:** Active / In-Progress

### SIH Challenge Requirements Scorecard

| # | SIH Challenge Requirement | Documentation / Review Claim | Actual Codebase Reality | Status / Gap Level |
|---|---|---|---|---|
| **13.1** | **State Representation (Vectors & Graphs)** | "6D Feature vector; could extend to graph" | 6D tabular vector in [`core/inference/features.go`](core/inference/features.go). **Zero graph representations exist.** | 🟡 **Partial** (Vector exists, Graph missing) |
| **13.2** | **State-Transition Dynamics (LSTM, Transformer, GNN)** | "Could extend to LSTM; current ensemble" | Only static **Isolation Forest** served in Go ONNX. OC-SVM/LOF only tuned in Python. **No sequence model exists.** | 🔴 **Major Gap** (Purely static point-in-time) |
| **13.3** | **Forecast Future States & Attacker Progression** | "Does this partially; predict next 5 requests" | **Purely reactive.** Scores $X_t$ in [`core/inference/middleware.go`](core/inference/middleware.go). **No forward simulation or progression probabilities.** | 🔴 **Major Gap** (No forecasting implemented) |
| **13.4** | **Map Behaviour to MITRE ATT&CK Stages** | "Current feature patterns map to MITRE stages" | Conceptual mapping only. **Zero MITRE ATT&CK code, structs, or metric labels exist.** | 🔴 **Missing in Code** (High-impact win) |
| **13.5** | **Explainability (Attention, Feature Attribution)** | "Each score comes with feature breakdown" | Engine returns a single scalar `float64`. **No SHAP, feature attribution, or model confidence breakdown.** | 🔴 **Missing in Code** (High-impact win) |
| **13.6** | **Demonstrable Learning (Not Just Static Classifier)** | "Learns dynamics; continually rescored" | Offline batch training in [`ml/training/train_model.py`](ml/training/train_model.py). **No online learning, drift detection, or retraining loop.** | 🟡 **Partial** (Static trained model) |

---

### 13.1 — Network State Representation: Lack of Graph-Based Modeling

- **Status:** Active / Unresolved (Gap)
- **SIH Requirement:** *"Represent network state using feature vectors or graphs"*
- **Current State:** The proxy extracts a 6-dimensional tabular vector per client IP (`requests_per_ip_10s`, `requests_per_ip_60s`, `endpoint_entropy`, `latency_spike`, `error_rate`, `request_variance`) in [`core/inference/features.go`](core/inference/features.go).
- **Flaw / Deficiency:** The SIH challenge specifically calls for graph representations or feature vectors. turboSH has zero graph data structures, topological metrics, or adjacency mappings.
- **Required Additions & Improvements:**
  1. **Bipartite & Temporal Interaction Graph:**
     - Build an in-memory directed graph representing client-to-API interactions:
       - **Nodes:** Client IP nodes $\to$ API Endpoint nodes (`/api/v1/auth`, `/api/v1/data`, etc.).
       - **Edges:** Request interactions weighted by `[timestamp, frequency, status_code, payload_bytes, error_flag]`.
  2. **Topological Graph Metrics in Feature Vectors:**
     - Integrate graph-structural metrics into the feature extraction pipeline:
       - **Node In-Degree / Out-Degree:** Ratio of distinct endpoints targeted by an IP over a sliding window.
       - **Endpoint Centrality & Graph Entropy:** Measures anomalous fan-out or broad reconnaissance scans.
       - **Graph Edit Distance / Clustering Coefficient:** Quantifies deviation from baseline API navigation topologies.
  3. **GNN / Embedding Pipeline:**
     - Add `ml/training/train_gnn.py` using PyTorch Geometric (PyG) or NetworkX to generate node embeddings from `logs/traffic.log`.

---

### 13.2 — State-Transition Dynamics: Absence of Sequence Models (LSTM / Transformer / GNN)

- **Status:** Active / Unresolved (Gap)
- **SIH Requirement:** *"Learn state-transition dynamics using sequence models (LSTM, Transformer, GNN)"*
- **Current State:** turboSH uses static point-in-time anomaly detection. Only a single scikit-learn `IsolationForest` model is loaded and executed via ONNX in [`core/inference/inference.go`](core/inference/inference.go). OC-SVM and LOF are merely benchmarked during offline GridSearch and never executed in Go.
- **Flaw / Deficiency:** The system treats every HTTP request independently. It has no temporal memory, cannot model state transitions between benign browsing and multi-stage exploits, and lacks sequence models.
- **Required Additions & Improvements:**
  1. **Sliding Window Sequence Buffer in Go Proxy:**
     - Maintain an in-memory ring buffer of the last $W$ feature vectors per IP in [`core/inference/middleware.go`](core/inference/middleware.go) (e.g., $W = 10$ steps: $[X_{t-9}, X_{t-8}, \dots, X_t]$).
  2. **LSTM / GRU Autoencoder:**
     - Create `ml/training/train_sequence_model.py`:
       - Train an **LSTM Autoencoder** in PyTorch on sliding sequence windows of normal traffic of shape `(batch, seq_len=10, features=6)`.
       - Anomalous sequences yield high reconstruction error (MSE) when sudden transition dynamics occur (e.g., normal probe $\to$ credential stuffing burst).
  3. **Discrete-Time Markov Chain (DTMC) State Transitions:**
     - Implement a state transition matrix for attacker phases:
       $$\text{States: } \{S_0: \text{Unauthenticated}, S_1: \text{Authenticated}, S_2: \text{Scanning}, S_3: \text{Burst Brute-Force}, S_4: \text{Exfiltration}\}$$
     - Calculate transition probabilities $P(S_{t+1} \mid S_t)$; alert when anomalous low-probability state jumps occur.
  4. **ONNX Export & Go Inference Integration:**
     - Export sequence model to `models/sequence_model.onnx` and integrate multi-timestep tensor execution into [`core/inference/inference.go`](core/inference/inference.go).

---

### 13.3 — Forward State Forecasting: Lack of Trajectory Prediction & Attacker Progression Probability

- **Status:** Active / Unresolved (Gap)
- **SIH Requirement:** *"Forecast future network states and estimate probability of attacker progression"*
- **Current State:** Completely reactive. The proxy scores current request $X_t$ and triggers `ALLOW`, `RATE_LIMIT`, or `BLOCK` only after thresholds are breached.
- **Flaw / Deficiency:** The project does not simulate forward states ($X_{t+1} \dots X_{t+5}$) and does not estimate the probability that an attacker will escalate along the kill chain.
- **Required Additions & Improvements:**
  1. **Multi-Step Forward Forecasting:**
     - Implement an autoregressive sequence predictor (LSTM decoder or linear state-space model) to project feature vectors for the next $H$ requests $[\hat{X}_{t+1}, \dots, \hat{X}_{t+5}]$.
  2. **Attacker Progression Probability ($P_{\text{progression}}$):**
     - Compute the escalation probability:
       $$P_{\text{escalation}} = \sigma\left(\mathbf{w}^T \cdot \hat{X}_{t+k} + b\right)$$
     - Predict the likelihood that an IP in reconnaissance will escalate to brute-force or denial of service.
  3. **Preemptive / Proactive Enforcement:**
     - Update [`core/decision/decision_engine.go`](core/decision/decision_engine.go) to support a `PREEMPTIVE_CHALLENGE` action:
       - If current score is normal ($0.50$), but predicted trajectory reaches $> 0.85$ within 3 requests with progression confidence $> 80\%$, initiate preemptive rate-limiting before backend exhaustion.
  4. **Forecasting Visualization on Dashboard:**
     - Expose predicted risk trajectories over the `/api/v1/status` endpoint and render a forward-looking risk chart in `ui/dark_desktop_ui.html`.

---

### 13.4 — Threat Mapping: MITRE ATT&CK Framework Completely Missing from Code

- **Status:** Active / Unresolved (Gap)
- **SIH Requirement:** *"Map predicted behaviour to recognised attack stages (e.g. MITRE ATT&CK)"*
- **Current State:** MITRE mapping exists solely as conceptual text in review notes. The codebase contains zero structs, constants, classification logic, or Prometheus labels referencing MITRE ATT&CK.
- **Flaw / Deficiency:** Disconnect between project documentation claims and codebase implementation.
- **Required Additions & Improvements:**
  1. **MITRE ATT&CK Engine (`core/security/mitre.go`):**
     - Define standardized MITRE enterprise mappings:
       - **T1595 (Reconnaissance - Active Scanning):** `EndpointEntropy > 0.8 && RequestsPerIP10s > 10 && ErrorRate < 0.2`
       - **T1110 (Credential Access - Brute Force):** `ErrorRate > 0.5 && RequestsPerIP60s > 30 && Path == "/login"`
       - **T1498 (Impact - Network Denial of Service):** `RequestsPerIP10s > 50 && LatencySpike == 1.0`
       - **T1020 (Exfiltration - Automated Exfiltration):** `Path in ["/data/*", "/export"] && Variance < 0.1 && AnomalyScore > 0.7`
       - **T1046 (Discovery - Network Service Discovery):** Sequential scanning across non-existent endpoints.
  2. **Integrate into Decision Pipeline:**
     - Add `Mitre *MitreAttack` field to `decision.Prediction` in [`core/decision/decision_engine.go`](core/decision/decision_engine.go).
  3. **Prometheus Metrics & Dashboard Badges:**
     - Add metric: `turbosh_mitre_threats_total{tactic="...", technique="..."}` in [`pipeline/monitoring/metrics.go`](pipeline/monitoring/metrics.go).
     - Render color-coded MITRE badges (e.g. `[T1110: Brute Force]`) in the Live Threat Detection table on the dashboard UI.

---

### 13.5 — Model Explainability: Absence of Feature Attribution and SHAP

- **Status:** Active / Unresolved (Gap)
- **SIH Requirement:** *"Provide explainability using attention mechanisms, feature attribution"*
- **Current State:** The ONNX inference engine outputs a single continuous `float64` anomaly score. No feature contribution values, SHAP values, or attention weights are calculated or logged.
- **Flaw / Deficiency:** The review claim ("Each anomaly score comes with feature breakdown... Which model is most confident?") is unimplemented.
- **Required Additions & Improvements:**
  1. **Real-Time Feature Contribution Breakdown in Go:**
     - In [`core/inference/features.go`](core/inference/features.go), calculate normalized deviation of each feature against baseline training means:
       ```go
       type FeatureAttribution struct {
           FeatureName  string  `json:"feature_name"`
           Value        float32 `json:"value"`
           BaselineMean float32 `json:"baseline_mean"`
           Contribution float64 `json:"contribution"` // Relative contribution percentage
       }
       ```
     - Output the **Top-3 Anomalous Features** in every decision payload.
  2. **Offline SHAP Analysis Pipeline:**
     - Create `ml/evaluation/explain_shap.py` using `shap.TreeExplainer` on trained models.
     - Generate SHAP summary plots, beeswarm plots, and waterfall charts for audit artifacts.
  3. **Multi-Model Consensus Scoring:**
     - Export and run the full ensemble (Isolation Forest, One-Class SVM, LOF) and expose individual model confidence levels alongside the consensus score.
  4. **Audit Header / Explainability API:**
     - Expose explainability in response headers or status API:
       `X-Anomaly-Explain: endpoint_entropy (48%), request_variance (32%)`.

---

### 13.6 — Demonstrable Learning: Static Offline Model Lacking Online Adaptation & Retraining

- **Status:** Active / Unresolved (Gap)
- **SIH Requirement:** *"Fully open-source solution with demonstrable learning, not just classification"*
- **Current State:** Models are trained once offline via [`ml/training/train_model.py`](ml/training/train_model.py) on static synthetic CSV data. The Go proxy runs the static `.onnx` model indefinitely without adaptation.
- **Flaw / Deficiency:** No mechanism to demonstrate learning over time, detect concept drift, or hot-reload models without downtime.
- **Required Additions & Improvements:**
  1. **Concept Drift Detection:**
     - Implement drift detection (e.g., ADWIN or Kolmogorov-Smirnov test) over sliding 24-hour feature windows to flag when traffic distributions shift.
  2. **Automated Continuous Retraining Script (`scripts/retrain_live.sh`):**
     - Extract real traffic patterns from `logs/traffic.log`, append labeled edge-cases, run retraining, and convert to ONNX.
  3. **Zero-Downtime Hot-Reloading in Go Proxy:**
     - Implement dynamic model swapping in [`core/inference/inference.go`](core/inference/inference.go) using an atomic pointer swap on `Engine.session`.
  4. **Jury Demonstration Walkthrough:**
     - Script demonstrating: Baseline traffic $\to$ New attack pattern emerges $\to$ Drift flagged $\to$ Auto-retrain executes $\to$ Model hot-reloaded $\to$ Decision accuracy verified live.

---

### 13.7 — Prioritized SIH Execution Roadmap

```mermaid
graph TD
    subgraph Phase 1: High Impact Quick Wins [Phase 1: High-Impact / Days 1-2]
        A[MITRE ATT&CK Engine in Go] --> B[Real-Time Feature Attribution Top-3]
        B --> C[Ensemble Multi-Model Output]
        C --> D[Live MITRE Badges on Web Dashboard]
    end

    subgraph Phase 2: Sequence & Progression [Phase 2: Core SIH Requirements / Days 2-4]
        E[Sliding Window Ring Buffer W=10] --> F[PyTorch LSTM Autoencoder / Markov Transitions]
        F --> G[Forward State Forecasting & Progression Score]
        G --> H[Preemptive Throttling Action in Decision Engine]
    end

    subgraph Phase 3: Graphs & Online Learning [Phase 3: Advanced Polish / Days 4-6]
        I[In-Memory IP-Endpoint Interaction Graph] --> J[Topological Graph Features Degree/Entropy]
        J --> K[Automated Retraining Loop & Drift Hot-Reload Demo]
    end

    Phase 1 --> Phase 2 --> Phase 3
```

---

## 14. Audit Summary Statistics

| Category                                      | Total Identified | Resolved / Closed | Retracted / Invalid | Active Unresolved |
| :-------------------------------------------- | :--------------: | :---------------: | :-----------------: | :---------------: |
| **False Positives / Retracted**               |        5         |         0         |          5          |         0         |
| **Critical Runtime Bugs & Panics**            |        5         |         5         |          0          |         0         |
| **Architecture & Pipeline Disconnects**       |        7         |         7         |          0          |         0         |
| **Security & Privacy Vulnerabilities**        |        8         |         8         |          0          |         0         |
| **Mathematical & ML Feature Inconsistencies** |        5         |         5         |          0          |         0         |
| **Memory Leaks & Concurrency Issues**         |        7         |         7         |          0          |         0         |
| **Monitoring, Metrics & Grafana Conflicts**   |        4         |         4         |          0          |         0         |
| **Cache & Resource Management Flaws**         |        3         |         3         |          0          |         0         |
| **Docker, Deployment & Network Issues**       |        4         |         4         |          0          |         0         |
| **Test & Tooling Flaws**                      |        5         |         5         |          0          |         0         |
| **Documentation & Code Quality Deficiencies** |        5         |         5         |          0          |         0         |
| **SIH Challenge Requirements & Gaps**         |        6         |         0         |          0          |         6         |
| **Total Flaws & Gaps Audited**                |      **64**      |      **53**       |        **5**        |       **6**       |


