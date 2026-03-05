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
}

// LRUCache is a thread-safe LRU cache with TTL support.
type LRUCache struct {
	capacity int
	items    map[string]*list.Element
	order    *list.List
	mu       sync.RWMutex
}

// NewLRUCache creates a new LRU cache with the given capacity.
func NewLRUCache(capacity int) *LRUCache {
	return &LRUCache{
		capacity: capacity,
		items:    make(map[string]*list.Element),
		order:    list.New(),
	}
}

// Get retrieves a cached response by key.
// Returns nil, false if the key is not found or has expired.
// Moves accessed entries to the front (most recently used).
func (c *LRUCache) Get(key string) (*CachedResponse, bool) {
	// Try a read lock first for the lookup
	c.mu.RLock()
	element, found := c.items[key]
	if !found {
		c.mu.RUnlock()
		return nil, false
	}

	entry := element.Value.(*entry)

	// Check if the entry has expired
	if !entry.value.Expiry.IsZero() && time.Now().After(entry.value.Expiry) {
		c.mu.RUnlock()
		// Expired — need write lock to remove it
		c.mu.Lock()
		// Re-check after acquiring write lock (another goroutine may have removed it)
		if element, found := c.items[key]; found {
			c.order.Remove(element)
			delete(c.items, key)
		}
		c.mu.Unlock()
		return nil, false
	}
	c.mu.RUnlock()

	// Move to front — needs write lock
	c.mu.Lock()
	// Re-check the element is still in the list
	if _, found := c.items[key]; found {
		c.order.MoveToFront(element)
	}
	c.mu.Unlock()

	return entry.value, true
}

// Set stores a response in the cache with a TTL.
// A zero TTL means the entry never expires.
// If the key already exists, its value and expiry are updated.
// If the cache is full, the least recently used entry is evicted.
func (c *LRUCache) Set(key string, value *CachedResponse, ttl time.Duration) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	// Compute expiry from TTL
	if ttl > 0 {
		value.Expiry = time.Now().Add(ttl)
	} else {
		value.Expiry = time.Time{} // zero = never expires
	}

	// Update existing entry
	if element, found := c.items[key]; found {
		c.order.MoveToFront(element)
		element.Value.(*entry).value = value
		return nil
	}

	// Insert new entry
	element := c.order.PushFront(&entry{key, value})
	c.items[key] = element

	// Evict if over capacity
	if c.order.Len() > c.capacity {
		c.evict()
	}

	return nil
}

// Delete removes a specific key from the cache.
func (c *LRUCache) Delete(key string) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if element, found := c.items[key]; found {
		c.order.Remove(element)
		delete(c.items, element.Value.(*entry).key)
	}

	return nil
}

// evict removes the least recently used entry (back of the list).
// Must be called with mu held.
func (c *LRUCache) evict() {
	lastElement := c.order.Back()
	if lastElement != nil {
		c.order.Remove(lastElement)
		entry := lastElement.Value.(*entry)
		delete(c.items, entry.key)
	}
}
