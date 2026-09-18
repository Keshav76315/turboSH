//go:build !cgo

package forecasting

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sync"
	"time"

	"github.com/Keshav76315/turboSH/core/inference"
)

// Attack stage taxonomy constants
const (
	StageNormal     = 0
	StageRecon      = 1
	StageEscalation = 2
	StageSurge      = 3
	StageSustained  = 4
)

// StageNames maps integer attack stages to human-readable labels.
var StageNames = [5]string{
	"NORMAL",
	"RECON",
	"ESCALATION",
	"SURGE",
	"SUSTAINED",
}

// ScalerParams represents feature standardization parameters (from scaler.json).
type ScalerParams struct {
	FeatureNames []string  `json:"feature_names"`
	Means        []float64 `json:"means"`
	Stds         []float64 `json:"stds"`
	Eps          float64   `json:"eps"`
}

// LoadScaler reads Z-score parameters from a JSON file.
func LoadScaler(path string) (ScalerParams, error) {
	var sp ScalerParams
	data, err := os.ReadFile(path)
	if err != nil {
		return sp, fmt.Errorf("failed to read scaler file: %w", err)
	}
	if err := json.Unmarshal(data, &sp); err != nil {
		return sp, fmt.Errorf("failed to parse scaler json: %w", err)
	}
	if sp.Eps == 0 {
		sp.Eps = 1e-8
	}
	return sp, nil
}

// ForecastResult represents the output of a multi-horizon forecast.
type ForecastResult struct {
	PredictedStages [3]string     `json:"predicted_stages"`
	StageIndices    [3]int        `json:"stage_indices"`
	Confidences     [3]float64    `json:"confidences"`
	Probabilities   [3][5]float64 `json:"probabilities"`
	RiskLevel       string        `json:"risk_level"`
	LeadTimeSeconds int           `json:"lead_time_seconds"`
	Timestamp       time.Time     `json:"timestamp"`
}

// Forecaster stub for non-CGO builds.
type Forecaster struct {
	scaler    ScalerParams
	buffer    []inference.StateSnapshot
	bufferCap int
	seqLen    int
	mu        sync.RWMutex
}

// NewForecaster initializes the stub forecaster with heuristics.
func NewForecaster(modelPath, scalerPath string, bufferCap int) (*Forecaster, error) {
	if bufferCap <= 0 {
		bufferCap = 30
	}
	seqLen := bufferCap
	if seqLen < 1 {
		seqLen = 1
	}
	scaler, _ := LoadScaler(scalerPath)
	return &Forecaster{
		scaler:    scaler,
		bufferCap: bufferCap,
		seqLen:    seqLen,
		buffer:    make([]inference.StateSnapshot, 0, bufferCap),
	}, nil
}

// IsModelLoaded reports whether the ONNX sequence model is loaded (always false in non-CGO builds).
func (f *Forecaster) IsModelLoaded() bool {
	return false
}

// Close is a no-op in non-CGO builds.
func (f *Forecaster) Close() {}

// AddState appends a snapshot to the sliding window with zero heap allocations once capacity is reached.
func (f *Forecaster) AddState(snap inference.StateSnapshot) {
	f.mu.Lock()
	defer f.mu.Unlock()

	if f.bufferCap <= 0 {
		f.bufferCap = 30
	}

	if len(f.buffer) < f.bufferCap {
		f.buffer = append(f.buffer, snap)
	} else {
		copy(f.buffer, f.buffer[1:])
		f.buffer[f.bufferCap-1] = snap
	}
}

// BufferLen returns current buffer size.
func (f *Forecaster) BufferLen() int {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return len(f.buffer)
}

// Predict provides heuristic forecasts in non-CGO environments.
func (f *Forecaster) Predict() (ForecastResult, error) {
	f.mu.RLock()
	defer f.mu.RUnlock()

	now := time.Now()
	res := ForecastResult{
		PredictedStages: [3]string{"NORMAL", "NORMAL", "NORMAL"},
		StageIndices:    [3]int{StageNormal, StageNormal, StageNormal},
		Confidences:     [3]float64{0.95, 0.90, 0.85},
		RiskLevel:       "LOW",
		LeadTimeSeconds: 0,
		Timestamp:       now,
	}

	bufLen := len(f.buffer)
	if bufLen == 0 {
		return res, nil
	}

	last := f.buffer[bufLen-1]
	var currStage int
	if last.AnomalyScore > 0.85 {
		currStage = StageSurge
	} else if last.AnomalyScore > 0.65 {
		currStage = StageEscalation
	} else if last.AnomalyScore > 0.40 {
		currStage = StageRecon
	} else {
		currStage = StageNormal
	}

	for h := 0; h < 3; h++ {
		stage := currStage
		if h > 0 && currStage == StageEscalation {
			stage = StageSurge
		} else if h > 0 && currStage == StageSurge {
			stage = StageSustained
		}
		res.StageIndices[h] = stage
		res.PredictedStages[h] = StageNames[stage]
		res.Confidences[h] = math.Max(0.50, 0.90-float64(h)*0.10)
		res.Probabilities[h][stage] = res.Confidences[h]
	}

	res.RiskLevel, res.LeadTimeSeconds = computeRiskAndLeadTime(res.StageIndices, res.Confidences)
	return res, nil
}

func computeRiskAndLeadTime(stages [3]int, confs [3]float64) (string, int) {
	hasSurge := false
	surgeHorizon := -1

	for h := 0; h < 3; h++ {
		if (stages[h] == StageSurge || stages[h] == StageSustained) && confs[h] >= 0.50 {
			hasSurge = true
			if surgeHorizon == -1 {
				surgeHorizon = h + 1
			}
		}
	}

	leadSecs := 0
	if surgeHorizon > 0 {
		leadSecs = surgeHorizon * 10
	}

	if hasSurge {
		if stages[0] == StageSurge || stages[0] == StageSustained || confs[surgeHorizon-1] >= 0.70 {
			return "CRITICAL", leadSecs
		}
		return "HIGH", leadSecs
	}

	for h := 0; h < 3; h++ {
		if stages[h] == StageEscalation && confs[h] >= 0.60 {
			return "HIGH", 0
		}
		if stages[h] == StageEscalation || (stages[h] == StageRecon && confs[h] >= 0.50) {
			return "ELEVATED", 0
		}
	}

	return "LOW", 0
}
