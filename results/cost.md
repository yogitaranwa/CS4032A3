# Cost estimate for 1,000 requests (estimated, no real charge)

Rates from data/rate_card.json: 3.5 INR per vCPU-hour, 0.45 INR per GiB-hour.
Billing rule: every replica is billed for its CPU limit and memory limit for every hour it runs.

1. Limits per replica (k8s/app/deployment.yaml): 1.0 vCPU, 1.0 GiB
2. Hourly cost per replica = 1.0 x 3.5 + 1.0 x 0.45 = 3.9500 INR
3. Running replicas: 2, hourly cost of all replicas = 2 x 3.9500 = 7.9000 INR
4. Measured throughput (results/standard/loadtest_stats.csv): 1.003 requests/s
5. Requests served per hour = 1.003 x 3600 = 3609.9
6. Cost per 1,000 requests = 7.9000 / 3609.9 x 1000 = **2.1884 INR**
