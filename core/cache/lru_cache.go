// LRU Cache — hashmap + doubly linked list implementation.
// Thread-safe using sync.RWMutex for concurrent read access.

package cachesystem

import (
	"container/list"
	"sync"
	"time"
)

type entry struct {
	key   string
	value *CachedResponse
	size  int // approximate memory footprint in bytes
}

// entrySize estimates the memory footprint of a cached response.
func entrySize(key string, resp *CachedResponse) int {
	size := len(key) + len(resp.Body) + 8 /*StatusCode*/ + 24 /*Expiry*/
	for k, vv := range resp.Headers {
		size += len(k)
		for _, v := range vv {
			size += len(v)
		}
	}
	return size
}

// LRUCache is a thread-safe LRU cache with TTL support.
type LRUCache struct {
	capacity      int
	maxMemory     int // max total bytes (0 = unlimited)
	currentMemory int // current total bytes of all cached entries
	items         map[string]*list.Element
	order         *list.List
	mu            sync.RWMutex
	metrics       *CacheMetrics
}

// NewLRUCache creates a new LRU cache.
//   - capacity: max number of entries (must be > 0)
//   - maxMemory: max total bytes for all cached entries (0 = unlimited)
func NewLRUCache(capacity int, maxMemory ...int) *LRUCache {
	if capacity <= 0 {
		capacity = 1
	}
	mem := 0
	if len(maxMemory) > 0 && maxMemory[0] > 0 {
		mem = maxMemory[0]
	}
	return &LRUCache{
		capacity:  capacity,
		maxMemory: mem,
		items:     make(map[string]*list.Element),
		order:     list.New(),
		metrics:   &CacheMetrics{},
	}
}

// copyResponse performs a deep copy of a CachedResponse (including Headers map and Body slice)
// to prevent data races and unintended mutations across concurrent requests.
func copyResponse(src *CachedResponse) *CachedResponse {
	if src == nil {
		return nil
	}
	dst := &CachedResponse{
		StatusCode: src.StatusCode,
		Expiry:     src.Expiry,
	}
	if src.Headers != nil {
		dst.Headers = make(map[string][]string, len(src.Headers))
		for k, v := range src.Headers {
			vCopy := make([]string, len(v))
			copy(vCopy, v)
			dst.Headers[k] = vCopy
		}
	}
	if src.Body != nil {
		dst.Body = make([]byte, len(src.Body))
		copy(dst.Body, src.Body)
	}
	return dst
}

// removeElement unlinks an element from the LRU list, decrements currentMemory,
// and deletes it from the items map. Must be called with c.mu write lock held.
func (c *LRUCache) removeElement(element *list.Element) {
	if element == nil {
		return
	}
	c.order.Remove(element)
	ent := element.Value.(*entry)
	c.currentMemory -= ent.size
	delete(c.items, ent.key)
}

// Get retrieves a cached response by key. Returns nil, false if the key is not found or has expired.
// Moves accessed entries to the front (most recently used).
// Uses a single write lock to avoid lock bouncing and redundant map lookups.
func (c *LRUCache) Get(key string) (*CachedResponse, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	element, found := c.items[key]
	if !found {
		c.metrics.RecordMiss()
		return nil, false
	}

	ent := element.Value.(*entry)

	// Check if the entry has expired
	if !ent.value.Expiry.IsZero() && time.Now().After(ent.value.Expiry) {
		c.removeElement(element)
		c.metrics.RecordMiss()
		c.metrics.RecordEviction()
		return nil, false
	}

	c.order.MoveToFront(element)
	c.metrics.RecordHit()
	return copyResponse(ent.value), true
}

// Set stores a response in the cache with a TTL.
// A zero TTL means the entry never expires.
// If the key already exists, its value and expiry are updated.
// If the cache is full, the least recently used entry is evicted.
// Performs a deep copy of the cached response to guarantee data integrity.
func (c *LRUCache) Set(key string, value *CachedResponse, ttl time.Duration) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	valCopy := copyResponse(value)
	// Compute expiry from TTL
	if ttl > 0 {
		valCopy.Expiry = time.Now().Add(ttl)
	} else {
		valCopy.Expiry = time.Time{} // zero = never expires
	}

	newSize := entrySize(key, valCopy)

	// Update existing entry
	if element, found := c.items[key]; found {
		old := element.Value.(*entry)
		c.currentMemory += newSize - old.size // adjust delta
		old.value = valCopy
		old.size = newSize
		c.order.MoveToFront(element)
		return nil
	}

	// Insert new entry
	c.currentMemory += newSize
	element := c.order.PushFront(&entry{key, valCopy, newSize})
	c.items[key] = element

	// Evict if over entry capacity
	for c.order.Len() > c.capacity {
		c.evict()
	}

	// Evict if over memory cap
	if c.maxMemory > 0 {
		for c.currentMemory > c.maxMemory && c.order.Len() > 0 {
			c.evict()
		}
	}

	return nil
}

// Delete removes a specific key from the cache.
func (c *LRUCache) Delete(key string) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if element, found := c.items[key]; found {
		c.removeElement(element)
	}

	return nil
}

// evict removes the least recently used entry (back of the list).
// Must be called with mu held.
func (c *LRUCache) evict() {
	lastElement := c.order.Back()
	if lastElement != nil {
		c.removeElement(lastElement)
		c.metrics.RecordEviction()
	}
}

// CurrentMemory returns the current memory usage of all cached entries in bytes.
func (c *LRUCache) CurrentMemory() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.currentMemory
}

// Metrics returns the cache's metrics collector.
func (c *LRUCache) Metrics() *CacheMetrics {
	return c.metrics
}
