# Kevin's Role in turboSH

You are the **Backend Systems Engineer** and **ML Systems Engineer** for the project **turboSH**, an AI‑powered middleware designed to:

- Optimize server performance
- Detect anomalous traffic
- Mitigate potential attacks

The system acts as an intelligent middleware layer between clients and backend servers.

**Your responsibilities include:**

- Backend infrastructure algorithms
- Machine learning model training
- ML inference integration
- System decision logic
- Observability and metrics

**You must work in coordination with Anzal**, who is responsible for:

- Traffic logging
- Data pipelines
- Feature engineering
- Dataset generation
- Exploratory analysis

Your systems will consume the processed features produced by Anzal.

---

## System Architecture Context

The full request flow is:

```
Client
  ↓
Reverse Proxy (Kevin)
  ↓
Scheduler / Rate Limiter (Kevin)
  ↓
Cache Layer (Kevin + Anzal)
  ↓
Traffic Logger (Anzal)
  ↓
Feature Extraction (Anzal)
  ↓
ML Inference Engine (Kevin)
  ↓
Decision Engine (Kevin)
  ↓
Backend Server
```

**Your systems operate primarily in:**

- `/core`
- `/ml`
- `/models`

**Anzal operates mainly in:**

- `/pipeline`
- `/datasets`
- `/notebooks`

---

## Part 1 — Reverse Proxy Middleware

You will build the primary middleware server responsible for handling client traffic.

**Responsibilities:**

- Request routing
- Concurrency management
- Forwarding requests to backend services

**Recommended libraries:**

- `net/http`
- `httputil.ReverseProxy`
- `gin-gonic/gin`

**Deliverables:**

- `/core/proxy/proxy.go`

**Capabilities:**

- Concurrent request handling
- Request forwarding
- Logging hooks for the data pipeline

---

## Part 2 — Request Scheduler

Build the traffic scheduling system to control load on the backend.

**Algorithms to implement:**

- Request queue
- Priority scheduling
- Burst detection
- Rate limiting

**Example flow:**

```
incoming request
      ↓
scheduler queue
      ↓
allowed request
```

**Deliverables:**

- `/core/scheduler/scheduler.go`
- `/core/scheduler/queue.go`

**Goals:**

- Prevent server overload
- Smooth traffic spikes
- Maintain fairness across clients

---

## Part 3 — Traffic Control Algorithms

Implement rule‑based protections that function even if ML is disabled.

**Examples:**

| Rule                     | Behavior                                 |
| ------------------------ | ---------------------------------------- |
| Rate limiting            | `requests_per_ip > threshold` → throttle |
| Burst detection          | Sudden traffic spike → slow requests     |
| Endpoint abuse detection | Excessive requests to same endpoint      |

**Deliverables:**

- `/core/security/rate_limiter.go`
- `/core/security/traffic_rules.go`

---

## Part 4 — Cache Management

Integrate the cache layer into the request pipeline.

**The cache system should:**

- Store frequently requested responses
- Reduce backend load
- Track hit/miss statistics

**Cache type:** LRU with TTL

**Deliverables:**

- `/core/cache/cache_manager.go`

---

## Part 5 — Metrics and Observability

Implement monitoring infrastructure.

**Metrics to expose:**

- Request throughput
- Scheduler queue length
- Cache hit rate
- Anomaly detection events

**Expose endpoint:** `/metrics`

**Use:** Prometheus client library

**Deliverables:**

- `/monitoring/metrics.go`

Metrics will be visualized using Grafana dashboards.

---

## Part 6 — Machine Learning Model Lifecycle

You are responsible for training, evaluating, and deploying the ML models.

Input data will come from Anzal's feature pipeline.

**Expected feature format:**

| Feature            |
| ------------------ |
| `timestamp`        |
| `ip_hash`          |
| `endpoint_entropy` |
| `request_rate_10s` |
| `request_rate_60s` |
| `error_rate`       |
| `latency_spike`    |

### ML Model Development

Train anomaly detection models.

**Recommended models:**

- Isolation Forest
- One‑Class SVM
- Local Outlier Factor

**Optional advanced:**

- LSTM Autoencoder

**Deliverables:**

- `/ml/train_model.py`
- `/ml/evaluate_model.py`

### Model Evaluation

Evaluate model performance using:

- Precision
- Recall
- F1 Score
- ROC-AUC

**Testing datasets will include:**

- Normal traffic
- Simulated DDoS attacks
- Endpoint scanning
- Brute force login attempts

**Deliverable:** `docs/model_evaluation_report.md`

### Model Export

Export the trained model to a deployable format.

- **Preferred format:** ONNX
- **Output location:** `/models/anomaly_model.onnx`

This model will be loaded during runtime.

### Real-Time Inference Engine

Integrate ML predictions into the system.

**Two possible architectures:**

| Option | Approach                                                  |
| ------ | --------------------------------------------------------- |
| 1      | Local Python inference service (FastAPI, `POST /predict`) |
| 2      | Embedded ONNX runtime in Go (removes Python dependency)   |

### Decision Engine

Translate ML predictions into system actions.

**Example policy:**

| Score          | Action     |
| -------------- | ---------- |
| `score > 0.85` | BLOCK IP   |
| `score > 0.65` | RATE LIMIT |
| `score < 0.65` | ALLOW      |

**Deliverables:**

- `/core/decision/decision_engine.go`

---

## Performance Targets

The ML inference system should achieve:

- **< 50 ms** inference latency

**Optimization methods:**

- Batch predictions
- Async processing
- Cached feature vectors

---

## Documentation System

All documentation must be maintained inside `/docs`. This directory coordinates development across both developers.

### `docs/PLAN.md`

Contains the project development plan.

**Structure:**

- Project overview & architecture summary
- Kevin plan & Anzal plan
- Milestones

Each developer maintains their own section.

### `docs/PROGRESS.md`

Tracks development history.

**Example:**

```
[2026-03-04] Kevin
  Implemented reverse proxy

[2026-03-05] Anzal
  Completed feature extraction pipeline
```

**Purpose:**

- Track system changes
- Avoid overlapping work
- Maintain project history

### `docs/AGENT.md`

Context file for AI development assistants.

**This file should include:**

- Project summary
- Architecture overview
- Module descriptions
- Developer responsibilities
- Current development status

AI agents should read this file before performing any task.

### `docs/README.md`

Main repository entry point.

**Contents:**

- Project overview
- Architecture diagram
- Quick start guide
- Installation
- Usage instructions
- Developer roles
- Documentation links

### Additional Recommended Docs

| File                   | Description                                        |
| ---------------------- | -------------------------------------------------- |
| `docs/ARCHITECTURE.md` | Detailed explanation of system components          |
| `docs/API.md`          | Internal APIs between middleware, pipeline, and ML |
| `docs/MODELS.md`       | ML model training and usage                        |

---

## Collaboration Rules

To prevent merge conflicts:

**Kevin owns:**

- `/core`
- `/ml`
- `/models`
- `/monitoring`

**Anzal owns:**

- `/pipeline`
- `/datasets`
- `/notebooks`

Shared interaction occurs through feature vector interfaces only.

---

## Kevin's Expected Deliverables

By the end of development you should produce:

- Reverse proxy middleware
- Request scheduling algorithms
- Rate limiting and traffic control
- ML anomaly detection models
- ML evaluation reports
- Real-time inference system
- Decision engine for mitigation
- System monitoring infrastructure

The final system should be capable of:

- Detecting anomalous traffic
- Mitigating attacks
- Optimizing backend resource usage

…while remaining lightweight enough to run on commodity hardware.
