// turboSH — AI-powered middleware for server optimization and anomaly detection.
//
// This is the main entry point. It starts the reverse proxy server with
// all middleware (scheduler, rate limiter, traffic rules) enabled.
package main

import (
	"log"

	"github.com/gin-gonic/gin"

	"github.com/Keshav76315/turboSH/config"
	"github.com/Keshav76315/turboSH/core/proxy"
)

func main() {
	// Load configuration
	cfg := config.Load()

	log.Println("=== turboSH Middleware ===")
	log.Printf("Backend:  %s", cfg.BackendURL)
	log.Printf("Listen:   %s", cfg.ListenPort)
	log.Printf("Max concurrent: %d", cfg.MaxConcurrent)
	log.Printf("Rate limit: %d tokens, %.1f/s refill", cfg.RateLimitCapacity, cfg.RateLimitRate)

	// Create the reverse proxy
	rp, err := proxy.New(cfg.BackendURL)
	if err != nil {
		log.Fatalf("Failed to create reverse proxy: %v", err)
	}

	// Create Gin engine
	router := gin.Default()

	// Setup middleware pipeline
	components := proxy.NewComponents(cfg)
	proxy.SetupMiddleware(router, components)

	// Catch-all route — forward everything to the backend
	router.NoRoute(rp.Handler())

	// Start server
	log.Printf("turboSH is running on %s → %s", cfg.ListenPort, rp.TargetURL())
	if err := router.Run(cfg.ListenPort); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
