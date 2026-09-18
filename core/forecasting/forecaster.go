//go:build cgo

package forecasting

import (
	"encoding/json"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/Keshav76315/turboSH/core/inference"
	ort "github.com/yalue/onnxruntime_go"
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
	PredictedStages [3]string     `json:"predicted_stages"` // t+1, t+2, t+3 stage names
	StageIndices    [3]int        `json:"stage_indices"`
	Confidences     [3]float64    `json:"confidences"`
	Probabilities   [3][5]float64 `json:"probabilities"`
	RiskLevel       string        `json:"risk_level"`       // "LOW", "ELEVATED", "HIGH", "CRITICAL"
	LeadTimeSeconds int           `json:"lead_time_seconds"`
	Timestamp       time.Time     `json:"timestamp"`
}

// Forecaster loads an ONNX forecast model and executes multi-step horizon inference.
type Forecaster struct {
	session     *ort.DynamicAdvancedSession
	modelLoaded bool
	scaler      ScalerParams
	buffer      []inference.StateSnapshot
	bufferCap   int
	seqLen      int
	mu          sync.RWMutex
}

// NewForecaster initializes the forecasting engine with model, scaler, and buffer capacity.
func NewForecaster(modelPath, scalerPath string, bufferCap int) (*Forecaster, error) {
	if bufferCap <= 0 {
		bufferCap = 30 // Default 5 minutes at 10s steps
	}

	scaler, err := LoadScaler(scalerPath)
	if err != nil {
		log.Printf("[Forecaster] Warning: Could not load scaler from %s: %v. Using defaults.", scalerPath, err)
		scaler = ScalerParams{
			Means: make([]float64, 6),
			Stds:  []float64{1, 1, 1, 1, 1, 1},
			Eps:   1e-8,
		}
	}

	seqLen := bufferCap
	if seqLen < 1 {
		seqLen = 1
	}

	f := &Forecaster{
		scaler:    scaler,
		bufferCap: bufferCap,
		seqLen:    seqLen,
		buffer:    make([]inference.StateSnapshot, 0, bufferCap),
	}

	if !ort.IsInitialized() {
		log.Printf("[Forecaster] ONNX environment not yet initialized. Running in fallback mode.")
		return f, nil
	}

	absPath, err := filepath.Abs(modelPath)
	if err != nil {
		return f, fmt.Errorf("invalid model path: %w", err)
	}

	if _, err := os.Stat(absPath); os.IsNotExist(err) {
		log.Printf("[Forecaster] Model file does not exist at %s. Forecaster will operate in fallback mode.", absPath)
		return f, nil
	}

	inputNames := []string{"input"}
	outputNames := []string{"output"}
	session, err := ort.NewDynamicAdvancedSession(absPath, inputNames, outputNames, nil)
	if err != nil {
		log.Printf("[Forecaster] Warning: Failed to create ONNX session for %s: %v. Using fallback.", absPath, err)
		return f, nil
	}

	f.session = session
	f.modelLoaded = true
	log.Printf("[Forecaster] Successfully loaded forecast model: %s", absPath)
	return f, nil
}

// IsModelLoaded reports whether the ONNX sequence model is successfully initialized and loaded.
func (f *Forecaster) IsModelLoaded() bool {
	if f == nil {
		return false
	}
	f.mu.RLock()
	defer f.mu.RUnlock()
	return f.modelLoaded
}

// Close releases any allocated ONNX session resources.
func (f *Forecaster) Close() {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.session != nil {
		f.session.Destroy()
		f.session = nil
		f.modelLoaded = false
	}
}

// AddState appends a new state telemetry snapshot into the sliding buffer.
// When the buffer reaches capacity, elements are shifted in-place with zero heap allocations.
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

// BufferLen returns the current number of snapshots in the sliding window.
func (f *Forecaster) BufferLen() int {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return len(f.buffer)
}

// Predict runs multi-horizon sequence inference over the latest buffered states.
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

	// Prepare window of length f.seqLen (pad with oldest observation if needed)
	seqLen := f.seqLen
	if seqLen <= 0 {
		seqLen = 10
	}
	window := make([]inference.StateSnapshot, seqLen)
	if bufLen >= seqLen {
		copy(window, f.buffer[bufLen-seqLen:])
	} else {
		// Repeat earliest observation to fill window
		for i := 0; i < seqLen-bufLen; i++ {
			window[i] = f.buffer[0]
		}
		copy(window[seqLen-bufLen:], f.buffer)
	}

	// If ONNX session is not loaded, run lightweight heuristic/Markov fallback
	if !f.modelLoaded || f.session == nil {
		return f.heuristicForecast(window, now), nil
	}

	// Flatten and standardize features: shape (1, seqLen, 6)
	flatInput := make([]float32, seqLen*6)
	means := f.scaler.Means
	stds := f.scaler.Stds
	eps := f.scaler.Eps

	for i, s := range window {
		raw := []float64{
			float64(s.RequestsPerIP10s),
			float64(s.RequestsPerIP60s),
			float64(s.EndpointEntropy),
			float64(s.LatencySpike),
			float64(s.ErrorRate),
			float64(s.RequestVariance),
		}
		for feat := 0; feat < 6; feat++ {
			m := 0.0
			sd := 1.0
			if feat < len(means) {
				m = means[feat]
			}
			if feat < len(stds) {
				sd = stds[feat]
			}
			norm := (raw[feat] - m) / (sd + eps)
			flatInput[i*6+feat] = float32(norm)
		}
	}

	// Input tensor: (1, seqLen, 6)
	inShape := ort.NewShape(1, int64(seqLen), 6)
	inTensor, err := ort.NewTensor(inShape, flatInput)
	if err != nil {
		return f.heuristicForecast(window, now), fmt.Errorf("failed creating input tensor: %w", err)
	}
	defer inTensor.Destroy()

	// Output tensor: (1, 3, 5)
	outData := make([]float32, 1*3*5)
	outShape := ort.NewShape(1, 3, 5)
	outTensor, err := ort.NewTensor(outShape, outData)
	if err != nil {
		return f.heuristicForecast(window, now), fmt.Errorf("failed creating output tensor: %w", err)
	}
	defer outTensor.Destroy()

	if err := f.session.Run([]ort.ArbitraryTensor{inTensor}, []ort.ArbitraryTensor{outTensor}); err != nil {
		return f.heuristicForecast(window, now), fmt.Errorf("ONNX inference failed: %w", err)
	}

	// Process output logits: apply softmax across classes for each horizon step
	for h := 0; h < 3; h++ {
		stepLogits := outData[h*5 : (h+1)*5]

		// Find max for numerical stability
		maxLogit := stepLogits[0]
		for _, v := range stepLogits {
			if v > maxLogit {
				maxLogit = v
			}
		}

		sumExp := 0.0
		exps := [5]float64{}
		for s := 0; s < 5; s++ {
			exps[s] = math.Exp(float64(stepLogits[s] - maxLogit))
			sumExp += exps[s]
		}

		bestStage := 0
		maxProb := 0.0
		for s := 0; s < 5; s++ {
			prob := exps[s] / sumExp
			res.Probabilities[h][s] = prob
			if prob > maxProb {
				maxProb = prob
				bestStage = s
			}
		}

		res.StageIndices[h] = bestStage
		res.PredictedStages[h] = StageNames[bestStage]
		res.Confidences[h] = maxProb
	}

	// Derive consolidated RiskLevel and LeadTimeSeconds
	res.RiskLevel, res.LeadTimeSeconds = computeRiskAndLeadTime(res.StageIndices, res.Confidences)
	return res, nil
}

// heuristicForecast provides graceful fallback predictions when ONNX is inactive.
func (f *Forecaster) heuristicForecast(window []inference.StateSnapshot, now time.Time) ForecastResult {
	last := window[len(window)-1]
	res := ForecastResult{
		Timestamp: now,
	}

	// Simple heuristic based on current anomaly score and rate trends
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
			stage = StageSurge // Progression
		} else if h > 0 && currStage == StageSurge {
			stage = StageSustained
		}
		res.StageIndices[h] = stage
		res.PredictedStages[h] = StageNames[stage]
		res.Confidences[h] = math.Max(0.50, 0.90-float64(h)*0.10)
		res.Probabilities[h][stage] = res.Confidences[h]
	}

	res.RiskLevel, res.LeadTimeSeconds = computeRiskAndLeadTime(res.StageIndices, res.Confidences)
	return res
}

// computeRiskAndLeadTime determines aggregate threat level and estimated attack lead time.
func computeRiskAndLeadTime(stages [3]int, confs [3]float64) (string, int) {
	hasSurge := false
	surgeHorizon := -1

	for h := 0; h < 3; h++ {
		if (stages[h] == StageSurge || stages[h] == StageSustained) && confs[h] >= 0.50 {
			hasSurge = true
			if surgeHorizon == -1 {
				surgeHorizon = h + 1 // 1-indexed (1, 2, or 3 steps)
			}
		}
	}

	leadSecs := 0
	if surgeHorizon > 0 {
		leadSecs = surgeHorizon * 10 // 10s per step
	}

	// Determine threat level
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
