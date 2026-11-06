"""Model download from object storage and generation. torch/transformers are imported lazily."""
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("parser")

PROMPT_TEMPLATE = "Command: {text}\nJSON:"  # must match training/train.py


def banned_next_tokens(generated, n):
    """Tokens that would repeat an n-gram already present in `generated` (the new tokens only, not the prompt).
    Pure python so it can be unit tested without torch. n <= 1 disables the guard."""
    if n <= 1 or len(generated) < n:
        return set()
    ctx = tuple(generated[-(n - 1):])
    banned = set()
    for i in range(len(generated) - n + 1):
        if tuple(generated[i:i + n - 1]) == ctx:
            banned.add(generated[i + n - 1])
    return banned


def banned_word_repeats(generated, structural):
    """Inside a value, a word token must not follow itself, and a word-token bigram must not repeat.
    `structural` is the set of token ids that belong to the JSON frame (braces, quotes, colons, commas, null);
    bigrams made only of those repeat legitimately (`": null, "` appears once per field) so they are exempt."""
    if not generated:
        return set()
    last = generated[-1]
    if last in structural:
        return set()
    banned = {last}
    for i in range(len(generated) - 1):
        if generated[i] == last:
            banned.add(generated[i + 1])
    return banned


def structural_ids(tok):
    ids = getattr(tok, "_structural_ids", None)
    if ids is None:
        ids = set()
        for i in range(len(tok)):
            piece = tok.decode([i])
            if any(c in piece for c in '{}":,') or piece.strip() == "null":
                ids.add(i)
        tok._structural_ids = ids
    return ids


def inside_string(text):
    """True when `text` (the model's output so far) ends inside an open JSON string. Escaped quotes are skipped."""
    return len(text.replace('\\"', "")) - len(text.replace('\\"', "").replace('"', "")) & 1 == 1


def stray_quote_ids(tok):
    """Token ids that start with a space and contain a quote (` "`, ` ",`). In a flat frame that only
    ever opens a value, so inside an open string it can only produce invalid JSON (`"zach "zain`)."""
    ids = getattr(tok, "_stray_quote_ids", None)
    if ids is None:
        ids = set()
        for i in range(len(tok)):
            piece = tok.decode([i])
            if piece.startswith(" ") and '"' in piece:
                ids.add(i)
        tok._stray_quote_ids = ids
    return ids


def make_loop_guard(prompt_len, n, tok=None):
    """HF LogitsProcessor: greedy decoding of a small model can fall into a loop (for example `hundred hundred ...`)
    and never close the JSON. This forbids repeating any n-gram of the model's own output. One general setting,
    applied identically in the service and in eval/predict.py. Returns None when n <= 1.
    With a tokenizer it also applies banned_word_repeats (the 6-gram alone lets a two-word loop such as
    `hundred thousand hundred ...` mutate instead of stopping)."""
    if n <= 1:
        return None
    from transformers import LogitsProcessor, LogitsProcessorList

    structural = structural_ids(tok) if tok is not None else None
    stray = stray_quote_ids(tok) if tok is not None else None

    class LoopGuard(LogitsProcessor):
        def __call__(self, input_ids, scores):
            for row in range(input_ids.shape[0]):
                gen = input_ids[row, prompt_len:].tolist()
                banned = banned_next_tokens(gen, n)
                if structural is not None:
                    banned |= banned_word_repeats(gen, structural)
                    if inside_string(tok.decode(gen)):
                        banned |= stray
                for t in banned:
                    scores[row, t] = float("-inf")
            return scores

    return LogitsProcessorList([LoopGuard()])


def build_prompt(text):
    return PROMPT_TEMPLATE.format(text=text)


def download_model(uri, endpoint, dest):
    """Download every object under s3://bucket/prefix/ into dest. Returns the file count."""
    import boto3
    from botocore.config import Config

    assert uri.startswith("s3://"), f"MODEL_URI must be an s3:// uri, got {uri!r}"
    bucket, _, prefix = uri[5:].partition("/")
    prefix = prefix.rstrip("/") + "/" if prefix else ""
    client = boto3.client("s3", endpoint_url=endpoint or None, region_name="us-east-1",
                          config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5}))
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"][len(prefix):]
            if not name or "/" in name:
                continue
            log.info("downloading s3://%s/%s (%d bytes)", bucket, obj["Key"], obj["Size"])
            client.download_file(bucket, obj["Key"], str(dest / name))
            count += 1
    return count


class Generator:
    def __init__(self, model_dir, threads=1, max_new_tokens=64, loop_guard_ngram=6):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(threads)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForCausalLM.from_pretrained(model_dir)
        self.model.eval()
        self.max_new_tokens = max_new_tokens
        self.loop_guard_ngram = loop_guard_ngram
        self.lock = threading.Lock()

    def generate(self, text):
        torch = self.torch
        enc = self.tok(build_prompt(text), return_tensors="pt", truncation=True, max_length=256)
        with self.lock, torch.inference_mode():
            guard = make_loop_guard(enc["input_ids"].shape[1], self.loop_guard_ngram, self.tok)
            out = self.model.generate(**enc, max_new_tokens=self.max_new_tokens, do_sample=False,
                                      logits_processor=guard, pad_token_id=self.tok.eos_token_id, eos_token_id=self.tok.eos_token_id)
        new = out[0][enc["input_ids"].shape[1]:]
        reply = self.tok.decode(new, skip_special_tokens=True)
        return reply.split("\n")[0].strip()


def load(settings):
    """Download then load. Returns a Generator."""
    t0 = time.time()
    n = download_model(settings.model_uri, settings.s3_endpoint, settings.model_dir)
    log.info("downloaded %d model files from %s in %.1fs", n, settings.model_uri, time.time() - t0)
    t1 = time.time()
    gen = Generator(settings.model_dir, settings.torch_threads, settings.max_new_tokens,
                    settings.loop_guard_ngram)
    log.info("model %s loaded in %.1fs (total start-up %.1fs)", settings.model_version, time.time() - t1,
             time.time() - t0)
    return gen


def verify_checksums(model_dir):
    """If files.sha256 is present, check every listed file. Returns a list of mismatches."""
    import hashlib

    listing = Path(model_dir) / "files.sha256"
    if not listing.exists():
        return []
    bad = []
    for line in listing.read_text().splitlines():
        digest, _, name = line.partition("  ")
        p = Path(model_dir) / name
        h = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if h != digest:
            bad.append(name)
    return bad

