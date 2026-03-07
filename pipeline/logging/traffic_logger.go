// Package logging implements request traffic logging for the turboSH data pipeline.
//
// It captures structured metadata for every HTTP request passing through the
// middleware and writes it as JSON Lines to a log file. These logs feed the
// feature extraction pipeline and ultimately the ML anomaly detection system.
package logging

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/Keshav76315/turboSH/config"
	"github.com/gin-gonic/gin"
)

// MLMetricsRecorder defines the feedback loop back to the ML engine
// without creating an import cycle with the inference package.
type MLMetricsRecorder interface {
	RecordBackendResponse(ip string, statusCode int, latencyMs float64)
}

// ---------- log entry ----------

// TrafficLogEntry represents a single request log record.
// Fields match the schema defined in docs/DATA_SCHEMA.md §1.
type TrafficLogEntry struct {
	Timestamp    string  `json:"timestamp"`     // ISO 8601 UTC
	IPHash       string  `json:"ip_hash"`       // SHA-256 of client IP
	Endpoint     string  `json:"endpoint"`      // URL path
	Method       string  `json:"method"`        // HTTP method
	StatusCode   int     `json:"status_code"`   // response status code
	ResponseTime float64 `json:"response_time"` // latency in milliseconds
	RequestSize  int     `json:"request_size"`  // request body size in bytes
}

// ---------- traffic logger ----------

// TrafficLogger is a Gin middleware that logs every request to a JSON Lines file.
type TrafficLogger struct {
	writer       *bufio.Writer
	file         *os.File
	mu           sync.Mutex
	closed       bool
	cfg          *config.Config
	mlProtection MLMetricsRecorder // Optional reference to feed metrics back to ML pipeline
}

// NewTrafficLogger creates a new traffic logger that writes to the given file path.
func NewTrafficLogger(cfg *config.Config, mlp MLMetricsRecorder) (*TrafficLogger, error) {
	if cfg == nil {
		return nil, fmt.Errorf("cfg is nil")
	}
	filePath := cfg.LogFilePath
	bufferSize := cfg.LogBufferSize
	if filePath == "" {
		filePath = "logs/traffic.jsonl"
	}

	// Ensure the directory exists
	if err := os.MkdirAll(filepath.Dir(filePath), 0755); err != nil {
		return nil, fmt.Errorf("failed to create log directory: %w", err)
	}

	file, err := os.OpenFile(filePath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to open log file %s: %w", filePath, err)
	}

	if bufferSize <= 0 {
		bufferSize = 4096
	}

	return &TrafficLogger{
		writer:       bufio.NewWriterSize(file, bufferSize),
		file:         file,
		closed:       false,
		cfg:          cfg,
		mlProtection: mlp,
	}, nil
}

// dirOf returns the directory portion of a file path.

// ---------- middleware ----------

// Middleware returns a gin.HandlerFunc that logs every request.
//
// Pipeline position: Scheduler → RateLimiter → TrafficRules → Cache → **Logger** → Proxy
func (tl *TrafficLogger) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		// Use custom extractor to guarantee we get the real IP behind load balancers
		clientIP := GetClientIP(c.Request, tl.cfg)
		ipHash := RedactIP(clientIP)

		// Let the rest of the pipeline run (proxy, etc.)
		c.Next()

		// After the response has been written — capture metadata
		elapsed := time.Since(start).Seconds() * 1000 // milliseconds
		statusCode := c.Writer.Status()

		// Feed metrics back to the ML engine so it can learn from actual backend behavior
		if tl.mlProtection != nil {
			tl.mlProtection.RecordBackendResponse(ipHash, statusCode, elapsed)
		}

		entry := TrafficLogEntry{
			Timestamp:    start.UTC().Format(time.RFC3339),
			IPHash:       ipHash,
			Endpoint:     c.Request.URL.Path,
			Method:       c.Request.Method,
			StatusCode:   statusCode,
			ResponseTime: elapsed,
			RequestSize:  int(c.Request.ContentLength),
		}

		// Non-negative request size (ContentLength can be -1 if unknown)
		if entry.RequestSize < 0 {
			entry.RequestSize = 0
		}

		tl.writeEntry(entry)
	}
}

// writeEntry serializes a log entry to JSON and writes it to the buffered file.
func (tl *TrafficLogger) writeEntry(entry TrafficLogEntry) {
	data, err := json.Marshal(entry)
	if err != nil {
		log.Printf("[traffic-logger] failed to marshal log entry: %v", err)
		return
	}

	tl.mu.Lock()
	defer tl.mu.Unlock()

	if tl.closed { // Do not write if the logger is closed
		return
	}

	if _, err := tl.writer.Write(data); err != nil {
		log.Printf("[traffic-logger] write error: %v", err)
		return
	}
	if err := tl.writer.WriteByte('\n'); err != nil { // Check error for WriteByte
		log.Printf("[traffic-logger] newline write error: %v", err)
	}
	// Removed: tl.writer.Flush() - logs are now flushed periodically or on close
}

// Flush writes any buffered data to the underlying file.
// Call this periodically or on shutdown to ensure all logs are persisted.
func (tl *TrafficLogger) Flush() error {
	tl.mu.Lock()
	defer tl.mu.Unlock()
	if tl.closed { // Do not flush if the logger is closed
		return nil
	}
	return tl.writer.Flush()
}

// Close flushes and closes the log file safely.
func (tl *TrafficLogger) Close() error {
	tl.mu.Lock()
	defer tl.mu.Unlock()

	if tl.closed { // Prevent closing multiple times
		return nil
	}
	tl.closed = true // Mark as closed

	// Attempt to flush before closing. If flush fails, still try to close the file.
	if err := tl.writer.Flush(); err != nil {
		tl.file.Close() // attempt to close even if flush fails
		return err
	}
	return tl.file.Close()
}

// ---------- helpers ----------
