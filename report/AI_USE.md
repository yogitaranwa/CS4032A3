# AI use

Author: Yogita Kumari (230101091). Course CS4032 Assessment 3

## Tools used

| Tool | Used for |
|---|---|
| phi3.5 (Phi-3.5-mini-instruct) on Ollama | The teacher model, as the handout requires: it labels the commands (temperature 0, seed 42). Its replies are stored exactly as generated. |
| EleutherAI/pythia-70m | The student model that is fine-tuned. |

No paid API and no other model produced training labels. Validation data was never used for training. The prompt
examples in `prompts/teacher_prompt.txt` were written by hand and are not taken from `validation.jsonl`

## How the AI output was checked

- Unit tests (`tests/`) cover the sharding, the five rejection rules, the reproducible checksum, the service endpoints,
  schema validation and fault injection, the Kubernetes manifests and the subnet and NACL answers.
- `tools/nacl_sim.py --check` passes on the sample packets, and extra packets were tested by hand in `tests/test_network.py`.
- The subnet table in `network/subnets.md` is recomputed with Python's `ipaddress` module in a test.
- A short training run on a few records was executed to check the loss file, the model files and the checksum.
- Every measured number in the report comes from files in `results/` that the workflows produced. Nothing was filled in by hand.
- The secret scan (gitleaks) runs in CI and reports nothing.

## What the AI did not do

- It did not choose the teacher, the student, the cluster tools or the limits; the handout fixed them.
- It did not edit teacher replies, and no label was written by hand.