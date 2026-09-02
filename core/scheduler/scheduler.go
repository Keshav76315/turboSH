// Package scheduler provides Gin middleware for request concurrency control.
package scheduler

import (
	"net/http"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

// Scheduler controls how many requests are processed concurrently.
// It uses a semaphore pattern (buffered channel) to limit active requests.
type Scheduler struct {
	semaphore    chan struct{} // Buffered channel acting as a semaphore
	timeout      time.Duration
	waitingCount atomic.Int64
}

// New creates a new Scheduler with the given concurrency limit and queue timeout.
func New(maxConcurrent int, queueTimeout time.Duration) *Scheduler {
	if maxConcurrent <= 0 {
		maxConcurrent = 1
	}
	return &Scheduler{
		semaphore: make(chan struct{}, maxConcurrent),
		timeout:   queueTimeout,
	}
}

// Middleware returns a Gin middleware that enforces concurrency limits.
func (s *Scheduler) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		timer := time.NewTimer(s.timeout)

		s.waitingCount.Add(1)

		// Try to acquire a slot within the timeout
		select {
		case s.semaphore <- struct{}{}:
			s.waitingCount.Add(-1)
			if !timer.Stop() {
				<-timer.C
			}
			// Got a slot — proceed with the request
			defer func() { <-s.semaphore }() // Release slot when done
			c.Next()

		case <-timer.C:
			s.waitingCount.Add(-1)
			// Timed out waiting for a slot
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
				"error":   "service_unavailable",
				"message": "Server is at capacity. Please try again later.",
			})
		}
	}
}

// ActiveCount returns the number of currently active requests.
func (s *Scheduler) ActiveCount() int {
	return len(s.semaphore)
}

// WaitingCount returns the number of requests currently blocked waiting for a slot.
func (s *Scheduler) WaitingCount() int {
	return int(s.waitingCount.Load())
}
