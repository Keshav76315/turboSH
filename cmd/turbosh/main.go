package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

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

	components, err := proxy.NewComponents(cfg)
	if err != nil {
		log.Fatalf("Failed to initialize middleware components: %v", err)
	}
	// 9.1 & 9.2: Ensure CacheStop, TrafficLogger, and ONNX resources are cleanly closed on exit
	defer components.Close()

	if components.Scheduler != nil {
		monitoring.SchedulerCapacity.Set(float64(cfg.MaxConcurrent))
	}

	proxy.SetupMiddleware(router, components)

	router.NoRoute(rp.Handler())

	// 5.5: Run internal listener for Prometheus metrics + Dashboard API + Dashboard HTML
	var metricsSrv *http.Server
	if cfg.MetricsEnabled {
		metricsMux := http.NewServeMux()
		metricsMux.Handle("/metrics", promhttp.Handler())

		// Dashboard: Wire real-time JSON API
		if components.DashboardState != nil {
			metricsMux.HandleFunc("/api/v1/status", monitoring.DashboardAPIHandler(components.DashboardState))
			log.Printf("[dashboard] Real-time status API: http://localhost%s/api/v1/status", cfg.MetricsPort)
		}

		// Dashboard: Serve HTML files from ui/ directory
		darkHTML := loadDashboardHTML("ui/dark_desktop_ui.html")
		lightHTML := loadDashboardHTML("ui/light_desktop_ui.html")
		if darkHTML != nil {
			metricsMux.HandleFunc("/dashboard", monitoring.DashboardHTMLHandler(darkHTML))
			metricsMux.HandleFunc("/dashboard/dark", monitoring.DashboardHTMLHandler(darkHTML))
			log.Printf("[dashboard] Dark UI:  http://localhost%s/dashboard", cfg.MetricsPort)
		}
		if lightHTML != nil {
			metricsMux.HandleFunc("/dashboard/light", monitoring.DashboardHTMLHandler(lightHTML))
			log.Printf("[dashboard] Light UI: http://localhost%s/dashboard/light", cfg.MetricsPort)
		}

		metricsSrv = &http.Server{
			Addr:    cfg.MetricsPort,
			Handler: metricsMux,
		}
		go func() {
			log.Printf("[monitoring] Internal listener on %s (/metrics, /api/v1/status, /dashboard)", cfg.MetricsPort)
			if err := metricsSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
				log.Printf("[monitoring] ERROR: Internal metrics server failed: %v", err)
			}
		}()
	}

	srv := &http.Server{
		Addr:    cfg.ListenPort,
		Handler: router,
	}

	// Run reverse proxy in background goroutine to allow graceful signal trapping
	go func() {
		log.Printf("turboSH is running on %s → %s", cfg.ListenPort, rp.TargetURL())
		if cfg.TLSEnabled {
			log.Printf("[security] TLS termination enabled (Cert: %s, Key: %s)", cfg.TLSCertFile, cfg.TLSKeyFile)
			if err := srv.ListenAndServeTLS(cfg.TLSCertFile, cfg.TLSKeyFile); err != nil && !errors.Is(err, http.ErrServerClosed) {
				log.Fatalf("Server failed with TLS: %v", err)
			}
		} else {
			if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
				log.Fatalf("Server failed: %v", err)
			}
		}
	}()

	// 9.2: Graceful shutdown on SIGINT / SIGTERM
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	sig := <-quit
	log.Printf("[shutdown] Received signal %v, initiating graceful shutdown...", sig)

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("[shutdown] Proxy server forced shutdown: %v", err)
	} else {
		log.Println("[shutdown] Proxy server stopped gracefully.")
	}

	if metricsSrv != nil {
		if err := metricsSrv.Shutdown(shutdownCtx); err != nil {
			log.Printf("[shutdown] Metrics server forced shutdown: %v", err)
		} else {
			log.Println("[shutdown] Metrics server stopped gracefully.")
		}
	}

	log.Println("[shutdown] turboSH shutdown complete.")
}

// loadDashboardHTML loads an HTML file from the given path relative to the current working directory.
// Returns nil if the file doesn't exist (non-fatal).
func loadDashboardHTML(relPath string) []byte {
	// Try CWD first
	absPath, _ := filepath.Abs(relPath)
	data, err := os.ReadFile(absPath)
	if err != nil {
		log.Printf("[dashboard] Could not load %s: %v (dashboard will not be available at this path)", relPath, err)
		return nil
	}
	log.Printf("[dashboard] Loaded %s (%d bytes)", relPath, len(data))
	return data
}
