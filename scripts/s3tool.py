"""Small S3 helper for the host scripts (credentials come from the environment or .secrets/s3.env).

  s3tool.py init                       create buckets datasets and models; upload pool, prompt, datasets/ (if present)
  s3tool.py put-dir DIR BUCKET PREFIX  upload every file in DIR (non-recursive) to s3://BUCKET/PREFIX/
  s3tool.py get-dir BUCKET PREFIX DIR  download s3://BUCKET/PREFIX/* into DIR
  s3tool.py ls BUCKET [PREFIX]
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_env():
    env_file = ROOT / ".secrets" / "s3.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    os.environ.setdefault("S3_ENDPOINT", "http://localhost:8333")


def client():
    from worker.storage import s3_client
    c = s3_client()
    for _ in range(60):  # the k3d load balancer needs a few seconds after SeaweedFS starts
        try:
            c.list_buckets()
            return c
        except Exception:
            time.sleep(2)
    sys.exit("object storage not reachable at " + os.environ["S3_ENDPOINT"])


def put_dir(c, d, bucket, prefix):
    for p in sorted(Path(d).iterdir()):
        if p.is_file():
            key = f"{prefix.strip('/')}/{p.name}"
            c.upload_file(str(p), bucket, key)
            print(f"uploaded {p} -> s3://{bucket}/{key}")


def main():
    load_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    c = client()
    if cmd == "init":
        existing = {b["Name"] for b in c.list_buckets()["Buckets"]}
        for b in ("datasets", "models"):
            if b not in existing:
                c.create_bucket(Bucket=b)
            print("bucket", b, "ready")
        c.upload_file(str(ROOT / "data" / "commands_pool.jsonl"), "datasets", "commands_pool.jsonl")
        print("uploaded s3://datasets/commands_pool.jsonl")
        c.upload_file(str(ROOT / "prompts" / "teacher_prompt.txt"), "datasets", "prompts/teacher_prompt.txt")
        for sub, prefix in (("datasets/teacher", "teacher"), ("datasets/v1", "v1")):
            if (ROOT / sub).is_dir():
                put_dir(c, ROOT / sub, "datasets", prefix)
    elif cmd == "put-dir":
        put_dir(c, sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "get-dir":
        bucket, prefix, dest = sys.argv[2], sys.argv[3].strip("/") + "/", Path(sys.argv[4])
        dest.mkdir(parents=True, exist_ok=True)
        for page in c.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for o in page.get("Contents", []):
                c.download_file(bucket, o["Key"], str(dest / o["Key"][len(prefix):]))
    elif cmd == "ls":
        prefix = sys.argv[3] if len(sys.argv) > 3 else ""
        for page in c.get_paginator("list_objects_v2").paginate(Bucket=sys.argv[2], Prefix=prefix):
            for o in page.get("Contents", []):
                print(o["Size"], o["Key"])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
