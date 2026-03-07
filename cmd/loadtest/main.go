package main

import (
	"fmt"
	"math"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const targetURL = "http://localhost:8081"

type Result struct {
	StatusCode int
	Latency    time.Duration
	Err        error
}

type PhaseStats struct {
	Name        string
	Concurrency int
	Total       int
	Status200   int
	Status404   int
	Status429   int
	Status503   int
	Status403   int
	OtherErr    int
	MeanLatency time.Duration
	P95Latency  time.Duration
	Throughput  float64
	Duration    time.Duration
}

func doRequest(path string, clientIP string) Result {
	client := &http.Client{Timeout: 10 * time.Second}
	req, err := http.NewRequest("GET", targetURL+path, nil)
	if err == nil && clientIP != "" {
		req.Header.Set("X-Forwarded-For", clientIP)
	}

	start := time.Now()
	resp, requestErr := client.Do(req)
	latency := time.Since(start)
	if requestErr != nil {
		return Result{Err: requestErr, Latency: latency}
	}
	resp.Body.Close()
	return Result{StatusCode: resp.StatusCode, Latency: latency}
}

func runPhase(name string, concurrency int, totalRequests int, path string) PhaseStats {
	results := make([]Result, 0, totalRequests)
	var mu sync.Mutex
	var wg sync.WaitGroup
	var sent atomic.Int64

	start := time.Now()

	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func(goroutineID int) {
			defer wg.Done()
			clientIP := fmt.Sprintf("192.168.10.%d", goroutineID%250) // simulate up to 250 distinct user IPs
			for {
				idx := sent.Add(1)
				if idx > int64(totalRequests) {
					return
				}
				r := doRequest(path, clientIP)
				mu.Lock()
				results = append(results, r)
				mu.Unlock()
			}
		}(i)
	}
	wg.Wait()
	elapsed := time.Since(start)

	stats := PhaseStats{
		Name:        name,
		Concurrency: concurrency,
		Total:       len(results),
		Duration:    elapsed,
	}

	var latencies []time.Duration
	for _, r := range results {
		if r.Err != nil {
			stats.OtherErr++
			continue
		}
		latencies = append(latencies, r.Latency)
		switch r.StatusCode {
		case 200:
			stats.Status200++
		case 404:
			stats.Status404++
		case 429:
			stats.Status429++
		case 503:
			stats.Status503++
		case 403:
			stats.Status403++
		default:
			stats.OtherErr++
		}
	}

	if len(latencies) > 0 {
		sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
		var total time.Duration
		for _, l := range latencies {
			total += l
		}
		stats.MeanLatency = total / time.Duration(len(latencies))
		p95idx := int(math.Ceil(float64(len(latencies))*0.95)) - 1
		if p95idx < 0 {
			p95idx = 0
		}
		stats.P95Latency = latencies[p95idx]
	}

	if elapsed > 0 {
		stats.Throughput = float64(stats.Total) / elapsed.Seconds()
	}

	return stats
}

func runBaseline() PhaseStats {
	fmt.Println("\n--- Phase 1: Baseline (Sequential) ---")
	results := make([]Result, 0, 50)
	start := time.Now()
	for i := 0; i < 50; i++ {
		r := doRequest("/api/baseline", "192.168.10.1")
		results = append(results, r)
		fmt.Printf("  [%d/50] %d  %.0fms\n", i+1, r.StatusCode, float64(r.Latency.Microseconds())/1000)
		time.Sleep(100 * time.Millisecond)
	}
	elapsed := time.Since(start)

	stats := PhaseStats{Name: "Baseline", Concurrency: 1, Total: 50, Duration: elapsed}
	var latencies []time.Duration
	for _, r := range results {
		if r.Err != nil {
			stats.OtherErr++
			continue
		}
		latencies = append(latencies, r.Latency)
		switch r.StatusCode {
		case 200:
			stats.Status200++
		case 404:
			stats.Status404++
		case 429:
			stats.Status429++
		case 503:
			stats.Status503++
		case 403:
			stats.Status403++
		default:
			stats.OtherErr++
		}
	}
	if len(latencies) > 0 {
		sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
		var total time.Duration
		for _, l := range latencies {
			total += l
		}
		stats.MeanLatency = total / time.Duration(len(latencies))
		p95idx := int(math.Ceil(float64(len(latencies))*0.95)) - 1
		stats.P95Latency = latencies[p95idx]
	}
	if elapsed > 0 {
		stats.Throughput = float64(stats.Total) / elapsed.Seconds()
	}
	return stats
}

func printStats(s PhaseStats) {
	fmt.Printf("\n  Results for [%s] (concurrency=%d):\n", s.Name, s.Concurrency)
	fmt.Printf("    Total: %d | 200: %d | 404: %d | 429: %d | 503: %d | 403: %d | Errors: %d\n",
		s.Total, s.Status200, s.Status404, s.Status429, s.Status503, s.Status403, s.OtherErr)
	fmt.Printf("    Mean Latency: %.1fms | P95: %.1fms | Throughput: %.1f req/s\n",
		float64(s.MeanLatency.Microseconds())/1000,
		float64(s.P95Latency.Microseconds())/1000,
		s.Throughput)
}

func generateReport(allStats []PhaseStats) string {
	var sb strings.Builder
	sb.WriteString("# turboSH — Performance Benchmark Report\n\n")
	sb.WriteString(fmt.Sprintf("> Generated: %s\n\n", time.Now().UTC().Format(time.RFC3339)))

	sb.WriteString("## Summary\n\n")
	sb.WriteString("| Phase | Concurrency | Total | 200 | 404 | 429 | 503 | 403 | Errors | Mean Latency | P95 Latency | Throughput |\n")
	sb.WriteString("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")

	for _, s := range allStats {
		sb.WriteString(fmt.Sprintf("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %.1fms | %.1fms | %.1f req/s |\n",
			s.Name, s.Concurrency, s.Total,
			s.Status200, s.Status404, s.Status429, s.Status503, s.Status403, s.OtherErr,
			float64(s.MeanLatency.Microseconds())/1000,
			float64(s.P95Latency.Microseconds())/1000,
			s.Throughput,
		))
	}

	sb.WriteString("\n## Phase Descriptions\n\n")
	sb.WriteString("- **Baseline**: 50 sequential requests at 100ms intervals. Establishes cold-start latency.\n")
	sb.WriteString("- **Ramp-10/25/50/100**: Increasing concurrency with 20 requests per goroutine. Measures scaling behavior.\n")
	sb.WriteString("- **Sustained**: 100 concurrent goroutines running continuously for 30 seconds.\n")
	sb.WriteString("- **Spike**: 500 concurrent goroutines in a single burst. Tests scheduler and rate limiter under extreme load.\n")

	sb.WriteString("\n## Observations\n\n")
	sb.WriteString("- 429 responses indicate the rate limiter is correctly throttling excess traffic.\n")
	sb.WriteString("- 503 responses indicate the scheduler queue is full (system at capacity).\n")
	sb.WriteString("- 403 responses indicate the ML anomaly detection engine is blocking suspicious patterns.\n")

	return sb.String()
}

func main() {
	fmt.Println("=== turboSH Load Test ===")
	fmt.Printf("Target: %s\n", targetURL)

	var allStats []PhaseStats

	baseline := runBaseline()
	printStats(baseline)
	allStats = append(allStats, baseline)

	time.Sleep(3 * time.Second)

	fmt.Println("\n--- Phase 2: Ramp-up ---")
	for _, c := range []int{10, 25, 50, 100} {
		fmt.Printf("\n  Running %d concurrent goroutines x 20 requests...\n", c)
		s := runPhase(fmt.Sprintf("Ramp-%d", c), c, c*20, "/api/ramp")
		printStats(s)
		allStats = append(allStats, s)
		time.Sleep(2 * time.Second)
	}

	fmt.Println("\n--- Phase 3: Sustained Load (100 concurrent, 30s) ---")
	sustainedResults := make([]Result, 0, 10000)
	var mu sync.Mutex
	var wg sync.WaitGroup
	done := make(chan struct{})

	start := time.Now()
	go func() {
		time.Sleep(30 * time.Second)
		close(done)
	}()

	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(goroutineID int) {
			defer wg.Done()
			clientIP := fmt.Sprintf("192.168.10.%d", goroutineID%250)
			for {
				select {
				case <-done:
					return
				default:
					r := doRequest("/api/sustained", clientIP)
					mu.Lock()
					sustainedResults = append(sustainedResults, r)
					mu.Unlock()
				}
			}
		}(i)
	}
	wg.Wait()
	sustainedElapsed := time.Since(start)

	sustained := PhaseStats{Name: "Sustained", Concurrency: 100, Total: len(sustainedResults), Duration: sustainedElapsed}
	var sLatencies []time.Duration
	for _, r := range sustainedResults {
		if r.Err != nil {
			sustained.OtherErr++
			continue
		}
		sLatencies = append(sLatencies, r.Latency)
		switch r.StatusCode {
		case 200:
			sustained.Status200++
		case 404:
			sustained.Status404++
		case 429:
			sustained.Status429++
		case 503:
			sustained.Status503++
		case 403:
			sustained.Status403++
		default:
			sustained.OtherErr++
		}
	}
	if len(sLatencies) > 0 {
		sort.Slice(sLatencies, func(i, j int) bool { return sLatencies[i] < sLatencies[j] })
		var total time.Duration
		for _, l := range sLatencies {
			total += l
		}
		sustained.MeanLatency = total / time.Duration(len(sLatencies))
		p95idx := int(math.Ceil(float64(len(sLatencies))*0.95)) - 1
		sustained.P95Latency = sLatencies[p95idx]
	}
	if sustainedElapsed > 0 {
		sustained.Throughput = float64(sustained.Total) / sustainedElapsed.Seconds()
	}
	printStats(sustained)
	allStats = append(allStats, sustained)

	time.Sleep(3 * time.Second)

	fmt.Println("\n--- Phase 4: Spike (500 concurrent burst) ---")
	spike := runPhase("Spike", 500, 500, "/api/spike")
	printStats(spike)
	allStats = append(allStats, spike)

	report := generateReport(allStats)
	err := os.WriteFile("docs/benchmark_report.md", []byte(report), 0644)
	if err != nil {
		fmt.Printf("\nFailed to write report: %v\n", err)
	} else {
		fmt.Println("\n✅ Benchmark report written to docs/benchmark_report.md")
	}

	fmt.Println("\n=== Load Test Complete ===")
}
