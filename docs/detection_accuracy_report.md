# turboSH — Detection Accuracy Report

> Generated: 2026-03-07T09:06:00Z

## Confusion Matrix

| | Predicted: Blocked | Predicted: Allowed |
| :--- | ---: | ---: |
| **Actual: Attack** | 231 (TP) | 19 (FN) |
| **Actual: Normal** | 0 (FP) | 30 (TN) |

## Metrics

| Metric | Value |
| :--- | ---: |
| Precision | 100.00% |
| Recall (Detection Rate) | 92.40% |
| F1 Score | 96.05% |
| False Positive Rate | 0.00% |

## Per-Profile Breakdown

### Normal Traffic (30 requests, human-paced)

- Correctly Allowed (TN): 30
- Incorrectly Blocked (FP): 0
- Result: PASS — No false positives

### DDoS Burst (200 concurrent requests)

- Correctly Blocked/Throttled (TP): 190
- Missed (FN): 10
- Detection Rate: 95.0%

### Endpoint Scraping (50 rapid randomized requests)

- Correctly Blocked/Throttled (TP): 41
- Missed (FN): 9
- Detection Rate: 82.0%

## Targets (from ARCHITECTURE.md)

| Target | Required | Actual | Status |
| :--- | ---: | ---: | :--- |
| Detection Rate (Recall) | > 70% | 92.4% | PASS |
| False Positive Rate | < 5% | 0.0% | PASS |
