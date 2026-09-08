package proxy

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestReverseProxy_HostHeaderRewrite(t *testing.T) {
	gin.SetMode(gin.TestMode)

	var mu sync.Mutex
	var receivedHost string

	// Backend server that records the incoming Host header
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		receivedHost = r.Host
		mu.Unlock()
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	}))
	defer backend.Close()

	backendURL, err := url.Parse(backend.URL)
	if err != nil {
		t.Fatalf("Failed to parse backend URL: %v", err)
	}

	rp, err := New(backend.URL)
	if err != nil {
		t.Fatalf("Failed to create reverse proxy: %v", err)
	}

	router := gin.New()
	router.NoRoute(rp.Handler())

	proxyServer := httptest.NewServer(router)
	defer proxyServer.Close()

	// Client sends request with a custom client Host header to the proxy
	req, err := http.NewRequest("GET", proxyServer.URL+"/test-endpoint", nil)
	if err != nil {
		t.Fatalf("Failed to create request: %v", err)
	}
	req.Host = "custom.client.domain.com"

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("Proxy request failed: %v", err)
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("Expected status 200, got %d", resp.StatusCode)
	}

	mu.Lock()
	actualReceivedHost := receivedHost
	mu.Unlock()

	// Target backend MUST receive its own host, not the client's Host header
	if actualReceivedHost != backendURL.Host {
		t.Errorf("Host header rewrite failed: expected backend host %q, got %q", backendURL.Host, actualReceivedHost)
	}
}
