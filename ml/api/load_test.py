import time
import requests
import statistics

URL = "http://localhost:8000/predict"
PAYLOAD = {"instance_type": "c5.2xlarge", "az": "eu-north-1a"}
NUM_REQUESTS = 100

def run_load_test():
    print(f"Starting load test on {URL} with {NUM_REQUESTS} requests...")
    response_times = []
    
    # Warm up
    for _ in range(5):
        requests.post(URL, json=PAYLOAD)
        
    start_test = time.time()
    for i in range(NUM_REQUESTS):
        start_req = time.time()
        resp = requests.post(URL, json=PAYLOAD)
        end_req = time.time()
        
        if resp.status_code == 200:
            response_times.append((end_req - start_req) * 1000) # in ms
        else:
            print(f"Request failed with {resp.status_code}")
            
    end_test = time.time()
    
    avg_time = statistics.mean(response_times)
    max_time = max(response_times)
    p95_time = statistics.quantiles(response_times, n=20)[18]
    total_time = end_test - start_test
    
    print("\n--- Load Test Results ---")
    print(f"Total Requests: {NUM_REQUESTS}")
    print(f"Total Time: {total_time:.2f} seconds")
    print(f"Average Response Time: {avg_time:.2f} ms")
    print(f"Max Response Time: {max_time:.2f} ms")
    print(f"95th Percentile: {p95_time:.2f} ms")
    
    if max_time < 200:
        print("✅ SUCCESS: All requests responded in under 200ms.")
    else:
        print("❌ FAILED: Some requests took longer than 200ms.")

if __name__ == "__main__":
    run_load_test()