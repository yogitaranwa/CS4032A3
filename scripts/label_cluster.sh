#!/usr/bin/env bash
# Run the labelling workers INSIDE the cluster (namespace pipeline): Ollama + an Indexed Job of SHARD_COUNT workers.
# Needs a running cluster (make up). Defaults label only the first LIMIT=40 commands as a demonstration;
# use LIMIT=0 SHARD_COUNT=N for the full 3,000 (hours on a CPU). Output goes to s3://datasets/$OUT_PREFIX/.
set -euo pipefail
cd "$(dirname "$0")/.."
export SHARD_COUNT="${SHARD_COUNT:-2}" LIMIT="${LIMIT:-40}" OUT_PREFIX="${OUT_PREFIX:-teacher-demo}"
kubectl apply -f k8s/pipeline/ollama.yaml
mkdir -p results/pipeline
kubectl -n pipeline rollout status deploy/ollama --timeout=2400s || {
  kubectl -n pipeline describe pod -l app=ollama > results/pipeline/ollama-describe.txt || true
  kubectl -n pipeline logs deploy/ollama --tail=60 > results/pipeline/ollama-log.txt || true
  tail -30 results/pipeline/ollama-log.txt; exit 1; }
kubectl -n pipeline delete job teacher-workers --ignore-not-found
envsubst < k8s/pipeline/worker-job.yaml | kubectl apply -f -
kubectl -n pipeline wait --for=condition=complete job/teacher-workers --timeout=5400s
mkdir -p results/pipeline
kubectl -n pipeline get pods -o wide | tee results/pipeline/pods.txt
for i in $(seq 0 $((SHARD_COUNT - 1))); do
  kubectl -n pipeline logs -l batch.kubernetes.io/job-completion-index="$i",app=teacher-worker --tail=20 \
    > "results/pipeline/worker-$i.log" || true
done
.venv/bin/python scripts/s3tool.py ls datasets "$OUT_PREFIX/" | tee results/pipeline/shard-objects.txt
