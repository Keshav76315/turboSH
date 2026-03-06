// Package proxy — middleware chain assembly for turboSH.
package proxy

import (
	"fmt"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/Keshav76315/turboSH/config"
	cachesystem "github.com/Keshav76315/turboSH/core/cache"
	"github.com/Keshav76315/turboSH/core/scheduler"
	"github.com/Keshav76315/turboSH/core/security"
	"github.com/Keshav76315/turboSH/pipeline/logging"
)

// Components holds all the middleware components for the pipeline.
type Components struct {
	Scheduler     *scheduler.Scheduler
	RateLimiter   *security.RateLimiter
	TrafficRules  *security.TrafficRules
	Cache         *cachesystem.CacheMiddleware
	CacheStop     chan struct{} // stop channel for the TTL manager
	TrafficLogger *logging.TrafficLogger
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

	trafficRules, err := security.NewTrafficRules(
		cfg.BurstThreshold,
		cfg.BurstWindow,
		cfg.EndpointAbuseThreshold,
		cfg.EndpointAbuseWindow,
	)
	if err != nil {
		return nil, err
	}

	// Create cache
	lruCache := cachesystem.NewLRUCache(cfg.CacheCapacity, cfg.CacheMaxMemory)
	stop := lruCache.StartTTLManager(30 * time.Second)
	cacheMiddleware := cachesystem.NewCacheMiddleware(lruCache, cfg.CacheTTL, 1<<20)

	// Create traffic logger
	trafficLogger, err := logging.NewTrafficLogger(cfg.LogFilePath, cfg.LogBufferSize)
	if err != nil {
		return nil, fmt.Errorf("failed to create traffic logger: %w", err)
	}

	return &Components{
		Scheduler:     scheduler.New(cfg.MaxConcurrent, cfg.QueueTimeout),
		RateLimiter:   rateLimiter,
		TrafficRules:  trafficRules,
		Cache:         cacheMiddleware,
		CacheStop:     stop,
		TrafficLogger: trafficLogger,
	}, nil
}

// SetupMiddleware registers all middleware in the correct pipeline order.
//
// Request flow:
//
//	Client → Scheduler → RateLimiter → TrafficRules → [future: Cache → Logger → ML] → Proxy
func SetupMiddleware(router *gin.Engine, components *Components) {
	if components == nil {
		return
	}

	// 1. Scheduler — concurrency control (first gate)
	if components.Scheduler != nil {
		router.Use(components.Scheduler.Middleware())
	}

	// 2. Rate limiter — per-IP token bucket
	if components.RateLimiter != nil {
		router.Use(components.RateLimiter.Middleware())
	}

	// 3. Traffic rules — burst detection + endpoint abuse
	if components.TrafficRules != nil {
		router.Use(components.TrafficRules.Middleware())
	}

	// 4. Cache layer (EPIC 3 — Anzal)
	if components.Cache != nil {
		router.Use(components.Cache.Middleware())
	}

	// 5. Traffic logger (EPIC 4 — Anzal)
	if components.TrafficLogger != nil {
		router.Use(components.TrafficLogger.Middleware())
	}

	// Future middleware slots (added in later EPICs):
	// 6. Feature extraction + ML inference (EPIC 7)
	// 7. Decision engine (EPIC 7 — currently using PassthroughPolicy)
}
