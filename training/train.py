"""Sequence-level distillation: fine-tune EleutherAI/pythia-70m on the teacher's replies (CPU only).

Each example is "Command: <command>\nJSON: <teacher JSON reply><eos>"; the loss is computed on the reply tokens only.

  python training/train.py --config training/config.yaml [--subset 50] [--variant v2]

Reads only the config file (plus --subset / --variant). Writes:
  <output_root>/<version>/   model + tokenizer + version.json + files.sha256 + model.sha256 (archive checksum)
  <loss_csv>                 one training-loss value per epoch
"""
import argparse
import csv
import json
import random
import sys
from importlib import metadata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPT_TEMPLATE = "Command: {text}\nJSON:"


def build_prompt(text):
    """Inference-time prefix. Training uses exactly this prefix followed by ' <json><eos>'."""
    return PROMPT_TEMPLATE.format(text=text)


def target_text(teacher_raw):
    """The teacher's JSON reply in one fixed layout (parsed and re-serialised, never edited by hand)."""
    return json.dumps(json.loads(teacher_raw.strip()), ensure_ascii=False)


def load_config(path, variant=None, subset=None):
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    variants = cfg.pop("variants", {}) or {}
    version = variant or cfg.get("version", "v1")
    if variant and variant in variants:
        cfg.update(variants[variant])
    cfg["version"] = version
    cfg["subset"] = int(subset) if subset else None
    return cfg


def load_records(cfg):
    path = ROOT / cfg["train_file"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda r: r["id"])
    n = cfg["max_records"]
    if cfg["subset"]:
        n = min(n, cfg["subset"])
    return rows[:n]


def encode_example(tok, rec, max_len):
    prompt_ids = tok(build_prompt(rec["text"]))["input_ids"]
    target_ids = tok(" " + target_text(rec["teacher_raw"]))["input_ids"] + [tok.eos_token_id]
    ids = (prompt_ids + target_ids)[:max_len]
    labels = ([-100] * len(prompt_ids) + target_ids)[:max_len]
    return ids, labels


def collate(batch, pad_id):
    width = max(len(ids) for ids, _ in batch)
    import torch
    input_ids = torch.full((len(batch), width), pad_id, dtype=torch.long)
    labels = torch.full((len(batch), width), -100, dtype=torch.long)
    attn = torch.zeros((len(batch), width), dtype=torch.long)
    for i, (ids, lab) in enumerate(batch):
        input_ids[i, :len(ids)] = torch.tensor(ids)
        labels[i, :len(lab)] = torch.tensor(lab)
        attn[i, :len(ids)] = 1
    return input_ids, attn, labels


def check_versions(cfg):
    for lib, want in cfg.get("library_versions", {}).items():
        if lib == "python":
            have = ".".join(map(str, sys.version_info[:2]))
        else:
            try:
                have = metadata.version(lib)
            except metadata.PackageNotFoundError:
                have = "missing"
        base = have.split("+")[0]
        if base != want and not (lib == "python" and have == want):
            print(f"WARNING: {lib} is {have}, config.yaml pins {want}", file=sys.stderr)


def installed_versions(cfg):
    out = {}
    for lib in cfg.get("library_versions", {}):
        try:
            out[lib] = ".".join(map(str, sys.version_info[:3])) if lib == "python" else metadata.version(lib)
        except metadata.PackageNotFoundError:
            out[lib] = None
    return out


def train(cfg):
    import numpy as np
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup

    seed = cfg["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(False)
    torch.set_num_threads(cfg.get("num_threads", 2))
    check_versions(cfg)

    tok = AutoTokenizer.from_pretrained(cfg["model_name"])
    tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(cfg["model_name"])
    model.train()

    records = load_records(cfg)
    data = [encode_example(tok, r, cfg["max_seq_length"]) for r in records]
    print(f"training on {len(data)} records for {cfg['epochs']} epochs (seed {seed})", flush=True)

    bs = cfg["batch_size"]
    steps_per_epoch = (len(data) + bs - 1) // bs
    total = steps_per_epoch * cfg["epochs"]
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg.get("weight_decay", 0.0))
    sched = get_linear_schedule_with_warmup(opt, int(total * cfg.get("warmup_ratio", 0.0)), total)
    gen = torch.Generator().manual_seed(seed)

    epoch_losses = []
    for epoch in range(1, cfg["epochs"] + 1):
        order = torch.randperm(len(data), generator=gen).tolist()
        loss_sum, tokens = 0.0, 0
        for s in range(0, len(order), bs):
            batch = [data[i] for i in order[s:s + bs]]
            input_ids, attn, labels = collate(batch, tok.pad_token_id)
            out = model(input_ids=input_ids, attention_mask=attn, labels=labels)
            n_tok = int((labels[:, 1:] != -100).sum())
            loss_sum += out.loss.item() * n_tok
            tokens += n_tok
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
        epoch_loss = loss_sum / max(tokens, 1)
        epoch_losses.append(epoch_loss)
        print(f"epoch {epoch}/{cfg['epochs']} train_loss {epoch_loss:.4f}", flush=True)

    loss_path = ROOT / cfg["loss_csv"]
    loss_path.parent.mkdir(parents=True, exist_ok=True)
    with open(loss_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train_loss"])
        for i, v in enumerate(epoch_losses, 1):
            w.writerow([i, f"{v:.6f}"])

    out_dir = ROOT / cfg["output_root"] / cfg["version"]
    model.eval()
    model.save_pretrained(out_dir, safe_serialization=True)
    tok.save_pretrained(out_dir)
    info = {
        "model_version": cfg["version"], "base_model": cfg["model_name"], "records": len(data),
        "epochs": cfg["epochs"], "seed": seed, "learning_rate": cfg["learning_rate"],
        "batch_size": bs, "max_seq_length": cfg["max_seq_length"], "subset": cfg["subset"],
        "final_train_loss": epoch_losses[-1], "libraries": installed_versions(cfg),
        "prompt_template": PROMPT_TEMPLATE,
    }
    (out_dir / "version.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

    from scripts.package_model import package
    package(out_dir, cfg["version"])
    print(f"saved model to {out_dir}")
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "training" / "config.yaml"))
    ap.add_argument("--subset", default=None, help="train on the first N records only (smoke test)")
    ap.add_argument("--variant", default=None, help="v2 = the second model version defined in config.yaml")
    a = ap.parse_args()
    cfg = load_config(a.config, a.variant, a.subset)
    if cfg["subset"]:
        cfg["version"] = f"{cfg['version']}-subset{cfg['subset']}"
    train(cfg)


if __name__ == "__main__":
    main()
