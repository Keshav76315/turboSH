package proxy

import (
	"testing"
	"time"

	"github.com/Keshav76315/turboSH/config"
)

func TestComponentsLifecycle(t *testing.T) {
	cfg := &config.Config{
		MaxConcurrent:          10,
		QueueTimeout:           1 * time.Second,
		RateLimitCapacity:      10,
		RateLimitRate:          1.0,
		BurstThreshold:         10,
		BurstWindow:            1 * time.Second,
		EndpointAbuseThreshold: 10,
		EndpointAbuseWindow:    1 * time.Second,
		CacheCapacity:          10,
		CacheTTL:               1 * time.Minute,
		LogFilePath:            "logs/test_traffic.jsonl",
		LogBufferSize:          1024,
	}

	components, err := NewComponents(cfg)
	if err != nil {
		t.Fatalf("Failed to create components: %v", err)
	}

	// Verify all background tickers and channels were started
	if components.CacheStop == nil {
		t.Error("Expected CacheStop channel to be active")
	}
	if components.RateLimiterStop == nil {
		t.Error("Expected RateLimiterStop channel to be active")
	}
	if components.TrafficRulesStop == nil {
		t.Error("Expected TrafficRulesStop channel to be active")
	}
	if components.PollerStop == nil {
		t.Error("Expected PollerStop channel to be active")
	}

	// Close components — must terminate all workers cleanly without hanging or panic
	components.Close()

	if components.CacheStop != nil || components.PollerStop != nil {
		t.Error("Expected stop channels to be nil after Close")
	}
}
