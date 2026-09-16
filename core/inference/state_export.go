// Package inference provides ML-based anomaly detection and traffic state export.
package inference

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"
)

// StateSnapshot captures the extracted network state and ML inference decision
// at a point in time for a specific client IP.
//
// Fields include the existing 6-dimensional feature vector, inference results,
// and an extensible map for future telemetry dimensions (IAT, TCP flags, etc.).
type StateSnapshot struct {
	Timestamp        time.Time              `json:"timestamp"`
	IPHash           string                 `json:"ip_hash"`
	RequestsPerIP10s float32                `json:"requests_per_ip_10s"`
	RequestsPerIP60s float32                `json:"requests_per_ip_60s"`
	EndpointEntropy  float32                `json:"endpoint_entropy"`
	LatencySpike     float32                `json:"latency_spike"`
	ErrorRate        float32                `json:"error_rate"`
	RequestVariance  float32                `json:"request_variance"`
	AnomalyScore     float64                `json:"anomaly_score"`
	Action           string                 `json:"action"`
	ExtendedFeatures map[string]interface{} `json:"extended_features,omitempty"`
}

// StateExporter asynchronously serializes and writes StateSnapshots to a JSONL file.
// It uses a buffered channel and dedicated background worker to ensure that state
// export is strictly non-blocking and never degrades proxy request throughput.
type StateExporter struct {
	ch           chan StateSnapshot
	file         *os.File
	writer       *bufio.Writer
	mu           sync.Mutex
	wg           sync.WaitGroup
	done         chan struct{}
	closed       bool
	droppedCount uint64
}

// DefaultStateExportChannelSize is the capacity of the async state export queue.
const DefaultStateExportChannelSize = 10000

// NewStateExporter creates and starts a new StateExporter writing to the given path.
func NewStateExporter(filePath string, bufferSize int) (*StateExporter, error) {
	if filePath == "" {
		filePath = "logs/state_telemetry.jsonl"
	}
	if bufferSize <= 0 {
		bufferSize = 4096
	}

	if err := os.MkdirAll(filepath.Dir(filePath), 0755); err != nil {
		return nil, fmt.Errorf("failed to create directory for state telemetry: %w", err)
	}

	file, err := os.OpenFile(filePath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to open state telemetry file %s: %w", filePath, err)
	}

	exp := &StateExporter{
		ch:     make(chan StateSnapshot, DefaultStateExportChannelSize),
		file:   file,
		writer: bufio.NewWriterSize(file, bufferSize),
		done:   make(chan struct{}),
	}

	exp.wg.Add(1)
	go exp.worker()

	return exp, nil
}

// ExportSnapshot enqueues a snapshot for async export.
// It is strictly non-blocking: if the queue is full, the snapshot is dropped
// and dropped count is incremented to safeguard proxy latency.
func (exp *StateExporter) ExportSnapshot(snapshot StateSnapshot) {
	if exp == nil {
		return
	}
	select {
	case exp.ch <- snapshot:
	default:
		atomic.AddUint64(&exp.droppedCount, 1)
	}
}

// DroppedCount returns the total number of snapshots dropped due to queue congestion.
func (exp *StateExporter) DroppedCount() uint64 {
	if exp == nil {
		return 0
	}
	return atomic.LoadUint64(&exp.droppedCount)
}

// worker is the background loop that batches writes to disk and periodically flushes.
func (exp *StateExporter) worker() {
	defer exp.wg.Done()

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case snapshot, ok := <-exp.ch:
			if !ok {
				// Channel closed: flush remaining writer buffer
				exp.mu.Lock()
				_ = exp.writer.Flush()
				exp.mu.Unlock()
				return
			}
			data, err := json.Marshal(snapshot)
			if err == nil {
				exp.mu.Lock()
				_, _ = exp.writer.Write(data)
				_ = exp.writer.WriteByte('\n')
				exp.mu.Unlock()
			}

		case <-ticker.C:
			exp.mu.Lock()
			_ = exp.writer.Flush()
			exp.mu.Unlock()

		case <-exp.done:
			// Drain remaining snapshots in channel before exiting
			for {
				select {
				case snapshot, ok := <-exp.ch:
					if !ok {
						exp.mu.Lock()
						_ = exp.writer.Flush()
						exp.mu.Unlock()
						return
					}
					data, err := json.Marshal(snapshot)
					if err == nil {
						exp.mu.Lock()
						_, _ = exp.writer.Write(data)
						_ = exp.writer.WriteByte('\n')
						exp.mu.Unlock()
					}
				default:
					exp.mu.Lock()
					_ = exp.writer.Flush()
					exp.mu.Unlock()
					return
				}
			}
		}
	}
}

// Close gracefully flushes buffered data, terminates the background worker, and closes the file.
func (exp *StateExporter) Close() error {
	if exp == nil {
		return nil
	}
	exp.mu.Lock()
	if exp.closed {
		exp.mu.Unlock()
		return nil
	}
	exp.closed = true
	exp.mu.Unlock()

	close(exp.done)
	exp.wg.Wait()

	exp.mu.Lock()
	defer exp.mu.Unlock()
	_ = exp.writer.Flush()
	return exp.file.Close()
}
