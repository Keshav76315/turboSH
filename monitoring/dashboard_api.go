package monitoring

import (
	"encoding/json"
	"net/http"
	"sync/atomic"
)

// DashboardDecisionCounters tracks ML decision counts independently of Prometheus.
// These are incremented from the same call sites as the Prometheus counters.
var (
	DashboardAllows    atomic.Int64
	DashboardThrottles atomic.Int64
	DashboardBlocks    atomic.Int64
)

// RecordDashboardMLBlock increments both Prometheus and dashboard block counters.
func RecordDashboardMLBlock() {
	RecordMLBlock()
	DashboardBlocks.Add(1)
}

// RecordDashboardMLThrottle increments both Prometheus and dashboard throttle counters.
func RecordDashboardMLThrottle() {
	RecordMLThrottle()
	DashboardThrottles.Add(1)
}

// RecordDashboardMLAllow increments both Prometheus and dashboard allow counters.
func RecordDashboardMLAllow() {
	RecordMLAllow()
	DashboardAllows.Add(1)
}

// DashboardAPIHandler returns an HTTP handler that serves the /api/v1/status endpoint.
func DashboardAPIHandler(ds *DashboardState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		snap := ds.Snapshot()

		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")

		if err := json.NewEncoder(w).Encode(snap); err != nil {
			http.Error(w, `{"error":"encoding_failed"}`, http.StatusInternalServerError)
		}
	}
}

// DashboardHTMLHandler serves the dashboard HTML file at /dashboard.
func DashboardHTMLHandler(htmlContent []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-cache")
		w.Write(htmlContent)
	}
}
