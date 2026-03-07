# turboSH — Performance Benchmark Report

> Generated: 2026-03-07T10:12:51Z

## Summary

| Phase | Concurrency | Total | 200 | 404 | 429 | 503 | 403 | Errors | Mean Latency | P95 Latency | Throughput |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1 | 50 | 20 | 0 | 30 | 0 | 0 | 0 | 11.0ms | 11.3ms | 8.9 req/s |
| Ramp-10 | 10 | 200 | 96 | 0 | 104 | 0 | 0 | 0 | 26.3ms | 36.7ms | 374.5 req/s |
| Ramp-25 | 25 | 500 | 225 | 0 | 275 | 0 | 0 | 0 | 43.3ms | 66.7ms | 565.8 req/s |
| Ramp-50 | 50 | 1000 | 448 | 0 | 552 | 0 | 0 | 0 | 80.1ms | 118.3ms | 613.2 req/s |
| Ramp-100 | 100 | 2000 | 1017 | 0 | 983 | 0 | 0 | 0 | 170.4ms | 226.7ms | 574.3 req/s |
| Sustained | 100 | 15112 | 2000 | 0 | 9632 | 0 | 0 | 3480 | 184.1ms | 402.1ms | 500.0 req/s |
| Spike | 500 | 500 | 149 | 0 | 0 | 0 | 0 | 351 | 682.4ms | 756.9ms | 654.9 req/s |

## Phase Descriptions

- **Baseline**: 50 sequential requests at 100ms intervals. Establishes cold-start latency.
- **Ramp-10/25/50/100**: Increasing concurrency with 20 requests per goroutine. Measures scaling behavior.
- **Sustained**: 100 concurrent goroutines running continuously for 30 seconds.
- **Spike**: 500 concurrent goroutines in a single burst. Tests scheduler and rate limiter under extreme load.

## Observations

- 429 responses indicate the rate limiter is correctly throttling excess traffic.
- 503 responses indicate the scheduler queue is full (system at capacity).
- 403 responses indicate the ML anomaly detection engine is blocking suspicious patterns.
