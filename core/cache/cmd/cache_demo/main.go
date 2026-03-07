// cache_demo — a Gin server that demonstrates cache metrics and stampede protection.
//
// Run:   go run ./core/cache/cmd/cache_demo
// Test:  curl http://localhost:8080/products       (slow first time, instant second time)
//        curl http://localhost:8080/cache/stats    (view metrics)

package main

import (
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/Keshav76315/turboSH/config"
	cachesystem "github.com/Keshav76315/turboSH/core/cache"
	"github.com/Keshav76315/turboSH/pipeline/logging"
)

func main() {
	// ---------- 1. Create cache + middleware ----------
	cache := cachesystem.NewLRUCache(100)

	// Start background TTL cleanup every 30 seconds
	stop := cache.StartTTLManager(30 * time.Second)
	defer close(stop)

	cacheMiddleware := cachesystem.NewCacheMiddleware(cache, 5*time.Minute, 1<<20)

	// ---------- 2. Create traffic logger ----------
	cfg := config.Load()
	trafficLogger, err := logging.NewTrafficLogger(cfg, nil)
	if err != nil {
		log.Fatalf("failed to create traffic logger: %v", err)
	}
	defer trafficLogger.Close()

	// ---------- 3. Create Gin router with middleware ----------
	router := gin.Default()
	router.Use(cacheMiddleware.Middleware())
	router.Use(trafficLogger.Middleware())

	// ---------- 3. Fake backend handlers ----------
	router.GET("/products", func(c *gin.Context) {
		log.Println("[backend] /products hit — sleeping 2 seconds...")
		time.Sleep(2 * time.Second)
		c.JSON(http.StatusOK, gin.H{
			"products": []string{"keyboard", "mouse", "monitor"},
		})
	})

	router.GET("/health", func(c *gin.Context) {
		c.String(http.StatusOK, "ok")
	})

	// ---------- 4. Metrics endpoint ----------
	router.GET("/cache/stats", func(c *gin.Context) {
		c.JSON(http.StatusOK, cache.Metrics().Snapshot())
	})

	// ---------- 5. Start server ----------
	addr := ":8080"
	fmt.Println("===========================================")
	fmt.Println("  turboSH Demo (Cache + Traffic Logger)")
	fmt.Println("===========================================")
	fmt.Printf("  Listening on http://localhost%s\n", addr)
	fmt.Println()
	fmt.Println("  Endpoints:")
	fmt.Println("    GET /products      — slow backend (2s)")
	fmt.Println("    GET /health        — fast")
	fmt.Println("    GET /cache/stats   — view metrics")
	fmt.Println()
	fmt.Println("  Logs → logs/traffic.jsonl")
	fmt.Println()
	fmt.Println("  Press Ctrl+C to stop.")
	fmt.Println("===========================================")

	log.Fatal(router.Run(addr))
}
