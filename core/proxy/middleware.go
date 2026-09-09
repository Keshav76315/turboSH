// Package proxy — middleware chain assembly for turboSH.
package proxy

import (
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/Keshav76315/turboSH/config"
	cachesystem "github.com/Keshav76315/turboSH/core/cache"
	"github.com/Keshav76315/turboSH/core/decision"
	"github.com/Keshav76315/turboSH/core/inference"
	"github.com/Keshav76315/turboSH/core/scheduler"
	"github.com/Keshav76315/turboSH/core/security"
	mon "github.com/Keshav76315/turboSH/monitoring"
	"github.com/Keshav76315/turboSH/pipeline/logging"
	"github.com/Keshav76315/turboSH/pipeline/monitoring"
)

// Components holds all the middleware components for the pipeline.
type Components struct {
	Config           *config.Config
	Scheduler        *scheduler.Scheduler
	RateLimiter      *security.RateLimiter
	TrafficRules     *security.TrafficRules
	Cache            *cachesystem.CacheMiddleware
	LRUCache         *cachesystem.LRUCache    // Direct reference for dashboard metrics
	CacheStop        chan struct{}             // stop channel for the TTL manager
	RateLimiterStop  chan struct{}             // stop channel for rate limiter cleanup
	TrafficRulesStop chan struct{}             // stop channel for traffic rules cleanup
	MLProtectionStop chan struct{}             // stop channel for ML abandoned IP cleanup
	PollerStop       chan struct{}             // stop channel for scheduler metrics poller
	TrafficLogger    *logging.TrafficLogger
	MLProtection     *inference.MLProtection   // EPIC 7: ONNX inference middleware
	DashboardState   *mon.DashboardState       // Real-time dashboard state aggregator
}

// Close gracefully stops all background cleanup goroutines, flushes loggers, and destroys ONNX resources.
func (c *Components) Close() {
	if c.CacheStop != nil {
		close(c.CacheStop)
		c.CacheStop = nil
	}
	if c.RateLimiterStop != nil {
		close(c.RateLimiterStop)
		c.RateLimiterStop = nil
	}
	if c.TrafficRulesStop != nil {
		close(c.TrafficRulesStop)
		c.TrafficRulesStop = nil
	}
	if c.MLProtectionStop != nil {
		close(c.MLProtectionStop)
		c.MLProtectionStop = nil
	}
	if c.PollerStop != nil {
		close(c.PollerStop)
		c.PollerStop = nil
	}
	if c.TrafficLogger != nil {
		_ = c.TrafficLogger.Close()
	}
	if c.MLProtection != nil {
		c.MLProtection.Close()
	}
	inference.Destroy()
}

// NewComponents creates all middleware components from the given config.
func NewComponents(cfg *config.Config) (*Components, error) {
	if cfg == nil {
		return nil, fmt.Errorf("config cannot be nil")
	}

	rateLimiter, err := security.NewRateLimiter(
		cfg.RateLimitCapacity,
		cfg.RateLimitRate,
	)
	if err != nil {
		return nil, err
	}
	rateLimiterStop := rateLimiter.StartCleanupManager(30*time.Second, 10*time.Minute)

	trafficRules, err := security.NewTrafficRules(
		cfg.BurstThreshold,
		cfg.BurstWindow,
		cfg.EndpointAbuseThreshold,
		cfg.EndpointAbuseWindow,
	)
	if err != nil {
		close(rateLimiterStop)
		return nil, err
	}
	trafficRulesStop := trafficRules.StartCleanupManager(30*time.Second)

	// Create cache
	lruCache := cachesystem.NewLRUCache(cfg.CacheCapacity, cfg.CacheMaxMemory)
	cacheStop := lruCache.StartTTLManager(30 * time.Second)
	cacheMiddleware := cachesystem.NewCacheMiddleware(lruCache, cfg.CacheTTL, 1<<20)

	// EPIC 7: Create ML Inference Engine first so we can pass it to the logger.
	var mlProtection *inference.MLProtection
	var mlProtectionStop chan struct{}
	mlModelLoaded := false
	err = inference.Initialize(cfg.ONNXSharedLibraryPath) // e.g., /usr/lib/onnxruntime.so
	if err == nil {
		engine, err := inference.NewEngine(cfg.ModelPath)
		if err == nil {
			de, err := decision.NewThresholdPolicy(cfg.BlockThreshold, cfg.RateLimitThreshold)
			if err != nil {
				log.Printf("[setup] Error creating ThresholdPolicy: %v. Running in static-rule mode.", err)
			} else {
				mlProtection = inference.NewMLProtection(cfg, engine, de)
				mlProtectionStop = mlProtection.StartCleanupManager(30 * time.Second)
				mlModelLoaded = true
			}
		} else {
			log.Printf("[setup] Could not start ML Engine: %v. Running in static-rule mode.", err)
		}
	} else {
		log.Printf("[setup] ONNX Runtime not initialized: %v. Running in static-rule mode.", err)
	}

	// Create traffic logger
	var mlRecorder logging.MLMetricsRecorder
	if mlProtection != nil {
		mlRecorder = mlProtection
	}
	trafficLogger, err := logging.NewTrafficLogger(cfg, mlRecorder)
	if err != nil {
		close(cacheStop)
		close(rateLimiterStop)
		close(trafficRulesStop)
		if mlProtectionStop != nil {
			close(mlProtectionStop)
		}
		return nil, fmt.Errorf("failed to create traffic logger: %w", err)
	}

	// EPIC 8: Background poller for gauge metrics with clean lifecycle
	sched := scheduler.New(cfg.MaxConcurrent, cfg.QueueTimeout)
	pollerStop := make(chan struct{})
	go func() {
		ticker := time.NewTicker(1 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				monitoring.SchedulerActive.Set(float64(sched.ActiveCount()))
				monitoring.SchedulerWaiting.Set(float64(sched.WaitingCount()))
			case <-pollerStop:
				return
			}
		}
	}()

	// Dashboard: Initialize real-time state aggregator
	ds := mon.NewDashboardState()
	ds.SetScheduler(sched)
	ds.SetCache(cachesystem.NewDashboardAdapter(lruCache, cfg.CacheMaxMemory, cfg.CacheCapacity))
	ds.SetConfig(mon.ConfigSnapshot{
		BackendURL:         cfg.BackendURL,
		ProxyPort:          cfg.ListenPort,
		MaxConcurrent:      cfg.MaxConcurrent,
		RateLimitCapacity:  cfg.RateLimitCapacity,
		RateLimitRate:      cfg.RateLimitRate,
		BlockThreshold:     cfg.BlockThreshold,
		RateLimitThreshold: cfg.RateLimitThreshold,
		CacheMaxMemory:     cfg.CacheMaxMemory,
		CacheCapacity:      cfg.CacheCapacity,
		MLModelLoaded:      mlModelLoaded,
	})

	return &Components{
		Config:           cfg,
		Scheduler:        sched,
		RateLimiter:      rateLimiter,
		TrafficRules:     trafficRules,
		Cache:            cacheMiddleware,
		LRUCache:         lruCache,
		CacheStop:        cacheStop,
		RateLimiterStop:  rateLimiterStop,
		TrafficRulesStop: trafficRulesStop,
		MLProtectionStop: mlProtectionStop,
		PollerStop:       pollerStop,
		TrafficLogger:    trafficLogger,
		MLProtection:     mlProtection,
		DashboardState:   ds,
	}, nil
}

// SetupMiddleware registers all middleware in the correct pipeline order.
//
// Request flow:
//
//	Client → Dashboard Recorder → Metrics → Client Identity → Scheduler → Traffic Logger → RateLimiter → TrafficRules → ML Inference → Cache → Proxy
//
// Design notes:
//   - Dashboard Recorder captures status codes and latencies for the real-time dashboard UI
//   - Client Identity establishes a canonical verified client IP and HMAC-SHA-256 hash for all downstream components
//   - Traffic Logger wraps downstream handlers so ALL traffic (allowed, cached, throttled, blocked) is logged
//   - Traffic Logger feeds all response metrics (status, latency) back to ML via RecordBackendResponse in real-time
//   - ML Inference runs before Cache so it evaluates every request in real time and enforces block/throttle actions
func SetupMiddleware(router *gin.Engine, components *Components) {
	if components == nil {
		return
	}

	// 0. Dashboard recorder — feeds real-time stats to the dashboard JSON API.
	// Must run first (outermost wrapper) to capture total end-to-end latency.
	if components.DashboardState != nil {
		ds := components.DashboardState
		router.Use(func(c *gin.Context) {
			start := time.Now()
			c.Next()
			latencyMs := float64(time.Since(start).Microseconds()) / 1000.0
			status := c.Writer.Status()
			ds.RecordRequest(status, latencyMs)

			switch status {
			case http.StatusTooManyRequests:
				ipHash := c.GetString(logging.ContextKeyClientIPHash)
				if ipHash == "" {
					ipHash = c.ClientIP()
				}
				if len(ipHash) > 8 {
					ipHash = ipHash[:8]
				}
				ds.RecordEvent(mon.MitigationEvent{
					Timestamp: time.Now(),
					Type:      "RATE_LIMIT",
					IPHash:    ipHash,
					Path:      c.Request.URL.Path,
					Score:     0.0,
					Detail:    "Rate limit exceeded (token bucket / burst)",
					Status:    status,
				})
			case http.StatusForbidden:
				ipHash := c.GetString(logging.ContextKeyClientIPHash)
				if ipHash == "" {
					ipHash = c.ClientIP()
				}
				if len(ipHash) > 8 {
					ipHash = ipHash[:8]
				}
				ds.RecordEvent(mon.MitigationEvent{
					Timestamp: time.Now(),
					Type:      "BLOCK",
					IPHash:    ipHash,
					Path:      c.Request.URL.Path,
					Score:     0.92,
					Detail:    "Blocked by security rules / ML",
					Status:    status,
				})
			}
		})
	}

	// 0.5 Base Metrics (EPIC 8)
	// Captures total proxy latency for Prometheus.
	router.Use(monitoring.MetricsMiddleware())

	// 0.6 Canonical Client Identity (EPIC 5 / Section 5)
	// Invariant: ONE REQUEST -> ONE CANONICAL CLIENT IDENTITY across ML, rate limiting, rules, logging
	if components.Config != nil {
		router.Use(logging.ClientIdentityMiddleware(components.Config))
	}

	// 1. Scheduler — concurrency control (first gate)
	if components.Scheduler != nil {
		router.Use(components.Scheduler.Middleware())
	}

	// 2. Traffic logger (EPIC 4 — Anzal)
	// Wraps downstream handlers so it captures all requests — allowed, rate-limited,
	// blocked by ML or static rules, and cache hits alike.
	// Feeds response metrics back to MLProtection.RecordBackendResponse in real time.
	if components.TrafficLogger != nil {
		router.Use(components.TrafficLogger.Middleware())
	}

	// 3. Rate limiter — per-IP token bucket
	if components.RateLimiter != nil {
		router.Use(components.RateLimiter.Middleware())
	}

	// 4. Traffic rules — burst detection + endpoint abuse
	if components.TrafficRules != nil {
		router.Use(components.TrafficRules.Middleware())
	}

	// 5. Feature Extraction + ML Inference + Decision Engine (EPIC 7)
	// Runs before cache so the ML engine sees all requests, even repetitive ones.
	// ML actively blocks (403) or rate-limits (429) suspicious traffic in real-time.
	if components.MLProtection != nil {
		router.Use(components.MLProtection.Middleware())
	}

	// 6. Cache layer (EPIC 3 — Anzal)
	if components.Cache != nil {
		router.Use(components.Cache.Middleware())
	}
}
