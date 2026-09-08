package logging

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"log"
	"net"
	"net/http"
	"os"
	"strings"

	"github.com/Keshav76315/turboSH/config"
	"github.com/gin-gonic/gin"
)

var ipSalt string

func init() {
	ipSalt = os.Getenv("TURBOSH_IP_SALT")
	if ipSalt == "" {
		randomBytes := make([]byte, 32)
		if _, err := rand.Read(randomBytes); err != nil {
			log.Fatalf("[logging] CRITICAL: Failed to generate secure random IP salt: %v", err)
		}
		ipSalt = hex.EncodeToString(randomBytes)
		log.Println("[logging] WARNING: TURBOSH_IP_SALT not set. Generated dynamic cryptographically secure runtime salt for IP redaction.")
	}
}

// SetIPSalt updates the IP redaction salt at runtime (e.g. from config or tests).
func SetIPSalt(salt string) {
	if salt != "" {
		ipSalt = salt
	}
}

// GetIPSalt returns the current salt used for IP redaction.
func GetIPSalt() string {
	return ipSalt
}

// RedactIP hashes the IP address using HMAC-SHA-256 with the secret salt
// and returns the full 256-bit representation (64 hex characters).
// This prevents precomputed rainbow-table lookups and eliminates hash collisions.
func RedactIP(ip string) string {
	mac := hmac.New(sha256.New, []byte(ipSalt))
	mac.Write([]byte(ip))
	return hex.EncodeToString(mac.Sum(nil))
}

// ClientIdentity represents the verified canonical client identity.
type ClientIdentity struct {
	IP         net.IP
	IPString   string
	IPHash     string
	Source     string // "remote_addr", "x-forwarded-for", "x-real-ip"
	Trusted    bool
	ProxyChain []net.IP
}

// ResolveClientIP inspects the connection and HTTP headers to establish
// a single canonical ClientIdentity based on trusted proxy configuration.
func ResolveClientIP(r *http.Request, cfg *config.Config) ClientIdentity {
	peerHost, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		peerHost = r.RemoteAddr
	}
	peerIP := net.ParseIP(strings.TrimSpace(peerHost))

	// Base identity if peer is direct or untrusted
	identity := ClientIdentity{
		IP:       peerIP,
		IPString: peerHost,
		Source:   "remote_addr",
		Trusted:  false,
	}

	isTrustedPeer := cfg != nil && cfg.IsProxyTrusted(peerHost)
	if !isTrustedPeer {
		// Untrusted peer: completely ignore XFF and X-Real-IP headers to prevent spoofing
		identity.IPHash = RedactIP(identity.IPString)
		return identity
	}

	identity.Trusted = true
	if peerIP != nil {
		identity.ProxyChain = append(identity.ProxyChain, peerIP)
	}

	// Peer is a trusted proxy. Process X-Forwarded-For if present.
	forwarded := r.Header.Get("X-Forwarded-For")
	if forwarded != "" {
		rawIPs := strings.Split(forwarded, ",")
		var parsedChain []net.IP
		for _, raw := range rawIPs {
			trimmed := strings.TrimSpace(raw)
			if parsed := net.ParseIP(trimmed); parsed != nil {
				parsedChain = append(parsedChain, parsed)
			}
		}

		if len(parsedChain) > 0 {
			// Walk backwards from right to left, skipping trusted proxies
			// The first untrusted IP from the right is the verified client IP.
			resolved := parsedChain[0]
			found := false
			for i := len(parsedChain) - 1; i >= 0; i-- {
				curr := parsedChain[i]
				if cfg != nil && cfg.IsProxyTrusted(curr.String()) {
					identity.ProxyChain = append(identity.ProxyChain, curr)
					continue
				}
				resolved = curr
				found = true
				break
			}
			if !found && len(parsedChain) > 0 {
				resolved = parsedChain[0]
			}
			identity.IP = resolved
			identity.IPString = resolved.String()
			identity.Source = "x-forwarded-for"
			identity.IPHash = RedactIP(identity.IPString)
			return identity
		}
	}

	// If XFF is missing, check X-Real-IP
	realIPHeader := strings.TrimSpace(r.Header.Get("X-Real-IP"))
	if realIPHeader != "" {
		if parsed := net.ParseIP(realIPHeader); parsed != nil {
			identity.IP = parsed
			identity.IPString = parsed.String()
			identity.Source = "x-real-ip"
			identity.IPHash = RedactIP(identity.IPString)
			return identity
		}
	}

	// Fallback to peer IP
	identity.IPHash = RedactIP(identity.IPString)
	return identity
}

// GetClientIP extracts the real client IP from HTTP headers (X-Forwarded-For, X-Real-IP)
// but ONLY if the request comes from a trusted proxy (calls ResolveClientIP).
func GetClientIP(r *http.Request, cfg *config.Config) string {
	return ResolveClientIP(r, cfg).IPString
}

// Context keys for Gin context
const (
	ContextKeyClientIdentity = "turbosh_client_identity"
	ContextKeyClientIP       = "turbosh_client_ip"
	ContextKeyClientIPHash   = "turbosh_client_ip_hash"
)

// ClientIdentityMiddleware establishes the single canonical client identity
// at the ingress of the request pipeline and caches it in the context.
func ClientIdentityMiddleware(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		identity := ResolveClientIP(c.Request, cfg)
		c.Set(ContextKeyClientIdentity, identity)
		c.Set(ContextKeyClientIP, identity.IPString)
		c.Set(ContextKeyClientIPHash, identity.IPHash)
		c.Next()
	}
}

// GetCanonicalIP returns the canonical client IP from the Gin context,
// falling back to on-the-fly resolution if not yet in context.
func GetCanonicalIP(c *gin.Context, cfg *config.Config) string {
	if val, exists := c.Get(ContextKeyClientIP); exists {
		if ip, ok := val.(string); ok && ip != "" {
			return ip
		}
	}
	return GetClientIP(c.Request, cfg)
}

// GetCanonicalIPHash returns the HMAC-SHA-256 redacted IP hash from context.
func GetCanonicalIPHash(c *gin.Context, cfg *config.Config) string {
	if val, exists := c.Get(ContextKeyClientIPHash); exists {
		if hash, ok := val.(string); ok && hash != "" {
			return hash
		}
	}
	return RedactIP(GetCanonicalIP(c, cfg))
}
