package logging

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Keshav76315/turboSH/config"
	"github.com/gin-gonic/gin"
)

func TestRedactIP_HMACFull256Bit(t *testing.T) {
	ip := "192.168.1.100"
	SetIPSalt("test_secret_salt_32_bytes_long_123456")

	hash := RedactIP(ip)
	// 256-bit HMAC-SHA256 hex string must be exactly 64 characters
	if len(hash) != 64 {
		t.Fatalf("Expected 64 hex characters (256 bits), got length %d: %s", len(hash), hash)
	}
}

func TestRedactIP_DifferentSalts(t *testing.T) {
	ip := "192.168.1.100"

	SetIPSalt("salt_alpha_12345678901234567890")
	hashA := RedactIP(ip)

	SetIPSalt("salt_beta_98765432109876543210")
	hashB := RedactIP(ip)

	if hashA == hashB {
		t.Fatalf("Expected different hashes for different salts, but got identical hash: %s", hashA)
	}

	// Verify consistency with same salt
	SetIPSalt("salt_alpha_12345678901234567890")
	hashA2 := RedactIP(ip)
	if hashA != hashA2 {
		t.Fatalf("Expected same hash for identical salt, got %s vs %s", hashA, hashA2)
	}
}

func TestResolveClientIP_DirectConnection(t *testing.T) {
	cfg := &config.Config{
		TrustedProxies: []string{"10.0.0.1"},
	}

	req := httptest.NewRequest("GET", "/api/test", nil)
	req.RemoteAddr = "203.0.113.50:54321"

	identity := ResolveClientIP(req, cfg)
	if identity.IPString != "203.0.113.50" {
		t.Fatalf("Expected 203.0.113.50, got %s", identity.IPString)
	}
	if identity.Source != "remote_addr" {
		t.Fatalf("Expected source remote_addr, got %s", identity.Source)
	}
	if identity.Trusted {
		t.Fatalf("Expected peer to be untrusted")
	}
}

func TestResolveClientIP_SpoofedXFFUntrustedPeer(t *testing.T) {
	cfg := &config.Config{
		TrustedProxies: []string{"10.0.0.1"},
	}

	req := httptest.NewRequest("GET", "/api/test", nil)
	req.RemoteAddr = "198.51.100.22:12345" // NOT in TrustedProxies
	req.Header.Set("X-Forwarded-For", "8.8.8.8, 1.1.1.1")
	req.Header.Set("X-Real-IP", "8.8.8.8")

	identity := ResolveClientIP(req, cfg)
	// Must ignore spoofed headers and attribute directly to the untrusted peer
	if identity.IPString != "198.51.100.22" {
		t.Fatalf("Spoofing vulnerability! Expected peer IP 198.51.100.22, got %s", identity.IPString)
	}
	if identity.Source != "remote_addr" {
		t.Fatalf("Expected source remote_addr, got %s", identity.Source)
	}
	if identity.Trusted {
		t.Fatalf("Untrusted peer was marked as trusted")
	}
}

func TestResolveClientIP_TrustedProxySingleXFF(t *testing.T) {
	cfg := &config.Config{
		TrustedProxies: []string{"10.0.0.1"},
	}

	req := httptest.NewRequest("GET", "/api/test", nil)
	req.RemoteAddr = "10.0.0.1:45678" // Trusted proxy
	req.Header.Set("X-Forwarded-For", "203.0.113.99")

	identity := ResolveClientIP(req, cfg)
	if identity.IPString != "203.0.113.99" {
		t.Fatalf("Expected client IP 203.0.113.99, got %s", identity.IPString)
	}
	if identity.Source != "x-forwarded-for" {
		t.Fatalf("Expected source x-forwarded-for, got %s", identity.Source)
	}
	if !identity.Trusted {
		t.Fatalf("Expected proxy to be trusted")
	}
}

func TestResolveClientIP_TrustedProxyChain(t *testing.T) {
	cfg := &config.Config{
		TrustedProxies: []string{"10.0.0.1", "10.0.0.2"},
	}

	req := httptest.NewRequest("GET", "/api/test", nil)
	req.RemoteAddr = "10.0.0.1:45678" // Peer is trusted proxy 1
	// Chain: Client (198.51.100.77) -> Intermediate trusted proxy (10.0.0.2)
	req.Header.Set("X-Forwarded-For", "198.51.100.77, 10.0.0.2")

	identity := ResolveClientIP(req, cfg)
	// Rightmost untrusted IP in the chain is the client
	if identity.IPString != "198.51.100.77" {
		t.Fatalf("Expected rightmost untrusted client IP 198.51.100.77, got %s", identity.IPString)
	}
}

func TestResolveClientIP_MalformedXFF(t *testing.T) {
	cfg := &config.Config{
		TrustedProxies: []string{"10.0.0.1"},
	}

	req := httptest.NewRequest("GET", "/api/test", nil)
	req.RemoteAddr = "10.0.0.1:45678"
	req.Header.Set("X-Forwarded-For", "garbage_not_an_ip, ;DROP TABLE")

	identity := ResolveClientIP(req, cfg)
	// Should safely fall back to the trusted peer IP
	if identity.IPString != "10.0.0.1" {
		t.Fatalf("Expected fallback to 10.0.0.1, got %s", identity.IPString)
	}
}

func TestClientIdentityMiddleware(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg := &config.Config{
		TrustedProxies: []string{"10.0.0.1"},
	}

	router := gin.New()
	router.Use(ClientIdentityMiddleware(cfg))
	router.GET("/test", func(c *gin.Context) {
		canonicalIP := GetCanonicalIP(c, cfg)
		canonicalHash := GetCanonicalIPHash(c, cfg)
		c.JSON(http.StatusOK, gin.H{
			"ip":   canonicalIP,
			"hash": canonicalHash,
		})
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/test", nil)
	req.RemoteAddr = "10.0.0.1:50000"
	req.Header.Set("X-Forwarded-For", "203.0.113.42")

	router.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected 200 OK, got %d", w.Code)
	}
}
