package inference

import (
	"math"
)

// RequestFeatures represents the structured format for the 6 features
// expected by our Isolation Forest anomaly detection model.
type RequestFeatures struct {
	RequestsPerIP10s float32
	RequestsPerIP60s float32
	EndpointEntropy  float32
	LatencySpike     float32 // 0.0 or 1.0
	ErrorRate        float32 // 0.0 to 1.0
	RequestVariance  float32
}

// ToArray converts the struct into a flat array of float32 expected by ONNX.
// The order MUST match the training order:
// ['requests_per_ip_10s', 'requests_per_ip_60s', 'endpoint_entropy',
//
//	'latency_spike', 'error_rate', 'request_variance']
func (f RequestFeatures) ToArray() []float32 {
	return []float32{
		f.RequestsPerIP10s,
		f.RequestsPerIP60s,
		f.EndpointEntropy,
		f.LatencySpike,
		f.ErrorRate,
		f.RequestVariance,
	}
}

// NormalizeScore converts the raw Isolation Forest decision_function output
// to a 0.0–1.0 anomaly score using a sigmoid transformation.
//
// Isolation Forest decision_function semantics:
//   - Negative values → anomalous (further negative = more anomalous)
//   - Positive values → normal (further positive = more normal)
//
// The sigmoid maps this to:
//   - Large negative → ~1.0 (high anomaly risk, triggers BLOCK)
//   - Near zero      → ~0.5 (moderate risk, triggers RATE_LIMIT)
//   - Large positive → ~0.0 (normal traffic, ALLOW)
//
// The steepness factor k=5 provides good separation around the decision boundary.
func NormalizeScore(decisionFuncValue float64) float64 {
	score := 1.0 / (1.0 + math.Exp(5.0*decisionFuncValue))
	// Clamp to [0.0, 1.0] for safety against floating-point edge cases
	return math.Max(0.0, math.Min(1.0, score))
}

// ShannonEntropy computes the normalized Shannon entropy of a given array of counts.
// Used to calculate EndpointEntropy. Returns a value between 0.0 (single endpoint)
// and 1.0 (uniform distribution across multiple endpoints).
func ShannonEntropy(counts []int) float32 {
	if len(counts) <= 1 {
		return 0.0
	}

	total := 0
	nonZero := 0
	for _, c := range counts {
		if c > 0 {
			total += c
			nonZero++
		}
	}
	if total == 0 || nonZero <= 1 {
		return 0.0
	}

	var entropy float64
	for _, c := range counts {
		if c > 0 {
			p := float64(c) / float64(total)
			entropy -= p * math.Log2(p)
		}
	}

	maxEntropy := math.Log2(float64(nonZero))
	if maxEntropy <= 0 {
		return 0.0
	}
	return float32(entropy / maxEntropy)
}
