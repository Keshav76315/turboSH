# turboSH — Detection Accuracy Report

> Generated: 2026-03-07T10:22:38Z

## Confusion Matrix

| | Predicted: Blocked | Predicted: Allowed |
| :--- | ---: | ---: |
| **Actual: Attack** | 228 (TP) | 22 (FN) |
| **Actual: Normal** | 1 (FP) | 29 (TN) |

## Metrics

| Metric | Value |
| :--- | ---: |
| Precision | 99.56% |
| Recall (Detection Rate) | 91.20% |
| F1 Score | 95.20% |
| False Positive Rate | 3.33% |

## Per-Profile Breakdown

### Normal Traffic (30 requests, human-paced)

- Correctly Allowed (TN): 29
- Incorrectly Blocked (FP): 1
- Result: REVIEW — 1 false positives detected

### DDoS Burst (200 concurrent requests)

- Correctly Blocked/Throttled (TP): 190
- Missed (FN): 10
- Detection Rate: 95.0%

### Endpoint Scraping (50 rapid randomized requests)

- Correctly Blocked/Throttled (TP): 38
- Missed (FN): 12
- Detection Rate: 76.0%

## Targets (from ARCHITECTURE.md)

| Target | Required | Actual | Status |
| :--- | ---: | ---: | :--- |
| Detection Rate (Recall) | > 70% | 91.2% | PASS |
| False Positive Rate | < 5% | 3.3% | PASS |
