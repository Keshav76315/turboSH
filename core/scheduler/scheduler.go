// Package scheduler provides Gin middleware for request concurrency control.
package scheduler

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// Scheduler controls how many requests are processed concurrently.
// It uses a semaphore pattern (buffered channel) to limit active requests.
type Scheduler struct {
	semaphore chan struct{} // Buffered channel acting as a semaphore
	timeout   time.Duration
	queue     *PriorityQueue
}

// New creates a new Scheduler with the given concurrency limit and queue timeout.
func New(maxConcurrent int, queueTimeout time.Duration) *Scheduler {
	return &Scheduler{
		semaphore: make(chan struct{}, maxConcurrent),
		timeout:   queueTimeout,
		queue:     NewPriorityQueue(),
	}
}

// Middleware returns a Gin middleware that enforces concurrency limits.
// If the scheduler is at capacity and the timeout expires, returns 503.
func (s *Scheduler) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		// Try to acquire a slot within the timeout
		select {
		case s.semaphore <- struct{}{}:
			// Got a slot — proceed with the request
			defer func() { <-s.semaphore }() // Release slot when done
			c.Next()

		case <-time.After(s.timeout):
			// Timed out waiting for a slot
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
				"error":   "service_unavailable",
				"message": "Server is at capacity. Please try again later.",
			})
		}
	}
}

// QueueSize returns the current number of items waiting in the priority queue.
func (s *Scheduler) QueueSize() int {
	return s.queue.Size()
}

// ActiveCount returns the number of currently active requests.
func (s *Scheduler) ActiveCount() int {
	return len(s.semaphore)
}
