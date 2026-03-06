package inference

import (
	"crypto/sha256"
	"encoding/hex"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/Keshav76315/turboSH/core/decision"
	"github.com/gin-gonic/gin"
)

// MLProtection encapsulates the inference engine, decision engine,
// and moving windows needed to compute live features.
type MLProtection struct {
	engine         *Engine
	decisionEngine decision.DecisionEngine

	// Feature tracking state
	requestTimes map[string][]time.Time
	endpoints    map[string]map[string]int // IP -> Endpoint -> Count

	// Moving window duration constants
	window10s time.Duration
	window60s time.Duration

	mu sync.Mutex
}

// redactIP hashes the IP address to protect raw PII in the logs.
func redactIP(ip string) string {
	hash := sha256.Sum256([]byte(ip + "turboSH_salt"))
	return hex.EncodeToString(hash[:8])
}

// NewMLProtection initializes the live ML-based protection middleware.
func NewMLProtection(engine *Engine, de decision.DecisionEngine) *MLProtection {
	return &MLProtection{
		engine:         engine,
		decisionEngine: de,
		requestTimes:   make(map[string][]time.Time),
		endpoints:      make(map[string]map[string]int),
		window10s:      10 * time.Second,
		window60s:      60 * time.Second,
	}
}

// prune records older than the maximum window (60s)
func (mlp *MLProtection) prune(ip string, now time.Time) {
	times := mlp.requestTimes[ip]
	cutoff60 := now.Add(-mlp.window60s)

	var valid []time.Time
	for _, t := range times {
		if t.After(cutoff60) {
			valid = append(valid, t)
		}
	}
	mlp.requestTimes[ip] = valid

	if len(valid) == 0 {
		delete(mlp.requestTimes, ip)
		delete(mlp.endpoints, ip)
	}
}

// recordRequest updates the internal trackers for a given IP and endpoint.
// It returns the computed features for the ML model.
func (mlp *MLProtection) recordRequest(ip string, endpoint string) RequestFeatures {
	mlp.mu.Lock()
	defer mlp.mu.Unlock()

	now := time.Now()
	mlp.requestTimes[ip] = append(mlp.requestTimes[ip], now)

	if mlp.endpoints[ip] == nil {
		mlp.endpoints[ip] = make(map[string]int)
	}
	mlp.endpoints[ip][endpoint]++

	mlp.prune(ip, now)

	// Calculate Requests per 10s and 60s
	cutoff10 := now.Add(-mlp.window10s)

	var reqs10s int
	var reqs60s int = len(mlp.requestTimes[ip])

	for _, t := range mlp.requestTimes[ip] {
		if t.After(cutoff10) {
			reqs10s++
		}
	}

	// Calculate Endpoint Entropy
	counts := make([]int, 0, len(mlp.endpoints[ip]))
	for _, c := range mlp.endpoints[ip] {
		counts = append(counts, c)
	}
	entropy := ShannonEntropy(counts)

	// Stubbing more advanced tracking (latency, error_rate, variance)
	// In a full implementation, these would read from shared metrics maps populated
	// by observing backend responses. Using robust estimations for now to allow
	// ML inference on the proxy request timeline.

	variance := float32(50.0) // Stub healthy variance
	if reqs60s > 100 {
		variance = 100.0
	} else if reqs60s < 10 {
		variance = 10.0
	}

	return RequestFeatures{
		RequestsPerIP10s: float32(reqs10s),
		RequestsPerIP60s: float32(reqs60s),
		EndpointEntropy:  entropy,
		LatencySpike:     0.0,  // Stub
		ErrorRate:        0.05, // Stub base error rate
		RequestVariance:  variance,
	}
}

// Middleware returns a Gin HandlerFunc that extracts features, predicts
// anomalies via ONNX, evaluates them against the Decision Engine, and takes action.
func (mlp *MLProtection) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		ip := c.ClientIP()
		endpoint := c.Request.URL.Path

		// 1. Extract dynamic features
		features := mlp.recordRequest(ip, endpoint)

		// 2. Predict Anomaly Score (0.0 to 1.0)
		score, err := mlp.engine.Predict(features)
		if err != nil {
			log.Printf("[ML Protection] Inference error for %s: %v", ip, err)
			c.Next() // Fail open to maintain proxy availability
			return
		}

		// 3. Evaluate Decision
		prediction := decision.Prediction{
			IPHash:       ip,
			AnomalyScore: score,
		}

		action := mlp.decisionEngine.Evaluate(prediction)

		// 4. Enforce Action
		switch action {
		case decision.ActionBlock:
			log.Printf("[ML Protection] 🚨 BLOCKING %s (Score: %.2f)", redactIP(ip), score)
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":   "access_denied",
				"message": "Traffic resembles a known attack signature. Blocked.",
			})
			return
		case decision.ActionRateLimit:
			// In a more complex setup, we would dynamically tighten the token bucket here.
			// Instead of a hard block, we simulate aggressive rate limiting by returning 429.
			log.Printf("[ML Protection] ⚠️ THROTTLING %s (Score: %.2f)", redactIP(ip), score)
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":   "rate_limit_exceeded",
				"message": "Suspicious traffic pattern detected. Please slow down.",
			})
			return
		case decision.ActionAllow:
			// log.Printf("[ML Protection] ✅ ALLOW %s", redactIP(ip))
			c.Next()
		default:
			log.Printf("[ML Protection] ❓ UNKNOWN ACTION %s for %s (Score: %.2f) - Defaulting to ALLOW", action, redactIP(ip), score)
			c.Next()
		}
	}
}
