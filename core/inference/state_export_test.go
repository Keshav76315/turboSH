package inference

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestStateExporter_ExportSnapshot(t *testing.T) {
	tempDir, err := os.MkdirTemp("", "turbosh_state_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	filePath := filepath.Join(tempDir, "state_telemetry.jsonl")
	exporter, err := NewStateExporter(filePath, 1024)
	if err != nil {
		t.Fatalf("NewStateExporter failed: %v", err)
	}

	snapshot := StateSnapshot{
		Timestamp:        time.Date(2026, 9, 16, 12, 0, 0, 0, time.UTC),
		IPHash:           "hash-ip-12345",
		RequestsPerIP10s: 15.0,
		RequestsPerIP60s: 50.0,
		EndpointEntropy:  0.82,
		LatencySpike:     1.0,
		ErrorRate:        0.12,
		RequestVariance:  25.4,
		AnomalyScore:     0.78,
		Action:           "RATE_LIMIT",
		ExtendedFeatures: map[string]interface{}{
			"iat_mean": 0.045,
		},
	}

	exporter.ExportSnapshot(snapshot)

	// Close to ensure all queued writes are flushed to disk
	if err := exporter.Close(); err != nil {
		t.Fatalf("Failed to close exporter: %v", err)
	}

	// Verify file contents
	file, err := os.Open(filePath)
	if err != nil {
		t.Fatalf("Failed to open exported state file: %v", err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	if !scanner.Scan() {
		t.Fatalf("Expected at least one line in state telemetry file")
	}

	line := scanner.Text()
	var decoded StateSnapshot
	if err := json.Unmarshal([]byte(line), &decoded); err != nil {
		t.Fatalf("Failed to decode JSON state snapshot: %v\nLine: %s", err, line)
	}

	if decoded.IPHash != snapshot.IPHash {
		t.Errorf("Expected IPHash %q, got %q", snapshot.IPHash, decoded.IPHash)
	}
	if decoded.RequestsPerIP10s != snapshot.RequestsPerIP10s {
		t.Errorf("Expected RequestsPerIP10s %f, got %f", snapshot.RequestsPerIP10s, decoded.RequestsPerIP10s)
	}
	if decoded.Action != snapshot.Action {
		t.Errorf("Expected Action %q, got %q", snapshot.Action, decoded.Action)
	}
	if decoded.AnomalyScore != snapshot.AnomalyScore {
		t.Errorf("Expected AnomalyScore %f, got %f", snapshot.AnomalyScore, decoded.AnomalyScore)
	}
	if decoded.ExtendedFeatures["iat_mean"] != 0.045 {
		t.Errorf("Expected extended feature iat_mean 0.045, got %v", decoded.ExtendedFeatures["iat_mean"])
	}
}

func TestStateExporter_NilSafe(t *testing.T) {
	var exp *StateExporter
	// Should not panic
	exp.ExportSnapshot(StateSnapshot{IPHash: "test"})
	if err := exp.Close(); err != nil {
		t.Errorf("Expected nil error closing nil exporter, got %v", err)
	}
	if exp.DroppedCount() != 0 {
		t.Errorf("Expected 0 dropped count for nil exporter")
	}
}

func TestStateExporter_MultipleExports(t *testing.T) {
	tempDir, err := os.MkdirTemp("", "turbosh_state_multi_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	filePath := filepath.Join(tempDir, "state_telemetry.jsonl")
	exporter, err := NewStateExporter(filePath, 2048)
	if err != nil {
		t.Fatalf("NewStateExporter failed: %v", err)
	}

	count := 50
	for i := 0; i < count; i++ {
		exporter.ExportSnapshot(StateSnapshot{
			Timestamp:        time.Now().UTC(),
			IPHash:           "client-ip",
			RequestsPerIP10s: float32(i),
			AnomalyScore:     0.1 * float64(i%10),
			Action:           "ALLOW",
		})
	}

	if err := exporter.Close(); err != nil {
		t.Fatalf("Failed to close exporter: %v", err)
	}

	content, err := os.ReadFile(filePath)
	if err != nil {
		t.Fatalf("Failed to read file: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(string(content)), "\n")
	if len(lines) != count {
		t.Errorf("Expected %d lines, got %d", count, len(lines))
	}
}
