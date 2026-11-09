#!/usr/bin/env bash
# Task 4 and Task 7 measurements on a running cluster (make up first). Everything is written to results/.
# Every number in the report must come from these files. Takes about 45 minutes.
#   scripts/evidence.sh            run all scenarios
#   scripts/evidence.sh lb coldstart   run selected ones (readiness lb recovery rollout coldstart hpa inventory)
set -uo pipefail
cd "$(dirname "$0")/.."
HOST=http://localhost:8080
R=results
mkdir -p $R/k8s
[ -x .venv/bin/locust ] || { [ -d .venv ] || python3 -m venv .venv; .venv/bin/pip install -q locust==2.32.0; }
LOCUST=.venv/bin/locust
SCENARIOS=("$@"); [ ${#SCENARIOS[@]} -eq 0 ] && SCENARIOS=(inventory readiness lb recovery rollout coldstart hpa)

ready()   { kubectl -n app get deploy parser -o jsonpath='{.status.readyReplicas}' 2>/dev/null; }
wait_ready() { # wait_ready N [timeout seconds]
  local n=$1 t=${2:-600} s=$SECONDS
  while [ "$(ready)" != "$n" ] || [ "$(kubectl -n app get deploy parser -o jsonpath='{.status.replicas}')" != "$n" ]; do
    [ $((SECONDS - s)) -gt "$t" ] && { echo "timeout waiting for $n ready replicas" >&2; return 1; }
    sleep 2
  done
}
pin_replicas() { # keep the HPA from changing the replica count during a scenario
  kubectl -n app patch hpa parser --type merge -p "{\"spec\":{\"minReplicas\":$1}}" >/dev/null
  kubectl -n app scale deploy parser --replicas="$1" >/dev/null
  wait_ready "$1"
}
locust_bg() { # locust_bg NAME RUNTIME   (the standard command, only --run-time and the output paths differ)
  mkdir -p "$R/$1"
  LOADTEST_HEADERS_OUT="$R/$1/loadtest_headers.json" $LOCUST -f tools/locustfile.py --headless --users 4 \
    --spawn-rate 4 --run-time "$2" --host $HOST --csv "$R/$1/loadtest" > "$R/$1/locust.log" 2>&1 &
  LOCUST_PID=$!
}
sample_top() { # sample_top FILE SECONDS INTERVAL   kubectl top pods while the load runs
  local end=$((SECONDS + $2))
  while [ $SECONDS -lt $end ]; do { date -u +%FT%TZ; kubectl -n app top pods 2>&1; echo; } >> "$1"; sleep "$3"; done
}
failed_pct() { python3 - "$1" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
agg = [r for r in rows if r["Name"] == "Aggregated"][0]
n, f = int(agg["Request Count"]), int(agg["Failure Count"])
print(f"requests={n} failures={f} failed_pct={100*f/max(n,1):.3f}")
PY
}

has() { for s in "${SCENARIOS[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }

if has inventory; then
  { echo "## kubectl get all,ingress,hpa -n app"; kubectl -n app get all,ingress,hpa -o wide
    echo; echo "## resources, probes"; kubectl -n app get deploy parser -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}{.spec.template.spec.containers[0].livenessProbe}{"\n"}{.spec.template.spec.containers[0].readinessProbe}{"\n"}'
    echo; echo "## nodes (single-node cluster limitation)"; kubectl get nodes -o wide
    echo; echo "## namespaces"; kubectl get ns
    echo; echo "## /parse through the ingress"; curl -si -X POST $HOST/parse -H 'content-type: application/json' -d '{"text":"what is the weather in london"}'
  } > $R/k8s/inventory.txt 2>&1
fi

if has readiness; then
  pin_replicas 2
  : > $R/k8s/readiness.txt
  kubectl -n app delete pods -l app=parser --wait=false >/dev/null
  for _ in $(seq 1 90); do
    { date -u +%T; kubectl -n app get pods -l app=parser --no-headers; echo "endpoints: $(kubectl -n app get endpoints parser -o jsonpath='{.subsets[*].addresses[*].ip}')"; echo; } >> $R/k8s/readiness.txt
    sleep 1
  done
  wait_ready 2
fi

if has lb; then   # Task 4 step 8 and the Task 7 standard run
  pin_replicas 2
  rm -f $R/standard/top.txt; mkdir -p $R/standard
  locust_bg standard 2m
  sample_top $R/standard/top.txt 125 10
  wait $LOCUST_PID
  failed_pct $R/standard/loadtest_stats.csv | tee $R/standard/failed.txt
  cat $R/standard/loadtest_headers.json
fi

if has recovery; then
  pin_replicas 2
  mkdir -p $R/recovery
  locust_bg recovery 3m
  sleep 40
  victim=$(kubectl -n app get pods -l app=parser -o name | head -1)
  { date -u +%T; echo "deleting $victim"; } > $R/recovery/timeline.txt
  kubectl -n app delete "$victim" --wait=false >> $R/recovery/timeline.txt
  for _ in $(seq 1 60); do
    echo "$(date -u +%T) ready=$(ready) $(kubectl -n app get pods -l app=parser --no-headers | awk '{print $1":"$2":"$3}' | tr '\n' ' ')" >> $R/recovery/timeline.txt
    sleep 3
  done
  wait $LOCUST_PID
  failed_pct $R/recovery/loadtest_stats.csv | tee $R/recovery/failed.txt
  echo "final ready replicas: $(ready)" | tee -a $R/recovery/timeline.txt
fi

if has rollout; then
  pin_replicas 2
  mkdir -p $R/rollout
  locust_bg rollout 4m
  sleep 40
  kubectl -n app set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/ > $R/rollout/commands.txt
  kubectl -n app rollout status deploy/parser --timeout=600s >> $R/rollout/commands.txt
  echo "--- after update: version from the ingress" >> $R/rollout/commands.txt
  for _ in 1 2 3 4 5 6; do curl -si -X POST $HOST/parse -H 'content-type: application/json' -d '{"text":"what time is it"}' | grep -i '^x-model-version' >> $R/rollout/commands.txt; done
  sleep 20
  kubectl -n app rollout undo deploy/parser >> $R/rollout/commands.txt
  kubectl -n app rollout status deploy/parser --timeout=600s >> $R/rollout/commands.txt
  echo "--- after rollback: version from the ingress" >> $R/rollout/commands.txt
  for _ in 1 2 3 4 5 6 7 8; do curl -si -X POST $HOST/parse -H 'content-type: application/json' -d '{"text":"what time is it"}' | grep -i '^x-model-version' >> $R/rollout/commands.txt; done
  kubectl -n app get deploy parser -o jsonpath='{.spec.template.spec.containers[0].env}' >> $R/rollout/commands.txt
  wait $LOCUST_PID
  failed_pct $R/rollout/loadtest_stats.csv | tee $R/rollout/failed.txt
  cat $R/rollout/loadtest_headers.json
fi

if has coldstart; then
  pin_replicas 2
  mkdir -p $R/coldstart; : > $R/coldstart/times.txt
  for run in 1 2 3; do
    kubectl -n app delete pods -l app=parser --wait=false >/dev/null
    sleep 3
    wait_ready 2
    kubectl -n app get pods -l app=parser -o json | python3 -c '
import json, sys
from datetime import datetime
def t(s): return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
for p in json.load(sys.stdin)["items"]:
    ready = [c for c in p["status"]["conditions"] if c["type"] == "Ready" and c["status"] == "True"]
    if ready:
        print(p["metadata"]["name"], (t(ready[0]["lastTransitionTime"]) - t(p["metadata"]["creationTimestamp"])).total_seconds())
' | sed "s/^/run$run /" >> $R/coldstart/times.txt
    for p in $(kubectl -n app get pods -l app=parser -o name); do
      echo "== run $run $p"; kubectl -n app logs "$p" | grep -E "downloading|downloaded|loaded"
    done >> $R/coldstart/logs.txt
  done
  python3 - <<'PY' | tee $R/coldstart/summary.json
import json, statistics
runs = {}
for line in open("results/coldstart/times.txt"):
    run, _, sec = line.split()
    runs.setdefault(run, []).append(float(sec))
per_run = {r: round(max(v), 1) for r, v in runs.items()}   # a run is over when its last Pod is Ready
print(json.dumps({"per_run_seconds_slowest_pod": per_run,
                  "median_seconds": statistics.median(per_run.values()),
                  "median_all_pods_seconds": statistics.median(x for v in runs.values() for x in v)}, indent=2))
PY
fi

if has hpa; then
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":1}}' >/dev/null
  kubectl -n app scale deploy parser --replicas=1 >/dev/null
  wait_ready 1
  sleep 90   # let the autoscaler settle at 1 replica before the load starts
  mkdir -p $R/hpa; : > $R/hpa/timeline.txt
  locust_bg hpa 3m
  end=$((SECONDS + 600))
  while [ $SECONDS -lt $end ]; do
    echo "$(date -u +%T) $(kubectl -n app get hpa parser --no-headers | tr -s ' ') | ready=$(ready) $(kubectl -n app top pods --no-headers 2>/dev/null | tr -s ' ' | tr '\n' ';')" >> $R/hpa/timeline.txt
    sleep 10
  done
  wait $LOCUST_PID 2>/dev/null
  kubectl -n app describe hpa parser > $R/hpa/describe.txt
fi

python3 scripts/summarize.py || true
