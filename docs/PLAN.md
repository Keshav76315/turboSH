# turboSH — Jira Style Development Plan

**Project:** turboSH
**Goal:** AI‑powered middleware for server optimization and anomaly detection

---

## Team

| Developer | Role                                          |
| --------- | --------------------------------------------- |
| Keshav     | Backend systems + ML engineering              |
| Anzal     | Data pipeline + caching system + data science |

---

## EPIC 1 — Project Foundation & Documentation

**Goal:** Establish project structure and documentation framework.

### STORY 1.1 — Repository Initialization

**Owner:** Keshav

**Tasks:**

- Initialize Git repository
- Setup Go modules
- Setup Python environment
- Create base folder structure

**Deliverables:**

- Project repository initialized
- Development environments configured

### STORY 1.2 — Documentation System

**Owner:** Anzal

**Tasks:**

- Create `/docs` folder and add:
  - `PLAN.md`
  - `PROGRESS.md`
  - `AGENT.md`
  - `README.md`
  - `ARCHITECTURE.md`
  - `DATA_SCHEMA.md`
  - `API.md`

**Deliverables:**

- `docs/` folder with all documentation templates

### STORY 1.3 — Architecture Definition

**Owner:** Keshav

**Tasks:**

- Create system architecture diagram
- Define request pipeline
- Define module ownership

**Deliverables:**

- `docs/ARCHITECTURE.md`

---

## EPIC 2 — Core Middleware System

**Goal:** Build the middleware that handles incoming traffic.
**Owner:** Keshav

### STORY 2.1 — Reverse Proxy Middleware

**Tasks:**

- Implement reverse proxy
- Setup request forwarding
- Handle concurrent requests

**Deliverables:**

- `/core/proxy/proxy.go`

### STORY 2.2 — Request Scheduler

**Tasks:**

- Implement request queue
- Implement priority scheduling
- Implement concurrency control

**Deliverables:**

- `/core/scheduler/scheduler.go`
- `/core/scheduler/queue.go`

### STORY 2.3 — Traffic Control Algorithms

**Tasks:**

- Implement IP rate limiter
- Implement burst detection
- Implement endpoint abuse detection

**Deliverables:**

- `/core/security/rate_limiter.go`
- `/core/security/traffic_rules.go`

### STORY 2.4 — Decision Engine

**Tasks:**

- Process ML anomaly score
- Translate score into actions

**Rules example:**

| Score          | Action     |
| -------------- | ---------- |
| `score > 0.85` | Block      |
| `score > 0.65` | Rate limit |
| else           | Allow      |

**Deliverables:**

- `/core/decision/decision_engine.go`

---

## EPIC 3 — Cache Optimization System

**Goal:** Reduce backend load through intelligent caching.
**Owner:** Anzal

### STORY 3.1 — LRU Cache Implementation

**Tasks:**

- Implement in‑memory LRU cache
- Implement TTL expiration
- Handle thread safety
- Implement memory limits

**Deliverables:**

- `/core/cache/cache.go`
- `/core/cache/lru_cache.go`
- `/core/cache/ttl_manager.go`

### STORY 3.2 — Cache Integration

**Tasks:**

- Intercept incoming requests
- Check cache before backend request
- Store responses in cache

**Flow:**

```
request
   ↓
cache lookup
   ↓
hit  → return response
miss → forward request
```

**Deliverables:**

- Cache middleware integration

### STORY 3.3 — Cache Metrics

**Tasks:**

- Track:
  - Cache hit rate
  - Cache miss rate
  - Cache eviction events

**Metrics:**

- `cache_hit_rate`
- `cache_miss_rate`
- `cache_evictions`

---

## EPIC 4 — Traffic Logging & Data Pipeline

**Goal:** Produce ML‑ready datasets from server traffic.
**Owner:** Anzal

### STORY 4.1 — Traffic Logging System

**Tasks:**

- Define traffic log schema
- Implement logging middleware
- Store structured logs

**Example fields:**

- `timestamp`
- `ip_hash`
- `endpoint`
- `status_code`
- `response_time`
- `request_size`

**Deliverables:**

- `/pipeline/logging/traffic_logger.go`
- `/pipeline/logging/log_schema.md`

### STORY 4.2 — Feature Extraction Pipeline

**Tasks:**

- Compute traffic features:
  - `requests_per_ip_10s`
  - `requests_per_ip_60s`
  - `endpoint_entropy`
  - `latency_spike`
  - `error_rate`

**Deliverables:**

- `/pipeline/feature_extractor.py`

### STORY 4.3 — Dataset Builder

**Tasks:**

- Convert logs into ML datasets
- Generate training data

**Deliverables:**

- `datasets/traffic_dataset.csv`
- `datasets/attack_dataset.csv`

---

## EPIC 5 — Data Analysis & Feature Engineering

**Owner:** Anzal

### STORY 5.1 — Exploratory Data Analysis

**Tasks:**

- Analyze traffic distributions
- Identify baseline traffic patterns
- Visualize traffic spikes

**Deliverables:**

- `notebooks/traffic_analysis.ipynb`

### STORY 5.2 — Attack Simulation

**Tasks:**

- Simulate attacks:
  - DDoS bursts
  - Endpoint scanning
  - Brute force attempts

**Deliverables:**

- `datasets/attack_traffic.csv`

---

## EPIC 6 — Machine Learning System

**Owner:** Keshav
**Goal:** Detect anomalous traffic patterns.

### STORY 6.1 — ML Model Training

**Tasks:**

- Train models:
  - Isolation Forest
  - One‑Class SVM
  - Local Outlier Factor

**Deliverables:**

- `/ml/train_model.py`

### STORY 6.2 — Model Evaluation

**Tasks:**

- Evaluate models using:
  - Precision
  - Recall
  - F1 Score
  - ROC-AUC

**Deliverables:**

- `docs/model_evaluation_report.md`

### STORY 6.3 — Model Export

**Tasks:**

- Export trained model
- **Preferred format:** ONNX

**Deliverables:**

- `/models/anomaly_model.onnx`

---

## EPIC 7 — ML Inference Integration

**Owner:** Keshav

### STORY 7.1 — ML Inference Engine

**Tasks:**

- Load trained model
- Accept feature vectors
- Output anomaly scores

**Deliverables:**

- ML inference system

### STORY 7.2 — Middleware Integration

**Tasks:**

- Connect: `feature pipeline → ML model → decision engine`

**Deliverables:**

- AI integrated middleware

---

## EPIC 8 — Monitoring & Observability

**Owner:** Anzal

### STORY 8.1 — Metrics Collector

**Track:**

- Request throughput
- Scheduler queue length
- Cache hit rate
- Anomaly alerts

**Deliverables:**

- `/monitoring/metrics.go`

### STORY 8.2 — Grafana Dashboard

**Tasks:**

- Setup Prometheus
- Create Grafana dashboards

**Deliverables:**

- System monitoring dashboard

---

## EPIC 9 — Testing & Optimization

**Owners:** Keshav + Anzal

### STORY 9.1 — Load Testing

**Tasks:**

- Simulate heavy traffic
- Measure system performance

**Deliverables:**

- Performance benchmark report

### STORY 9.2 — Detection Accuracy Testing

**Tasks:**

- Test ML accuracy
- Evaluate false positives

**Deliverables:**

- Model performance report

---

## Project Phases Overview

| Phase   | Focus                         |
| ------- | ----------------------------- |
| Phase 1 | Project setup & documentation |
| Phase 2 | Core middleware development   |
| Phase 3 | Cache system                  |
| Phase 4 | Data pipeline                 |
| Phase 5 | ML model training             |
| Phase 6 | ML integration                |
| Phase 7 | Monitoring                    |
| Phase 8 | Testing & optimization        |

---

## Final Ownership Summary

| System Component   | Owner |
| ------------------ | ----- |
| Reverse Proxy      | Keshav |
| Scheduler          | Keshav |
| Traffic Control    | Keshav |
| Decision Engine    | Keshav |
| ML Models          | Keshav |
| ML Inference       | Keshav |
| Monitoring         | Keshav |
| Cache System       | Anzal |
| Traffic Logging    | Anzal |
| Feature Extraction | Anzal |
| Dataset Pipeline   | Anzal |
| Data Analysis      | Anzal |
