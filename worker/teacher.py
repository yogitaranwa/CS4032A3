"""Teacher client: Ollama with the fixed phi3.5 model, temperature 0, seed 42."""
import json
import os
import time
import urllib.request
from pathlib import Path

MODEL = os.environ.get("TEACHER_MODEL", "phi3.5")
DEFAULT_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "teacher_prompt.txt"
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "data" / "schema.json"

# The stop sequences cut the reply after the JSON object. Without them phi3.5 often appends a "(Note: ...)" paragraph or
# invents the next "Command: ..." line, which makes the reply invalid JSON. This is decoding configuration: the reply that
# is stored is still exactly what the teacher generated.
OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 100, "num_ctx": 2048,
           "stop": ["\n\n", "\nCommand:", "Command:", "(Note", "Note:"]}


def response_format():
    """Structured-output schema for Ollama: exactly the four keys, intent restricted to the eight values.

    Only the output grammar is constrained. Slot values are still chosen freely by the teacher, and the cleaner still
    applies rules (a) to (e) to every reply.
    """
    intents = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["intents"]
    nullable = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    return {"type": "object", "additionalProperties": False,
            "required": ["intent", "date", "time", "place"],
            "properties": {"intent": {"type": "string", "enum": intents},
                           "date": nullable, "time": nullable, "place": nullable}}


def load_prompt(path=None):
    return Path(path or os.environ.get("PROMPT_FILE") or DEFAULT_PROMPT).read_text(encoding="utf-8")


def render(template, command):
    # str.replace, not str.format: the prompt contains literal JSON braces.
    # The command goes last so Ollama can reuse the cached prompt prefix.
    return template.replace("{command}", command)


def ask(command, template, host=None, model=MODEL, retries=5, timeout=600):
    """Return the teacher's exact reply text for one command."""
    host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    if not host.startswith("http"):
        host = "http://" + host
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": render(template, command)}],
        "stream": False,
        "format": response_format(),
        "options": OPTIONS,
    }).encode("utf-8")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(host + "/api/chat", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))["message"]["content"]
        except Exception as exc:  # network hiccup or model still loading
            last = exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"teacher call failed after {retries} attempts: {last}")
