import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.summarize import cost, cost_md  # noqa: E402


def test_score_gate_passes_on_gold_and_fails_on_garbage(tmp_path):
    gold = [json.loads(line) for line in open(ROOT / "data" / "validation.jsonl")][:20]
    good = tmp_path / "good.jsonl"
    bad = tmp_path / "bad.jsonl"
    good.write_text("".join(json.dumps({"id": g["id"], "prediction": json.dumps({k: g[k] for k in ("intent", "date", "time", "place")})}) + "\n" for g in gold))
    bad.write_text("".join(json.dumps({"id": g["id"], "prediction": "nonsense"}) + "\n" for g in gold))
    gold_file = tmp_path / "gold.jsonl"
    gold_file.write_text("".join(json.dumps(g) + "\n" for g in gold))
    cmd = [sys.executable, str(ROOT / "tools" / "score.py")]
    assert subprocess.run(cmd + [str(good), str(gold_file), "--min-validity", "95"], capture_output=True).returncode == 0
    assert subprocess.run(cmd + [str(bad), str(gold_file), "--min-validity", "95"], capture_output=True).returncode == 1


def test_cost_formula():
    rc = json.loads((ROOT / "data" / "rate_card.json").read_text())
    dep = {"spec": {"replicas": 2, "template": {"spec": {"containers": [{"resources": {"limits": {"cpu": "1", "memory": "1Gi"}}}]}}}}
    x = cost(rc, dep, {"Requests/s": "10.0"})
    assert abs(x["hourly"] - 2 * (3.5 + 0.45)) < 1e-9
    assert abs(x["per_1000"] - 7.9 / 36000 * 1000) < 1e-9
    assert "per 1,000" in cost_md(x)
