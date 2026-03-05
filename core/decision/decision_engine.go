// Package decision implements the decision engine that translates anomaly scores into actions.
package decision

// Action represents the action to take based on an anomaly score.
type Action int

const (
	ActionAllow     Action = iota // Allow the request to proceed
	ActionRateLimit               // Throttle the client
	ActionBlock                   // Block the request entirely
)

// String returns a human-readable name for the action.
func (a Action) String() string {
	switch a {
	case ActionAllow:
		return "ALLOW"
	case ActionRateLimit:
		return "RATE_LIMIT"
	case ActionBlock:
		return "BLOCK"
	default:
		return "UNKNOWN"
	}
}

// Prediction represents the output of the ML inference engine.
type Prediction struct {
	IPHash            string  `json:"ip_hash"`
	AnomalyScore      float64 `json:"anomaly_score"`
	RiskLevel         string  `json:"risk_level"`
	RecommendedAction string  `json:"recommended_action"`
}

// DecisionEngine evaluates predictions and returns the action to take.
type DecisionEngine interface {
	Evaluate(prediction Prediction) Action
}

// ThresholdPolicy is the default decision engine using configurable score thresholds.
type ThresholdPolicy struct {
	BlockThreshold     float64 // Score above this → BLOCK
	RateLimitThreshold float64 // Score above this → RATE_LIMIT
}

// NewThresholdPolicy creates a new threshold-based policy.
// Default: block > 0.85, rate_limit > 0.65, allow otherwise.
func NewThresholdPolicy(blockThreshold, rateLimitThreshold float64) *ThresholdPolicy {
	return &ThresholdPolicy{
		BlockThreshold:     blockThreshold,
		RateLimitThreshold: rateLimitThreshold,
	}
}

// Evaluate takes a prediction and returns the appropriate action.
func (tp *ThresholdPolicy) Evaluate(prediction Prediction) Action {
	if prediction.AnomalyScore > tp.BlockThreshold {
		return ActionBlock
	}
	if prediction.AnomalyScore > tp.RateLimitThreshold {
		return ActionRateLimit
	}
	return ActionAllow
}

// PassthroughPolicy is a stub that always allows requests.
// Used when ML inference is not yet integrated.
type PassthroughPolicy struct{}

// Evaluate always returns ActionAllow. This is the default until ML is connected.
func (pp *PassthroughPolicy) Evaluate(_ Prediction) Action {
	return ActionAllow
}
