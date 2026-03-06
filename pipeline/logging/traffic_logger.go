// Package logging implements request traffic logging for the turboSH data pipeline.
//
// It captures structured metadata for every HTTP request passing through the
// middleware and writes it as JSON Lines to a log file. These logs feed the
// feature extraction pipeline and ultimately the ML anomaly detection system.
package logging

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

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
	writer *bufio.Writer
	file   *os.File
	mu     sync.Mutex
}

// NewTrafficLogger creates a new traffic logger that writes to the given file path.  The file is created (or appended to) automatically. bufferSize controls the write buffer size in bytes (0 = default 4096).
func NewTrafficLogger(filePath string, bufferSize int) (*TrafficLogger, error) {
	if filePath == "" {
		filePath = "logs/traffic.jsonl"
	}

	// Ensure the directory exists
	if err := os.MkdirAll(dirOf(filePath), 0755); err != nil {
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
		writer: bufio.NewWriterSize(file, bufferSize),
		file:   file,
	}, nil
}

// dirOf returns the directory portion of a file path.
func dirOf(path string) string {
	for i := len(path) - 1; i >= 0; i-- {
		if path[i] == '/' || path[i] == '\\' {
			return path[:i]
		}
	}
	return "."
}

// ---------- middleware ----------

// Middleware returns a gin.HandlerFunc that logs every request.
//
// Pipeline position: Scheduler → RateLimiter → TrafficRules → Cache → **Logger** → Proxy
func (tl *TrafficLogger) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		// Let the rest of the pipeline run (proxy, etc.)
		c.Next()

		// After the response has been written — capture metadata
		elapsed := time.Since(start).Seconds() * 1000 // milliseconds

		entry := TrafficLogEntry{
			Timestamp:    start.UTC().Format(time.RFC3339),
			IPHash:       hashIP(c.ClientIP()),
			Endpoint:     c.Request.URL.Path,
			Method:       c.Request.Method,
			StatusCode:   c.Writer.Status(),
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

	if _, err := tl.writer.Write(data); err != nil {
		log.Printf("[traffic-logger] write error: %v", err)
		return
	}
	tl.writer.WriteByte('\n')

	// Flush immediately so logs survive signal interrupts
	if err := tl.writer.Flush(); err != nil {
		log.Printf("[traffic-logger] flush error: %v", err)
	}
}

// Flush writes any buffered data to the underlying file.
// Call this periodically or on shutdown to ensure all logs are persisted.
func (tl *TrafficLogger) Flush() error {
	tl.mu.Lock()
	defer tl.mu.Unlock()
	return tl.writer.Flush()
}

// Close flushes and closes the log file.
func (tl *TrafficLogger) Close() error {
	if err := tl.Flush(); err != nil {
		return err
	}
	return tl.file.Close()
}

// ---------- helpers ----------

// hashIP returns the first 16 hex characters of a SHA-256 hash of the IP address.
// This anonymizes the client IP while still allowing per-IP aggregation.
func hashIP(ip string) string {
	h := sha256.Sum256([]byte(ip))
	return hex.EncodeToString(h[:8]) // 16 hex chars
}
