//here is goona be used the hashmap + doubly linked list: to sotre the clients ip and

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

type LRUCache struct {
	capacity int
	items    map[string]*list.Element
	order    *list.List
	mu       sync.Mutex
}

// to look up into the cache (with TTL check) i have done 2 look ups one is manual when the user sends get request and one is when tll reaches its limit
func (c *LRUCache) Get(key string) (*CachedResponse, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if element, found := c.items[key]; found {

		entry := element.Value.(*entry)

		// check if the entry has expired
		if !entry.value.Expiry.IsZero() && time.Now().After(entry.value.Expiry) {
			c.order.Remove(element)
			delete(c.items, key)
			return nil, false
		}

		c.order.MoveToFront(element)

		return entry.value, true
	}

	return nil, false
}

// to set into the cache
func (c *LRUCache) Set(key string, value *CachedResponse) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if element, found := c.items[key]; found {

		c.order.MoveToFront(element)
		element.Value.(*entry).value = value
		return nil
	}

	element := c.order.PushFront(&entry{key, value})

	c.items[key] = element

	if c.order.Len() > c.capacity {

		c.evict()
	}

	return nil
}

// to delete a specific key from the cache
func (c *LRUCache) Delete(key string) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if element, found := c.items[key]; found {

		c.order.Remove(element)
		delete(c.items, element.Value.(*entry).key)
		return nil
	}

	return nil
}

// to evict from the cache
func (c *LRUCache) evict() {

	lastElement := c.order.Back()

	if lastElement != nil {

		c.order.Remove(lastElement)

		entry := lastElement.Value.(*entry)

		delete(c.items, entry.key)
	}
}

// to add a new user into the cache
func NewLRUCache(capacity int) *LRUCache {
	return &LRUCache{
		capacity: capacity,
		items:    make(map[string]*list.Element),
		order:    list.New(),
	}
}
