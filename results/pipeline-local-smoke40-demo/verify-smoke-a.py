import json
import pathlib
import sys

root = pathlib.Path.cwd()
pool = [json.loads(line) for line in open(root / "data/commands_pool.jsonl") if line.strip()][:40]
d = pathlib.Path(sys.argv[1])
fs = sorted(d.glob("shard-*.jsonl"))
print("files:", [f.name for f in fs])
shards = {}
for f in fs:
    idx = int(f.stem.split("-")[1])
    shards[idx] = [json.loads(line) for line in f.open() if line.strip()]
print("counts:", {k: len(v) for k, v in shards.items()})
exp = {i: pool[i::2] for i in (0, 1)}
ids_ok = {k: [r["id"] for r in shards.get(k, [])] == [r["id"] for r in exp[k]] for k in (0, 1)}
text_ok = {k: [r["text"] for r in shards.get(k, [])] == [r["text"] for r in exp[k]] for k in (0, 1)}
print("ids_match:", ids_ok)
print("text_match:", text_ok)
allids = [r["id"] for v in shards.values() for r in v]
print("total:", len(allids), "unique:", len(set(allids)), "eq_pool40:", sorted(allids) == sorted(r["id"] for r in pool))
ok = (len(fs) == 2 and all(len(v) == 20 for v in shards.values()) and len(allids) == 40
      and len(set(allids)) == 40 and all(ids_ok.values()) and all(text_ok.values()))
print("VERIFY:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
