// Package proxy implements the reverse proxy server for turboSH.
package proxy

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"

	"github.com/gin-gonic/gin"
)

// ReverseProxy wraps Go's httputil.ReverseProxy for use with Gin.
type ReverseProxy struct {
	target *url.URL
	proxy  *httputil.ReverseProxy
}

// New creates a new ReverseProxy pointing to the given backend URL.
func New(backendURL string) (*ReverseProxy, error) {
	target, err := url.Parse(backendURL)
	if err != nil {
		return nil, err
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("[turboSH] proxy error: %v", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		w.Write([]byte(`{"error":"bad_gateway","message":"Backend server is unreachable."}`))
	}

	return &ReverseProxy{
		target: target,
		proxy:  proxy,
	}, nil
}

// Handler returns a Gin handler that forwards requests to the backend.
// This should be the LAST handler in the middleware chain.
func (rp *ReverseProxy) Handler() gin.HandlerFunc {
	return func(c *gin.Context) {
		// Forward the request to the backend
		rp.proxy.ServeHTTP(c.Writer, c.Request)
	}
}

// TargetURL returns the backend URL this proxy forwards to.
func (rp *ReverseProxy) TargetURL() string {
	return rp.target.String()
}
