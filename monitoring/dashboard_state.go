package monitoring

import (
	"math"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

// DashboardState holds all real-time metrics for the dashboard API.
// It aggregates data from the scheduler, cache, ML, and request pipeline.
// All methods are safe for concurrent access.
type DashboardState struct {
	startTime time.Time

	// Request counters
	totalRequests atomic.Int64
	statusCounts  sync.Map // map[int]*atomic.Int64 — status code → count

	// Latency tracking (lock-free ring buffer for p99)
	latencyMu      sync.Mutex
	latencies      []float64 // ring buffer of recent latencies (ms)
	latencyIdx     int
	latencyCount   int
	latencySum     float64
	latencyRingCap int

	// Throughput tracking
	rpsWindow    []rpsSlot
	rpsMu        sync.Mutex
	rpsSlotWidth time.Duration

	// Recent mitigation events (ring buffer)
	eventsMu   sync.Mutex
	events     []MitigationEvent
	eventsIdx  int
	eventsFull bool

	// References set after construction
	scheduler SchedulerStats
	cache     CacheStats
	config    ConfigSnapshot
}

// SchedulerStats provides read access to scheduler state.
type SchedulerStats interface {
	ActiveCount() int
	WaitingCount() int
}

// CacheStats provides read access to cache state.
type CacheStats interface {
	Hits() int64
	Misses() int64
	Evictions() int64
	HitRate() float64
	CurrentMemoryBytes() int
	MaxMemoryBytes() int
	EntryCount() int
	EntryCapacity() int
}

// ConfigSnapshot holds static config values for the dashboard.
type ConfigSnapshot struct {
	BackendURL         string
	ProxyPort          string
	MaxConcurrent      int
	RateLimitCapacity  int
	RateLimitRate      float64
	BlockThreshold     float64
	RateLimitThreshold float64
	CacheMaxMemory     int
	CacheCapacity      int
	MLModelLoaded      bool
}

// MitigationEvent represents a security event for the dashboard feed.
type MitigationEvent struct {
	Timestamp time.Time `json:"timestamp"`
	Type      string    `json:"type"`     // "BLOCK", "THROTTLE", "RATE_LIMIT", "RULES"
	IPHash    string    `json:"ip_hash"`  // first 8 chars of HMAC hash
	Path      string    `json:"path"`     // request path
	Score     *float64  `json:"score"`    // anomaly score (nil if absent / rule-based)
	Detail    string    `json:"detail"`   // human-readable explanation
	Status    int       `json:"status"`   // HTTP status code returned (403, 429, etc.)
}

type rpsSlot struct {
	timestamp time.Time
	count     int64
}

// StatusSnapshot is the complete dashboard snapshot returned as JSON.
type StatusSnapshot struct {
	UptimeSeconds float64 `json:"uptime_seconds"`
	BackendURL    string  `json:"backend_url"`
	ProxyPort     string  `json:"proxy_port"`
	GoVersion     string  `json:"go_version"`

	Scheduler SchedulerSnapshot `json:"scheduler"`
	Cache     CacheSnapshot     `json:"cache"`
	Requests  RequestSnapshot   `json:"requests"`
	ML        MLSnapshot        `json:"ml"`

	RateLimiter RateLimiterSnapshot `json:"rate_limiter"`
	Events      []MitigationEvent   `json:"recent_events"`
}

// SchedulerSnapshot holds scheduler gauge readings.
type SchedulerSnapshot struct {
	Active   int `json:"active"`
	Waiting  int `json:"waiting"`
	Capacity int `json:"capacity"`
}

// CacheSnapshot holds cache metrics.
type CacheSnapshot struct {
	Hits               int64   `json:"hits"`
	Misses             int64   `json:"misses"`
	Evictions          int64   `json:"evictions"`
	HitRate            float64 `json:"hit_rate"`
	CurrentMemoryBytes int     `json:"current_memory_bytes"`
	MaxMemoryBytes     int     `json:"max_memory_bytes"`
	EntryCount         int     `json:"entry_count"`
	EntryCapacity      int     `json:"entry_capacity"`
}

// RequestSnapshot holds request throughput metrics.
type RequestSnapshot struct {
	Total        int64          `json:"total"`
	ByStatus     map[int]int64  `json:"by_status"`
	RecentRPS    float64        `json:"recent_rps"`
	AvgLatencyMs float64        `json:"avg_latency_ms"`
	P99LatencyMs float64        `json:"p99_latency_ms"`
}

// MLSnapshot holds ML engine state.
type MLSnapshot struct {
	ModelLoaded        bool           `json:"model_loaded"`
	BlockThreshold     float64        `json:"block_threshold"`
	RateLimitThreshold float64        `json:"rate_limit_threshold"`
	Decisions          DecisionCounts `json:"decisions"`
}

// DecisionCounts holds ML decision counters.
type DecisionCounts struct {
	Allow     int64 `json:"allow"`
	RateLimit int64 `json:"rate_limit"`
	Block     int64 `json:"block"`
}

// RateLimiterSnapshot holds rate limiter config.
type RateLimiterSnapshot struct {
	CapacityPerIP int     `json:"capacity_per_ip"`
	RefillRate    float64 `json:"refill_rate"`
}

// NewDashboardState creates a new dashboard state tracker.
func NewDashboardState() *DashboardState {
	return &DashboardState{
		startTime:    time.Now(),
		latencies:    make([]float64, 2000), // ring buffer for ~2000 recent latencies
		latencyRingCap: 2000,
		rpsWindow:    make([]rpsSlot, 0, 60),
		rpsSlotWidth: 1 * time.Second,
		events:       make([]MitigationEvent, 50), // ring buffer for 50 most recent events
	}
}

// SetScheduler attaches the scheduler for live gauge reading.
func (ds *DashboardState) SetScheduler(s SchedulerStats) {
	ds.scheduler = s
}

// SetCache attaches the cache for live metric reading.
func (ds *DashboardState) SetCache(c CacheStats) {
	ds.cache = c
}

// SetConfig sets the static config snapshot.
func (ds *DashboardState) SetConfig(cfg ConfigSnapshot) {
	ds.config = cfg
}

// RecordRequest records an incoming request with its status code and latency.
func (ds *DashboardState) RecordRequest(statusCode int, latencyMs float64) {
	ds.totalRequests.Add(1)

	// Increment per-status counter
	key := statusCode
	val, _ := ds.statusCounts.LoadOrStore(key, &atomic.Int64{})
	val.(*atomic.Int64).Add(1)

	// Record latency in ring buffer
	ds.latencyMu.Lock()
	ds.latencies[ds.latencyIdx] = latencyMs
	ds.latencyIdx = (ds.latencyIdx + 1) % ds.latencyRingCap
	if ds.latencyCount < ds.latencyRingCap {
		ds.latencyCount++
	}
	ds.latencySum += latencyMs
	ds.latencyMu.Unlock()

	// Record RPS slot
	now := time.Now().Truncate(ds.rpsSlotWidth)
	ds.rpsMu.Lock()
	if len(ds.rpsWindow) > 0 && ds.rpsWindow[len(ds.rpsWindow)-1].timestamp.Equal(now) {
		ds.rpsWindow[len(ds.rpsWindow)-1].count++
	} else {
		ds.rpsWindow = append(ds.rpsWindow, rpsSlot{timestamp: now, count: 1})
		// Keep only last 60 slots (60 seconds)
		if len(ds.rpsWindow) > 60 {
			ds.rpsWindow = ds.rpsWindow[len(ds.rpsWindow)-60:]
		}
	}
	ds.rpsMu.Unlock()
}

// RecordEvent adds a mitigation event to the ring buffer.
func (ds *DashboardState) RecordEvent(evt MitigationEvent) {
	ds.eventsMu.Lock()
	defer ds.eventsMu.Unlock()

	ds.events[ds.eventsIdx] = evt
	ds.eventsIdx = (ds.eventsIdx + 1) % len(ds.events)
	if !ds.eventsFull && ds.eventsIdx == 0 {
		ds.eventsFull = true
	}
}

// Snapshot returns a complete, point-in-time snapshot of all metrics.
func (ds *DashboardState) Snapshot() StatusSnapshot {
	snap := StatusSnapshot{
		UptimeSeconds: time.Since(ds.startTime).Seconds(),
		BackendURL:    ds.config.BackendURL,
		ProxyPort:     ds.config.ProxyPort,
		GoVersion:     "go1.24+",
	}

	// Scheduler
	if ds.scheduler != nil {
		snap.Scheduler = SchedulerSnapshot{
			Active:   ds.scheduler.ActiveCount(),
			Waiting:  ds.scheduler.WaitingCount(),
			Capacity: ds.config.MaxConcurrent,
		}
	} else {
		snap.Scheduler = SchedulerSnapshot{Capacity: ds.config.MaxConcurrent}
	}

	// Cache
	if ds.cache != nil {
		snap.Cache = CacheSnapshot{
			Hits:               ds.cache.Hits(),
			Misses:             ds.cache.Misses(),
			Evictions:          ds.cache.Evictions(),
			HitRate:            ds.cache.HitRate(),
			CurrentMemoryBytes: ds.cache.CurrentMemoryBytes(),
			MaxMemoryBytes:     ds.cache.MaxMemoryBytes(),
			EntryCount:         ds.cache.EntryCount(),
			EntryCapacity:      ds.cache.EntryCapacity(),
		}
	} else {
		snap.Cache = CacheSnapshot{
			MaxMemoryBytes: ds.config.CacheMaxMemory,
			EntryCapacity:  ds.config.CacheCapacity,
		}
	}

	// Requests
	snap.Requests.Total = ds.totalRequests.Load()
	snap.Requests.ByStatus = make(map[int]int64)
	ds.statusCounts.Range(func(key, value any) bool {
		snap.Requests.ByStatus[key.(int)] = value.(*atomic.Int64).Load()
		return true
	})

	// Average & p99 latency
	ds.latencyMu.Lock()
	count := ds.latencyCount
	var sorted []float64
	var avgLatency float64
	if count > 0 {
		avgLatency = math.Round(ds.latencySum/float64(snap.Requests.Total)*100) / 100

		// Compute p99 from ring buffer (simple: sort and pick 99th percentile)
		sorted = make([]float64, count)
		if count <= ds.latencyRingCap {
			copy(sorted, ds.latencies[:count])
		} else {
			copy(sorted, ds.latencies)
		}
	}
	ds.latencyMu.Unlock()

	if len(sorted) > 0 {
		snap.Requests.AvgLatencyMs = avgLatency
		sort.Float64s(sorted)
		p99Idx := int(math.Ceil(float64(len(sorted))*0.99)) - 1
		if p99Idx < 0 {
			p99Idx = 0
		}
		if p99Idx >= len(sorted) {
			p99Idx = len(sorted) - 1
		}
		snap.Requests.P99LatencyMs = math.Round(sorted[p99Idx]*100) / 100
	}

	// RPS (average over last 5 seconds)
	ds.rpsMu.Lock()
	now := time.Now()
	cutoff := now.Add(-5 * time.Second)
	var rpsTotal int64
	var rpsSlots int
	for i := len(ds.rpsWindow) - 1; i >= 0; i-- {
		slot := ds.rpsWindow[i]
		if slot.timestamp.Before(cutoff) {
			break
		}
		rpsTotal += slot.count
		rpsSlots++
	}
	if rpsSlots > 0 {
		snap.Requests.RecentRPS = math.Round(float64(rpsTotal)/5.0*10) / 10
	}
	ds.rpsMu.Unlock()

	// ML
	snap.ML = MLSnapshot{
		ModelLoaded:        ds.config.MLModelLoaded,
		BlockThreshold:     ds.config.BlockThreshold,
		RateLimitThreshold: ds.config.RateLimitThreshold,
	}
	snap.ML.Decisions.Allow = DashboardAllows.Load()
	snap.ML.Decisions.RateLimit = DashboardThrottles.Load()
	snap.ML.Decisions.Block = DashboardBlocks.Load()

	// Rate limiter
	snap.RateLimiter = RateLimiterSnapshot{
		CapacityPerIP: ds.config.RateLimitCapacity,
		RefillRate:    ds.config.RateLimitRate,
	}

	// Recent events (reverse chronological)
	ds.eventsMu.Lock()
	var recentEvents []MitigationEvent
	if ds.eventsFull {
		// Full ring buffer — read from eventsIdx backwards (wrap around)
		for i := 0; i < len(ds.events); i++ {
			idx := (ds.eventsIdx - 1 - i + len(ds.events)) % len(ds.events)
			if ds.events[idx].Timestamp.IsZero() {
				continue
			}
			recentEvents = append(recentEvents, ds.events[idx])
		}
	} else {
		// Not full — read from 0 to eventsIdx (reverse)
		for i := ds.eventsIdx - 1; i >= 0; i-- {
			if ds.events[i].Timestamp.IsZero() {
				continue
			}
			recentEvents = append(recentEvents, ds.events[i])
		}
	}
	ds.eventsMu.Unlock()
	snap.Events = recentEvents
	if snap.Events == nil {
		snap.Events = []MitigationEvent{}
	}

	return snap
}
