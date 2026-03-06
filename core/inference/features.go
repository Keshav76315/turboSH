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

// NormalizeScore takes the raw ONNX Isolation Forest output
// (1 = normal, -1 = anomaly) and converts it to a 0.0 to 1.0 scale
// where 1.0 is highest anomaly risk, to be usable by DecisionEngine.
func NormalizeScore(rawScore int64) float64 {
	if rawScore == -1 {
		return 1.0 // Maximum anomaly
	}
	return 0.0 // Normal
}

// ShannonEntropy computes the entropy of a given array of counts.
// Used to calculate EndpointEntropy.
func ShannonEntropy(counts []int) float32 {
	if len(counts) == 0 {
		return 0.0
	}

	total := 0
	for _, c := range counts {
		total += c
	}
	if total == 0 {
		return 0.0
	}

	var entropy float64
	for _, c := range counts {
		if c > 0 {
			p := float64(c) / float64(total)
			entropy -= p * math.Log2(p)
		}
	}
	return float32(entropy)
}
