"""All configuration comes from environment variables.

MODEL_URI        s3://models/v1/   where the model and tokenizer files live in object storage
MODEL_VERSION    v1                returned in the X-Model-Version header
S3_ENDPOINT      http://seaweedfs.data.svc.cluster.local:8333
MAX_NEW_TOKENS   64                generation limit
FAULT_INJECT     0|1               1 replaces the model output with the text "not json" before validation

Credentials: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, injected from a Kubernetes Secret (never in the image or repo).
POD_NAME (downward API) gives X-Served-By; it falls back to the hostname.
"""
import os
import socket


class Settings:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.model_uri = env.get("MODEL_URI", "")
        self.model_version = env.get("MODEL_VERSION", "unknown")
        self.s3_endpoint = env.get("S3_ENDPOINT", "")
        self.max_new_tokens = int(env.get("MAX_NEW_TOKENS", "64"))
        self.loop_guard_ngram = int(env.get("LOOP_GUARD_NGRAM", "6"))
        self.fault_inject = env.get("FAULT_INJECT", "0") == "1"
        self.served_by = env.get("POD_NAME") or env.get("HOSTNAME") or socket.gethostname()
        self.model_dir = env.get("MODEL_DIR", "/tmp/model")
        self.torch_threads = int(env.get("TORCH_THREADS", "1"))
