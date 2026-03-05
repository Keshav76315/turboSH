// TTL Manager — runs a background goroutine that periodically scans the cache and evicts expired entries so they don't sit in memory.

package cachesystem

import "time"

// StartTTLManager launches a background goroutine that checks for expired cache entries at the given interval. It returns a stop channel — send on it (or close it) to shut down the cleanup goroutine.
func (c *LRUCache) StartTTLManager(interval time.Duration) chan struct{} {
	stop := make(chan struct{})

	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				c.removeExpired()
			case <-stop:
				return
			}
		}
	}()

	return stop
}

// removeExpired walks the linked list from back (oldest) to front and removes every entry whose Expiry has passed.
func (c *LRUCache) removeExpired() {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now() // cache time.Now() once — avoids a syscall per iteration

	element := c.order.Back()

	for element != nil {
		prev := element.Prev() // grab prev before we potentially remove this one

		entry := element.Value.(*entry)

		if !entry.value.Expiry.IsZero() && now.After(entry.value.Expiry) {
			c.order.Remove(element)
			delete(c.items, entry.key)
		}

		element = prev
	}
}
