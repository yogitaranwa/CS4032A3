#!/usr/bin/env bash
# Build and deploy the whole system on a local k3d cluster. Usage: scripts/up.sh [cluster-storage]
# "cluster-storage" stops after the cluster, images and object storage (used by the labelling demo).
set -euo pipefail
cd "$(dirname "$0")/.."
STOP_AFTER="${1:-all}"
CLUSTER=cca

for bin in docker k3d kubectl openssl python3; do
  command -v "$bin" >/dev/null || { echo "missing required tool: $bin" >&2; exit 1; }
done

if ! k3d cluster list 2>/dev/null | grep -q "^${CLUSTER} "; then
  k3d cluster create -c cluster/k3d.yaml
fi
kubectl config use-context "k3d-${CLUSTER}" >/dev/null
kubectl wait --for=condition=Ready node --all --timeout=180s

echo "== building images"
docker build -q -f service/Dockerfile -t command-parser:1.0.0 .
docker build -q -f worker/Dockerfile -t cca-worker:1.0.0 .
k3d image import -c "$CLUSTER" command-parser:1.0.0 cca-worker:1.0.0

echo "== namespaces, secrets, object storage"
kubectl apply -f k8s/00-namespaces.yaml
scripts/secrets.sh
kubectl apply -f k8s/data/seaweedfs.yaml
kubectl -n data rollout status deploy/seaweedfs --timeout=300s

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q boto3==1.35.30
.venv/bin/python scripts/s3tool.py init
[ "$STOP_AFTER" = "cluster-storage" ] && { echo "cluster and storage ready"; exit 0; }

echo "== models"
scripts/fetch_models.sh
for v in v1 v2; do
  if [ -d "out/models/$v" ]; then .venv/bin/python scripts/s3tool.py put-dir "out/models/$v" models "$v"; fi
done

echo "== application"
kubectl apply -f k8s/app/
kubectl -n app rollout status deploy/parser --timeout=600s || {
  echo "Pods are not Ready: is the model in s3://models/v1/ ? (make train + publish, or a GitHub Release named 'models')" >&2
  kubectl -n app get pods; exit 1; }
echo "ready: curl -s localhost:8080/parse -H 'content-type: application/json' -d '{\"text\":\"what is the weather in london\"}'"
