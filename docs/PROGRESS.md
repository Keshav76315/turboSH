# turboSH — Development Progress

> Track all development updates here. Each entry includes the date, developer, and what was done.

---

## Log

### 2026-03-05

**Keshav**

- Initialized Git repository and pushed to GitHub
- Created base folder structure (`core/`, `pipeline/`, `ml/`, `models/`, `monitoring/`, `datasets/`, `notebooks/`)
- Setup Go modules (`go mod init github.com/Keshav76315/turboSH`)
- Setup Python virtual environment (`.venv`, Python 3.10.11)
- Created `requirements.txt`
- Created `docs/ARCHITECTURE.md` (system diagrams, request pipeline, module ownership)
- **EPIC 2 — Core Middleware System:**
  - Implemented reverse proxy (`core/proxy/proxy.go`) — wraps `httputil.ReverseProxy` with Gin
  - Implemented middleware pipeline assembly (`core/proxy/middleware.go`) — ordered chain: Scheduler → RateLimiter → TrafficRules → Cache → Proxy
  - Implemented request scheduler (`core/scheduler/scheduler.go`, `queue.go`) — semaphore-based concurrency control
  - Implemented rate limiter (`core/security/rate_limiter.go`) — per-IP token bucket
  - Implemented traffic rules (`core/security/traffic_rules.go`) — burst detection + endpoint abuse
  - Implemented decision engine (`core/decision/decision_engine.go`) — anomaly score → action mapping
  - Created centralized config system (`config/config.go`) — env vars with sensible defaults
  - Created main entry point (`cmd/turbosh/main.go`)

**Anzal**

- Created `docs/PLAN.md` (Jira-style development plan with 9 EPICs)
- Created documentation templates (`PROGRESS.md`, `AGENT.md`, `README.md`, `DATA_SCHEMA.md`, `API.md`)
- **EPIC 3 — Cache Optimization System:**
  - **Story 3.1 — LRU Cache:**
    - Implemented in-memory LRU cache (`core/cache/lru_cache.go`) — hashmap + doubly linked list
    - Defined `Cache` interface and `CachedResponse` type (`core/cache/cache.go`)
    - Implemented TTL eviction: lazy check in `Get()` + background cleanup goroutine (`core/cache/ttl_manager.go`)
    - Added thread safety via `sync.RWMutex` (concurrent reads, exclusive writes)
    - Added byte-level memory cap (default 512 MB) alongside entry-count limit
    - Wrote 6 unit tests covering LRU eviction, TTL, combined behavior, and concurrency stress (`core/cache/lru_cache_test.go`)
  - **Story 3.2 — Cache Integration:**
    - Implemented Gin-native cache middleware (`core/cache/cache_middleware.go`) — `Middleware() gin.HandlerFunc`
    - Captures backend responses via `ginResponseRecorder` for caching
    - Cache key includes method + path + query params
    - Admission rules: method filtering (GET/HEAD only), status code filtering, `Cache-Control` header respect, body size limit
    - `X-Cache: HIT` header for debugging
    - Integrated into pipeline at slot #4 in `SetupMiddleware()`
    - Implemented stampede protection (`core/cache/stampede.go`) — request coalescing via `singleflight`
  - **Story 3.3 — Cache Metrics:**
    - Implemented lock-free metrics (`core/cache/cache_metrics.go`) — `sync/atomic` counters for hits, misses, evictions
    - `HitRate()` computed on demand, `Snapshot()` returns JSON-serializable struct
    - Metrics auto-instrumented in `LRUCache.Get()` and `evict()`
  - Created demo server (`core/cache/cmd/cache_demo/main.go`) with `/cache/stats` endpoint
  - Added `golang.org/x/sync` dependency for `singleflight`
  - Added `CacheMaxMemory` config field (default 512 MB, env `TURBOSH_CACHE_MAX_MEMORY`)
  - **EPIC 4 — Traffic Logging & Data Pipeline:**
    - Implemented Traffic Logger middleware (`pipeline/logging/traffic_logger.go`)
    - Created Feature Extractor (`pipeline/feature_extraction/feature_extractor.py`)
    - Built Dataset Builder (`pipeline/dataset_builder/build_dataset.py`)
  - **EPIC 5 — Data Analysis & Feature Engineering:**
    - Performed Exploratory Data Analysis (`notebooks/traffic_analysis.ipynb`)
    - Simulated Attacks (`datasets/attack_dataset.csv`)

### 2026-03-07

**Keshav**

- **EPIC 6 — Machine Learning System:**
  - Written Synthetic Data Generator (`ml/data/generate_synthetic_data.py`) which generated 22k rows of data.
  - Developed and executed model training script via GridSearchCV (`ml/training/train_model.py`) over IsolationForest, One-Class SVM and LOF.
  - Selected IsolationForest as winner (Validation F1 Score ~0.99).
  - Authored evaluation report documenting the selection (`docs/model_evaluation_report.md`).
  - Exported the finalized model via skl2onnx (`ml/export/export_onnx.py` to `models/anomaly_model.onnx`).
- **EPIC 7 — ML Inference Integration:**
  - Created ONNX Runtime Go wrapper (`core/inference/inference.go`) with CGO build tags for cross-platform compilation.
  - Created non-CGO stub (`core/inference/inference_nocgo.go`) for graceful degradation on machines without `gcc`.
  - Defined `RequestFeatures` struct and `ShannonEntropy` helper (`core/inference/features.go`).
  - Built ML Protection middleware (`core/inference/middleware.go`) — extracts live features, runs ONNX inference, enforces BLOCK/RATE_LIMIT/ALLOW.
  - Integrated inference engine into middleware pipeline (`core/proxy/middleware.go`).
  - Downgraded `onnxruntime_go` v1.27.0 → v1.9.0 to match ORT API Version 17.
  - Fixed output tensor rank mismatch (`ort.NewShape(1)` → `ort.NewShape(1, 1)`) for skl2onnx compatibility.
  - Reordered middleware pipeline so ML runs before Cache to prevent cache from masking attack patterns.

**Anzal**

- **EPIC 7 — ML Inference Engine (Enhancements):**
  - Integrated `MLProtection` middleware with the CGo ONNX engine.
  - Replaced stubbed features with real-time `ErrorRate`, `LatencySpike`, and `RequestVariance` using feedback from `TrafficLogger`.
  - Added explicit HTTP timeouts to the `attacker/main.go` load testing script.
  - Standardized privacy-first hashed IP tracking (`RedactIP`) across the ML decision state and traffic logs.
- **EPIC 8 — Monitoring & Observability:**
  - **Story 8.1 — Metrics Collector:**
    - Integrated `prometheus/client_golang` and exported the router's `/metrics` endpoint.
    - Instrumented internal components to track Request Throughput, Cache Hit Ratio, and ML Anomaly Alerts via Prometheus Counters.
    - Added concurrent tracking for `Scheduler` Active and Waiting Queues via Prometheus Gauges.
  - **Story 8.2 — Grafana Dashboard:**
    - Created `docker-compose.yml` defining the Prometheus + Grafana stack.
    - Configured auto-provisioning for Prometheus scraping (`prometheus.yml`) and Grafana datasources/dashboards.
    - Built a pre-configured `turbosh.json` Grafana dashboard featuring the core system metrics.

**Keshav & Anzal**

- **EPIC 9 — Testing & Optimization:**
  - **Story 9.1 — Load Testing:**
    - Built `cmd/loadtest/main.go` — A 4-phase stress testing tool (Baseline, Ramp-up, Sustained, Spike).
    - Validated high-throughput proxy performance (~2500 req/s during ramp-up, stable 600 req/s during 30s sustained load with mixed block/allow traffic).
    - Auto-generated `docs/benchmark_report.md`.
  - **Story 9.2 — Detection Accuracy Testing:**
    - Built `cmd/accuracy_test/main.go` — ML detection evaluator.
    - Executed Normal Traffic against DDoS Burst and Endpoint Scraping profiles.
    - Achieved **92.4% Detection Rate (Recall)** and **0.0% False Positive Rate**, officially passing the `ARCHITECTURE.md` targets.
    - Auto-generated `docs/detection_accuracy_report.md`.

---

<!--
TEMPLATE — Copy this for new entries:

### YYYY-MM-DD

**Developer Name**
- What was done
- What was done
-->
