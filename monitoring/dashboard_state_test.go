package monitoring

import (
	"testing"
	"time"
)

type mockForecastProvider struct {
	snapshot ForecastSnapshot
}

func (m *mockForecastProvider) GetForecastSnapshot() ForecastSnapshot {
	return m.snapshot
}

func TestDashboardStateForecastIntegration(t *testing.T) {
	ds := NewDashboardState()

	// Initially without provider
	snap := ds.Snapshot()
	if snap.Forecast.Enabled {
		t.Errorf("expected disabled Forecast snapshot when no provider registered, got %+v", snap.Forecast)
	}

	// Register provider
	mock := &mockForecastProvider{
		snapshot: ForecastSnapshot{
			Enabled:         true,
			ModelName:       "Transformer-Forecaster",
			ThreatLevel:     "ELEVATED",
			Predictions:     [3]string{"NORMAL", "RECON", "ESCALATION"},
			Confidences:     [3]float64{0.82, 0.74, 0.69},
			LeadTimeSec:     20,
			MITRETechniques: []string{"T1595 (Active Scanning)"},
			Justification:   "Early reconnaissance detected.",
			LastUpdated:     time.Now(),
		},
	}
	ds.SetForecastProvider(mock)

	snapWithForecast := ds.Snapshot()
	if !snapWithForecast.Forecast.Enabled {
		t.Fatal("expected enabled Forecast snapshot after setting provider")
	}
	if snapWithForecast.Forecast.ThreatLevel != "ELEVATED" {
		t.Errorf("expected ThreatLevel ELEVATED, got %s", snapWithForecast.Forecast.ThreatLevel)
	}
	if snapWithForecast.Forecast.LeadTimeSec != 20 {
		t.Errorf("expected LeadTimeSec 20, got %d", snapWithForecast.Forecast.LeadTimeSec)
	}
	if len(snapWithForecast.Forecast.MITRETechniques) != 1 {
		t.Errorf("expected 1 MITRE technique, got %d", len(snapWithForecast.Forecast.MITRETechniques))
	}
}
