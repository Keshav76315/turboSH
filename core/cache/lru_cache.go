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

// Get retrieves a cached response by key. Returns nil, false if the key is not found or has expired. Moves accessed entries to the front (most recently used).
func (c *LRUCache) Get(key string) (*CachedResponse, bool) {
	// Try a read lock first for the lookup
	c.mu.RLock()
	element, found := c.items[key]
	if !found {
		c.mu.RUnlock()
		c.metrics.RecordMiss()
		return nil, false
	}

	ent := element.Value.(*entry)

	// Check if the entry has expired
	if !ent.value.Expiry.IsZero() && time.Now().After(ent.value.Expiry) {
		c.mu.RUnlock()
		// Expired — need write lock to remove it
		c.mu.Lock()
		// Re-check after acquiring write lock (another goroutine may have removed or updated it)
		if elem2, found2 := c.items[key]; found2 {
			ent2 := elem2.Value.(*entry)
			if !ent2.value.Expiry.IsZero() && time.Now().After(ent2.value.Expiry) {
				c.order.Remove(elem2)
				delete(c.items, key)
				c.mu.Unlock()
				c.metrics.RecordMiss()
				c.metrics.RecordEviction()
				return nil, false
			}
			// It was updated while waiting for the lock, so return the valid entry
			c.mu.Unlock()
			return ent2.value, true
		}
		c.mu.Unlock()
		c.metrics.RecordMiss()
		return nil, false
	}
	c.mu.RUnlock()

	// Move to front — needs write lock
	c.mu.Lock()
	// Re-check the element is still in the list and get a fresh reference
	if elemFresh, foundFresh := c.items[key]; foundFresh {
		c.order.MoveToFront(elemFresh)
		freshEnt := elemFresh.Value.(*entry)
		c.mu.Unlock()
		c.metrics.RecordHit()
		return freshEnt.value, true
	}
	c.mu.Unlock()
	c.metrics.RecordMiss()
	return nil, false
}

// Set stores a response in the cache with a TTL.
// A zero TTL means the entry never expires.
// If the key already exists, its value and expiry are updated.
// If the cache is full, the least recently used entry is evicted.
func (c *LRUCache) Set(key string, value *CachedResponse, ttl time.Duration) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	valCopy := *value
	// Compute expiry from TTL
	if ttl > 0 {
		valCopy.Expiry = time.Now().Add(ttl)
	} else {
		valCopy.Expiry = time.Time{} // zero = never expires
	}

	newSize := entrySize(key, &valCopy)

	// Update existing entry
	if element, found := c.items[key]; found {
		old := element.Value.(*entry)
		c.currentMemory += newSize - old.size // adjust delta
		old.value = &valCopy
		old.size = newSize
		c.order.MoveToFront(element)
		return nil
	}

	// Insert new entry
	c.currentMemory += newSize
	element := c.order.PushFront(&entry{key, &valCopy, newSize})
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
		ent := element.Value.(*entry)
		c.currentMemory -= ent.size
		c.order.Remove(element)
		delete(c.items, ent.key)
	}

	return nil
}

// evict removes the least recently used entry (back of the list).
// Must be called with mu held.
func (c *LRUCache) evict() {
	lastElement := c.order.Back()
	if lastElement != nil {
		c.order.Remove(lastElement)
		ent := lastElement.Value.(*entry)
		c.currentMemory -= ent.size
		delete(c.items, ent.key)
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
