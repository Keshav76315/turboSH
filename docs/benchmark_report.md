# turboSH — Performance Benchmark Report

> Generated: 2026-03-07T09:07:19Z

## Summary

| Phase | Concurrency | Total | 200 | 404 | 429 | 503 | 403 | Errors | Mean Latency | P95 Latency | Throughput |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1 | 50 | 20 | 0 | 30 | 0 | 0 | 0 | 4.3ms | 8.8ms | 9.4 req/s |
| Ramp-10 | 10 | 200 | 6 | 0 | 194 | 0 | 0 | 0 | 4.3ms | 7.5ms | 2221.9 req/s |
| Ramp-25 | 25 | 500 | 5 | 0 | 495 | 0 | 0 | 0 | 9.8ms | 15.8ms | 2473.0 req/s |
| Ramp-50 | 50 | 1000 | 4 | 0 | 996 | 0 | 0 | 0 | 18.9ms | 22.5ms | 2586.2 req/s |
| Ramp-100 | 100 | 2000 | 5 | 0 | 1995 | 0 | 0 | 0 | 43.6ms | 80.4ms | 2252.6 req/s |
| Sustained | 100 | 18377 | 39 | 0 | 11702 | 0 | 0 | 6636 | 76.7ms | 128.1ms | 598.7 req/s |
| Spike | 500 | 500 | 13 | 0 | 58 | 0 | 0 | 429 | 4585.5ms | 4717.8ms | 105.8 req/s |

## Phase Descriptions

- **Baseline**: 50 sequential requests at 100ms intervals. Establishes cold-start latency.
- **Ramp-10/25/50/100**: Increasing concurrency with 20 requests per goroutine. Measures scaling behavior.
- **Sustained**: 100 concurrent goroutines running continuously for 30 seconds.
- **Spike**: 500 concurrent goroutines in a single burst. Tests scheduler and rate limiter under extreme load.

## Observations

- 429 responses indicate the rate limiter is correctly throttling excess traffic.
- 503 responses indicate the scheduler queue is full (system at capacity).
- 403 responses indicate the ML anomaly detection engine is blocking suspicious patterns.
