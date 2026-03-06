# Traffic Log Schema

> Produced by the **Traffic Logger** (`pipeline/logging/traffic_logger.go`).

---

## Format

Each log entry is a single JSON object per line (**JSON Lines** / `.jsonl` format).

## Fields

| Field           | Type     | Description                          | Example                |
| --------------- | -------- | ------------------------------------ | ---------------------- |
| `timestamp`     | ISO 8601 | Request arrival time (UTC)           | `2026-03-05T12:00:00Z` |
| `ip_hash`       | string   | SHA-256 hash of client IP (16 chars) | `a1b2c3d4e5f67890`     |
| `endpoint`      | string   | Requested URL path                   | `/api/login`           |
| `method`        | string   | HTTP method                          | `POST`                 |
| `status_code`   | int      | Response status code                 | `200`                  |
| `response_time` | float    | Response latency in milliseconds     | `45.2`                 |
| `request_size`  | int      | Request body size in bytes           | `512`                  |

## Example

```json
{"timestamp":"2026-03-05T12:00:00Z","ip_hash":"a1b2c3d4e5f67890","endpoint":"/api/login","method":"POST","status_code":200,"response_time":45.2,"request_size":512}
```

## Notes

- IP addresses are **anonymized** using a truncated SHA-256 hash — the raw IP is never stored.
- `request_size` is `0` when `Content-Length` is unknown (e.g., chunked encoding).
- Log file default path: `logs/traffic.jsonl` (configurable via `TURBOSH_LOG_FILE_PATH`).
- Writes are buffered for performance; call `Flush()` or `Close()` on shutdown.

See [DATA_SCHEMA.md](../../docs/DATA_SCHEMA.md) §1 for the canonical schema definition.
