package cachesystem

import (
	"bytes"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// CacheMiddleware implements the Gin middleware for the turboSH cache layer.
// It sits between the scheduler/rate-limiter and the reverse proxy.
type CacheMiddleware struct {
	cache       Cache
	defaultTTL  time.Duration
	maxBodySize int
	stampede    *StampedeProtector
}

// NewCacheMiddleware creates a new cache middleware.
//   - cache: the underlying cache backend (e.g. LRUCache)
//   - defaultTTL: TTL applied to cached entries (0 = never expires)
//   - maxBodySize: responses larger than this (bytes) are not cached
func NewCacheMiddleware(cache Cache, defaultTTL time.Duration, maxBodySize int) *CacheMiddleware {
	if maxBodySize <= 0 {
		maxBodySize = 1 << 20 // 1 MB default
	}
	return &CacheMiddleware{
		cache:       cache,
		defaultTTL:  defaultTTL,
		maxBodySize: maxBodySize,
		stampede:    NewStampedeProtector(),
	}
}

// ---------- Gin response recorder ----------

// ginResponseRecorder wraps gin.ResponseWriter to capture the response body
// so we can store it in the cache after the downstream handler writes it.
type ginResponseRecorder struct {
	gin.ResponseWriter
	body *bytes.Buffer
}

func (r *ginResponseRecorder) Write(b []byte) (int, error) {
	r.body.Write(b) // capture a copy
	return r.ResponseWriter.Write(b)
}

// ---------- cache key ----------

// cacheKey builds a deterministic key from the request.
// Format: METHOD:path?query
func cacheKey(r *http.Request) string {
	key := r.Method + ":" + r.URL.Path
	if r.URL.RawQuery != "" {
		key += "?" + r.URL.RawQuery
	}
	return key
}

// ---------- admission helpers ----------

// cacheable methods — only idempotent, safe methods should be cached.
var cacheableMethods = map[string]bool{
	http.MethodGet:  true,
	http.MethodHead: true,
}

// isCacheableMethod returns true if the request method is safe to cache.
func isCacheableMethod(method string) bool {
	return cacheableMethods[method]
}

// isCacheableStatus returns true for status codes that are safe to cache.
func isCacheableStatus(code int) bool {
	switch code {
	case http.StatusOK,
		http.StatusNonAuthoritativeInfo,
		http.StatusNoContent,
		http.StatusPartialContent,
		http.StatusMovedPermanently,
		http.StatusNotModified:
		return true
	default:
		return false
	}
}

// isCacheAllowedByHeaders checks the response's Cache-Control header.
// Returns false if the response explicitly opts out of caching.
func isCacheAllowedByHeaders(h http.Header) bool {
	cc := h.Get("Cache-Control")
	if cc == "" {
		return true // no directive = cacheable
	}
	cc = strings.ToLower(cc)
	if strings.Contains(cc, "no-store") || strings.Contains(cc, "no-cache") || strings.Contains(cc, "private") {
		return false
	}
	return true
}

// ---------- Gin middleware ----------

// Middleware returns a gin.HandlerFunc that implements the cache layer.
//
// Pipeline position: Scheduler → RateLimiter → TrafficRules → **Cache** → Proxy
//
// Features:
//   - Admission rules (method, status, headers, body size)
//   - Stampede protection via request coalescing (singleflight)
func (m *CacheMiddleware) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {

		// ---- Admission Rule 1: only cache safe methods ----
		if !isCacheableMethod(c.Request.Method) {
			c.Next()
			return
		}

		key := cacheKey(c.Request)

		// ---- Cache lookup ----
		if cachedResp, found := m.cache.Get(key); found {
			// Cache HIT — write the stored response and abort the chain.
			serveCachedResponse(c, cachedResp)
			return
		}

		// ---- Cache MISS with stampede protection ----
		//
		// Use singleflight: if 1000 requests arrive for the same key
		// while the cache is empty, only ONE request is forwarded to
		// the backend. The other 999 goroutines wait here and receive
		// the cached result once the first request completes.
		result, err, shared := m.stampede.Do(key, func() (interface{}, error) {
			// Double-check: another goroutine may have populated the cache
			// while we were waiting to enter singleflight.
			if cachedResp, found := m.cache.Get(key); found {
				return cachedResp, nil
			}

			// This goroutine is the "winner" — actually call the backend.
			recorder := &ginResponseRecorder{
				ResponseWriter: c.Writer,
				body:           &bytes.Buffer{},
			}
			c.Writer = recorder

			c.Next() // downstream handlers (proxy) run here

			// Build the response to cache
			resp := &CachedResponse{
				StatusCode: recorder.Status(),
				Headers:    recorder.Header().Clone(),
				Body:       recorder.body.Bytes(),
			}
			http.Header(resp.Headers).Del("X-Cache")

			// Apply admission rules before caching
			if isCacheableStatus(resp.StatusCode) &&
				isCacheAllowedByHeaders(recorder.Header()) &&
				recorder.body.Len() <= m.maxBodySize {

				if err := m.cache.Set(key, resp, m.defaultTTL); err != nil {
					log.Printf("[cache] failed to store response for %s: %v", key, err)
				}
			}

			return resp, nil
		})

		if err != nil {
			log.Printf("[cache] stampede error for %s: %v", key, err)
			c.Next()
			return
		}

		// If this goroutine was a "waiter" (shared=true), it didn't run
		// c.Next() itself — serve the result from the cache/winning goroutine.
		if shared {
			cachedResp := result.(*CachedResponse)
			serveCachedResponse(c, cachedResp)
		}
		// If shared=false, this was the "winner" goroutine. It already
		// wrote the response via the recorder and c.Next(), so nothing
		// more to do.
	}
}

// serveCachedResponse writes a CachedResponse to the Gin context and aborts.
func serveCachedResponse(c *gin.Context, resp *CachedResponse) {
	c.Header("X-Cache", "HIT")
	for k, vv := range resp.Headers {
		if strings.EqualFold(k, "X-Cache") {
			continue
		}
		for _, v := range vv {
			c.Writer.Header().Add(k, v)
		}
	}
	c.Data(resp.StatusCode, http.Header(resp.Headers).Get("Content-Type"), resp.Body)
	c.Abort()
}
