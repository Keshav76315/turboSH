# --- Builder Stage ---
FROM golang:1.25-bookworm AS builder

# Install build dependencies (gcc, libc-dev) required for CGO and wget for ONNX
RUN apt-get update && apt-get install -y gcc libc-dev wget ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download Linux ONNX Runtime (v1.17.1 to align with yalue/onnxruntime_go v1.9.0)
RUN wget -qO onnurl.tgz https://github.com/microsoft/onnxruntime/releases/download/v1.17.1/onnxruntime-linux-x64-1.17.1.tgz && \
    tar -xzf onnurl.tgz && \
    mkdir -p /app/onnx_lib && \
    mv onnxruntime-linux-x64-1.17.1/lib/libonnxruntime.so.1.17.1 /app/onnx_lib/libonnxruntime.so && \
    rm -rf onnurl.tgz onnxruntime-linux-x64-1.17.1

# Download Go modules
COPY go.mod go.sum ./
RUN go mod download

# Copy source code and ML models
COPY . .

# Build the proxy binary with CGO enabled
# We compile cmd/turbosh/main.go into a binary named 'turbosh'
RUN CGO_ENABLED=1 GOOS=linux GOARCH=amd64 go build -o turbosh ./cmd/turbosh/main.go

# --- Runtime Stage ---
FROM debian:bookworm-slim

# Install CA certificates to allow outgoing TLS connections if the proxy forwards to HTTPS backends
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the compiled binary from builder
COPY --from=builder /app/turbosh /app/turbosh

# Copy the ONNX shared library
COPY --from=builder /app/onnx_lib /app/onnx_lib

# Copy the actual exported ML model file required for inference
COPY --from=builder /app/models/anomaly_model.onnx /app/models/anomaly_model.onnx

# Ensure the proxy knows where to find the ONNX runtime library
ENV TURBOSH_ONNX_LIB_PATH="/app/onnx_lib/libonnxruntime.so"

# Default configuration variables (operators override these via 'docker run -e')
ENV TURBOSH_PORT="8080"
ENV TURBOSH_BACKEND="http://localhost:9090"

# Expose the proxy port
EXPOSE 8080

# Run the proxy
ENTRYPOINT ["/app/turbosh"]
