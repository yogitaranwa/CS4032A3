"""Run a causal LM on validation commands and write predictions for tools/score.py.

  python eval/predict.py --model out/models/v1 --data data/validation.jsonl --out results/student_v1_predictions.jsonl
  python eval/predict.py --model EleutherAI/pythia-70m ...     # the original, untrained model

Output lines: {"id": "V001", "prediction": "<raw model text>"}
Uses greedy decoding with the same prompt prefix, stop rule and token limit as the service.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service.app.model import build_prompt, make_loop_guard  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="local model dir or Hugging Face id")
    ap.add_argument("--data", default=str(ROOT / "data" / "validation.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--loop-guard-ngram", type=int, default=6, help="same as the service LOOP_GUARD_NGRAM; 0 disables")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(a.threads)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model).eval()
    rows = [json.loads(line) for line in open(a.data, encoding="utf-8") if line.strip()]
    if a.limit:
        rows = rows[:a.limit]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f, torch.inference_mode():
        for r in rows:
            enc = tok(build_prompt(r["text"]), return_tensors="pt", truncation=True, max_length=256)
            guard = make_loop_guard(enc["input_ids"].shape[1], a.loop_guard_ngram, tok)
            out = model.generate(**enc, max_new_tokens=a.max_new_tokens, do_sample=False, logits_processor=guard,
                                 pad_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id)
            text = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
            f.write(json.dumps({"id": r["id"], "prediction": text.split("\n")[0].strip()}, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} predictions to {a.out}")


if __name__ == "__main__":
    main()
