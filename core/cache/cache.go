
//imports
package cachesystem
import "time"

type Cache interface {
    Get(key string)(*CachedResponse,bool)/* returns cached response and bool */
    Set(key string, response *CachedResponse) error/* set cached response */
    Delete(key string) error/* delete cached response */
}

// CachedResponse represents the cached HTTP response.
type CachedResponse struct {
	StatusCode int
	Headers    map[string][]string
	Body       []byte
	Expiry     time.Time
}
