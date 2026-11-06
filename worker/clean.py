"""Clean the teacher shard outputs into datasets/v1/train.jsonl (+ train.sha256).

Rejection rules, applied in this order to every record (a record is counted under the FIRST rule it breaks):
  (a) teacher_raw is not valid JSON
  (b) the JSON is not an object with exactly the keys intent, date, time, place
  (c) intent is not one of the eight intents in data/schema.json
  (d) a slot (date, time, place) is neither null nor a non-empty text that appears in the command
  (e) duplicate command text: among the records that passed (a)-(d), keep the smallest id

input = rejected_a + rejected_b + rejected_c + rejected_d + duplicates + kept

Before cleaning, the shards are checked against the pool: every pool id must appear in exactly one shard
(no gaps, no repeats). Use --allow-partial only for smoke tests.

Output is deterministic: records in id order, fixed JSON formatting, so the SHA-256 is reproducible.

Usage
  python worker/clean.py --shards out/teacher --out datasets/v1
  python worker/clean.py --s3-endpoint http://localhost:8333 --shards s3://datasets/teacher/ --out s3://datasets/v1/
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

KEYS = {"intent", "date", "time", "place"}
SLOTS = ("date", "time", "place")


def load_intents(schema_path=ROOT / "data" / "schema.json"):
    return set(json.loads(Path(schema_path).read_text(encoding="utf-8"))["intents"])


def classify(record, intents):
    """Return None if the record is acceptable, else 'a'|'b'|'c'|'d'."""
    try:
        obj = json.loads(record["teacher_raw"].strip())
    except (json.JSONDecodeError, AttributeError, TypeError):
        return "a"
    if not isinstance(obj, dict) or set(obj.keys()) != KEYS:
        return "b"
    if not isinstance(obj["intent"], str) or obj["intent"] not in intents:
        return "c"
    command = record["text"]
    for slot in SLOTS:
        v = obj[slot]
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip() or v not in command:
            return "d"
    return None


def clean(records, intents):
    """records: all shard records. Returns (kept_records_in_id_order, counts)."""
    counts = {"input": len(records), "rejected_a_invalid_json": 0, "rejected_b_keys": 0,
              "rejected_c_intent": 0, "rejected_d_slot": 0, "duplicates": 0, "kept": 0}
    names = {"a": "rejected_a_invalid_json", "b": "rejected_b_keys", "c": "rejected_c_intent", "d": "rejected_d_slot"}
    passed = []
    for rec in records:
        bad = classify(rec, intents)
        if bad:
            counts[names[bad]] += 1
        else:
            passed.append(rec)
    passed.sort(key=lambda r: r["id"])
    seen, kept = set(), []
    for rec in passed:
        key = rec["text"].strip()
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        kept.append(rec)
    counts["kept"] = len(kept)
    total = sum(v for k, v in counts.items() if k != "input")
    assert total == counts["input"], counts
    return kept, counts


def check_coverage(pool_ids, shard_records, allow_partial=False):
    ids = [r["id"] for r in shard_records]
    repeated = sorted({i for i in ids if ids.count(i) > 1}) if len(ids) != len(set(ids)) else []
    missing = sorted(set(pool_ids) - set(ids))
    extra = sorted(set(ids) - set(pool_ids))
    problems = []
    if repeated:
        problems.append(f"{len(repeated)} ids appear more than once, e.g. {repeated[:3]}")
    if extra:
        problems.append(f"{len(extra)} ids are not in the pool, e.g. {extra[:3]}")
    if missing and not allow_partial:
        problems.append(f"{len(missing)} pool ids missing from the shards, e.g. {missing[:3]}")
    return problems


def render_train(kept):
    return "".join(
        json.dumps({"id": r["id"], "text": r["text"], "teacher_raw": r["teacher_raw"]}, ensure_ascii=False) + "\n"
        for r in kept)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl_text(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shards", default="out/teacher", help="directory with shard-N.jsonl, or s3://bucket/prefix/")
    ap.add_argument("--out", default="datasets/v1", help="output directory, or s3://bucket/prefix/")
    ap.add_argument("--pool", default=str(ROOT / "data" / "commands_pool.jsonl"))
    ap.add_argument("--schema", default=str(ROOT / "data" / "schema.json"))
    ap.add_argument("--s3-endpoint", default=None)
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--counts-out", default=None, help="also write the counts JSON here")
    a = ap.parse_args(argv)

    from worker.storage import Store, parse_uri

    shards = []
    if a.shards.startswith("s3://"):
        bucket, prefix = parse_uri(a.shards)
        store = Store(a.s3_endpoint)
        for key in store.list_keys(bucket, prefix):
            if key.endswith(".jsonl") and "shard-" in key:
                shards += read_jsonl_text(store.get_text(bucket, key))
    else:
        for p in sorted(Path(a.shards).glob("shard-*.jsonl")):
            shards += read_jsonl_text(p.read_text(encoding="utf-8"))
    if not shards:
        sys.exit("no shard records found")

    pool_ids = [json.loads(line)["id"] for line in open(a.pool, encoding="utf-8") if line.strip()]
    problems = check_coverage(pool_ids, shards, a.allow_partial)
    if problems:
        sys.exit("shard coverage check failed: " + "; ".join(problems))

    kept, counts = clean(shards, load_intents(a.schema))
    train = render_train(kept)
    digest = sha256_text(train)
    sha_line = f"{digest}  train.jsonl\n"
    counts_text = json.dumps(counts, indent=2) + "\n"

    if a.out.startswith("s3://"):
        bucket, prefix = parse_uri(a.out)
        prefix = prefix.strip("/")
        store = Store(a.s3_endpoint)
        store.put_text(bucket, f"{prefix}/train.jsonl", train)
        store.put_text(bucket, f"{prefix}/train.sha256", sha_line)
        store.put_text(bucket, f"{prefix}/counts.json", counts_text)
    else:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "train.jsonl").write_text(train, encoding="utf-8")
        (out / "train.sha256").write_text(sha_line, encoding="utf-8")
        (out / "counts.json").write_text(counts_text, encoding="utf-8")
    if a.counts_out:
        Path(a.counts_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.counts_out).write_text(counts_text, encoding="utf-8")
    print(counts_text, end="")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
