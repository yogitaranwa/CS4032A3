"""Check model output against data/schema.json (the json_schema section)."""
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(os.environ.get("SCHEMA_PATH", Path(__file__).resolve().parent / "schema.json"))
if not SCHEMA_PATH.exists():  # running from a source checkout
    SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "schema.json"

_validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["json_schema"])


def parse_and_validate(text):
    """Return the parsed object if `text` is one valid four-key JSON object, else None."""
    try:
        obj = json.loads(text.strip())
    except (json.JSONDecodeError, AttributeError):
        return None
    return obj if _validator.is_valid(obj) else None
