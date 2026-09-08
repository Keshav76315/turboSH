# --- Builder Stage ---
FROM golang:1.24-bookworm AS builder

# Install build dependencies (gcc, libc-dev) required for CGO and wget for ONNX
RUN apt-get update && apt-get install -y gcc libc-dev wget ca-certificates && rm -rf /var/lib/apt/lists/*

# Target architecture supplied by docker buildx (defaults to amd64)
ARG TARGETARCH

WORKDIR /app

# Download Linux ONNX Runtime (v1.17.1 to align with yalue/onnxruntime_go v1.9.0)
# Supports both x86_64 (amd64) and aarch64 (arm64)
RUN ARCH="${TARGETARCH:-amd64}" && \
    if [ "$ARCH" = "arm64" ]; then ONNX_ARCH="aarch64"; else ONNX_ARCH="x64"; fi && \
    wget -qO onnurl.tgz "https://github.com/microsoft/onnxruntime/releases/download/v1.17.1/onnxruntime-linux-${ONNX_ARCH}-1.17.1.tgz" && \
    tar -xzf onnurl.tgz && \
    mkdir -p /app/onnx_lib && \
    mv onnxruntime-linux-${ONNX_ARCH}-1.17.1/lib/libonnxruntime.so.1.17.1 /app/onnx_lib/libonnxruntime.so && \
    rm -rf onnurl.tgz onnxruntime-linux-${ONNX_ARCH}-1.17.1

# Download Go modules
COPY go.mod go.sum ./
RUN go mod download

# Copy source code and ML models
COPY . .

# Build the proxy binary with CGO enabled
# We compile cmd/turbosh/main.go into a binary named 'turbosh'
RUN CGO_ENABLED=1 GOOS=linux GOARCH=${TARGETARCH:-amd64} go build -o turbosh ./cmd/turbosh/main.go

# --- Runtime Stage ---
FROM debian:bookworm-slim

# Install CA certificates to allow outgoing TLS connections if the proxy forwards to HTTPS backends
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# Create non-root system user and group
RUN groupadd -g 10001 turbosh && \
    useradd -u 10001 -g turbosh -s /bin/sh -d /app turbosh

WORKDIR /app

# Copy the compiled binary from builder
COPY --from=builder /app/turbosh /app/turbosh

# Copy the ONNX shared library
COPY --from=builder /app/onnx_lib /app/onnx_lib

# Copy the actual exported ML model file required for inference
COPY --from=builder /app/models/anomaly_model.onnx /app/models/anomaly_model.onnx

# Ensure permissions for non-root user (including writable logs directory)
RUN mkdir -p /app/logs && chown -R turbosh:turbosh /app

# Ensure the proxy knows where to find the ONNX runtime library
ENV TURBOSH_ONNX_LIB_PATH="/app/onnx_lib/libonnxruntime.so"

# Default configuration variables (operators override these via 'docker run -e')
ENV TURBOSH_PORT="8080"
ENV TURBOSH_BACKEND="http://localhost:9092"
ENV TURBOSH_METRICS_PORT=":9090"

# Expose proxy traffic port and internal metrics port
EXPOSE 8080 9090

# Run as non-root user
USER turbosh

# Run the proxy
ENTRYPOINT ["/app/turbosh"]
