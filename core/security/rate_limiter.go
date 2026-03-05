// Package security implements rate limiting, burst detection, and endpoint abuse detection.
package security

import (
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// TokenBucket implements the token bucket algorithm for per-IP rate limiting.
type TokenBucket struct {
	capacity   int       // Max tokens the bucket can hold
	tokens     float64   // Current token count
	rate       float64   // Tokens added per second
	lastRefill time.Time // Last time tokens were refilled
}

// RateLimiter manages per-IP token buckets.
type RateLimiter struct {
	buckets  map[string]*TokenBucket
	capacity int
	rate     float64
	mu       sync.Mutex
}

// NewRateLimiter creates a new per-IP rate limiter.
// capacity is the max burst size, rate is tokens refilled per second.
func NewRateLimiter(capacity int, rate float64) *RateLimiter {
	return &RateLimiter{
		buckets:  make(map[string]*TokenBucket),
		capacity: capacity,
		rate:     rate,
	}
}

// Allow checks if a request from the given IP is allowed.
// Returns true if a token was consumed, false if rate-limited.
func (rl *RateLimiter) Allow(ip string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	bucket, exists := rl.buckets[ip]
	if !exists {
		bucket = &TokenBucket{
			capacity:   rl.capacity,
			tokens:     float64(rl.capacity), // Start with a full bucket
			rate:       rl.rate,
			lastRefill: time.Now(),
		}
		rl.buckets[ip] = bucket
	}

	// Refill tokens based on elapsed time
	now := time.Now()
	elapsed := now.Sub(bucket.lastRefill).Seconds()
	bucket.tokens += elapsed * bucket.rate
	if bucket.tokens > float64(bucket.capacity) {
		bucket.tokens = float64(bucket.capacity)
	}
	bucket.lastRefill = now

	// Try to consume a token
	if bucket.tokens >= 1.0 {
		bucket.tokens -= 1.0
		return true
	}

	return false
}

// Middleware returns a Gin middleware that rate-limits requests by client IP.
func (rl *RateLimiter) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		ip := c.ClientIP()

		if !rl.Allow(ip) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":   "rate_limited",
				"message": "Too many requests. Please slow down.",
			})
			return
		}

		c.Next()
	}
}

// Cleanup removes stale buckets that haven't been used recently.
// Call this periodically to prevent memory leaks from abandoned IPs.
func (rl *RateLimiter) Cleanup(maxAge time.Duration) {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	cutoff := time.Now().Add(-maxAge)
	for ip, bucket := range rl.buckets {
		if bucket.lastRefill.Before(cutoff) {
			delete(rl.buckets, ip)
		}
	}
}
