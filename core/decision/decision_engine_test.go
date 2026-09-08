package decision_test

import (
	"testing"

	"github.com/Keshav76315/turboSH/core/decision"
)

func TestNewDefaultThresholdPolicy(t *testing.T) {
	policy := decision.NewDefaultThresholdPolicy()
	if policy == nil {
		t.Fatal("Expected non-nil default threshold policy")
	}
	if policy.BlockThreshold != decision.DefaultBlockThreshold {
		t.Errorf("Expected BlockThreshold %f, got %f", decision.DefaultBlockThreshold, policy.BlockThreshold)
	}
	if policy.RateLimitThreshold != decision.DefaultRateLimitThreshold {
		t.Errorf("Expected RateLimitThreshold %f, got %f", decision.DefaultRateLimitThreshold, policy.RateLimitThreshold)
	}
}

func TestNewThresholdPolicy_ZeroThresholds(t *testing.T) {
	// Flaw 6.5: 0.0 rate limit threshold must not be overridden to 0.65
	policy, err := decision.NewThresholdPolicy(0.5, 0.0)
	if err != nil {
		t.Fatalf("Unexpected error configuring 0.0 rate limit threshold: %v", err)
	}
	if policy.RateLimitThreshold != 0.0 {
		t.Errorf("Expected RateLimitThreshold 0.0, got %f", policy.RateLimitThreshold)
	}
	if policy.BlockThreshold != 0.5 {
		t.Errorf("Expected BlockThreshold 0.5, got %f", policy.BlockThreshold)
	}

	// 0.0 block threshold with negative rate limit threshold
	policyZeroBlock, err := decision.NewThresholdPolicy(0.0, -0.1)
	if err != nil {
		t.Fatalf("Unexpected error configuring 0.0 block threshold: %v", err)
	}
	if policyZeroBlock.BlockThreshold != 0.0 {
		t.Errorf("Expected BlockThreshold 0.0, got %f", policyZeroBlock.BlockThreshold)
	}
	if policyZeroBlock.RateLimitThreshold != -0.1 {
		t.Errorf("Expected RateLimitThreshold -0.1, got %f", policyZeroBlock.RateLimitThreshold)
	}
}

func TestNewThresholdPolicy_Validation(t *testing.T) {
	// rateLimitThreshold >= blockThreshold should return an error
	_, err := decision.NewThresholdPolicy(0.5, 0.5)
	if err == nil {
		t.Error("Expected error when rateLimitThreshold == blockThreshold, got nil")
	}

	_, err = decision.NewThresholdPolicy(0.4, 0.6)
	if err == nil {
		t.Error("Expected error when rateLimitThreshold > blockThreshold, got nil")
	}
}

func TestThresholdPolicy_Evaluate(t *testing.T) {
	policy, err := decision.NewThresholdPolicy(0.85, 0.65)
	if err != nil {
		t.Fatalf("Unexpected error creating policy: %v", err)
	}

	tests := []struct {
		score    float64
		expected decision.Action
	}{
		{0.95, decision.ActionBlock},
		{0.86, decision.ActionBlock},
		{0.85, decision.ActionRateLimit}, // boundary: > 0.85 is block, 0.85 is rate limit
		{0.75, decision.ActionRateLimit},
		{0.66, decision.ActionRateLimit},
		{0.65, decision.ActionAllow},     // boundary: > 0.65 is rate limit, 0.65 is allow
		{0.50, decision.ActionAllow},
		{0.0, decision.ActionAllow},
	}

	for _, tc := range tests {
		pred := decision.Prediction{AnomalyScore: tc.score}
		act := policy.Evaluate(pred)
		if act != tc.expected {
			t.Errorf("Score %f: expected %s, got %s", tc.score, tc.expected, act)
		}
	}
}

func TestPassthroughPolicy(t *testing.T) {
	pp := &decision.PassthroughPolicy{}
	act := pp.Evaluate(decision.Prediction{AnomalyScore: 0.99})
	if act != decision.ActionAllow {
		t.Errorf("Expected ActionAllow from PassthroughPolicy, got %s", act)
	}
}

func TestAction_String(t *testing.T) {
	if decision.ActionAllow.String() != "ALLOW" {
		t.Errorf("Expected ALLOW, got %s", decision.ActionAllow.String())
	}
	if decision.ActionRateLimit.String() != "RATE_LIMIT" {
		t.Errorf("Expected RATE_LIMIT, got %s", decision.ActionRateLimit.String())
	}
	if decision.ActionBlock.String() != "BLOCK" {
		t.Errorf("Expected BLOCK, got %s", decision.ActionBlock.String())
	}
	if decision.Action(999).String() != "UNKNOWN" {
		t.Errorf("Expected UNKNOWN, got %s", decision.Action(999).String())
	}
}
