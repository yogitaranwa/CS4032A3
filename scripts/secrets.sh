#!/usr/bin/env bash
# Create the S3 credentials at deploy time. They are generated randomly, kept in .secrets/ (git-ignored)
# and handed to the cluster as Kubernetes Secrets. Nothing secret is ever committed.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .secrets
if [ ! -f .secrets/s3.env ]; then
  umask 077
  {
    echo "AWS_ACCESS_KEY_ID=$(openssl rand -hex 10)"
    echo "AWS_SECRET_ACCESS_KEY=$(openssl rand -hex 24)"
  } > .secrets/s3.env
fi
# shellcheck disable=SC1091
set -a; . .secrets/s3.env; set +a

kubectl -n data create secret generic seaweedfs-s3-config \
  --from-literal=s3.json="{\"identities\":[{\"name\":\"admin\",\"credentials\":[{\"accessKey\":\"${AWS_ACCESS_KEY_ID}\",\"secretKey\":\"${AWS_SECRET_ACCESS_KEY}\"}],\"actions\":[\"Admin\",\"Read\",\"Write\",\"List\",\"Tagging\"]}]}" \
  --dry-run=client -o yaml | kubectl apply -f -
for ns in pipeline app; do
  kubectl -n "$ns" create secret generic s3-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
done
