# turboSH — AI Agent Context

> **Read this file first** before performing any development task on the turboSH project.

---

## Project Summary

turboSH is an AI‑powered middleware system that sits between clients and backend servers. It intercepts HTTP traffic and applies:

- Request scheduling and rate limiting
- Response caching
- Traffic logging and feature extraction
- ML‑based anomaly detection
- Automated threat mitigation (block / rate limit / allow)

The system is designed to run on commodity hardware without GPUs.

---

## Repository Structure

```
turboSH/
├── core/                    ← Go: middleware components (Keshav)
│   ├── proxy/               Reverse proxy server
│   ├── scheduler/           Request scheduling & rate limiting
│   ├── cache/               LRU cache with TTL (Anzal)
│   ├── security/            Rule-based traffic control
│   └── decision/            ML score → action mapping
├── pipeline/                ← Go/Python: data pipeline (Anzal)
│   ├── logging/             Traffic log capture
│   ├── feature_extraction/  Log → feature vectors
│   └── dataset_builder/     Feature vectors → CSV datasets
├── ml/                      ← Python: ML system (Keshav)
│   ├── training/            Model training scripts
│   └── evaluation/          Model evaluation & reports
├── models/                  ← Trained model artifacts (.onnx)
├── monitoring/              ← Go: Prometheus metrics (Keshav)
├── datasets/                ← Generated CSV datasets (Anzal)
├── notebooks/               ← Jupyter notebooks (Anzal)
└── docs/                    ← Shared documentation
```

---

## Developer Roles

| Developer | Owns                                                  | Does Not Modify                                              |
| --------- | ----------------------------------------------------- | ------------------------------------------------------------ |
| Keshav     | `core/`, `ml/`, `models/`, `monitoring/`              | `pipeline/`, `datasets/`, `notebooks/`                       |
| Anzal     | `pipeline/`, `datasets/`, `notebooks/`, `core/cache/` | `core/{proxy,scheduler,security,decision}`, `ml/`, `models/` |

---

## Technology Stack

| Component     | Technology                  |
| ------------- | --------------------------- |
| Middleware    | Go (gin, net/http)          |
| Data Pipeline | Go + Python (pandas, numpy) |
| ML Training   | Python (scikit-learn)       |
| ML Inference  | ONNX Runtime                |
| Monitoring    | Prometheus + Grafana        |

---

## Current Status

**Phase:** 1 — Project Foundation & Documentation
**Completed:**

- Repository initialized
- Folder structure created
- Go modules initialized
- Python environment configured
- Documentation system in place
- Architecture defined

**Next:** EPIC 2 — Core Middleware System

---

## Key Files

| File                   | Purpose                                         |
| ---------------------- | ----------------------------------------------- |
| `docs/PLAN.md`         | Jira-style development plan with EPICs          |
| `docs/ARCHITECTURE.md` | System architecture and component interfaces    |
| `docs/PROGRESS.md`     | Development history log                         |
| `docs/DATA_SCHEMA.md`  | Traffic log and feature vector schemas          |
| `docs/API.md`          | Internal API definitions                        |
| `docs/Keshav.md`        | Keshav's detailed development guide (gitignored) |
| `requirements.txt`     | Python dependencies                             |
| `go.mod`               | Go module definition                            |

---

## Interface Contracts

Components communicate through JSON. See `docs/ARCHITECTURE.md` § 7 for the full contracts:

1. **Traffic Logger → Feature Extraction:** JSON lines with request metadata
2. **Feature Extraction → ML Inference:** Feature vectors (JSON)
3. **ML Inference → Decision Engine:** Anomaly score + recommended action (JSON)

---

## Rules for AI Agents

1. Always check `docs/PROGRESS.md` for the latest development status
2. Respect module ownership — do not modify files outside your assigned directories
3. Follow the interface contracts defined in `docs/ARCHITECTURE.md`
4. Update `docs/PROGRESS.md` after completing any work
5. Run `go mod tidy` after adding Go dependencies
6. Run `pip install -r requirements.txt` within `.venv` for Python work
