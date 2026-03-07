package main

import (
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"time"
)

func main() {
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
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

	fmt.Println("Dummy Backend listening on :9092")
	log.Fatal(http.ListenAndServe(":9092", nil))
}
