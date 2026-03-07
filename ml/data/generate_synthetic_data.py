import csv
import os
import random
import numpy as np

# Set random seed for reproducibility
np.random.seed(42)
random.seed(42)

OUTPUT_FILE = "datasets/synthetic_traffic_dataset.csv"
NUM_NORMAL = 20000
NUM_ATTACK = 2000

COLUMNS = [
    "requests_per_ip_10s",
    "requests_per_ip_60s",
    "endpoint_entropy",
    "latency_spike",
    "error_rate",
    "request_variance",
    "label",
]

def generate_normal_traffic() -> dict:
    # Normal traffic usually has low request rates, but active browsing can cause bursts 
    # of 20-30 requests in 10s due to assets loading.
    if np.random.rand() < 0.8:
        reqs_10s = int(np.random.poisson(5))
        reqs_60s = int(reqs_10s + np.random.poisson(15))
    else:
        # Active browsing burst (simulating the accuracy test's 30 requests)
        reqs_10s = int(np.random.uniform(10, 40))
        reqs_60s = int(reqs_10s + np.random.uniform(5, 40))
    
    # Entropy should be reasonably high for normal browsing, or very low for static asset fetching
    # We will pick a mixed normal distribution
    entropy = np.clip(np.random.normal(1.5, 0.5), 0.0, 3.0)
    
    # Rarely any latency spikes
    spike = np.random.choice([0, 1], p=[0.95, 0.05])
    
    # Very low error rates
    error_rate = np.clip(np.random.exponential(0.02), 0.0, 0.15)
    
    # Healthy variance
    variance = np.clip(np.random.normal(50.0, 20.0), 10.0, 200.0)
    
    return {
        "requests_per_ip_10s": reqs_10s,
        "requests_per_ip_60s": reqs_60s,
        "endpoint_entropy": round(entropy, 4),
        "latency_spike": spike,
        "error_rate": round(error_rate, 4),
        "request_variance": round(variance, 4),
        "label": 0
    }

def generate_ddos_burst() -> dict:
    """Generates a sudden DDoS burst attack."""
    # requests_per_ip_10s >= 50
    reqs_10s = int(np.random.uniform(50, 1000))
    # It must also be high over 60s
    reqs_60s = int(reqs_10s + np.random.uniform(0, 500))
    
    # Often hitting the same or a small set of endpoints
    entropy = np.clip(np.random.uniform(0.0, 1.0), 0.0, 1.0)
    
    spike = np.random.choice([0, 1], p=[0.2, 0.8])
    error_rate = np.clip(np.random.exponential(0.1), 0.0, 0.4)
    variance = np.clip(np.random.uniform(1.0, 10.0), 1.0, 100.0)
    
    return {
        "requests_per_ip_10s": reqs_10s,
        "requests_per_ip_60s": reqs_60s,
        "endpoint_entropy": round(entropy, 4),
        "latency_spike": spike,
        "error_rate": round(error_rate, 4),
        "request_variance": round(variance, 4),
        "label": 1
    }

def generate_brute_force() -> dict:
    """Generates a brute force login attempt."""
    # error_rate >= 0.5 AND requests_per_ip_60s >= 20
    reqs_10s = int(np.random.uniform(1, 15))
    reqs_60s = int(np.random.uniform(20, 100))
    
    # Repeatedly hitting the same endpoint (e.g. /login)
    entropy = np.clip(np.random.uniform(0.0, 0.5), 0.0, 0.5)
    
    spike = np.random.choice([0, 1], p=[0.8, 0.2])
    # Very high error rate from constant 401 Unauthorized responses
    error_rate = np.clip(np.random.uniform(0.5, 0.99), 0.5, 1.0)
    variance = np.clip(np.random.uniform(10.0, 30.0), 10.0, 100.0)
    
    return {
        "requests_per_ip_10s": reqs_10s,
        "requests_per_ip_60s": reqs_60s,
        "endpoint_entropy": round(entropy, 4),
        "latency_spike": spike,
        "error_rate": round(error_rate, 4),
        "request_variance": round(variance, 4),
        "label": 1
    }

def generate_request_flooding() -> dict:
    """Generates a sustained request flood."""
    # requests_per_ip_60s >= 200
    reqs_10s = int(np.random.uniform(10, 45)) # Might fly under 10s radar
    reqs_60s = int(np.random.uniform(200, 5000))
    
    entropy = np.clip(np.random.uniform(1.0, 2.5), 0.0, 3.0)
    spike = np.random.choice([0, 1], p=[0.5, 0.5])
    error_rate = np.clip(np.random.uniform(0.0, 0.4), 0.0, 1.0)
    variance = np.clip(np.random.uniform(2.0, 20.0), 1.0, 100.0)
    
    return {
        "requests_per_ip_10s": reqs_10s,
        "requests_per_ip_60s": reqs_60s,
        "endpoint_entropy": round(entropy, 4),
        "latency_spike": spike,
        "error_rate": round(error_rate, 4),
        "request_variance": round(variance, 4),
        "label": 1
    }

def generate_latency_attack() -> dict:
    """Generates an attack meant to drain server resources and cause timeouts."""
    # latency_spike == 1 AND error_rate >= 0.3
    reqs_10s = int(np.random.uniform(1, 40)) 
    reqs_60s = int(np.random.uniform(10, 150))
    
    entropy = np.clip(np.random.uniform(1.0, 3.0), 0.0, 3.0)
    spike = 1
    # Very high error rate from 504 Gateway Timeouts
    error_rate = np.clip(np.random.uniform(0.3, 1.0), 0.3, 1.0)
    variance = np.clip(np.random.uniform(100.0, 500.0), 50.0, 1000.0)
    
    return {
        "requests_per_ip_10s": reqs_10s,
        "requests_per_ip_60s": reqs_60s,
        "endpoint_entropy": round(entropy, 4),
        "latency_spike": spike,
        "error_rate": round(error_rate, 4),
        "request_variance": round(variance, 4),
        "label": 1
    }

def generate_dataset():
    data = []
    
    print(f"Generating {NUM_NORMAL} normal traffic records...")
    for _ in range(NUM_NORMAL):
        data.append(generate_normal_traffic())
        
    print(f"Generating {NUM_ATTACK} total attack records...")
    for _ in range(NUM_ATTACK // 4):
        data.append(generate_ddos_burst())
        data.append(generate_brute_force())
        data.append(generate_request_flooding())
        data.append(generate_latency_attack())
        
    # Shuffle the dataset
    random.shuffle(data)
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, mode='w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in data:
            writer.writerow(row)
            
    print(f"✅ Generated {len(data)} rows successfully. Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_dataset()
