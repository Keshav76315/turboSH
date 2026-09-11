# Devlog

## Date: March 5, 2026

### Added LRU Cache System
- Created an in-memory caching system using a doubly linked list + hashmap pattern.
- Implemented LRU (Least Recently Used) eviction algorithm to maintain a fixed cache capacity.
- Created `LRUCache.Get`, `LRUCache.Set`, and `LRUCache.Delete` methods to interact with the cache, fully implementing the `Cache` interface in `cache.go`.
- Designed a TTL (Time-To-Live) eviction strategy:
  1. Lazy eviction built into `Get()` checks for expiration when accessing the cache.
  2. Background TTL manager (`StartTTLManager`) runs a goroutine traversing the cache and evicting expired entries actively, keeping memory clean.
- Added thread safety using `sync.Mutex` on all cache accessor/modifier functions to prevent race conditions when accessed by multiple goroutines.
- Verified system functionality using Go's built-in testing features (`lru_cache_test.go`) and race condition detector (`go test -race`).

---

## Date: March 7, 2026

### Machine Learning, In-Process Inference & Observability
- Integrated scikit-learn Isolation Forest model via GridSearchCV into the pipeline.
- Exported model to ONNX format and embedded ONNX Runtime into Go using `yalue/onnxruntime_go` CGO bindings, eliminating Python runtime dependencies for inference.
- Implemented real-time ML Protection middleware with in-memory sliding ring buffers computing windowed features.
- Configured Prometheus metrics on `/metrics` and built initial Grafana dashboards.
- Built end-to-end testing tools: `cmd/loadtest/main.go` and `cmd/accuracy_test/main.go`.

---

## Date: September 8, 2026

### Security Hardening & Concurrency Audit
- Re-architected middleware order: Traffic Logger wraps all requests (capturing hits and blocks), and ML Inference runs prior to Cache.
- Implemented canonical IP extraction and HMAC-SHA-256 anonymization in `pipeline/logging/ip_extractor.go` with trusted proxy verification (`TURBOSH_TRUSTED_PROXIES`).
- Added in-process TLS termination support (`TURBOSH_TLS_ENABLED`, `TURBOSH_TLS_CERT`, `TURBOSH_TLS_KEY`).
- Standardized TTL and LRU memory accounting in `core/cache/`, preventing upward memory drift.
- Added background cleanup managers to `RateLimiter`, `TrafficRules`, and `MLProtection` to evict inactive client IPs and bound memory.
- Converted `LRUCache.Get()` to single-lock pattern and introduced deep-copy response isolation.
- Fixed Prometheus metric label conversions, consolidated duplicate registrations, and aligned Grafana PromQL queries.
- Added graceful shutdown handling with signal trapping and resource cleanup via `Components.Close()`.

---

## Date: September 9, 2026

### Mathematical Unification, Flaw Closure & Real-Time Dashboard
- Unified Shannon entropy normalization in Go and Python to $H / \log_2(N) \in [0.0, 1.0]$.
- Standardized latency spike thresholds across Python and Go (`> 1.5x avg and > 100ms`).
- Replaced whole-log averaging with 60s sliding window feature extraction in `pipeline/feature_extraction/feature_extractor.py`.
- Closed all 53 active flaws in `flaws.md`.
- Implemented thread-safe `DashboardState` aggregator in `monitoring/dashboard_state.go` with rolling latency tracking and threat mitigation ring buffer.
- Added `/api/v1/status` JSON API and embedded web dashboards in `ui/` (`dark_desktop_ui.html`, `light_desktop_ui.html`).
- Created one-command demo runner `scripts/demo.sh` for complete live demonstrations.