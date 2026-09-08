package logging

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Keshav76315/turboSH/config"
)

func TestTrafficLoggerPeriodicFlush(t *testing.T) {
	tmpDir := t.TempDir()
	logPath := filepath.Join(tmpDir, "periodic_test.jsonl")

	cfg := &config.Config{
		LogFilePath:   logPath,
		LogBufferSize: 8192, // large buffer: 8KB
	}

	tl, err := NewTrafficLogger(cfg, nil)
	if err != nil {
		t.Fatalf("failed to create traffic logger: %v", err)
	}
	defer tl.Close()

	// Write a small entry that is well below 8KB buffer
	entry := TrafficLogEntry{
		Timestamp:    time.Now().UTC().Format(time.RFC3339),
		IPHash:       "test-hash-1234",
		Endpoint:     "/api/v1/test",
		Method:       "GET",
		StatusCode:   200,
		ResponseTime: 12.5,
		RequestSize:  64,
	}
	tl.writeEntry(entry)

	// Before flush interval, file size might be 0 because buffer is 8KB
	// Wait 1.5 seconds for periodic flush (default 1s interval) to trigger automatically
	time.Sleep(1500 * time.Millisecond)

	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("failed to read log file: %v", err)
	}

	if len(data) == 0 {
		t.Fatalf("expected data to be automatically flushed to disk, but file is empty")
	}

	if !strings.Contains(string(data), "test-hash-1234") {
		t.Errorf("expected log file to contain 'test-hash-1234', got %s", string(data))
	}
}

func TestTrafficLoggerCloseIdempotent(t *testing.T) {
	tmpDir := t.TempDir()
	logPath := filepath.Join(tmpDir, "close_test.jsonl")

	cfg := &config.Config{
		LogFilePath:   logPath,
		LogBufferSize: 4096,
	}

	tl, err := NewTrafficLogger(cfg, nil)
	if err != nil {
		t.Fatalf("failed to create traffic logger: %v", err)
	}

	entry := TrafficLogEntry{
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
		IPHash:     "close-hash",
		Endpoint:   "/health",
		Method:     "GET",
		StatusCode: 200,
	}
	tl.writeEntry(entry)

	if err := tl.Close(); err != nil {
		t.Fatalf("first Close() failed: %v", err)
	}

	// Second Close() should be a safe no-op
	if err := tl.Close(); err != nil {
		t.Fatalf("second Close() failed: %v", err)
	}

	// Writes after close should be safely ignored without panicking
	tl.writeEntry(entry)
	if err := tl.Flush(); err != nil {
		t.Fatalf("Flush() after Close() returned error: %v", err)
	}

	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("failed to read log file: %v", err)
	}
	if !strings.Contains(string(data), "close-hash") {
		t.Errorf("expected log file to contain 'close-hash', got %s", string(data))
	}
}
