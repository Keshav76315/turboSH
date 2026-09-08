# TurboSH Resource Management, Concurrency & Lifecycle Architecture

This document details the architectural principles, fixes, and verification results for **Section 7 (Memory Leaks & Concurrency Issues)** as well as related pipeline and security invariants resolved in TurboSH.

---

## 1. Architectural Core Principle: Bounded State & Explicit Lifecycles

In an ML-based continuous traffic proxy, unbounded memory accumulation corrupts both system resource limits and ML feature extraction integrity. TurboSH enforces bounded state and explicit goroutine lifecycles across all components:

```
Unbounded Input Stream (Network Traffic)
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│                   Bounded Active State                  │
│                                                         │
│ - LRU Cache:      c.removeElement() memory accounting   │
│ - Rate Limiter:   Background bucket cleanup (10m idle)  │
│ - Traffic Rules:  Sliding window timestamp cleanup (30s)│
│ - ML Protection:  PruneAll abandoned client IPs (60s)   │
│ - Endpoints:      Windowed strictly within 60s window   │
│ - Metric Poller:  Managed lifecycle with stop channel   │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Summary of Fixes

### 7.1 — Unified TTL Memory Accounting
- **Files:** [`core/cache/lru_cache.go`](../core/cache/lru_cache.go), [`core/cache/ttl_manager.go`](../core/cache/ttl_manager.go)
- **Problem:** TTL expiration removed elements from the list and map but failed to decrement `c.currentMemory` and record eviction metrics. Over time, internal memory accounting drifted upward, causing premature evictions.
- **Fix:** Standardized all eviction and deletion paths through a unified `c.removeElement(element)` helper that decrements `c.currentMemory -= ent.size` and records eviction metrics in both `ttl_manager.go` and `lru_cache.go`.

### 7.2 — RateLimiter Inactive Bucket Cleanup
- **Files:** [`core/security/rate_limiter.go`](../core/security/rate_limiter.go), [`core/proxy/middleware.go`](../core/proxy/middleware.go)
- **Problem:** `RateLimiter.Cleanup(maxAge)` was implemented but never invoked by any background worker. High client cardinality caused `rl.buckets` to grow indefinitely.
- **Fix:** Added `StartCleanupManager(interval, maxAge time.Duration) chan struct{}`. Configured in `NewComponents` to run every 30s evicting client buckets inactive for >10 minutes.

### 7.3 — TrafficRules Sliding Window Cleanup
- **Files:** [`core/security/traffic_rules.go`](../core/security/traffic_rules.go), [`core/proxy/middleware.go`](../core/proxy/middleware.go)
- **Problem:** `burstTracker` and `endpointTracker` maps never evicted old client timestamps if the client stopped sending requests, leaking memory during distributed IP scans.
- **Fix:** Added `StartCleanupManager(interval time.Duration) chan struct{}`. Configured in `NewComponents` to clean expired sliding window entries every 30 seconds.

### 7.4 — MLProtection Abandoned IP Accumulation & Windowed Endpoints
- **File:** [`core/inference/middleware.go`](../core/inference/middleware.go)
- **Problem:**
  1. `prune()` was only invoked for the active client IP on incoming requests. Abandoned single-request client IPs remained in memory indefinitely.
  2. `endpoints[ip]` counters were never decremented or windowed, accumulating lifetime visit counts and skewing entropy calculations.
- **Fix:**
  - Replaced unwindowed endpoint maps with timestamped `requestRecord` events. Endpoint entropy is now calculated strictly over requests within the active 60-second window.
  - Implemented `PruneAll(now time.Time)` and `StartCleanupManager(interval time.Duration)` to purge abandoned client IPs after 60 seconds of inactivity.

### 7.5 — Managed Metric Poller Lifecycle & Centralized Shutdown
- **File:** [`core/proxy/middleware.go`](../core/proxy/middleware.go)
- **Problem:** The gauge metric poller ran an infinite `for { time.Sleep(1 * time.Second) }` goroutine without a cancellation channel, leaking background goroutines across test runs and restarts.
- **Fix:** Replaced with a `time.NewTicker` listening to a dedicated `PollerStop` channel. Added `Components.Close()` to provide a centralized graceful shutdown mechanism for all background workers.

### 7.6 — Single-Lock LRU Cache Access
- **File:** [`core/cache/lru_cache.go`](../core/cache/lru_cache.go)
- **Problem:** `Get()` used an `RLock() -> RUnlock() -> Lock()` sequence. Because an LRU cache hit must update node order (`MoveToFront`), write locks are required on hits. The double-lock pattern caused lock bouncing and redundant map lookups under high concurrent read load.
- **Fix:** Switched `Get()` to an exclusive `c.mu.Lock()` with `defer c.mu.Unlock()`. Eliminates lock bouncing and redundant map lookups.

### 7.7 — Deep Copy Cache Isolation
- **File:** [`core/cache/lru_cache.go`](../core/cache/lru_cache.go)
- **Problem:** `Set()` performed a shallow copy (`valCopy := *value`), sharing `Headers` (`map[string][]string`) and `Body` (`[]byte`) references with the caller. Subsequent mutations by callers or concurrent handlers corrupted cached data and induced data races.
- **Fix:** Added `copyResponse()` to perform full deep copies of headers and body buffers on both `Set()` and `Get()`, ensuring the cache strictly owns its internal state.

---

## 3. Verification & Race Detection

### Automated Test Suite
- **Cache Tests (`core/cache`)**:
  - `TestDeepCopyIsolation`: Verifies mutations to original structs or returned copies do not affect cached memory.
  - `TestTTLMemoryDecrement`: Verifies `CurrentMemory()` returns to 0 upon entry expiration.
  - `TestConcurrencyStress`: Verifies concurrent read, write, and delete operations without panics or deadlocks.
- **Security Tests (`core/security`)**:
  - `TestRateLimiterCleanup`: Verifies inactive IP buckets are pruned while active buckets remain.
  - `TestTrafficRulesCleanup`: Verifies expired sliding window timestamps are pruned.
  - `TestCleanupManagersStop`: Verifies cleanup manager stop channels terminate background worker goroutines.
- **Inference Tests (`core/inference`)**:
  - `TestMLProtectionPruneAll`: Verifies abandoned client IPs are purged.
  - `TestMLProtectionWindowedEndpoints`: Verifies old endpoints age out and do not contaminate Shannon entropy.
- **Lifecycle Tests (`core/proxy`)**:
  - `TestComponentsLifecycle`: Verifies `Components.Close()` halts all background workers cleanly.

### Go Race Detector Execution
```bash
go test -race ./...
```
**Result:** Passed across all packages with zero data races detected and all unit tests passing.
