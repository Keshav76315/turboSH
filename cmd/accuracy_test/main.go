package main

import (
	"fmt"
	"math/rand"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const targetURL = "http://localhost:8080"

type RequestResult struct {
	StatusCode int
	IsAttack   bool
	Err        error
}

func doRequest(path string) (int, error) {
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(targetURL + path)
	if err != nil {
		return 0, err
	}
	resp.Body.Close()
	return resp.StatusCode, nil
}

func runNormalTraffic() []RequestResult {
	fmt.Println("\n--- Normal Traffic Profile ---")
	endpoints := []string{"/api/users", "/api/products", "/api/health", "/api/docs", "/api/status"}
	var results []RequestResult

	for i := 0; i < 30; i++ {
		path := endpoints[rand.Intn(len(endpoints))]
		code, err := doRequest(path)
		r := RequestResult{StatusCode: code, IsAttack: false, Err: err}
		results = append(results, r)
		if err != nil {
			fmt.Printf("  [Normal %d/30] %s -> ERROR: %v\n", i+1, path, err)
		} else {
			fmt.Printf("  [Normal %d/30] %s -> %d\n", i+1, path, code)
		}
		delay := time.Duration(200+rand.Intn(300)) * time.Millisecond
		time.Sleep(delay)
	}

	return results
}

func runDDoSAttack() []RequestResult {
	fmt.Println("\n--- Attack Profile: DDoS Burst (200 concurrent) ---")
	var results []RequestResult
	var mu sync.Mutex
	var wg sync.WaitGroup

	for i := 0; i < 200; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			code, err := doRequest("/api/target")
			mu.Lock()
			results = append(results, RequestResult{StatusCode: code, IsAttack: true, Err: err})
			mu.Unlock()
		}()
	}
	wg.Wait()

	blocked := 0
	throttled := 0
	for _, r := range results {
		if r.StatusCode == 403 {
			blocked++
		} else if r.StatusCode == 429 {
			throttled++
		}
	}
	fmt.Printf("  Sent: 200 | Blocked (403): %d | Throttled (429): %d | Allowed: %d\n",
		blocked, throttled, 200-blocked-throttled)

	return results
}

func runScrapingAttack() []RequestResult {
	fmt.Println("\n--- Attack Profile: Endpoint Scraping (50 rapid, randomized paths) ---")
	var results []RequestResult

	for i := 0; i < 50; i++ {
		path := fmt.Sprintf("/api/hidden/resource_%d", rand.Intn(1000))
		code, err := doRequest(path)
		results = append(results, RequestResult{StatusCode: code, IsAttack: true, Err: err})
		if err != nil {
			fmt.Printf("  [Scan %d/50] %s -> ERROR\n", i+1, path)
		} else {
			fmt.Printf("  [Scan %d/50] %s -> %d\n", i+1, path, code)
		}
		time.Sleep(20 * time.Millisecond)
	}

	return results
}

func computeMetrics(results []RequestResult) (tp, tn, fp, fn int) {
	for _, r := range results {
		if r.Err != nil {
			continue
		}
		blocked := r.StatusCode == 403 || r.StatusCode == 429
		if r.IsAttack && blocked {
			tp++
		} else if r.IsAttack && !blocked {
			fn++
		} else if !r.IsAttack && blocked {
			fp++
		} else {
			tn++
		}
	}
	return
}

func generateReport(normalResults, ddosResults, scrapingResults []RequestResult) string {
	allResults := make([]RequestResult, 0, len(normalResults)+len(ddosResults)+len(scrapingResults))
	allResults = append(allResults, normalResults...)
	allResults = append(allResults, ddosResults...)
	allResults = append(allResults, scrapingResults...)

	tp, tn, fp, fn := computeMetrics(allResults)

	precision := float64(0)
	if tp+fp > 0 {
		precision = float64(tp) / float64(tp+fp)
	}
	recall := float64(0)
	if tp+fn > 0 {
		recall = float64(tp) / float64(tp+fn)
	}
	f1 := float64(0)
	if precision+recall > 0 {
		f1 = 2 * (precision * recall) / (precision + recall)
	}
	fpr := float64(0)
	if fp+tn > 0 {
		fpr = float64(fp) / float64(fp+tn)
	}

	var sb strings.Builder
	sb.WriteString("# turboSH — Detection Accuracy Report\n\n")
	sb.WriteString(fmt.Sprintf("> Generated: %s\n\n", time.Now().UTC().Format(time.RFC3339)))

	sb.WriteString("## Confusion Matrix\n\n")
	sb.WriteString("| | Predicted: Blocked | Predicted: Allowed |\n")
	sb.WriteString("| :--- | ---: | ---: |\n")
	sb.WriteString(fmt.Sprintf("| **Actual: Attack** | %d (TP) | %d (FN) |\n", tp, fn))
	sb.WriteString(fmt.Sprintf("| **Actual: Normal** | %d (FP) | %d (TN) |\n", fp, tn))

	sb.WriteString("\n## Metrics\n\n")
	sb.WriteString("| Metric | Value |\n")
	sb.WriteString("| :--- | ---: |\n")
	sb.WriteString(fmt.Sprintf("| Precision | %.2f%% |\n", precision*100))
	sb.WriteString(fmt.Sprintf("| Recall (Detection Rate) | %.2f%% |\n", recall*100))
	sb.WriteString(fmt.Sprintf("| F1 Score | %.2f%% |\n", f1*100))
	sb.WriteString(fmt.Sprintf("| False Positive Rate | %.2f%% |\n", fpr*100))

	sb.WriteString("\n## Per-Profile Breakdown\n\n")

	ntp, ntn, nfp, nfn := computeMetrics(normalResults)
	sb.WriteString("### Normal Traffic (30 requests, human-paced)\n\n")
	sb.WriteString(fmt.Sprintf("- Correctly Allowed (TN): %d\n", ntn))
	sb.WriteString(fmt.Sprintf("- Incorrectly Blocked (FP): %d\n", nfp))
	sb.WriteString(fmt.Sprintf("- Result: %s\n\n", func() string {
		if nfp == 0 {
			return "PASS — No false positives"
		}
		return fmt.Sprintf("REVIEW — %d false positives detected", nfp)
	}()))
	_ = ntp
	_ = nfn

	dtp, dtn, dfp, dfn := computeMetrics(ddosResults)
	sb.WriteString("### DDoS Burst (200 concurrent requests)\n\n")
	sb.WriteString(fmt.Sprintf("- Correctly Blocked/Throttled (TP): %d\n", dtp))
	sb.WriteString(fmt.Sprintf("- Missed (FN): %d\n", dfn))
	dRecall := float64(0)
	if dtp+dfn > 0 {
		dRecall = float64(dtp) / float64(dtp+dfn) * 100
	}
	sb.WriteString(fmt.Sprintf("- Detection Rate: %.1f%%\n\n", dRecall))
	_ = dtn
	_ = dfp

	stp, stn, sfp, sfn := computeMetrics(scrapingResults)
	sb.WriteString("### Endpoint Scraping (50 rapid randomized requests)\n\n")
	sb.WriteString(fmt.Sprintf("- Correctly Blocked/Throttled (TP): %d\n", stp))
	sb.WriteString(fmt.Sprintf("- Missed (FN): %d\n", sfn))
	sRecall := float64(0)
	if stp+sfn > 0 {
		sRecall = float64(stp) / float64(stp+sfn) * 100
	}
	sb.WriteString(fmt.Sprintf("- Detection Rate: %.1f%%\n\n", sRecall))
	_ = stn
	_ = sfp

	sb.WriteString("## Targets (from ARCHITECTURE.md)\n\n")
	sb.WriteString("| Target | Required | Actual | Status |\n")
	sb.WriteString("| :--- | ---: | ---: | :--- |\n")
	recallStatus := "PASS"
	if recall < 0.70 {
		recallStatus = "FAIL"
	}
	fprStatus := "PASS"
	if fpr > 0.05 {
		fprStatus = "FAIL"
	}
	sb.WriteString(fmt.Sprintf("| Detection Rate (Recall) | > 70%% | %.1f%% | %s |\n", recall*100, recallStatus))
	sb.WriteString(fmt.Sprintf("| False Positive Rate | < 5%% | %.1f%% | %s |\n", fpr*100, fprStatus))

	return sb.String()
}

func main() {
	fmt.Println("=== turboSH Detection Accuracy Test ===")
	fmt.Printf("Target: %s\n", targetURL)

	normalResults := runNormalTraffic()

	time.Sleep(5 * time.Second)

	ddosResults := runDDoSAttack()

	time.Sleep(3 * time.Second)

	scrapingResults := runScrapingAttack()

	report := generateReport(normalResults, ddosResults, scrapingResults)

	err := os.WriteFile("docs/detection_accuracy_report.md", []byte(report), 0644)
	if err != nil {
		fmt.Printf("\nFailed to write report: %v\n", err)
	} else {
		fmt.Println("\n✅ Detection accuracy report written to docs/detection_accuracy_report.md")
	}

	fmt.Println("\n=== Detection Accuracy Test Complete ===")
}
