"""Score the teacher on validation.jsonl with the same prompt and settings as Task 1.

  python eval/teacher_predict.py --out results/teacher_validation_predictions.jsonl
The raw reply is stored exactly as generated.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worker import teacher  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "validation.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    template = teacher.load_prompt()
    rows = [json.loads(line) for line in open(a.data, encoding="utf-8") if line.strip()]
    if a.limit:
        rows = rows[:a.limit]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for n, r in enumerate(rows, 1):
            f.write(json.dumps({"id": r["id"], "prediction": teacher.ask(r["text"], template)}, ensure_ascii=False) + "\n")
            f.flush()
            if n % 10 == 0:
                print(f"{n}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
