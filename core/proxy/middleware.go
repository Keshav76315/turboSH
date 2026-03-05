// Package proxy — middleware chain assembly for turboSH.
package proxy

import (
	"github.com/gin-gonic/gin"

	"github.com/Keshav76315/turboSH/config"
	"github.com/Keshav76315/turboSH/core/scheduler"
	"github.com/Keshav76315/turboSH/core/security"
)

// Components holds all the middleware components for the pipeline.
type Components struct {
	Scheduler    *scheduler.Scheduler
	RateLimiter  *security.RateLimiter
	TrafficRules *security.TrafficRules
}

// NewComponents creates all middleware components from the given config.
func NewComponents(cfg *config.Config) *Components {
	return &Components{
		Scheduler: scheduler.New(cfg.MaxConcurrent, cfg.QueueTimeout),
		RateLimiter: security.NewRateLimiter(
			cfg.RateLimitCapacity,
			cfg.RateLimitRate,
		),
		TrafficRules: security.NewTrafficRules(
			cfg.BurstThreshold,
			cfg.BurstWindow,
			cfg.EndpointAbuseThreshold,
			cfg.EndpointAbuseWindow,
		),
	}
}

// SetupMiddleware registers all middleware in the correct pipeline order.
//
// Request flow:
//
//	Client → Scheduler → RateLimiter → TrafficRules → [future: Cache → Logger → ML] → Proxy
func SetupMiddleware(router *gin.Engine, components *Components) {
	// 1. Scheduler — concurrency control (first gate)
	router.Use(components.Scheduler.Middleware())

	// 2. Rate limiter — per-IP token bucket
	router.Use(components.RateLimiter.Middleware())

	// 3. Traffic rules — burst detection + endpoint abuse
	router.Use(components.TrafficRules.Middleware())

	// Future middleware slots (added in later EPICs):
	// 4. Cache layer (EPIC 3 — Anzal)
	// 5. Traffic logger (EPIC 4 — Anzal)
	// 6. Feature extraction + ML inference (EPIC 7)
	// 7. Decision engine (EPIC 7 — currently using PassthroughPolicy)
}
