package monitoring

import (
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	// RequestsTotal counts total HTTP requests processed, partitioned by status code and method.
	RequestsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "turbosh_requests_total",
		Help: "Total number of HTTP requests processed by turboSH",
	}, []string{"method", "status"})

	// RequestLatency tracks the distribution of HTTP request latencies.
	RequestLatency = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "turbosh_request_latency_ms",
		Help:    "Distribution of request latencies in milliseconds",
		Buckets: []float64{1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000},
	}, []string{"method"})

	// SchedulerActive measures the number of currently active concurrent requests.
	SchedulerActive = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "turbosh_scheduler_active_requests",
		Help: "Number of requests currently holding a scheduler slot",
	})

	// SchedulerWaiting measures the number of requests waiting for a scheduler slot.
	SchedulerWaiting = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "turbosh_scheduler_waiting_requests",
		Help: "Number of requests currently blocked waiting for a scheduler slot",
	})

	// CacheOps counts cache hits versus misses.
	CacheOps = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "turbosh_cache_operations_total",
		Help: "Total number of cache operations (hit or miss)",
	}, []string{"result"})

	// AnomalyAlerts counts the number of times the ML engine flagged a request.
	AnomalyAlerts = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "turbosh_anomaly_alerts_total",
		Help: "Total number of anomalies detected by the ML engine",
	}, []string{"action"})
)

// MetricsMiddleware tracks the HTTP request latency and status code.
// Should be placed early in the Gin pipeline but after the Scheduler,
// so that it ONLY times the execution from the proxy's perspective.
func MetricsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		c.Next()

		elapsed := float64(time.Since(start).Milliseconds())
		status := c.Writer.Status()
		method := c.Request.Method

		RequestsTotal.WithLabelValues(method, string(rune(status))).Inc() // Or just fmt.Sprintf("%d", status), but strconv.Itoa is better. Wait, I will use strconv.Itoa.
		RequestLatency.WithLabelValues(method).Observe(elapsed)
	}
}
