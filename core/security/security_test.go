package security

import (
	"testing"
	"time"
)

func TestRateLimiterCleanup(t *testing.T) {
	rl, err := NewRateLimiter(10, 1.0)
	if err != nil {
		t.Fatalf("Failed to create RateLimiter: %v", err)
	}

	// Make request for active and inactive IPs
	rl.Allow("active-ip")
	rl.Allow("stale-ip")

	rl.mu.Lock()
	if len(rl.buckets) != 2 {
		rl.mu.Unlock()
		t.Fatalf("Expected 2 buckets, got %d", len(rl.buckets))
	}
	// Artificially age the stale-ip bucket
	rl.buckets["stale-ip"].lastRefill = time.Now().Add(-10 * time.Minute)
	rl.mu.Unlock()

	// Run cleanup with 5 minute max age
	rl.Cleanup(5 * time.Minute)

	rl.mu.Lock()
	defer rl.mu.Unlock()

	if _, exists := rl.buckets["stale-ip"]; exists {
		t.Errorf("Expected stale-ip to be deleted by Cleanup")
	}
	if _, exists := rl.buckets["active-ip"]; !exists {
		t.Errorf("Expected active-ip to be retained by Cleanup")
	}
	if len(rl.buckets) != 1 {
		t.Errorf("Expected 1 bucket remaining, got %d", len(rl.buckets))
	}
}

func TestTrafficRulesCleanup(t *testing.T) {
	tr, err := NewTrafficRules(10, 50*time.Millisecond, 10, 50*time.Millisecond)
	if err != nil {
		t.Fatalf("Failed to create TrafficRules: %v", err)
	}

	tr.CheckBurst("stale-burst-ip")
	tr.CheckEndpointAbuse("stale-abuse-ip", "/api/v1")

	tr.mu.Lock()
	if len(tr.burstTracker) != 1 || len(tr.endpointTracker) != 1 {
		tr.mu.Unlock()
		t.Fatalf("Expected trackers to have 1 entry each")
	}
	tr.mu.Unlock()

	// Wait for windows to expire
	time.Sleep(75 * time.Millisecond)

	tr.Cleanup()

	tr.mu.Lock()
	defer tr.mu.Unlock()

	if len(tr.burstTracker) != 0 {
		t.Errorf("Expected burstTracker to be empty after Cleanup, got %d", len(tr.burstTracker))
	}
	if len(tr.endpointTracker) != 0 {
		t.Errorf("Expected endpointTracker to be empty after Cleanup, got %d", len(tr.endpointTracker))
	}
}

func TestCleanupManagersStop(t *testing.T) {
	rl, _ := NewRateLimiter(10, 1.0)
	stopRL := rl.StartCleanupManager(10*time.Millisecond, 1*time.Minute)
	close(stopRL)

	tr, _ := NewTrafficRules(10, 1*time.Second, 10, 1*time.Second)
	stopTR := tr.StartCleanupManager(10*time.Millisecond)
	close(stopTR)
}
