// Package security — traffic rules for burst detection and endpoint abuse detection.
package security

import (
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// requestRecord tracks when requests occurred for a specific key.
type requestRecord struct {
	timestamps []time.Time
}

// TrafficRules implements burst detection and endpoint abuse detection
// using a sliding window counter approach.
type TrafficRules struct {
	// Burst detection: tracks requests per IP in a time window
	burstTracker   map[string]*requestRecord
	burstThreshold int
	burstWindow    time.Duration

	// Endpoint abuse: tracks requests per IP+endpoint in a time window
	endpointTracker   map[string]*requestRecord
	endpointThreshold int
	endpointWindow    time.Duration

	mu sync.Mutex
}

// NewTrafficRules creates a new TrafficRules instance.
func NewTrafficRules(burstThreshold int, burstWindow time.Duration, endpointThreshold int, endpointWindow time.Duration) *TrafficRules {
	return &TrafficRules{
		burstTracker:      make(map[string]*requestRecord),
		burstThreshold:    burstThreshold,
		burstWindow:       burstWindow,
		endpointTracker:   make(map[string]*requestRecord),
		endpointThreshold: endpointThreshold,
		endpointWindow:    endpointWindow,
	}
}

// recordRequest adds a timestamp to the tracker and prunes old entries outside the window.
// Returns the count of requests within the window after recording.
func (tr *TrafficRules) recordRequest(tracker map[string]*requestRecord, key string, window time.Duration) int {
	now := time.Now()
	cutoff := now.Add(-window)

	record, exists := tracker[key]
	if !exists {
		record = &requestRecord{}
		tracker[key] = record
	}

	// Prune old timestamps
	pruned := make([]time.Time, 0, len(record.timestamps))
	for _, ts := range record.timestamps {
		if ts.After(cutoff) {
			pruned = append(pruned, ts)
		}
	}

	// Add current request
	pruned = append(pruned, now)
	record.timestamps = pruned

	return len(pruned)
}

// CheckBurst records a request for the given IP and returns true if it's within limits.
func (tr *TrafficRules) CheckBurst(ip string) bool {
	tr.mu.Lock()
	defer tr.mu.Unlock()

	count := tr.recordRequest(tr.burstTracker, ip, tr.burstWindow)
	return count <= tr.burstThreshold
}

// CheckEndpointAbuse records a request for the given IP+endpoint combo
// and returns true if it's within limits.
func (tr *TrafficRules) CheckEndpointAbuse(ip, endpoint string) bool {
	tr.mu.Lock()
	defer tr.mu.Unlock()

	key := ip + ":" + endpoint
	count := tr.recordRequest(tr.endpointTracker, key, tr.endpointWindow)
	return count <= tr.endpointThreshold
}

// Middleware returns a Gin middleware that checks burst and endpoint abuse rules.
func (tr *TrafficRules) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		ip := c.ClientIP()
		endpoint := c.Request.URL.Path

		// Check burst detection
		if !tr.CheckBurst(ip) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":   "burst_detected",
				"message": "Traffic burst detected. Requests are being throttled.",
			})
			return
		}

		// Check endpoint abuse
		if !tr.CheckEndpointAbuse(ip, endpoint) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":   "endpoint_abuse",
				"message": "Excessive requests to the same endpoint.",
			})
			return
		}

		c.Next()
	}
}

// Cleanup removes stale tracking entries to prevent memory leaks.
func (tr *TrafficRules) Cleanup() {
	tr.mu.Lock()
	defer tr.mu.Unlock()

	now := time.Now()

	// Clean burst tracker
	for key, record := range tr.burstTracker {
		if len(record.timestamps) == 0 || now.Sub(record.timestamps[len(record.timestamps)-1]) > tr.burstWindow {
			delete(tr.burstTracker, key)
		}
	}

	// Clean endpoint tracker
	for key, record := range tr.endpointTracker {
		if len(record.timestamps) == 0 || now.Sub(record.timestamps[len(record.timestamps)-1]) > tr.endpointWindow {
			delete(tr.endpointTracker, key)
		}
	}
}
