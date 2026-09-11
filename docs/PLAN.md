# turboSH — Jira Style Development Plan

**Project:** turboSH  
**Goal:** High-throughput AI‑powered middleware for server optimization and automated anomaly mitigation  
**Overall Status:** Complete & Verified (EPICs 1–9 Finished, Flaw Audit Remediation Verified)

---

## Team & Ownership

| Developer | Role | Areas Owned |
| :--- | :--- | :--- |
| **Keshav** | Backend Systems & ML Engineer | `core/{proxy, scheduler, security, inference, decision}`, `ml/`, `models/`, `Dockerfile` |
| **Anzal** | Data Systems & Observability Engineer | `core/cache/`, `pipeline/`, `monitoring/`, `ui/`, `datasets/`, `notebooks/`, `docs/` |

---

## EPIC 1 — Project Foundation & Documentation

**Goal:** Establish repository structure, interfaces, schemas, and documentation framework.  
**Status:** Completed

### STORY 1.1 — Repository Initialization
- **Owner:** Keshav
- **Tasks:** Setup Git repo, Go modules (`github.com/Keshav76315/turboSH`), Python environment, and base layout.
- **Deliverables:** `go.mod`, `requirements.txt`, `.gitignore`

### STORY 1.2 — Documentation System
- **Owner:** Anzal
- **Tasks:** Establish initial documentation framework (`PLAN.md`, `PROGRESS.md`, `AGENT.md`, `DATA_SCHEMA.md`, `API.md`, `ARCHITECTURE.md`).
- **Deliverables:** `docs/` specification suite

### STORY 1.3 — Architecture Definition
- **Owner:** Keshav + Anzal
- **Tasks:** Detail system diagrams, pipeline execution flow, and interface contracts.
- **Deliverables:** `docs/ARCHITECTURE.md`

---

## EPIC 2 — Core Middleware System

**Goal:** Build the proxy middleware, concurrency limiter, rule-based traffic controls, and decision logic.  
**Status:** Completed

### STORY 2.1 — Reverse Proxy Middleware
- **Owner:** Keshav
- **Tasks:** Build reverse proxy wrapping `httputil.ReverseProxy` with Gin, upstream `Host` header rewrite, and connection pooling.
- **Deliverables:** `core/proxy/proxy.go`

### STORY 2.2 — Request Scheduler & Concurrency Control
- **Owner:** Keshav
- **Tasks:** Semaphore channel concurrency limiter with waiting queue timeouts and active/waiting telemetry counters.
- **Deliverables:** `core/scheduler/scheduler.go`

### STORY 2.3 — Rule-Based Traffic Controls
- **Owner:** Keshav
- **Tasks:** Token-bucket rate limiting per client IP, sliding-window burst detection, and single-endpoint abuse tracking, with background memory cleanup managers.
- **Deliverables:** `core/security/rate_limiter.go`, `core/security/traffic_rules.go`

### STORY 2.4 — Decision Engine
- **Owner:** Keshav
- **Tasks:** Multi-tiered mitigation policy translating anomaly scores to actions (`score > 0.85` Block, `score > 0.65` Rate Limit, `score <= 0.65` Allow).
- **Deliverables:** `core/decision/decision_engine.go`

---

## EPIC 3 — Cache Optimization System

**Goal:** Reduce backend origin load through in-memory caching with TTL and memory budgeting.  
**Owner:** Anzal  
**Status:** Completed

### STORY 3.1 — LRU Cache Implementation
- **Tasks:** In-memory doubly linked list + hashmap LRU, byte-level bounds (default 512 MB), lazy expiration, and deep-copy thread safety.
- **Deliverables:** `core/cache/lru_cache.go`, `core/cache/cache.go`, `core/cache/ttl_manager.go`

### STORY 3.2 — Cache Middleware & Stampede Collapse
- **Tasks:** Gin middleware with method/status filtering, response recorder, and `singleflight` request coalescing for concurrent cache misses.
- **Deliverables:** `core/cache/cache_middleware.go`, `core/cache/stampede.go`

### STORY 3.3 — Cache Telemetry
- **Tasks:** Lock-free atomic hit/miss/eviction counters and dashboard telemetry adapter.
- **Deliverables:** `core/cache/cache_metrics.go`, `core/cache/dashboard_adapter.go`

---

## EPIC 4 — Traffic Logging & Data Pipeline

**Goal:** Capture structured request telemetry and extract normalized behavioral feature vectors.  
**Owner:** Anzal  
**Status:** Completed

### STORY 4.1 — Traffic Logging System
- **Tasks:** 4 KB buffered JSON Lines writer with timer-based flushing, flush on graceful shutdown, and HMAC-SHA-256 IP anonymization.
- **Deliverables:** `pipeline/logging/traffic_logger.go`, `pipeline/logging/ip_extractor.go`

### STORY 4.2 — Sliding-Window Feature Extraction
- **Tasks:** Batch sliding-window feature extractor over 60s windows with 10s sub-windows calculating 6 normalized features.
- **Deliverables:** `pipeline/feature_extraction/feature_extractor.py`, `pipeline/feature_extraction/test_feature_extractor.py`

### STORY 4.3 — Dataset Builder
- **Tasks:** Pipeline converting traffic logs into labeled CSV datasets.
- **Deliverables:** `pipeline/dataset_builder/build_dataset.py`, `datasets/traffic_dataset.csv`, `datasets/synthetic_traffic_dataset.csv`, `datasets/attack_dataset.csv`, `datasets/features.csv`

---

## EPIC 5 — Data Analysis & Attack Profiling

**Owner:** Anzal  
**Status:** Completed

### STORY 5.1 — Exploratory Data Analysis
- **Tasks:** Analyze request distributions, entropy clustering, and baseline response latencies.
- **Deliverables:** `notebooks/traffic_analysis.ipynb`

### STORY 5.2 — Attack Simulation Scenarios
- **Tasks:** Synthesize realistic traffic scenarios (DDoS bursts, brute forcing, request flooding, latency attacks).
- **Deliverables:** `ml/data/generate_synthetic_data.py`, `datasets/attack_dataset.csv`

---

## EPIC 6 — Machine Learning System

**Owner:** Keshav  
**Goal:** Train, evaluate, and export anomaly detection models.  
**Status:** Completed

### STORY 6.1 — Model Training & GridSearchCV
- **Tasks:** Train Isolation Forest, One-Class SVM, and Local Outlier Factor via 3-fold cross validation.
- **Deliverables:** `ml/training/train_model.py`

### STORY 6.2 — Model Evaluation & Selection
- **Tasks:** Evaluate models against precision, recall, F1-score, and false positive rates. Selected Isolation Forest (`n_estimators=200`).
- **Deliverables:** `docs/model_evaluation_report.md`

### STORY 6.3 — ONNX Export
- **Tasks:** Export best scikit-learn model to ONNX format using `skl2onnx`.
- **Deliverables:** `ml/export/export_onnx.py` → `models/anomaly_model.onnx`

---

## EPIC 7 — Real-Time ML Inference Integration

**Owner:** Keshav + Anzal  
**Status:** Completed

### STORY 7.1 — In-Process Go ONNX Engine
- **Tasks:** Embed ONNX Runtime in Go via CGO (`yalue/onnxruntime_go`) with non-CGO fallback stub, achieving sub-millisecond inference.
- **Deliverables:** `core/inference/inference.go`, `core/inference/inference_nocgo.go`

### STORY 7.2 — ML Protection Middleware & Ring Buffers
- **Tasks:** In-memory per-IP sliding ring buffers tracking 60s request histories to feed 6D features directly into the ONNX session.
- **Deliverables:** `core/inference/features.go`, `core/inference/middleware.go`

---

## EPIC 8 — Observability & Real-Time Dashboard

**Owner:** Anzal  
**Status:** Completed

### STORY 8.1 — Prometheus Metrics & Port Isolation
- **Tasks:** Canonical Prometheus metrics (`turbosh_requests_total`, `turbosh_request_latency_ms`, scheduler gauges, cache counters, ML alerts) hosted on isolated port `:9090`.
- **Deliverables:** `pipeline/monitoring/metrics.go`, `monitoring/metrics.go`, `monitoring/prometheus.yml`, `monitoring/grafana/`

### STORY 8.2 — Real-Time Dashboard State & Web UI
- **Tasks:** Thread-safe `DashboardState` aggregator, `/api/v1/status` JSON API, zero-dependency dark/light web UI, and demo runner.
- **Deliverables:** `monitoring/dashboard_state.go`, `monitoring/dashboard_api.go`, `ui/dark_desktop_ui.html`, `ui/light_desktop_ui.html`, `scripts/demo.sh`

---

## EPIC 9 — Testing, Hardening & Flaw Remediation

**Owners:** Keshav + Anzal  
**Status:** Completed

### STORY 9.1 — Concurrency Stress Testing & Benchmarking
- **Tasks:** 4-phase stress test (baseline, ramp, sustained, spike) measuring proxy throughput, latency, and rate limiting.
- **Deliverables:** `cmd/loadtest/main.go` → `docs/benchmark_report.md`

### STORY 9.2 — Detection Accuracy Testing
- **Tasks:** End-to-end detection evaluator testing normal browsing against DDoS and scraping profiles. Achieved 91.2% detection rate, 3.3% FPR.
- **Deliverables:** `cmd/accuracy_test/main.go` → `docs/detection_accuracy_report.md`

### STORY 9.3 — Flaw Audit & Hardening
- **Tasks:** Audited all 53 active flaws across memory leaks, metric panics, pipeline ordering, IP salting, and Docker packaging.
- **Deliverables:** `flaws.md`, `docs/RESOURCE_AND_CONCURRENCY_FIXES.md`
