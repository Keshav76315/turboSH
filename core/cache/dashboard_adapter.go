package cachesystem

// LRUCacheDashboardAdapter wraps an LRUCache to implement the monitoring.CacheStats interface.
type LRUCacheDashboardAdapter struct {
	cache     *LRUCache
	maxMemory int
	capacity  int
}

// NewDashboardAdapter creates a new adapter for the dashboard.
func NewDashboardAdapter(cache *LRUCache, maxMemory int, capacity int) *LRUCacheDashboardAdapter {
	return &LRUCacheDashboardAdapter{
		cache:     cache,
		maxMemory: maxMemory,
		capacity:  capacity,
	}
}

func (a *LRUCacheDashboardAdapter) Hits() int64 {
	return a.cache.Metrics().Snapshot().Hits
}

func (a *LRUCacheDashboardAdapter) Misses() int64 {
	return a.cache.Metrics().Snapshot().Misses
}

func (a *LRUCacheDashboardAdapter) Evictions() int64 {
	return a.cache.Metrics().Snapshot().Evictions
}

func (a *LRUCacheDashboardAdapter) HitRate() float64 {
	return a.cache.Metrics().Snapshot().HitRate
}

func (a *LRUCacheDashboardAdapter) CurrentMemoryBytes() int {
	return a.cache.CurrentMemory()
}

func (a *LRUCacheDashboardAdapter) MaxMemoryBytes() int {
	return a.maxMemory
}

func (a *LRUCacheDashboardAdapter) EntryCount() int {
	a.cache.mu.RLock()
	defer a.cache.mu.RUnlock()
	return a.cache.order.Len()
}

func (a *LRUCacheDashboardAdapter) EntryCapacity() int {
	return a.capacity
}
