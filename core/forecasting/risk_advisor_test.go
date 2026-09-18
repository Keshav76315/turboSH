package forecasting

import (
	"testing"
	"time"

	"github.com/Keshav76315/turboSH/core/decision"
	"github.com/Keshav76315/turboSH/core/inference"
)

func TestRiskAdvisorDefaultState(t *testing.T) {
	ra := NewRiskAdvisor(nil)
	adv := ra.LatestAdvisory()

	if adv.ThreatLevel != "NORMAL" {
		t.Errorf("expected default ThreatLevel NORMAL, got %s", adv.ThreatLevel)
	}
	if adv.RecommendedAction != decision.ActionAllow {
		t.Errorf("expected default ActionAllow, got %v", adv.RecommendedAction)
	}
}

func TestRiskAdvisorPreemptiveBlock(t *testing.T) {
	f, _ := NewForecaster("", "", 10)
	defer f.Close()

	// High anomaly causing surge forecast
	f.AddState(inference.StateSnapshot{
		AnomalyScore: 0.90,
	})

	ra := NewRiskAdvisor(f)
	// Current score 0.55 (> 0.50), base action is RATE_LIMIT
	adv := ra.Assess(0.55, decision.ActionRateLimit)

	if adv.RecommendedAction != decision.ActionBlock {
		t.Errorf("expected Preemptive ActionBlock, got %v", adv.RecommendedAction)
	}
	if adv.ThreatLevel != "CRITICAL" {
		t.Errorf("expected ThreatLevel CRITICAL, got %s", adv.ThreatLevel)
	}
	if len(adv.MITRETechniques) == 0 {
		t.Errorf("expected MITRE techniques for surge block")
	}
}

func TestRiskAdvisorPreemptiveThrottle(t *testing.T) {
	f, _ := NewForecaster("", "", 10)
	defer f.Close()

	// Moderate anomaly causing escalation forecast
	f.AddState(inference.StateSnapshot{
		AnomalyScore: 0.70,
	})

	ra := NewRiskAdvisor(f)
	// Base action is ALLOW
	adv := ra.Assess(0.30, decision.ActionAllow)

	if adv.RecommendedAction != decision.ActionRateLimit {
		t.Errorf("expected Preemptive ActionRateLimit, got %v", adv.RecommendedAction)
	}
	if adv.ThreatLevel != "HIGH" {
		t.Errorf("expected ThreatLevel HIGH, got %s", adv.ThreatLevel)
	}
}

func TestRiskAdvisorMonotonicUpgradeGuarantee(t *testing.T) {
	f, _ := NewForecaster("", "", 10)
	defer f.Close()

	// Low anomaly / normal state
	f.AddState(inference.StateSnapshot{
		AnomalyScore: 0.10,
	})

	ra := NewRiskAdvisor(f)

	// Even if forecast is completely NORMAL, if the real-time engine has already decided to BLOCK,
	// the advisor MUST NEVER downgrade to Allow or RateLimit.
	adv := ra.Assess(0.95, decision.ActionBlock)
	if adv.RecommendedAction != decision.ActionBlock {
		t.Errorf("VIOLATION: advisor downgraded ActionBlock to %v", adv.RecommendedAction)
	}

	// Similarly, if base action is RATE_LIMIT, it must never be downgraded to ALLOW.
	advRate := ra.Assess(0.70, decision.ActionRateLimit)
	if advRate.RecommendedAction < decision.ActionRateLimit {
		t.Errorf("VIOLATION: advisor downgraded ActionRateLimit to %v", advRate.RecommendedAction)
	}
}

func TestRiskAdvisorForecastCacheTTL(t *testing.T) {
	f, _ := NewForecaster("", "", 10)
	defer f.Close()

	ra := NewRiskAdvisor(f)
	ra.SetCacheTTL(100 * time.Millisecond)

	// First assessment generates initial cached forecast
	adv1 := ra.Assess(0.10, decision.ActionAllow)
	if adv1.ThreatLevel != "NORMAL" {
		t.Errorf("expected ThreatLevel NORMAL, got %s", adv1.ThreatLevel)
	}

	// Add high anomaly state immediately
	f.AddState(inference.StateSnapshot{
		AnomalyScore: 0.95,
	})

	// Within TTL (0ms passed), cached forecast is reused
	adv2 := ra.Assess(0.10, decision.ActionAllow)
	if adv2.ThreatLevel != "NORMAL" {
		t.Errorf("expected cached ThreatLevel NORMAL within TTL, got %s", adv2.ThreatLevel)
	}

	// Wait for TTL to expire
	time.Sleep(120 * time.Millisecond)

	// Now assessment should refresh forecast with the high anomaly state
	adv3 := ra.Assess(0.55, decision.ActionAllow)
	if adv3.ThreatLevel != "CRITICAL" {
		t.Errorf("expected updated ThreatLevel CRITICAL after TTL expiration, got %s", adv3.ThreatLevel)
	}
}
