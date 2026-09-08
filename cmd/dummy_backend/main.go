package main

import (
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"strings"
	"time"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = os.Getenv("BACKEND_PORT")
	}
	if port == "" {
		port = ":9092"
	}
	if !strings.HasPrefix(port, ":") {
		port = ":" + port
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// Simulate occasional slow responses (latency spikes)
		if rand.Float32() < 0.1 {
			time.Sleep(200 * time.Millisecond) // 200ms sleep
		}
		// Simulate occasional 500 errors (error rate)
		if rand.Float32() < 0.05 {
			w.WriteHeader(http.StatusInternalServerError)
			fmt.Fprintf(w, "Internal Server Error\n")
			return
		}

		w.WriteHeader(http.StatusOK)
		fmt.Fprintf(w, "OK. Backend received request for %s\n", r.URL.Path)
	})

	server := &http.Server{
		Addr:         port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	fmt.Printf("Dummy Backend listening on %s\n", port)
	log.Fatal(server.ListenAndServe())
}
