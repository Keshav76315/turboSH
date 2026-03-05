package cachesystem

import (
	"fmt"
	"testing"
	"time"
)

// helper to create a CachedResponse with a given TTL
func newResponse(statusCode int, ttl time.Duration) *CachedResponse {
	expiry := time.Time{} // zero = no expiry
	if ttl > 0 {
		expiry = time.Now().Add(ttl)
	}
	return &CachedResponse{
		StatusCode: statusCode,
		Headers:    map[string][]string{"Content-Type": {"text/plain"}},
		Body:       []byte(fmt.Sprintf("response-%d", statusCode)),
		Expiry:     expiry,
	}
}

// Test 1: Basic LRU eviction when cache is full
func TestLRUEviction(t *testing.T) {
	cache := NewLRUCache(3) // capacity of 3

	cache.Set("a", newResponse(200, 0)) // no TTL
	cache.Set("b", newResponse(201, 0))
	cache.Set("c", newResponse(202, 0))

	// Cache is full. Adding "d" should evict "a" (least recently used)
	cache.Set("d", newResponse(203, 0))

	if _, found := cache.Get("a"); found {
		t.Error("Expected 'a' to be evicted (LRU), but it was still found")
	}

	// b, c, d should still be present
	for _, key := range []string{"b", "c", "d"} {
		if _, found := cache.Get(key); !found {
			t.Errorf("Expected '%s' to be in cache, but it was not found", key)
		}
	}

	t.Log("✅ LRU eviction works — oldest entry removed when capacity exceeded")
}

// Test 2: LRU order updates on access — accessing an entry makes it "recent"
func TestLRUOrderUpdatesOnAccess(t *testing.T) {
	cache := NewLRUCache(3)

	cache.Set("a", newResponse(200, 0))
	cache.Set("b", newResponse(201, 0))
	cache.Set("c", newResponse(202, 0))

	// Access "a" so it becomes the most recently used
	cache.Get("a")

	// Now add "d" — should evict "b" (new LRU), NOT "a"
	cache.Set("d", newResponse(203, 0))

	if _, found := cache.Get("b"); found {
		t.Error("Expected 'b' to be evicted (it was the LRU after 'a' was accessed), but it was found")
	}

	if _, found := cache.Get("a"); !found {
		t.Error("Expected 'a' to still be in cache (it was recently accessed), but it was not found")
	}

	t.Log("✅ LRU order correctly updates on Get — accessed entries are kept")
}

// Test 3: TTL eviction — expired entries are removed on Get
func TestTTLEvictionOnGet(t *testing.T) {
	cache := NewLRUCache(10)

	cache.Set("short-lived", newResponse(200, 100*time.Millisecond)) // expires in 100ms
	cache.Set("long-lived", newResponse(201, 10*time.Second))        // expires in 10s

	// Both should be available immediately
	if _, found := cache.Get("short-lived"); !found {
		t.Error("Expected 'short-lived' to be found before expiry")
	}

	// Wait for the short-lived entry to expire
	time.Sleep(150 * time.Millisecond)

	// short-lived should now be gone (lazy TTL check in Get)
	if _, found := cache.Get("short-lived"); found {
		t.Error("Expected 'short-lived' to be expired, but it was still found")
	}

	// long-lived should still be present
	if _, found := cache.Get("long-lived"); !found {
		t.Error("Expected 'long-lived' to still be in cache")
	}

	t.Log("✅ TTL eviction works — expired entries removed on Get()")
}

// Test 4: Background TTL manager proactively removes expired entries
func TestTTLManagerBackgroundCleanup(t *testing.T) {
	cache := NewLRUCache(10)

	cache.Set("expire-soon", newResponse(200, 100*time.Millisecond))
	cache.Set("stay-forever", newResponse(201, 0)) // no TTL = never expires

	// Start background cleanup every 50ms
	stop := cache.StartTTLManager(50 * time.Millisecond)
	defer close(stop)

	// Wait for the entry to expire + cleanup to run
	time.Sleep(250 * time.Millisecond)

	// The background manager should have already removed "expire-soon"
	// without us calling Get on it
	cache.mu.Lock()
	_, stillInMap := cache.items["expire-soon"]
	cache.mu.Unlock()

	if stillInMap {
		t.Error("Expected 'expire-soon' to be removed by background TTL manager, but it's still in the map")
	}

	if _, found := cache.Get("stay-forever"); !found {
		t.Error("Expected 'stay-forever' to remain (no TTL), but it was removed")
	}

	t.Log("✅ Background TTL manager proactively cleans expired entries")
}

// Test 5: LRU + TTL working together
func TestLRUAndTTLTogether(t *testing.T) {
	cache := NewLRUCache(3)

	// Fill cache: "a" has short TTL, "b" and "c" have no TTL
	cache.Set("a", newResponse(200, 100*time.Millisecond)) // expires in 100ms
	cache.Set("b", newResponse(201, 0))
	cache.Set("c", newResponse(202, 0))

	// Start background cleanup
	stop := cache.StartTTLManager(50 * time.Millisecond)
	defer close(stop)

	// Wait for "a" to expire and get cleaned up
	time.Sleep(200 * time.Millisecond)

	// "a" should be gone (TTL expired), freeing a slot
	if _, found := cache.Get("a"); found {
		t.Error("Expected 'a' to be expired by TTL")
	}

	// Cache now has 2 entries (b, c). Adding "d" should NOT evict anything
	// because TTL freed up space.
	cache.Set("d", newResponse(203, 0))

	// All three should be present
	for _, key := range []string{"b", "c", "d"} {
		if _, found := cache.Get(key); !found {
			t.Errorf("Expected '%s' to be in cache — TTL freed space, no LRU eviction needed", key)
		}
	}

	// Now add "e" — cache is full again (b, c, d). LRU eviction should kick in.
	// "b" is the least recently used (c and d were accessed by Get above)
	cache.Set("e", newResponse(204, 0))

	if _, found := cache.Get("b"); found {
		t.Error("Expected 'b' to be evicted by LRU (oldest after TTL cleanup)")
	}

	if _, found := cache.Get("e"); !found {
		t.Error("Expected 'e' to be in cache")
	}

	t.Log("✅ LRU + TTL eviction work together — TTL frees slots, LRU kicks in when full")
}
