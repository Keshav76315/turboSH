### this folder contains the chache optimization system ---

# this chache system will be interceting the traffic passed form the scheduler and backend server also the flow is written below :
        request
            ↓
       cache lookup
            ↓
    hit → return cached response
            or 
    miss → call backend
            ↓
       store response


### step1: i took for this cache system is that there is interface for chache system and also have the chached response struct used to store the HTTP response.

### step2&3 : it make me do the application of LRU cache system and also have the TTL manager to manage the TTL of the cache.(core structure of the cache system: hashmap + doubly linked list).

### step4 : Add Thread Safety

Your cache will be accessed by many concurrent requests.

So add synchronization.

Example:

sync.RWMutex

Read operations:

RLock

Write operations:

Lock

This ensures safe concurrent access.

5. Implement TTL Expiration System

Each cache entry must expire after a certain time.

Example:

expiry = now + ttl

Two approaches you can implement now:

Lazy expiration

Check expiration during Get().

if expired:
    delete entry
Background cleanup worker

Create a goroutine that periodically removes expired entries.

Example:

every 60 seconds:
    scan cache
    remove expired items

File to create:

ttl_manager.go
6. Implement Cache Key Generator

Before caching anything, you must define how keys are created.

Example function:

func GenerateCacheKey(r *http.Request) string {
    return r.Method + ":" + r.URL.String()
}

Example result:

GET:/products?page=2

Later the middleware will use this function.

7. Implement Cache Admission Rules

Your cache should only store safe responses.

Define rules now.

Cacheable requests:

GET requests

Never cache:

POST
PUT
DELETE

Also avoid caching responses with:

Set-Cookie
Authorization

You can implement a function:

IsCacheable(request, response)
8. Build Cache Metrics System

Your plan includes cache metrics 

PLAN

.

You can implement counters now.

Track:

cache_hits
cache_misses
cache_evictions

Example struct:

type CacheMetrics struct {
    Hits int64
    Misses int64
    Evictions int64
}

Later this connects to monitoring.

9. Write Unit Tests for Cache

Before integration, test your cache thoroughly.

Tests you should write:

LRU behavior
insert A B C
access A
insert D
expect B removed
TTL expiration
insert item
wait TTL
expect expired
concurrency safety

simulate multiple goroutines.

10. Create Cache Middleware Skeleton

Even if Keshav hasn't finished the middleware, you can build a placeholder wrapper.

Example concept:

func CacheMiddleware(next http.Handler) http.Handler

Flow:

request
   ↓
generate cache key
   ↓
check cache
   ↓
hit → return response
miss → call next handler
          ↓
       store response

You can simulate this with a simple test server.

11. Build a Local Simulation Server

Create a small test server to simulate backend behavior.

Example:

localhost:8080/products

Add artificial delay:

sleep(2 seconds)

Then test:

first request slow
second request fast (cache hit)

This will prove your cache works.

12. Prepare Documentation for Integration

Write documentation explaining:

Cache API
Cache key rules
Cacheable responses
Memory limits
Metrics

So that when Keshav finishes the middleware, integration becomes simple.

13. Final Things You Can Complete Now

Before middleware exists, you can already finish:

✔ cache interface
✔ LRU algorithm
✔ TTL manager
✔ thread safety
✔ cache key generator
✔ admission rules
✔ metrics system
✔ unit tests
✔ test server

That is almost the entire cache subsystem from your plan 

PLAN

.

14. What You Must Wait For

You only need Keshav’s part for:

middleware hook
request pipeline
proxy integration

Everything else can be ready.

