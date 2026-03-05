# Cache Optimization System

> LRU cache with TTL support for turboSH middleware.

---

## Overview

This package implements the cache layer that sits between the request scheduler and the backend server. It reduces backend load by storing frequently requested responses in memory.

```
request → cache lookup → hit → return cached response
                       → miss → forward to backend → store response
```

---

## Files

| File                | Purpose                                                 |
| ------------------- | ------------------------------------------------------- |
| `cache.go`          | `Cache` interface and `CachedResponse` type             |
| `lru_cache.go`      | LRU cache implementation (hashmap + doubly linked list) |
| `ttl_manager.go`    | Background goroutine for expired entry cleanup          |
| `lru_cache_test.go` | Unit tests (LRU, TTL, combined, concurrency)            |

---

## Design

- **Data structure:** `map[string]*list.Element` + `container/list` (doubly linked list)
- **Eviction policy:** Least Recently Used (LRU) — oldest unused entry removed when capacity is exceeded
- **TTL support:** Dual approach:
  - **Lazy eviction:** Expired entries are removed on `Get()` access
  - **Background cleanup:** A goroutine periodically scans and removes expired entries
- **Thread safety:** `sync.RWMutex` — concurrent reads allowed, exclusive writes

---

## Usage

```go
cache := cache.NewLRUCache(1000) // capacity of 1000 entries

// Start background TTL cleanup (every 30 seconds)
stop := cache.StartTTLManager(30 * time.Second)
defer close(stop)

// Store a response with 5-minute TTL
cache.Set("GET:/api/users", response, 5*time.Minute)

// Retrieve (returns nil, false if expired or not found)
resp, found := cache.Get("GET:/api/users")

// Delete explicitly
cache.Delete("GET:/api/users")
```

---

## Integration Points

- **Input:** Approved requests from the Scheduler
- **Output (hit):** Cached response returned directly to client
- **Output (miss):** Request forwarded to backend via Traffic Logger
- **Metrics:** (planned) `cache_hit_rate`, `cache_miss_rate`, `cache_evictions`

See [ARCHITECTURE.md](../../docs/ARCHITECTURE.md) § 3.3 and [API.md](../../docs/API.md) § 1.3 for interface contracts.
