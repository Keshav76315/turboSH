package forecasting

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/Keshav76315/turboSH/core/inference"
)

func TestForecasterBufferSliding(t *testing.T) {
	f, err := NewForecaster("", "", 5)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	defer f.Close()

	if f.BufferLen() != 0 {
		t.Errorf("expected empty buffer, got %d", f.BufferLen())
	}

	for i := 0; i < 10; i++ {
		f.AddState(inference.StateSnapshot{
			Timestamp:        time.Now(),
			IPHash:           "test_ip",
			RequestsPerIP10s: float32(i * 10),
			AnomalyScore:     0.2,
		})
	}

	if f.BufferLen() != 5 {
		t.Errorf("expected buffer len 5 after overflow, got %d", f.BufferLen())
	}
}

func TestLoadScaler(t *testing.T) {
	tmpDir := t.TempDir()
	scalerPath := filepath.Join(tmpDir, "scaler.json")

	content := `{
		"feature_names": ["f1", "f2"],
		"means": [10.0, 20.0],
		"stds": [2.0, 5.0],
		"eps": 0.00001
	}`
	if err := os.WriteFile(scalerPath, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test scaler: %v", err)
	}

	scaler, err := LoadScaler(scalerPath)
	if err != nil {
		t.Fatalf("LoadScaler failed: %v", err)
	}

	if len(scaler.Means) != 2 || scaler.Means[0] != 10.0 || scaler.Stds[1] != 5.0 {
		t.Errorf("unexpected scaler values: %+v", scaler)
	}
}

func TestForecasterPredictFallback(t *testing.T) {
	f, err := NewForecaster("non_existent_model.onnx", "non_existent_scaler.json", 10)
	if err != nil {
		t.Fatalf("NewForecaster failed: %v", err)
	}
	defer f.Close()

	// Empty buffer should return valid default result
	res, err := f.Predict()
	if err != nil {
		t.Fatalf("Predict on empty buffer failed: %v", err)
	}
	if res.RiskLevel != "LOW" {
		t.Errorf("expected LOW risk on empty buffer, got %s", res.RiskLevel)
	}

	// Add elevated anomaly state
	f.AddState(inference.StateSnapshot{
		Timestamp:    time.Now(),
		AnomalyScore: 0.90, // Triggers surge in fallback
	})

	res, err = f.Predict()
	if err != nil {
		t.Fatalf("Predict failed: %v", err)
	}
	if res.RiskLevel != "CRITICAL" {
		t.Errorf("expected CRITICAL risk for surge snapshot, got %s", res.RiskLevel)
	}
	if res.PredictedStages[0] != "SURGE" {
		t.Errorf("expected t+1 SURGE, got %s", res.PredictedStages[0])
	}
}

func TestComputeRiskAndLeadTime(t *testing.T) {
	tests := []struct {
		name         string
		stages       [3]int
		confs        [3]float64
		wantRisk     string
		wantLeadSecs int
	}{
		{
			name:         "All Normal",
			stages:       [3]int{StageNormal, StageNormal, StageNormal},
			confs:        [3]float64{0.9, 0.9, 0.9},
			wantRisk:     "LOW",
			wantLeadSecs: 0,
		},
		{
			name:         "Recon at t+1",
			stages:       [3]int{StageRecon, StageNormal, StageNormal},
			confs:        [3]float64{0.7, 0.8, 0.8},
			wantRisk:     "ELEVATED",
			wantLeadSecs: 0,
		},
		{
			name:         "Escalation at t+1",
			stages:       [3]int{StageEscalation, StageNormal, StageNormal},
			confs:        [3]float64{0.65, 0.7, 0.7},
			wantRisk:     "HIGH",
			wantLeadSecs: 0,
		},
		{
			name:         "Surge at t+2 (20s lead time)",
			stages:       [3]int{StageEscalation, StageSurge, StageSustained},
			confs:        [3]float64{0.60, 0.75, 0.70},
			wantRisk:     "CRITICAL",
			wantLeadSecs: 20,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			gotRisk, gotLead := computeRiskAndLeadTime(tc.stages, tc.confs)
			if gotRisk != tc.wantRisk {
				t.Errorf("expected risk %s, got %s", tc.wantRisk, gotRisk)
			}
			if gotLead != tc.wantLeadSecs {
				t.Errorf("expected lead %ds, got %ds", tc.wantLeadSecs, gotLead)
			}
		})
	}
}
