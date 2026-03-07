package inference

import (
	"crypto/sha256"
	"encoding/hex"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/Keshav76315/turboSH/core/decision"
	"github.com/Keshav76315/turboSH/monitoring"
	"github.com/gin-gonic/gin"
)

var ipSalt string

func init() {
	ipSalt = os.Getenv("TURBOSH_IP_SALT")
	if ipSalt == "" {
		ipSalt = "turboSH_default_salt"
		log.Println("[inference] TURBOSH_IP_SALT not set, using default salt for IP redaction")
	}
}

// BackendResponse tracks the outcome of a request for ML features.
type BackendResponse struct {
	Timestamp  time.Time
	StatusCode int
	LatencyMs  float64
}

// MLProtection encapsulates the inference engine, decision engine,
// and moving windows needed to compute live features.
type MLProtection struct {
	engine         *Engine
	decisionEngine decision.DecisionEngine

	// Feature tracking state
	requestTimes map[string][]time.Time
	endpoints    map[string]map[string]int    // IP -> Endpoint -> Count
	ipStats      map[string][]BackendResponse // IP -> Recent Responses

	// Moving window duration constants
	window10s time.Duration
	window60s time.Duration

	mu sync.Mutex
}

// RedactIP hashes the IP address to protect raw PII in the logs.
func RedactIP(ip string) string {
	hash := sha256.Sum256([]byte(ip + ipSalt))
	return hex.EncodeToString(hash[:8])
}

// NewMLProtection initializes the live ML-based protection middleware.
func NewMLProtection(engine *Engine, de decision.DecisionEngine) *MLProtection {
	return &MLProtection{
		engine:         engine,
		decisionEngine: de,
		requestTimes:   make(map[string][]time.Time),
		endpoints:      make(map[string]map[string]int),
		ipStats:        make(map[string][]BackendResponse),
		window10s:      10 * time.Second,
		window60s:      60 * time.Second,
	}
}

// prune records older than the maximum window (60s)
func (mlp *MLProtection) prune(ip string, now time.Time) {
	times := mlp.requestTimes[ip]
	cutoff60 := now.Add(-mlp.window60s)

	var validTimes []time.Time
	for _, t := range times {
		if t.After(cutoff60) {
			validTimes = append(validTimes, t)
		}
	}
	mlp.requestTimes[ip] = validTimes

	// Prune IP stats as well
	stats := mlp.ipStats[ip]
	var validStats []BackendResponse
	for _, s := range stats {
		if s.Timestamp.After(cutoff60) {
			validStats = append(validStats, s)
		}
	}
	mlp.ipStats[ip] = validStats

	if len(validTimes) == 0 && len(validStats) == 0 {
		delete(mlp.requestTimes, ip)
		delete(mlp.endpoints, ip)
		delete(mlp.ipStats, ip)
	}
}

// RecordBackendResponse is called by the traffic logger after a request completes
// to feed actual response metrics back into the ML feature window.
func (mlp *MLProtection) RecordBackendResponse(ip string, statusCode int, latencyMs float64) {
	mlp.mu.Lock()
	defer mlp.mu.Unlock()

	now := time.Now()
	mlp.ipStats[ip] = append(mlp.ipStats[ip], BackendResponse{
		Timestamp:  now,
		StatusCode: statusCode,
		LatencyMs:  latencyMs,
	})

	mlp.prune(ip, now)
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

	// Calculate Error Rate, Latency Spike, and Request Variance from ipStats
	stats := mlp.ipStats[ip]

	var errorCount int
	var totalLatency float64
	var maxLatency float64
	var latencies []float64

	for _, s := range stats {
		if s.StatusCode >= 400 {
			errorCount++
		}
		totalLatency += s.LatencyMs
		latencies = append(latencies, s.LatencyMs)
		if s.LatencyMs > maxLatency {
			maxLatency = s.LatencyMs
		}
	}

	var errorRate float32 = 0.0
	if len(stats) > 0 {
		errorRate = float32(errorCount) / float32(len(stats))
	}

	var latencySpike float32 = 0.0
	if len(stats) > 0 {
		avgLatency := totalLatency / float64(len(stats))
		// If the max latency in the window is > 1.5x the average (and at least 100ms), flag as a spike
		if maxLatency > (avgLatency*1.5) && maxLatency > 100.0 {
			latencySpike = 1.0
		}
	}

	// Calculate Variance of Latency
	var variance float32 = 0.0
	if len(latencies) > 1 {
		avg := totalLatency / float64(len(latencies))
		var sumSquares float64
		for _, l := range latencies {
			diff := l - avg
			sumSquares += diff * diff
		}
		variance = float32(sumSquares / float64(len(latencies)-1))
	} else if len(latencies) == 1 {
		variance = 0.0 // mathematically correct variance for a single request
	}

	return RequestFeatures{
		RequestsPerIP10s: float32(reqs10s),
		RequestsPerIP60s: float32(reqs60s),
		EndpointEntropy:  entropy,
		LatencySpike:     latencySpike,
		ErrorRate:        errorRate,
		RequestVariance:  variance,
	}
}

// Middleware returns a Gin HandlerFunc that extracts features, predicts
// anomalies via ONNX, evaluates them against the Decision Engine, and takes action.
func (mlp *MLProtection) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		ipHash := RedactIP(c.ClientIP())
		endpoint := c.Request.URL.Path

		// 1. Extract dynamic features
		features := mlp.recordRequest(ipHash, endpoint)

		// 2. Predict Anomaly Score (0.0 to 1.0)
		score, err := mlp.engine.Predict(features)
		if err != nil {
			log.Printf("[ML Protection] Inference error for %s: %v", ipHash, err)
			c.Next() // Fail open to maintain proxy availability
			return
		}

		// 3. Evaluate Decision
		prediction := decision.Prediction{
			IPHash:       ipHash,
			AnomalyScore: score,
		}

		action := mlp.decisionEngine.Evaluate(prediction)

		// 4. Enforce Action
		switch action {
		case decision.ActionBlock:
			monitoring.RecordMLBlock()
			log.Printf("[ML Protection] 🚨 BLOCKING %s (Score: %.2f)", ipHash, score)
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":   "access_denied",
				"message": "Traffic resembles a known attack signature. Blocked.",
			})
			return
		case decision.ActionRateLimit:
			monitoring.RecordMLThrottle()
			log.Printf("[ML Protection] ⚠️ THROTTLING %s (Score: %.2f)", ipHash, score)
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":   "rate_limit_exceeded",
				"message": "Suspicious traffic pattern detected. Please slow down.",
			})
			return
		case decision.ActionAllow:
			monitoring.RecordMLAllow()
			log.Printf("[ML Protection] ✅ ALLOW %s", ipHash)
			c.Next()
		default:
			log.Printf("[ML Protection] ❓ UNKNOWN ACTION %s for %s (Score: %.2f) - Defaulting to ALLOW", action, ipHash, score)
			c.Next()
		}
	}
}
