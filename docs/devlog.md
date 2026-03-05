
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