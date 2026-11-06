"""Sharded teacher-labelling worker.

Environment
  SHARD_INDEX   this worker's shard, counting from 0
  SHARD_COUNT   total number of shards
  POOL_FILE     commands_pool.jsonl (default data/commands_pool.jsonl)
  S3_ENDPOINT   if set, the shard object is written to s3://$S3_BUCKET/$OUT_PREFIX/shard-N.jsonl
                otherwise to $OUT_ROOT/$OUT_PREFIX/shard-N.jsonl (default out/teacher/shard-N.jsonl)
  OLLAMA_HOST   teacher endpoint (default http://localhost:11434)
  LIMIT         optional: only look at the first LIMIT pool lines (smoke tests only)

A command is handled by this shard when (line number counted from 0) % SHARD_COUNT == SHARD_INDEX.
Output line: {"id": ..., "text": ..., "teacher_raw": "<exact teacher reply>"}
The worker resumes: ids already present in its output are skipped, and the object is rewritten every FLUSH_EVERY records.
"""
import json
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker import teacher  # noqa: E402
from worker.storage import Store  # noqa: E402


def shard_records(lines, shard_index, shard_count):
    """Select the pool records for one shard. `lines` are parsed pool records in file order."""
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError(f"bad shard {shard_index}/{shard_count}")
    return [rec for n, rec in enumerate(lines) if n % shard_count == shard_index]


def read_pool(path, limit=0):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recs.append(json.loads(line))
    return recs[:limit] if limit else recs


def to_jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def main():
    idx = int(os.environ["SHARD_INDEX"])
    count = int(os.environ["SHARD_COUNT"])
    pool = Path(os.environ.get("POOL_FILE", "data/commands_pool.jsonl"))
    limit = int(os.environ.get("LIMIT", "0") or 0)
    bucket = os.environ.get("S3_BUCKET", "datasets")
    prefix = os.environ.get("OUT_PREFIX", "teacher").strip("/")
    flush_every = int(os.environ.get("FLUSH_EVERY", "25"))
    key = f"{prefix}/shard-{idx}.jsonl"

    store = Store(os.environ.get("S3_ENDPOINT") or None, os.environ.get("OUT_ROOT", "out"))

    template = teacher.load_prompt()
    mine = shard_records(read_pool(pool, limit), idx, count)

    done = {}
    try:
        for line in store.get_text(bucket, key).splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["id"]] = r
    except Exception:
        pass

    print(f"shard {idx}/{count}: {len(mine)} commands, {len(done)} already done, output {key}", flush=True)
    t0 = time.time()
    out = []
    for n, rec in enumerate(mine, 1):
        if rec["id"] in done:
            out.append(done[rec["id"]])
            continue
        raw = teacher.ask(rec["text"], template)
        out.append({"id": rec["id"], "text": rec["text"], "teacher_raw": raw})
        if n % flush_every == 0:
            store.put_text(bucket, key, to_jsonl(out))
            print(f"  {n}/{len(mine)} done, {time.time() - t0:.0f}s elapsed", flush=True)
    store.put_text(bucket, key, to_jsonl(out))
    print(f"shard {idx}: wrote {len(out)} records to {key} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
