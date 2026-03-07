package logging

import (
	"crypto/sha256"
	"encoding/hex"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
)

var ipSalt string

func init() {
	ipSalt = os.Getenv("TURBOSH_IP_SALT")
	if ipSalt == "" {
		ipSalt = "turboSH_default_salt"
		log.Println("[logging] TURBOSH_IP_SALT not set, using default salt for IP redaction")
	}
}

// RedactIP hashes the IP address to protect raw PII in the logs.
// Using SHA-256 with a local salt.
func RedactIP(ip string) string {
	hash := sha256.Sum256([]byte(ip + ipSalt))
	return hex.EncodeToString(hash[:8])
}

// GetClientIP extracts the real client IP from HTTP headers (X-Forwarded-For, X-Real-IP)
// before falling back to the raw RemoteAddr. Essential for proxy/load-balancer setups.
func GetClientIP(r *http.Request) string {
	// Check X-Forwarded-For header
	forwarded := r.Header.Get("X-Forwarded-For")
	if forwarded != "" {
		ips := strings.Split(forwarded, ",")
		return strings.TrimSpace(ips[0])
	}

	// Check X-Real-IP
	realIP := r.Header.Get("X-Real-IP")
	if realIP != "" {
		return strings.TrimSpace(realIP)
	}

	// Fallback to RemoteAddr
	ip, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		// If SplitHostPort fails (e.g., no port), just use the raw address
		return r.RemoteAddr
	}
	return ip
}
