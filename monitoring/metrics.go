package monitoring

import (
	"strconv"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

var (
	RequestsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "turbosh_requests_total",
			Help: "Total HTTP requests processed by turboSH.",
		},
		[]string{"status"},
	)

	RequestDuration = prometheus.NewHistogram(
		prometheus.HistogramOpts{
			Name:    "turbosh_request_duration_seconds",
			Help:    "Latency distribution of proxied requests.",
			Buckets: prometheus.DefBuckets,
		},
	)

	CacheHitsTotal = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "turbosh_cache_hits_total",
			Help: "Total cache hits.",
		},
	)

	CacheMissesTotal = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "turbosh_cache_misses_total",
			Help: "Total cache misses.",
		},
	)

	MLBlocksTotal = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "turbosh_ml_blocks_total",
			Help: "Total requests blocked by ML anomaly detection.",
		},
	)

	MLThrottlesTotal = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "turbosh_ml_throttles_total",
			Help: "Total requests throttled by ML anomaly detection.",
		},
	)

	MLAllowsTotal = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "turbosh_ml_allows_total",
			Help: "Total requests allowed by ML anomaly detection.",
		},
	)

	SchedulerActive = prometheus.NewGauge(
		prometheus.GaugeOpts{
			Name: "turbosh_scheduler_active",
			Help: "Number of requests currently being processed by the scheduler.",
		},
	)

	SchedulerCapacity = prometheus.NewGauge(
		prometheus.GaugeOpts{
			Name: "turbosh_scheduler_capacity",
			Help: "Maximum concurrent requests allowed by the scheduler.",
		},
	)

	registerOnce sync.Once
)

func Register() {
	registerOnce.Do(func() {
		prometheus.MustRegister(
			RequestsTotal,
			RequestDuration,
			CacheHitsTotal,
			CacheMissesTotal,
			MLBlocksTotal,
			MLThrottlesTotal,
			MLAllowsTotal,
			SchedulerActive,
			SchedulerCapacity,
		)
	})
}

func RecordRequest(statusCode int, duration time.Duration) {
	RequestsTotal.WithLabelValues(strconv.Itoa(statusCode)).Inc()
	RequestDuration.Observe(duration.Seconds())
}

func RecordMLBlock()    { MLBlocksTotal.Inc() }
func RecordMLThrottle() { MLThrottlesTotal.Inc() }
func RecordMLAllow()    { MLAllowsTotal.Inc() }
func RecordCacheHit()   { CacheHitsTotal.Inc() }
func RecordCacheMiss()  { CacheMissesTotal.Inc() }
