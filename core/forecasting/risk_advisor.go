package forecasting

import (
	"fmt"
	"sync"
	"time"

	"github.com/Keshav76315/turboSH/core/decision"
	"github.com/Keshav76315/turboSH/monitoring"
)

// RiskAdvisory encapsulates the fused real-time + predictive threat assessment.
type RiskAdvisory struct {
	ThreatLevel       string          `json:"threat_level"`       // "NORMAL", "ELEVATED", "HIGH", "CRITICAL"
	RecommendedAction decision.Action `json:"recommended_action"` // ActionAllow, ActionRateLimit, ActionBlock
	CurrentScore      float64         `json:"current_score"`      // From real-time Isolation Forest
	ForecastStages    [3]string       `json:"forecast_stages"`    // Predicted stages at t+1, t+2, t+3
	ForecastConf      [3]float64      `json:"forecast_conf"`      // Confidences per step
	LeadTimeSec       int             `json:"lead_time_seconds"`  // Estimated lead time until attack peak/surge
	Justification     string          `json:"justification"`      // Human-readable explainable rationale
	MITRETechniques   []string        `json:"mitre_techniques"`    // Relevant MITRE ATT&CK technique IDs
	Timestamp         time.Time       `json:"timestamp"`
}

// DefaultForecastCacheTTL is the default cache lifetime for sequence predictions (250ms).
// This prevents running full ONNX/heuristic sequence models synchronously on every single HTTP packet.
const DefaultForecastCacheTTL = 250 * time.Millisecond

// RiskAdvisor integrates real-time anomaly telemetry with forward-looking predictions.
type RiskAdvisor struct {
	forecaster     *Forecaster
	latestAdvisory *RiskAdvisory
	cachedForecast *ForecastResult
	lastForecast   time.Time
	cacheTTL       time.Duration
	mu             sync.RWMutex
}

// NewRiskAdvisor creates a new risk advisory engine.
func NewRiskAdvisor(forecaster *Forecaster) *RiskAdvisor {
	return &RiskAdvisor{
		forecaster: forecaster,
		cacheTTL:   DefaultForecastCacheTTL,
		latestAdvisory: &RiskAdvisory{
			ThreatLevel:       "NORMAL",
			RecommendedAction: decision.ActionAllow,
			ForecastStages:    [3]string{"NORMAL", "NORMAL", "NORMAL"},
			ForecastConf:      [3]float64{0.95, 0.90, 0.85},
			LeadTimeSec:       0,
			Justification:     "Baseline network telemetry — no threat patterns detected.",
			MITRETechniques:   []string{},
			Timestamp:         time.Now(),
		},
	}
}

// SetCacheTTL configures the minimum interval between sequence model predictions.
func (ra *RiskAdvisor) SetCacheTTL(ttl time.Duration) {
	ra.mu.Lock()
	defer ra.mu.Unlock()
	ra.cacheTTL = ttl
}

// Forecaster returns the underlying forecaster instance.
func (ra *RiskAdvisor) Forecaster() *Forecaster {
	return ra.forecaster
}

// LatestAdvisory returns the most recent cached risk advisory.
func (ra *RiskAdvisor) LatestAdvisory() *RiskAdvisory {
	ra.mu.RLock()
	defer ra.mu.RUnlock()
	return ra.latestAdvisory
}

// AssessAction returns the recommended action, satisfying decision.RiskAssessor.
func (ra *RiskAdvisor) AssessAction(currentScore float64, baseAction decision.Action) decision.Action {
	advisory := ra.Assess(currentScore, baseAction)
	return advisory.RecommendedAction
}

// GetForecastSnapshot satisfies the monitoring.ForecastProvider interface.
func (ra *RiskAdvisor) GetForecastSnapshot() monitoring.ForecastSnapshot {
	advisory := ra.LatestAdvisory()
	if advisory == nil {
		return monitoring.ForecastSnapshot{
			Enabled:     false,
			ModelName:   "None",
			ThreatLevel: "NORMAL",
			LastUpdated: time.Now(),
		}
	}

	enabled := false
	modelName := "None"
	if ra.forecaster != nil {
		enabled = true
		if ra.forecaster.IsModelLoaded() {
			modelName = "Transformer Forecaster (ONNX)"
		} else {
			modelName = "Heuristic Forecaster"
		}
	}

	return monitoring.ForecastSnapshot{
		Enabled:         enabled,
		ModelName:       modelName,
		ThreatLevel:     advisory.ThreatLevel,
		Predictions:     advisory.ForecastStages,
		Confidences:     advisory.ForecastConf,
		LeadTimeSec:     advisory.LeadTimeSec,
		MITRETechniques: advisory.MITRETechniques,
		Justification:   advisory.Justification,
		LastUpdated:     advisory.Timestamp,
	}
}

// getOrRefreshForecast retrieves the cached forecast if within TTL, or runs a fresh prediction.
func (ra *RiskAdvisor) getOrRefreshForecast() (ForecastResult, error) {
	ra.mu.RLock()
	if ra.cachedForecast != nil && ra.cacheTTL > 0 && time.Since(ra.lastForecast) < ra.cacheTTL {
		fc := *ra.cachedForecast
		ra.mu.RUnlock()
		return fc, nil
	}
	ra.mu.RUnlock()

	ra.mu.Lock()
	defer ra.mu.Unlock()

	// Double-check after acquiring write lock
	if ra.cachedForecast != nil && ra.cacheTTL > 0 && time.Since(ra.lastForecast) < ra.cacheTTL {
		return *ra.cachedForecast, nil
	}

	if ra.forecaster == nil {
		return ForecastResult{}, fmt.Errorf("forecaster is nil")
	}

	fc, err := ra.forecaster.Predict()
	// Always cache the returned forecast (including heuristic fallback) and timestamp
	ra.cachedForecast = &fc
	ra.lastForecast = time.Now()
	return fc, err
}

// Assess evaluates the current anomaly score and existing decision against the forecast world model.
//
// INVARIANT: The returned RecommendedAction is strictly monotonically non-decreasing
// relative to baseAction. A forecast can upgrade protection (ALLOW -> RATE_LIMIT -> BLOCK)
// but NEVER downgrade an already triggered firewall decision.
func (ra *RiskAdvisor) Assess(currentScore float64, baseAction decision.Action) RiskAdvisory {
	now := time.Now()

	// Default fallback advisory
	advisory := RiskAdvisory{
		ThreatLevel:       "NORMAL",
		RecommendedAction: baseAction,
		CurrentScore:      currentScore,
		ForecastStages:    [3]string{"NORMAL", "NORMAL", "NORMAL"},
		ForecastConf:      [3]float64{0.95, 0.90, 0.85},
		LeadTimeSec:       0,
		Justification:     "Regular baseline traffic pattern.",
		MITRETechniques:   []string{},
		Timestamp:         now,
	}

	if ra.forecaster == nil {
		ra.updateCached(advisory)
		return advisory
	}

	fc, err := ra.getOrRefreshForecast()

	advisory.ForecastStages = fc.PredictedStages
	advisory.ForecastConf = fc.Confidences
	advisory.LeadTimeSec = fc.LeadTimeSeconds
	advisory.ThreatLevel = fc.RiskLevel

	// ─── Fusion Policy ─────────────────────────────────────────────────────────────
	// 1. Preemptive Block: High confidence SURGE/SUSTAINED predicted + non-trivial current anomaly
	hasSurge := false
	surgeConf := 0.0
	for h := 0; h < 3; h++ {
		if (fc.StageIndices[h] == StageSurge || fc.StageIndices[h] == StageSustained) && fc.Confidences[h] > 0.70 {
			hasSurge = true
			if fc.Confidences[h] > surgeConf {
				surgeConf = fc.Confidences[h]
			}
		}
	}

	if hasSurge && currentScore > 0.50 {
		advisory.RecommendedAction = decision.ActionBlock
		advisory.ThreatLevel = "CRITICAL"
		advisory.MITRETechniques = []string{"T1498", "T1499"}
		advisory.Justification = fmt.Sprintf(
			"Preemptive Block: Model forecasts imminent volumetric attack (conf: %.0f%%) with elevated current anomaly (%.2f).",
			surgeConf*100, currentScore,
		)
	} else if fc.StageIndices[0] == StageEscalation && fc.Confidences[0] > 0.60 && baseAction == decision.ActionAllow {
		// 2. Preemptive Throttle: Escalation approaching at t+1
		advisory.RecommendedAction = decision.ActionRateLimit
		advisory.ThreatLevel = "HIGH"
		advisory.MITRETechniques = []string{"T1498.001", "T1499"}
		advisory.Justification = fmt.Sprintf(
			"Preemptive Throttle: Attack escalation predicted at t+1 (conf: %.0f%%). Throttling traffic to protect downstream services.",
			fc.Confidences[0]*100,
		)
	} else if fc.StageIndices[0] == StageRecon && fc.Confidences[0] > 0.50 {
		// 3. Reconnaissance: Increase monitoring level
		advisory.ThreatLevel = "ELEVATED"
		advisory.MITRETechniques = []string{"T1595"}
		advisory.Justification = fmt.Sprintf(
			"Scanning and reconnaissance probing detected (conf: %.0f%%). Increased telemetry logging active.",
			fc.Confidences[0]*100,
		)
	} else if fc.RiskLevel == "CRITICAL" || fc.RiskLevel == "HIGH" {
		// Higher level predicted without meeting immediate block criteria
		advisory.ThreatLevel = fc.RiskLevel
		advisory.MITRETechniques = []string{"T1498", "T1499"}
		advisory.Justification = fmt.Sprintf(
			"Forward trajectory indicates %s risk (lead time: %ds).",
			fc.RiskLevel, fc.LeadTimeSeconds,
		)
	} else {
		advisory.ThreatLevel = "NORMAL"
		advisory.Justification = "Traffic characteristics align with normal operating profile."
	}

	if err != nil {
		advisory.Justification = fmt.Sprintf("Forecaster error (%v); using fallback heuristic: %s", err, advisory.Justification)
	}

	// ─── Monotonic Upgrade Guarantee ──────────────────────────────────────────────
	// A forecast recommendation MUST NEVER weaken an action determined by the base engine.
	if advisory.RecommendedAction < baseAction {
		advisory.RecommendedAction = baseAction
	}

	ra.updateCached(advisory)
	return advisory
}

func (ra *RiskAdvisor) updateCached(advisory RiskAdvisory) {
	ra.mu.Lock()
	defer ra.mu.Unlock()
	ra.latestAdvisory = &advisory
}
