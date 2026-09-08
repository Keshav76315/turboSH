package monitoring

import (
	"strconv"
	"time"

	pipelinemon "github.com/Keshav76315/turboSH/pipeline/monitoring"
)

var (
	// Aliases to canonical pipeline metrics
	RequestsTotal     = pipelinemon.RequestsTotal
	RequestLatency    = pipelinemon.RequestLatency
	SchedulerActive   = pipelinemon.SchedulerActive
	SchedulerWaiting  = pipelinemon.SchedulerWaiting
	SchedulerCapacity = pipelinemon.SchedulerCapacity
	CacheOps          = pipelinemon.CacheOps
	AnomalyAlerts     = pipelinemon.AnomalyAlerts

	// Backward-compatible counters delegating to canonical vector metrics
	CacheHitsTotal   = pipelinemon.CacheOps.WithLabelValues("hit")
	CacheMissesTotal = pipelinemon.CacheOps.WithLabelValues("miss")
	MLBlocksTotal    = pipelinemon.AnomalyAlerts.WithLabelValues("block")
	MLThrottlesTotal = pipelinemon.AnomalyAlerts.WithLabelValues("rate_limit")
	MLAllowsTotal    = pipelinemon.AnomalyAlerts.WithLabelValues("allow")
)

// Register is kept for backwards compatibility; pipeline metrics are auto-registered via promauto.
// Making this a no-op prevents duplicate descriptor panics on startup (Section 3.2 / 8.1).
func Register() {
}

func RecordRequest(method string, statusCode int, duration time.Duration) {
	RequestsTotal.WithLabelValues(method, strconv.Itoa(statusCode)).Inc()
	RequestLatency.WithLabelValues(method).Observe(float64(duration.Microseconds()) / 1000.0)
}

func RecordMLBlock()    { MLBlocksTotal.Inc() }
func RecordMLThrottle() { MLThrottlesTotal.Inc() }
func RecordMLAllow()    { MLAllowsTotal.Inc() }
func RecordCacheHit()   { CacheHitsTotal.Inc() }
func RecordCacheMiss()  { CacheMissesTotal.Inc() }
