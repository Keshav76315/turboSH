// Package config provides configuration loading for the turboSH middleware.
package config

import (
	"net"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds all turboSH configuration values.
type Config struct {
	// Server settings
	ListenPort     string   // Port the proxy listens on (default ":8080")
	BackendURL     string   // Backend server URL to forward requests to
	TrustedProxies []string // List of trusted proxy IPs/CIDRs for parsing X-Forwarded-For

	// Scheduler settings
	MaxConcurrent int           // Max concurrent requests allowed through the scheduler
	QueueTimeout  time.Duration // How long a request can wait in the queue

	// Rate limiter settings
	RateLimitCapacity int     // Token bucket capacity per IP
	RateLimitRate     float64 // Token refill rate per second per IP

	// Burst detection
	BurstThreshold int           // Max requests in burst window before flagging
	BurstWindow    time.Duration // Time window for burst detection

	// Endpoint abuse
	EndpointAbuseThreshold int           // Max requests to same endpoint per IP
	EndpointAbuseWindow    time.Duration // Time window for endpoint abuse detection

	// Decision engine
	BlockThreshold     float64 // Anomaly score above this → BLOCK
	RateLimitThreshold float64 // Anomaly score above this → RATE_LIMIT

	// Cache settings
	CacheCapacity  int           // Max number of cached responses
	CacheTTL       time.Duration // Default TTL for cached responses
	CacheMaxMemory int           // Max total memory for cached entries (bytes)

	// Traffic logging settings
	LogFilePath   string // Path to traffic log file (JSON Lines)
	LogBufferSize int    // Write buffer size in bytes

	// ML Inference settings
	ONNXSharedLibraryPath string // Path to the downloaded ONNX Runtime shared library (.so, .dll, .dylib)
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
	// Handle ListenPort separately to normalize input
	port := os.Getenv("TURBOSH_PORT")
	if port == "" {
		port = "8080" // Default if not set
	} else if port[0] == ':' {
		port = port[1:] // Remove leading colon if present for consistency
	}
	// Always prepend a colon for the final ListenPort value
	port = ":" + port

	return &Config{
		// Server
		ListenPort:     port,
		BackendURL:     envOrDefault("TURBOSH_BACKEND", "http://localhost:9092"),
		TrustedProxies: envOrDefaultSlice("TURBOSH_TRUSTED_PROXIES", nil),

		// Scheduler
		MaxConcurrent: envOrDefaultInt("TURBOSH_MAX_CONCURRENT", 100),
		QueueTimeout:  envOrDefaultDuration("TURBOSH_QUEUE_TIMEOUT", 10*time.Second),

		// Rate limiter
		RateLimitCapacity: envOrDefaultInt("TURBOSH_RATE_LIMIT_CAPACITY", 10),
		RateLimitRate:     envOrDefaultFloat("TURBOSH_RATE_LIMIT_RATE", 2.0),

		// Burst detection
		BurstThreshold: envOrDefaultInt("TURBOSH_BURST_THRESHOLD", 50),
		BurstWindow:    envOrDefaultDuration("TURBOSH_BURST_WINDOW", 10*time.Second),

		// Endpoint abuse
		EndpointAbuseThreshold: envOrDefaultInt("TURBOSH_ENDPOINT_ABUSE_THRESHOLD", 20),
		EndpointAbuseWindow:    envOrDefaultDuration("TURBOSH_ENDPOINT_ABUSE_WINDOW", 30*time.Second),

		// Decision engine
		BlockThreshold:     envOrDefaultFloat("TURBOSH_BLOCK_THRESHOLD", 0.85),
		RateLimitThreshold: envOrDefaultFloat("TURBOSH_RATE_LIMIT_THRESHOLD", 0.65),

		// Cache
		CacheCapacity:  envOrDefaultInt("TURBOSH_CACHE_CAPACITY", 1000),
		CacheTTL:       envOrDefaultDuration("TURBOSH_CACHE_TTL", 5*time.Minute),
		CacheMaxMemory: envOrDefaultInt("TURBOSH_CACHE_MAX_MEMORY", 512*1024*1024), // 512 MB

		// Traffic logging
		LogFilePath:   envOrDefault("TURBOSH_LOG_FILE_PATH", "logs/traffic.jsonl"),
		LogBufferSize: envOrDefaultInt("TURBOSH_LOG_BUFFER_SIZE", 4096),

		// ML Inference
		ONNXSharedLibraryPath: envOrDefault("TURBOSH_ONNX_LIB_PATH", ""),
	}
}

// IsProxyTrusted checks if the given remote address (from r.RemoteAddr) is in the TrustedProxies list.
// It supports both exact IP matches and CIDR ranges.
func (cfg *Config) IsProxyTrusted(remoteAddr string) bool {
	if len(cfg.TrustedProxies) == 0 {
		return false
	}

	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	remoteIP := net.ParseIP(host)
	if remoteIP == nil {
		return false
	}

	for _, proxy := range cfg.TrustedProxies {
		// Try parsing as CIDR
		_, ipNet, err := net.ParseCIDR(proxy)
		if err == nil {
			if ipNet.Contains(remoteIP) {
				return true
			}
			continue
		}

		// Try parsing as exact IP
		proxyIP := net.ParseIP(proxy)
		if proxyIP != nil && proxyIP.Equal(remoteIP) {
			return true
		}
	}

	return false
}

func envOrDefault(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}

func envOrDefaultInt(key string, fallback int) int {
	if val := os.Getenv(key); val != "" {
		if n, err := strconv.Atoi(val); err == nil {
			return n
		}
	}
	return fallback
}

func envOrDefaultFloat(key string, fallback float64) float64 {
	if val := os.Getenv(key); val != "" {
		if f, err := strconv.ParseFloat(val, 64); err == nil {
			return f
		}
	}
	return fallback
}

func envOrDefaultDuration(key string, fallback time.Duration) time.Duration {
	if val := os.Getenv(key); val != "" {
		if d, err := time.ParseDuration(val); err == nil {
			return d
		}
	}
	return fallback
}

func envOrDefaultSlice(key string, fallback []string) []string {
	if val := os.Getenv(key); val != "" {
		parts := strings.Split(val, ",")
		var cleaned []string
		for _, p := range parts {
			trimmed := strings.TrimSpace(p)
			if trimmed != "" {
				cleaned = append(cleaned, trimmed)
			}
		}
		if len(cleaned) > 0 {
			return cleaned
		}
	}
	return fallback
}
