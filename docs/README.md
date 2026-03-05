# turboSH

> AI‑powered middleware for server optimization and anomaly detection.

---

## What is turboSH?

turboSH is an intelligent middleware layer that sits between clients and backend servers. It automatically:

- **Schedules and rate-limits** incoming requests to prevent overload
- **Caches** frequent responses to reduce backend load
- **Logs** traffic and extracts behavioral features
- **Detects anomalies** using machine learning (Isolation Forest, One‑Class SVM, LOF)
- **Mitigates threats** automatically (block, throttle, or allow)

Designed to run on commodity hardware — no GPU required.

---

## Architecture

```
Client → Reverse Proxy → Scheduler → Cache → Traffic Logger
                                                    ↓
                              Backend ← Decision ← ML Inference ← Feature Extraction
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

---

## Repository Structure

```
turboSH/
├── core/           Middleware components (proxy, scheduler, cache, security, decision)
├── pipeline/       Data pipeline (logging, feature extraction, dataset builder)
├── ml/             ML model training and evaluation
├── models/         Trained model artifacts (.onnx)
├── monitoring/     Prometheus metrics and dashboards
├── datasets/       Generated traffic datasets
├── notebooks/      Jupyter notebooks for analysis
└── docs/           Project documentation
```

---

## Tech Stack

| Layer         | Technology                      |
| ------------- | ------------------------------- |
| Middleware    | Go (`net/http`, `gin`)          |
| Data Pipeline | Go + Python (`pandas`, `numpy`) |
| ML            | Python (`scikit-learn`, `ONNX`) |
| Monitoring    | Prometheus + Grafana            |

---

## Getting Started

### Prerequisites

- Go 1.26+
- Python 3.10+

### Setup

```bash
# Clone
git clone https://github.com/Keshav76315/turboSH.git
cd turboSH

# Go dependencies
go mod tidy

# Python environment
python -m venv .venv
.venv/Scripts/Activate      # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

---

## Team

| Developer | Role                                          |
| --------- | --------------------------------------------- |
| Keshav     | Backend systems + ML engineering              |
| Anzal     | Data pipeline + caching system + data science |

---

## Documentation

| Document                                | Description                        |
| --------------------------------------- | ---------------------------------- |
| [PLAN.md](docs/PLAN.md)                 | Development plan (EPICs & stories) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture & interfaces   |
| [PROGRESS.md](docs/PROGRESS.md)         | Development history                |
| [AGENT.md](docs/AGENT.md)               | AI agent context                   |
| [DATA_SCHEMA.md](docs/DATA_SCHEMA.md)   | Log & feature schemas              |
| [API.md](docs/API.md)                   | Internal API definitions           |

---

## License

TBD
