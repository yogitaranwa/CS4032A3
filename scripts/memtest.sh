#!/usr/bin/env bash
# Task 3: 50 sequential requests to the container limited to 1 CPU and 1 GiB. Reports peak memory and OOM status.
# Uses a throw-away SeaweedFS container as the object store (model v1 from out/models/v1), so no cluster is needed.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=results/memtest; mkdir -p $OUT
NET=memtest-net
AK=$(openssl rand -hex 8); SK=$(openssl rand -hex 16)
cleanup() { docker rm -f memtest-s3 memtest-svc >/dev/null 2>&1 || true; docker network rm $NET >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
scripts/fetch_models.sh
[ -f out/models/v1/model.safetensors ] || { echo "no model v1 available" >&2; exit 1; }
docker build -q -f service/Dockerfile -t command-parser:1.0.0 .
docker image ls command-parser:1.0.0 --format 'image size: {{.Size}}' | tee $OUT/image_size.txt
docker image inspect command-parser:1.0.0 --format '{{.Size}}' > $OUT/image_size_bytes.txt
test "$(cat $OUT/image_size_bytes.txt)" -le 2000000000 && echo "image <= 2 GB" | tee -a $OUT/image_size.txt

docker network create $NET >/dev/null
mkdir -p .secrets
printf '{"identities":[{"name":"admin","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","Write","List"]}]}' "$AK" "$SK" > .secrets/memtest-s3.json
docker run -d --name memtest-s3 --network $NET -p 18333:8333 -v "$PWD/.secrets/memtest-s3.json:/s3.json:ro" \
  chrislusf/seaweedfs:3.80 server -dir=/data -s3 -s3.port=8333 -s3.config=/s3.json >/dev/null
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q boto3==1.35.30
export AWS_ACCESS_KEY_ID=$AK AWS_SECRET_ACCESS_KEY=$SK S3_ENDPOINT=http://localhost:18333
.venv/bin/python - <<'PY'
import boto3, os, time
from botocore.config import Config
c = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1", config=Config(s3={"addressing_style": "path"}))
for _ in range(60):
    try: c.list_buckets(); break
    except Exception: time.sleep(2)
c.create_bucket(Bucket="models")
PY
.venv/bin/python scripts/s3tool.py put-dir out/models/v1 models v1

docker run -d --name memtest-svc --network $NET --cpus 1 --memory 1g --memory-swap 1g -p 18000:8000 \
  -e MODEL_URI=s3://models/v1/ -e MODEL_VERSION=v1 -e S3_ENDPOINT=http://memtest-s3:8333 -e MAX_NEW_TOKENS=64 \
  -e AWS_ACCESS_KEY_ID=$AK -e AWS_SECRET_ACCESS_KEY=$SK command-parser:1.0.0 >/dev/null
for _ in $(seq 1 120); do curl -fs localhost:18000/readyz >/dev/null && break; sleep 2; done
curl -fs localhost:18000/readyz >/dev/null || { docker logs memtest-svc | tail -30; exit 1; }
docker logs memtest-svc 2>&1 | grep -E "downloading|downloaded|loaded" | tee $OUT/startup_log.txt

: > $OUT/docker_stats.txt
( while true; do docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' memtest-svc >> $OUT/docker_stats.txt 2>/dev/null || break; sleep 0.5; done ) &
SAMPLER=$!
ok=0; invalid=0; other=0
: > $OUT/requests.log
for i in $(seq 1 50); do
  text=$(sed -n "${i}p" data/validation.jsonl | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["text"])')
  payload=$(python3 -c 'import json,sys;print(json.dumps({"text":sys.argv[1]}))' "$text")
  code=$(curl -s --max-time 30 -o /tmp/memtest_body.txt -w '%{http_code}' -X POST localhost:18000/parse \
    -H 'content-type: application/json' -d "$payload") || code=000
  body=$(cat /tmp/memtest_body.txt 2>/dev/null || true)
  echo "request $i code=$code text=[$text] body=$body" >> $OUT/requests.log
  if [ "$code" = "200" ]; then
    ok=$((ok + 1))
  elif [ "$code" = "500" ] && [ "$body" = '{"error":"invalid_model_output"}' ]; then
    # the service answered correctly: the untrained-quality student produced output that fails schema validation
    invalid=$((invalid + 1)); echo "NOTE request $i: HTTP 500 invalid_model_output for [$text]"
  else
    other=$((other + 1)); echo "FAIL request $i: HTTP $code body=$body text=[$text]"
  fi
done
kill $SAMPLER 2>/dev/null || true
oom=$(docker inspect memtest-svc --format '{{.State.OOMKilled}}')
peak=$(python3 - <<'PY'
import re
best = 0.0
for line in open("results/memtest/docker_stats.txt"):
    m = re.match(r"([\d.]+)(KiB|MiB|GiB)", line)
    if m:
        v = float(m.group(1)) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[m.group(2)]
        best = max(best, v)
print(f"{best:.1f} MiB")
PY
)
{ echo "requests completed: $((ok + invalid)) / 50 (HTTP 200: $ok, HTTP 500 invalid_model_output: $invalid, other failures: $other)"; echo "OOMKilled: $oom"; echo "peak memory (docker stats, limit 1 GiB): $peak"
  echo "limits: --cpus 1 --memory 1g"; } | tee $OUT/summary.txt
rm -f .secrets/memtest-s3.json
docker logs memtest-svc 2>&1 | tail -20 > $OUT/service_log_tail.txt
[ "$other" = 0 ] && [ "$oom" = false ]
