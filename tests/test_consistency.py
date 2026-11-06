import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from service.app import model as service_model  # noqa: E402
from training import train  # noqa: E402


def test_training_and_serving_prompts_match():
    assert train.build_prompt("set an alarm") == service_model.build_prompt("set an alarm") == "Command: set an alarm\nJSON:"


def test_config_has_the_six_required_items():
    cfg = yaml.safe_load((ROOT / "training" / "config.yaml").read_text())
    for key in ("seed", "learning_rate", "batch_size", "epochs", "max_seq_length", "library_versions"):
        assert key in cfg
    assert cfg["max_records"] <= 1500
    loaded = train.load_config(ROOT / "training" / "config.yaml", "v2", 50)
    assert loaded["epochs"] == cfg["epochs"] + 1 and loaded["subset"] == 50 and loaded["version"] == "v2"


def test_target_text_is_json_of_teacher_reply():
    assert train.target_text(' {"intent": "alarm_set", "date": null, "time": "seven am", "place": null}\n') == \
        '{"intent": "alarm_set", "date": null, "time": "seven am", "place": null}'


def test_fewshot_examples_are_not_validation_items():
    val = {json.loads(line)["text"] for line in open(ROOT / "data" / "validation.jsonl")}
    for line in (ROOT / "prompts" / "teacher_prompt.txt").read_text().splitlines():
        if line.startswith("Command: ") and "{command}" not in line:
            assert line[len("Command: "):] not in val


def test_worker_end_to_end_with_stub_teacher(tmp_path, monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["options"]["temperature"] == 0 and body["options"]["seed"] == 42
            assert body["format"]["properties"]["intent"]["enum"] and "\nCommand:" in body["options"]["stop"]
            reply = json.dumps({"message": {"content": '{"intent": "weather_query", "date": null, "time": null, "place": null}'}})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(reply.encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pool = tmp_path / "pool.jsonl"
    pool.write_text("".join(json.dumps({"id": f"C{n}", "text": f"cmd {n}"}) + "\n" for n in range(7)))
    from worker import worker
    for var, val in {"SHARD_INDEX": "1", "SHARD_COUNT": "3", "POOL_FILE": str(pool), "OUT_ROOT": str(tmp_path / "o"),
                     "OLLAMA_HOST": f"http://127.0.0.1:{srv.server_port}"}.items():
        monkeypatch.setenv(var, val)
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    worker.main()
    rows = [json.loads(line) for line in (tmp_path / "o" / "teacher" / "shard-1.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["C1", "C4"]
    assert set(rows[0]) == {"id", "text", "teacher_raw"}
    srv.shutdown()
