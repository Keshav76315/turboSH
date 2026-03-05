package cachesystem

import (
	"golang.org/x/sync/singleflight"
)

// StampedeProtector prevents cache stampedes using request coalescing.
//
// When a cache entry expires and many concurrent requests arrive for the
// same key, only ONE request is forwarded to the backend. All other
// callers wait for that single request to complete and share the result.
//
// This uses Go's singleflight package under the hood.
type StampedeProtector struct {
	group singleflight.Group
}

// NewStampedeProtector creates a new stampede protector.
func NewStampedeProtector() *StampedeProtector {
	return &StampedeProtector{}
}

// Do executes fn once per unique key. If another goroutine is already
// executing fn for the same key, the caller blocks until that execution
// completes and receives the same result.
//
// Returns:
//   - val: the value returned by fn
//   - err: any error from fn
//   - shared: true if the result was shared with another caller
func (sp *StampedeProtector) Do(key string, fn func() (interface{}, error)) (interface{}, error, bool) {
	return sp.group.Do(key, fn)
}
