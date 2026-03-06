// Package proxy — middleware chain assembly for turboSH.
package proxy

import (
	"fmt"
	"log"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/Keshav76315/turboSH/config"
	cachesystem "github.com/Keshav76315/turboSH/core/cache"
	"github.com/Keshav76315/turboSH/core/decision"
	"github.com/Keshav76315/turboSH/core/inference"
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
	MLProtection  *inference.MLProtection // EPIC 7: ONNX inference middleware
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
		close(stop) // prevent TTL manager goroutine leak
		return nil, fmt.Errorf("failed to create traffic logger: %w", err)
	}

	// EPIC 7: Try creating ML Inference Engine. Fail gracefully if ONNX library is missing.
	var mlProtection *inference.MLProtection
	err = inference.Initialize(cfg.ONNXSharedLibraryPath) // e.g., /usr/lib/onnxruntime.so
	if err == nil {
		modelPath := "models/anomaly_model.onnx"
		engine, err := inference.NewEngine(modelPath)
		if err == nil {
			// ThresholdPolicy from EPIC 2
			de, _ := decision.NewThresholdPolicy(0.85, 0.65)
			mlProtection = inference.NewMLProtection(engine, de)
		} else {
			log.Printf("[setup] Could not start ML Engine: %v. Running in static-rule mode.", err)
		}
	} else {
		log.Printf("[setup] ONNX Runtime not initialized: %v. Running in static-rule mode.", err)
	}

	return &Components{
		Scheduler:     scheduler.New(cfg.MaxConcurrent, cfg.QueueTimeout),
		RateLimiter:   rateLimiter,
		TrafficRules:  trafficRules,
		Cache:         cacheMiddleware,
		CacheStop:     stop,
		TrafficLogger: trafficLogger,
		MLProtection:  mlProtection,
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

	// 6. Feature Extraction + ML Inference + Decision Engine (EPIC 7)
	if components.MLProtection != nil {
		router.Use(components.MLProtection.Middleware())
	}
}
