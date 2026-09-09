#!/bin/bash
# ==============================================================================
# turboSH Real-Time Monitoring Dashboard Demo
# ==============================================================================
# Workflow:
#   1. Starts Dummy Backend server on :9092
#   2. Starts turboSH Proxy on :8080 (metrics & dashboard on :9090)
#   3. Opens the real-time dashboard in your default browser
#   4. Generates live traffic (steady requests + bursts + cache hits)
#   5. All data updates on the dashboard in real-time
#
# Press Ctrl+C at any time to cleanly stop all servers.
# ==============================================================================

set -uo pipefail

# ANSI Colors
BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
PURPLE='\033[0;35m'
RESET='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p "$ROOT_DIR/bin" "$ROOT_DIR/logs"

BACKEND_PID=""
TURBOSH_PID=""
TRAFFIC_PID=""

cleanup() {
  echo ""
  echo -e "${YELLOW}[demo] Shutting down demo processes...${RESET}"
  if [[ -n "$TRAFFIC_PID" ]] && kill -0 "$TRAFFIC_PID" 2>/dev/null; then
    kill "$TRAFFIC_PID" 2>/dev/null || true
  fi
  if [[ -n "$TURBOSH_PID" ]] && kill -0 "$TURBOSH_PID" 2>/dev/null; then
    kill "$TURBOSH_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi

  # Double check port cleanup
  lsof -ti:9092 | xargs kill -9 2>/dev/null || true
  lsof -ti:9090 | xargs kill -9 2>/dev/null || true
  lsof -ti:8080 | xargs kill -9 2>/dev/null || true

  echo -e "${GREEN}[demo] All servers stopped cleanly. Goodbye!${RESET}"
  exit 0
}

trap cleanup EXIT INT TERM

echo -e "${BOLD}${CYAN}"
echo "============================================================"
echo "          🚀 turboSH Real-Time Dashboard Demo               "
echo "============================================================"
echo -e "${RESET}"

# ── 1. Check for stale processes on required ports ───────────────────────
for PORT in 9092 8080 9090; do
  PID=$(lsof -ti:$PORT 2>/dev/null || true)
  if [[ -n "$PID" ]]; then
    echo -e "${YELLOW}[demo] Port :$PORT is occupied by PID $PID. Terminating...${RESET}"
    kill -9 $PID 2>/dev/null || true
    sleep 0.5
  fi
done

# ── 2. Build binaries ───────────────────────────────────────────────────
echo -e "${CYAN}[1/4] Building binaries...${RESET}"
go build -o "$ROOT_DIR/bin/dummy_backend" ./cmd/dummy_backend
echo -e "  ✔ Built bin/dummy_backend"
go build -o "$ROOT_DIR/bin/turbosh" ./cmd/turbosh
echo -e "  ✔ Built bin/turbosh"

# ── 3. Start Dummy Backend on :9092 ─────────────────────────────────────
echo -e "${CYAN}[2/4] Starting Dummy Backend on :9092...${RESET}"
PORT=":9092" "$ROOT_DIR/bin/dummy_backend" > "$ROOT_DIR/logs/dummy_backend.log" 2>&1 &
BACKEND_PID=$!

# Wait for backend to be ready
READY=false
for i in {1..30}; do
  if curl -s -f "http://localhost:9092/" >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 0.2
done

if [[ "$READY" != "true" ]]; then
  echo -e "${RED}[ERROR] Dummy Backend failed to start. See logs/dummy_backend.log${RESET}"
  exit 1
fi
echo -e "  ✔ Dummy Backend is listening on ${GREEN}http://localhost:9092${RESET}"

# ── 4. Start turboSH Proxy on :8080 ─────────────────────────────────────
echo -e "${CYAN}[3/4] Starting turboSH Proxy (:8080 -> :9092, metrics/dashboard :9090)...${RESET}"
TURBOSH_PORT="8080" \
TURBOSH_BACKEND="http://localhost:9092" \
TURBOSH_METRICS_PORT=":9090" \
TURBOSH_METRICS_ENABLED="true" \
TURBOSH_RATE_LIMIT_CAPACITY="10" \
TURBOSH_RATE_LIMIT_RATE="2.0" \
TURBOSH_BURST_THRESHOLD="15" \
"$ROOT_DIR/bin/turbosh" > "$ROOT_DIR/logs/turbosh.log" 2>&1 &
TURBOSH_PID=$!

# Wait for proxy and dashboard status API to be ready
READY=false
for i in {1..30}; do
  if curl -s -f "http://localhost:9090/api/v1/status" >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 0.2
done

if [[ "$READY" != "true" ]]; then
  echo -e "${RED}[ERROR] turboSH failed to start. See logs/turbosh.log${RESET}"
  exit 1
fi
echo -e "  ✔ turboSH Proxy is listening on ${GREEN}http://localhost:8080${RESET}"
echo -e "  ✔ Real-Time Status API on   ${GREEN}http://localhost:9090/api/v1/status${RESET}"
echo -e "  ✔ Monitoring Dashboard on  ${BOLD}${GREEN}http://localhost:9090/dashboard${RESET}"
echo -e "  ✔ Light Monitoring UI on   ${GREEN}http://localhost:9090/dashboard/light${RESET}"

# ── 5. Open browser ──────────────────────────────────────────────────────
NO_BROWSER="${NO_BROWSER:-false}"
if [[ "$*" == *"--no-browser"* ]]; then
  NO_BROWSER=true
fi

DASHBOARD_URL="http://localhost:9090/dashboard"
if [[ "$*" == *"--light"* ]]; then
  DASHBOARD_URL="http://localhost:9090/dashboard/light"
fi

if [[ "$NO_BROWSER" != "true" ]]; then
  echo -e "${CYAN}[4/4] Opening dashboard in browser...${RESET}"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    open "$DASHBOARD_URL"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 &
  fi
else
  echo -e "${YELLOW}[demo] Skipping browser launch (--no-browser). Visit: $DASHBOARD_URL${RESET}"
fi

echo ""
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo -e "${BOLD}${GREEN}  ✨ DEMO RUNNING — LIVE TRAFFIC SIMULATION ACTIVE          ${RESET}"
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo -e "Watch the browser dashboard at: ${CYAN}$DASHBOARD_URL${RESET}"
echo -e "Press ${YELLOW}Ctrl+C${RESET} to terminate demo."
echo ""

# ── 6. Traffic Generator Loop ───────────────────────────────────────────
ENDPOINTS=(
  "/api/users"
  "/api/products"
  "/api/orders"
  "/api/search?q=test"
  "/api/dashboard/stats"
  "/health"
)

TOTAL_SENT=0
CYCLE=0

while true; do
  CYCLE=$((CYCLE + 1))

  # Normal Traffic: Send steady requests (mix of repeated endpoints for cache hits)
  for i in {1..3}; do
    EP="${ENDPOINTS[$RANDOM % ${#ENDPOINTS[@]}]}"
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080$EP")
    TOTAL_SENT=$((TOTAL_SENT + 1))
    echo -e "  [$(date +%T)] ${GREEN}NORMAL${RESET} -> GET $EP (HTTP $STATUS)"
    sleep 0.3
  done

  # Cache Hit Exercise: repeatedly hit the same endpoint to drive up Cache Hit Rate
  for i in {1..4}; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/api/static/cached-catalog")
    TOTAL_SENT=$((TOTAL_SENT + 1))
    echo -e "  [$(date +%T)] ${CYAN}CACHE TEST${RESET} -> GET /api/static/cached-catalog (HTTP $STATUS)"
    sleep 0.15
  done

  # Every 4 cycles: Trigger burst traffic to test Rate Limiting / Threat Feed
  if (( CYCLE % 4 == 0 )); then
    echo -e "  ${YELLOW}⚡ SIMULATING BURST ATTACK (${TOTAL_SENT} total reqs) -> firing 18 rapid requests to /api/login...${RESET}"
    BURST_PIDS=()
    for b in {1..18}; do
      curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/api/login" >/dev/null 2>&1 &
      BURST_PIDS+=($!)
      TOTAL_SENT=$((TOTAL_SENT + 1))
    done
    for pid in "${BURST_PIDS[@]}"; do
      wait "$pid" 2>/dev/null || true
    done
    echo -e "  ${PURPLE}✔ Burst finished. Check Threat Feed & Rate Limit alerts in Dashboard!${RESET}"
  fi

  # Query latest dashboard stats snapshot to display in terminal
  STATS=$(curl -s "http://localhost:9090/api/v1/status" 2>/dev/null || true)
  if [[ -n "$STATS" ]]; then
    RPS=$(echo "$STATS" | grep -o '"recent_rps":[0-9.]*' | cut -d: -f2 || echo "0")
    HITS=$(echo "$STATS" | grep -o '"hits":[0-9]*' | head -1 | cut -d: -f2 || echo "0")
    MISSES=$(echo "$STATS" | grep -o '"misses":[0-9]*' | head -1 | cut -d: -f2 || echo "0")
    RATE=$(echo "$STATS" | grep -o '"hit_rate":[0-9.]*' | head -1 | cut -d: -f2 || echo "0")
    ACTIVE=$(echo "$STATS" | grep -o '"active":[0-9]*' | head -1 | cut -d: -f2 || echo "0")
    echo -e "  ${BOLD}── LIVE STATS ── Throughput: ${RPS} req/s | Cache Hits: ${HITS} / Misses: ${MISSES} (Hit Rate: ${RATE}) | Sched Active: ${ACTIVE}${RESET}"
  fi

  sleep 1
done
