package cachesystem

import (
	"sync/atomic"
)

// CacheMetrics tracks cache performance counters using lock-free atomics.
// Safe for concurrent use from multiple goroutines.
type CacheMetrics struct {
	hits      atomic.Int64
	misses    atomic.Int64
	evictions atomic.Int64
}

// RecordHit increments the hit counter.
func (m *CacheMetrics) RecordHit() { m.hits.Add(1) }

// RecordMiss increments the miss counter.
func (m *CacheMetrics) RecordMiss() { m.misses.Add(1) }

// RecordEviction increments the eviction counter.
func (m *CacheMetrics) RecordEviction() { m.evictions.Add(1) }

// MetricsSnapshot is a point-in-time copy of all cache metrics.
type MetricsSnapshot struct {
	Hits      int64   `json:"cache_hits"`
	Misses    int64   `json:"cache_misses"`
	Evictions int64   `json:"cache_evictions"`
	HitRate   float64 `json:"cache_hit_rate"`
}

// Snapshot returns a consistent, point-in-time copy of all metrics.
func (m *CacheMetrics) Snapshot() MetricsSnapshot {
	h := m.hits.Load()
	mi := m.misses.Load()
	total := h + mi

	var rate float64
	if total > 0 {
		rate = float64(h) / float64(total)
	}

	return MetricsSnapshot{
		Hits:      h,
		Misses:    mi,
		Evictions: m.evictions.Load(),
		HitRate:   rate,
	}
}

// Reset zeros all counters.
func (m *CacheMetrics) Reset() {
	m.hits.Store(0)
	m.misses.Store(0)
	m.evictions.Store(0)
}
