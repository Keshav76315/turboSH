package main

import (
	"log"
	"net/url"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/Keshav76315/turboSH/config"
	"github.com/Keshav76315/turboSH/core/proxy"
	"github.com/Keshav76315/turboSH/monitoring"
)

func main() {
	cfg := config.Load()

	log.Println("=== turboSH Middleware ===")
	if parsedURL, err := url.Parse(cfg.BackendURL); err == nil {
		log.Printf("Backend:  %s://%s", parsedURL.Scheme, parsedURL.Host)
	} else {
		log.Printf("Backend:  [redacted/invalid]")
	}
	log.Printf("Listen:   %s", cfg.ListenPort)
	log.Printf("Max concurrent: %d", cfg.MaxConcurrent)
	log.Printf("Rate limit: %d tokens, %.1f/s refill", cfg.RateLimitCapacity, cfg.RateLimitRate)

	monitoring.Register()

	rp, err := proxy.New(cfg.BackendURL)
	if err != nil {
		log.Fatalf("Failed to create reverse proxy: %v", err)
	}

	router := gin.Default()

	// Securely handle X-Forwarded-For parsing based on trusted proxies.
	if len(cfg.TrustedProxies) > 0 {
		log.Printf("[Init] Trusting proxies: %v", cfg.TrustedProxies)
		if err := router.SetTrustedProxies(cfg.TrustedProxies); err != nil {
			log.Fatalf("[CRITICAL] Failed to set trusted proxies %v: %v", cfg.TrustedProxies, err)
		}
	} else {
		log.Println("[Init] No trusted proxies defined. Disabling wildcard proxy trust.")
		if err := router.SetTrustedProxies(nil); err != nil {
			log.Fatalf("[CRITICAL] Failed to disable wildcard proxy trust: %v", err)
		}
	}

	router.GET("/metrics", gin.WrapH(promhttp.Handler()))

	router.Use(monitoring.MetricsMiddleware())

	components, err := proxy.NewComponents(cfg)
	if err != nil {
		log.Fatalf("Failed to initialize middleware components: %v", err)
	}

	if components.Scheduler != nil {
		monitoring.SchedulerCapacity.Set(float64(cfg.MaxConcurrent))
	}

	proxy.SetupMiddleware(router, components)

	router.NoRoute(rp.Handler())

	log.Printf("turboSH is running on %s → %s", cfg.ListenPort, rp.TargetURL())
	log.Printf("Prometheus metrics available at %s/metrics", cfg.ListenPort)
	if err := router.Run(cfg.ListenPort); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
