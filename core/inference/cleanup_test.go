package inference

import (
	"testing"
	"time"

	"github.com/Keshav76315/turboSH/config"
	"github.com/Keshav76315/turboSH/core/decision"
)

func TestMLProtectionPruneAll(t *testing.T) {
	cfg := &config.Config{}
	de, _ := decision.NewThresholdPolicy(0.85, 0.65)
	mlp := NewMLProtection(cfg, nil, de)

	now := time.Now()

	// Simulate active IP and abandoned IP
	mlp.requests["active-ip"] = []requestRecord{
		{Timestamp: now.Add(-5 * time.Second), Endpoint: "/api/active"},
	}
	mlp.requests["abandoned-ip"] = []requestRecord{
		{Timestamp: now.Add(-70 * time.Second), Endpoint: "/api/stale"},
	}

	mlp.ipStats["active-ip"] = []BackendResponse{
		{Timestamp: now.Add(-5 * time.Second), StatusCode: 200, LatencyMs: 20},
	}
	mlp.ipStats["abandoned-ip"] = []BackendResponse{
		{Timestamp: now.Add(-70 * time.Second), StatusCode: 500, LatencyMs: 200},
	}

	// Prune all entries older than 60s
	mlp.PruneAll(now)

	mlp.mu.Lock()
	defer mlp.mu.Unlock()

	if _, exists := mlp.requests["abandoned-ip"]; exists {
		t.Errorf("Expected abandoned-ip requests to be purged by PruneAll")
	}
	if _, exists := mlp.ipStats["abandoned-ip"]; exists {
		t.Errorf("Expected abandoned-ip stats to be purged by PruneAll")
	}
	if _, exists := mlp.requests["active-ip"]; !exists {
		t.Errorf("Expected active-ip requests to be retained")
	}
	if _, exists := mlp.ipStats["active-ip"]; !exists {
		t.Errorf("Expected active-ip stats to be retained")
	}
}

func TestMLProtectionWindowedEndpoints(t *testing.T) {
	cfg := &config.Config{}
	de, _ := decision.NewThresholdPolicy(0.85, 0.65)
	mlp := NewMLProtection(cfg, nil, de)

	ip := "test-ip"
	// Old requests from 70s ago
	oldTime := time.Now().Add(-70 * time.Second)
	mlp.requests[ip] = []requestRecord{
		{Timestamp: oldTime, Endpoint: "/api/old1"},
		{Timestamp: oldTime, Endpoint: "/api/old2"},
		{Timestamp: oldTime, Endpoint: "/api/old3"},
	}

	// New single request to /api/new
	features := mlp.recordRequest(ip, "/api/new")

	// Since the old 3 requests aged out of the 60s window,
	// only /api/new is in the window.
	// Endpoint entropy for a single unique endpoint must be 0.0!
	if features.EndpointEntropy != 0.0 {
		t.Errorf("Expected windowed endpoint entropy to be 0.0 (single active endpoint), got %f", features.EndpointEntropy)
	}
	if features.RequestsPerIP60s != 1.0 {
		t.Errorf("Expected RequestsPerIP60s to be 1.0, got %f", features.RequestsPerIP60s)
	}
}

func TestMLProtectionCleanupManagerStop(t *testing.T) {
	cfg := &config.Config{}
	de, _ := decision.NewThresholdPolicy(0.85, 0.65)
	mlp := NewMLProtection(cfg, nil, de)

	stop := mlp.StartCleanupManager(10 * time.Millisecond)
	close(stop)
}
