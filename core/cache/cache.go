package cachesystem

import "time"

// Cache defines the interface for the turboSH cache system.
type Cache interface {
	// Get retrieves a cached response. Returns nil, false if not found or expired.
	Get(key string) (*CachedResponse, bool)

	// Set stores a response in the cache with a TTL.
	// A zero TTL means the entry never expires.
	Set(key string, response *CachedResponse, ttl time.Duration) error

	// Delete removes a specific key from the cache.
	Delete(key string) error
}

// CachedResponse represents a cached HTTP response.
type CachedResponse struct {
	StatusCode int
	Headers    map[string][]string
	Body       []byte
	Expiry     time.Time
}
