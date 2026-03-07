# The turboSH Playbook

Welcome to **turboSH**! This playbook is a definitive guide on how to integrate and deploy the world's first Intelligent ML-Powered Reverse Proxy into your own existing infrastructure.

---

## 🚀 1. What is turboSH?

`turboSH` is an AI-native reverse proxy built in Go. It sits between the internet and your backend API. Instead of relying on static, hardcoded rate limits (which sophisticated attackers can easily bypass), turboSH uses an **Isolation Forest machine learning model** to actively evaluate incoming traffic.

**It automatically defends your backend against:**

1. **DDoS Bursts:** Sudden massive spikes from a single hashed IP.
2. **Endpoint Scraping:** High-entropy, randomized scans looking for hidden endpoints.
3. **Backend Stress:** If an IP is repeatedly causing your backend to return `500 Internal Server Error` or high latency responses, turboSH identifies that correlation and throttles/blocks the offender.

On top of this, it provides **in-memory caching** and a **fair-queueing scheduler** to ensure your backend never gets overwhelmed.

---

## 🐳 2. Quick Start (Plug-and-Play Docker)

You do not need Go, Python, or C compilers installed to use turboSH. Everything you need (including the ML engine and ONNX bindings) is bundled into a single lightweight Docker container.

### Step 1: Build the image

Run this once from the root of the repository:

```bash
docker build -t turbosh-proxy .
```

### Step 2: Drop it in front of your API

Assuming you have an existing application running on `http://api.mycompany.com:5000`:

```bash
docker run -d \
  --name turbosh \
  -p 8080:8080 \
  -e TURBOSH_BACKEND="http://api.mycompany.com:5000" \
  turbosh-proxy
```

Now, point your DNS or load balancer to port `8080` of the turboSH container. **That's it!** Your API is now protected by an ML-anomaly detection engine, in-memory caching, and request scheduling.

---

## ⚙️ 3. Environment Variable Reference

You can customize almost every aspect of the proxy's behavior by passing environment variables (via Docker `-e` flags or a `.env` file).

### Network & Routing

| Variable                  | Default                 | Description                                                                                                                                                                                                         |
| :------------------------ | :---------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `TURBOSH_PORT`            | `:8080`                 | The port turboSH listens on.                                                                                                                                                                                        |
| `TURBOSH_BACKEND`         | `http://localhost:9090` | The exact URL of the upstream server it protects.                                                                                                                                                                   |
| `TURBOSH_IP_SALT`         | `turboSH_default_salt`  | The salt used to locally hash visitor IPs. Change this in production for privacy.                                                                                                                                   |
| `TURBOSH_TRUSTED_PROXIES` | _None_                  | Comma-separated list of IP CIDRs (e.g. `10.0.0.0/8,192.168.0.0/16`) of load balancers. Required to safely parse `X-Forwarded-For` headers so the ML engine tracks the real user IP instead of the Load Balancer IP. |

### Scheduler & Protection Limits

| Variable                      | Default | Description                                               |
| :---------------------------- | :------ | :-------------------------------------------------------- |
| `TURBOSH_MAX_CONCURRENT`      | `100`   | Max simultaneous connections allowed to hit your backend. |
| `TURBOSH_RATE_LIMIT_CAPACITY` | `10`    | Baseline token bucket capacity per IP.                    |
| `TURBOSH_RATE_LIMIT_RATE`     | `2.0`   | Tokens refilled per second per IP.                        |

### Machine Learning Engine

| Variable                       | Default | Description                                                                     |
| :----------------------------- | :------ | :------------------------------------------------------------------------------ |
| `TURBOSH_BLOCK_THRESHOLD`      | `0.85`  | Anomaly score (0.0 - 1.0) above which a request yields a harsh `403 Forbidden`. |
| `TURBOSH_RATE_LIMIT_THRESHOLD` | `0.65`  | Anomaly score above which a request yields a soft `429 Too Many Requests`.      |

### Caching

| Variable                 | Default | Description                                                        |
| :----------------------- | :------ | :----------------------------------------------------------------- |
| `TURBOSH_CACHE_CAPACITY` | `1000`  | Max number of distinct HTTP responses the proxy will cache in RAM. |
| `TURBOSH_CACHE_TTL`      | `5m`    | How long an item stays in cache (Go duration string).              |

---

## 📊 4. Monitoring Stack Integration

turboSH natively exposes Prometheus metrics for the ML Engine, Caching, and Request flow out-of-the-box.

### The `/metrics` Endpoint

When the proxy is running, navigate to `http://<turbosh-ip>:8080/metrics` to see the raw Prometheus exposition format.

### Connecting Your Grafana

If you already run Prometheus and Grafana in your cluster:

1. Add a scrape job pointing to the turboSH proxy IP on port `8080`.
2. Import the official **turboSH — System Monitor** dashboard located in [`monitoring/grafana/dashboards/turbosh.json`](monitoring/grafana/dashboards/turbosh.json).

You will instantly get real-time graphs showing:

- Cache Hit / Miss Rates
- P50, P95, and P99 Latencies
- Active ML Interventions (Red lines for Blocks, Orange for Throttles)
- Scheduler Saturation

---

_For architectural details regarding how the ML models were trained, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)._
