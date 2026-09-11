# turboSH — AI Agent Context

> **Read this file first** before performing any development task on the turboSH project.

---

## Project Summary

turboSH is an AI‑powered middleware system that sits between clients and backend servers. It intercepts HTTP traffic and applies:

- Request scheduling, concurrency limits, and token-bucket rate limiting
- High-speed LRU response caching with TTL and singleflight stampede collapse
- Structured traffic logging and normalized feature extraction
- Real-time ML‑based anomaly detection via in-process ONNX Runtime
- Automated three-tier threat mitigation (block / rate limit / allow)
- Full-stack observability: isolated Prometheus metrics and a live real-time browser dashboard

The system is designed to run on commodity hardware without GPUs.

---

## Repository Structure

```
turboSH/
├── cmd/                     ← Application entry points & test tools
│   ├── turbosh/             Main reverse proxy server entry point
│   ├── dummy_backend/       Upstream backend simulator (:9092)
│   ├── loadtest/            4-phase concurrent stress testing tool
│   ├── accuracy_test/       ML detection rate & FPR evaluator
│   └── attacker/            Targeted attack traffic generator
├── core/                    ← Go: middleware components (Keshav & Anzal)
│   ├── proxy/               Reverse proxy & middleware pipeline assembly
│   ├── scheduler/           Concurrency limiter & active/waiting queue tracking
│   ├── cache/               LRU cache, TTL manager, singleflight (Anzal)
│   ├── security/            Token-bucket rate limiter & traffic abuse rules
│   ├── inference/           In-process CGO ONNX Runtime engine & sliding windows
│   └── decision/            ML anomaly score → action mapping
├── pipeline/                ← Go/Python: data pipeline (Anzal)
│   ├── logging/             Traffic logger, buffered I/O, canonical IP extractor
│   ├── monitoring/          Canonical Prometheus metrics & Gin middleware
│   ├── feature_extraction/  Sliding-window log → feature vectors
│   └── dataset_builder/     Feature vectors → CSV datasets
├── ml/                      ← Python: ML system (Keshav)
│   ├── data/                Synthetic dataset generator (argparse CLI)
│   ├── training/            Model training scripts & GridSearchCV
│   ├── export/              Model export to ONNX format (skl2onnx)
│   └── evaluation/          Model evaluation & validation reports
├── models/                  ← Trained model artifacts (.onnx, .pkl)
├── monitoring/              ← Go: Prometheus metrics & Real-time dashboard state
│   ├── dashboard_state.go   Thread-safe aggregator & latency ring buffer
│   ├── dashboard_api.go     GET /api/v1/status & /dashboard handlers
│   ├── metrics.go           Prometheus metric registrations & aliases
│   ├── prometheus.yml       Prometheus scrape configuration
│   └── grafana/             Grafana dashboard & datasource provisioning
├── ui/                      ← Web: Real-time monitoring frontend (Anzal)
│   ├── dark_desktop_ui.html Self-contained dark-theme desktop dashboard
│   ├── light_desktop_ui.html Self-contained light-theme desktop dashboard
│   ├── dark_mobile_ui.html  Responsive mobile dark dashboard
│   └── light_mobile_ui.html Responsive mobile light dashboard
├── datasets/                ← Generated CSV datasets (Anzal)
├── notebooks/               ← Jupyter notebooks for traffic EDA (Anzal)
├── scripts/                 ← Operational scripts (demo.sh live runner)
└── docs/                    ← Project documentation & reports
```

---

## Developer Roles

| Developer | Owns | Coordinates With |
| :--- | :--- | :--- |
| **Keshav** | `core/{proxy, scheduler, security, inference, decision}`, `ml/`, `models/`, `Dockerfile` | Backend pipeline interfaces, model schemas |
| **Anzal** | `core/cache/`, `pipeline/`, `monitoring/`, `ui/`, `datasets/`, `notebooks/`, `docs/` | Feature vector contracts, middleware pipeline assembly |

---

## Technology Stack

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Middleware & Proxy** | Go 1.24+ (`net/http`, `gin-gonic/gin`) | High-throughput concurrent reverse proxy |
| **Caching Layer** | Go (`sync.RWMutex`, `singleflight`) | In-memory LRU with TTL & byte bounds |
| **Data Pipeline** | Go + Python (`pandas`, `numpy`) | Buffered logging, IP HMAC, sliding windows |
| **ML Training** | Python 3.10+ (`scikit-learn`, `skl2onnx`) | Isolation Forest with GridSearchCV |
| **ML Inference** | Go CGO (`yalue/onnxruntime_go`) | In-process ONNX Runtime ($<1\text{ ms}$) |
| **Metrics & Telemetry** | Prometheus + Grafana | Dedicated administrative listener on `:9090` |
| **Real-Time UI** | Vanilla HTML / CSS / JavaScript | Polling engine fetching `/api/v1/status` |
| **Containerization** | Docker (multi-arch `amd64`/`arm64`) | Production non-root container deployment |

---

## Current Status

**Phase:** Production Ready / Complete (EPICs 1–9 Finished, Full Flaw Audit Remediation Verified, Real-Time Dashboard Active)

- **EPIC 1:** Project setup, documentation, interfaces & schemas
- **EPIC 2:** Core middleware (Reverse proxy, semaphore scheduler, token bucket rate limiter, traffic rules, decision engine)
- **EPIC 3:** LRU cache, TTL background manager, singleflight stampede collapse, byte-level memory limits
- **EPIC 4:** Traffic logging pipeline with buffer flushing, HMAC-SHA-256 IP hashing, batch sliding-window feature extraction
- **EPIC 5:** Data analysis & feature engineering with normalized Shannon entropy
- **EPIC 6:** ML model training & evaluation (Isolation Forest, continuous anomaly scoring, ONNX export)
- **EPIC 7:** Real-time ML inference integration in Go via in-process ONNX Runtime CGO bindings
- **EPIC 8:** Prometheus metrics, Grafana dashboards, and thread-safe Real-Time Dashboard (`/dashboard`, `/api/v1/status`)
- **EPIC 9:** End-to-end integration, Docker multi-arch packaging, load testing, detection accuracy validation, and flaw audit remediation (all 53 active flaws closed)

---

## Key Files

| File | Purpose |
| :--- | :--- |
| `docs/PLAN.md` | Jira-style development plan with EPICs |
| `docs/ARCHITECTURE.md` | System architecture, request pipeline, and component interfaces |
| `docs/PROGRESS.md` | Chronological development and flaw audit history |
| `docs/DATA_SCHEMA.md` | Traffic log, feature vector, dataset, and status API schemas |
| `docs/API.md` | Internal Go APIs, Prometheus metrics, and Dashboard status API |
| `docs/REALTIME_DASHBOARD_DEMO.md` | Real-time monitoring architecture, port allocation, and demo guide |
| `docs/KESHAV.md` | Keshav's role, backend modules, ML lifecycle, and deliverables |
| `docs/ANZAL.md` | Anzal's role, data pipeline, caching, and observability systems |
| `docs/RESOURCE_AND_CONCURRENCY_FIXES.md` | Bounded memory, lifecycle managers, and race detector audit |
| `flaws.md` | Exhaustive flaw audit log and remediation records (53 closed) |
| `scripts/demo.sh` | One-command live demo runner |
| `requirements.txt` | Python dependencies |
| `go.mod` | Go module definition |

---

## Interface Contracts

1. **Traffic Logger → Feature Extraction:** Structured JSON lines (`logs/traffic.jsonl`) with ISO-8601 timestamp, canonical IP hash, endpoint, method, status code, response time, and request size.
2. **In-Process Feature Extraction → ML Inference:** In-memory 6-dimensional float32 vector (`requests_per_ip_10s`, `requests_per_ip_60s`, `endpoint_entropy`, `latency_spike`, `error_rate`, `request_variance`).
3. **ML Inference → Decision Engine:** Continuous anomaly score in $[0.0, 1.0]$ evaluated against `BlockThreshold` (default 0.85) and `RateLimitThreshold` (default 0.65).
4. **Middleware → Dashboard State:** Thread-safe lock-free atomic counters, sliding window RPS, 1,000-sample latency ring buffers, and mitigation event ring buffers served via `GET /api/v1/status`.

---

## Rules for AI Agents

1. Always check `docs/PROGRESS.md` and `flaws.md` for the latest status and verified invariants
2. Respect module ownership — do not modify files outside your assigned directories
3. Follow the verified pipeline order: `Dashboard Recorder → Metrics → Client Identity → Scheduler → Traffic Logger → RateLimiter → TrafficRules → ML Inference → Cache → Proxy`
4. Preserve bounded memory and explicit goroutine lifecycles (use `StartCleanupManager` and `Components.Close()`)
5. Run `go mod tidy` and `go test ./...` after adding or modifying Go code
6. Run Python commands within `.venv`
