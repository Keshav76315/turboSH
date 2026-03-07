package main

import (
	"fmt"
	"net/http"
	"sync"
	"time"
)

const targetURL = "http://localhost:8080" // turboSH proxy port

func main() {
	fmt.Println("Starting Attack Simulation...")

	// Phase 1: Normal Traffic (warm up the proxy + ML engine)
	fmt.Println("\n--- Phase 1: Normal Traffic ---")
	sendRequests(10, 200*time.Millisecond, "/api/users")
	time.Sleep(2 * time.Second)

	// Phase 2: High Request Rate (Rate Limiting / ML trigger)
	fmt.Println("\n--- Phase 2: High Burst Traffic (Should trigger Rate Limiter/ML) ---")
	sendConcurrentRequests(50, "/api/products")
	time.Sleep(2 * time.Second)

	// Phase 3: Endpoint Scrape (High Entropy / ML trigger)
	fmt.Println("\n--- Phase 3: Endpoint Scraping (High Entropy) ---")
	for i := 0; i < 20; i++ {
		sendRequest(fmt.Sprintf("/api/hidden/%d", i))
		time.Sleep(50 * time.Millisecond)
	}

	fmt.Println("\nAttack Simulation Complete.")
}

func sendRequest(path string) {
	client := &http.Client{
		Timeout: 5 * time.Second,
	}
	resp, err := client.Get(targetURL + path)
	if err != nil {
		fmt.Printf("Request Failed: %v\n", err)
		return
	}
	defer resp.Body.Close()
	fmt.Printf("GET %s -> Status: %d\n", path, resp.StatusCode)
}

func sendRequests(count int, interval time.Duration, path string) {
	for i := 0; i < count; i++ {
		sendRequest(path)
		time.Sleep(interval)
	}
}

func sendConcurrentRequests(count int, path string) {
	var wg sync.WaitGroup
	for i := 0; i < count; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			sendRequest(path)
		}()
	}
	wg.Wait()
}
