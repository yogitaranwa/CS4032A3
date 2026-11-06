import json
import sys
import threading
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service.app.config import Settings  # noqa: E402
from service.app.main import create_app  # noqa: E402
from service.app.validate import parse_and_validate  # noqa: E402

GOOD = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


class Fake:
    def __init__(self, reply):
        self.reply = reply

    def generate(self, text):
        return self.reply


def make(reply=GOOD, **env):
    env = {"MODEL_VERSION": "v9", "POD_NAME": "pod-a", **env}
    return TestClient(create_app(Settings(env), loader=lambda s: Fake(reply)))


def test_endpoints_and_headers():
    with make() as c:
        for _ in range(200):
            if c.get("/readyz").status_code == 200:
                break
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 200
        r = c.post("/parse", json={"text": "what is the weather in london"})
        assert r.status_code == 200
        assert r.json() == json.loads(GOOD)
        assert r.headers["X-Model-Version"] == "v9"
        assert r.headers["X-Served-By"] == "pod-a"


def test_readyz_503_until_model_loaded():
    gate = threading.Event()

    def slow_loader(settings):
        gate.wait(5)
        return Fake(GOOD)

    app = create_app(Settings({"MODEL_VERSION": "v1"}), loader=slow_loader)
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 503
        assert c.post("/parse", json={"text": "hi"}).status_code == 503
        gate.set()
        for _ in range(500):
            if c.get("/readyz").status_code == 200:
                break
            threading.Event().wait(0.01)
        assert c.get("/readyz").status_code == 200


def test_invalid_output_gives_500_exact_body():
    for bad in ("garbage", '{"intent": "alarm_set"}', '{"intent": "nope", "date": null, "time": null, "place": null}',
                '{"intent": "alarm_set", "date": 3, "time": null, "place": null}',
                '{"intent": "alarm_set", "date": null, "time": null, "place": null, "x": 1}'):
        with make(bad) as c:
            for _ in range(200):
                if c.get("/readyz").status_code == 200:
                    break
            r = c.post("/parse", json={"text": "x"})
            assert r.status_code == 500
            assert r.json() == {"error": "invalid_model_output"}


def test_fault_inject_replaces_output():
    with make(GOOD, FAULT_INJECT="1") as c:
        for _ in range(200):
            if c.get("/readyz").status_code == 200:
                break
        r = c.post("/parse", json={"text": "x"})
        assert r.status_code == 500 and r.json() == {"error": "invalid_model_output"}


def test_schema_validation_helper():
    assert parse_and_validate(GOOD) is not None
    assert parse_and_validate("not json") is None
    assert parse_and_validate('["a"]') is None


def test_settings_read_the_four_variables():
    s = Settings({"MODEL_URI": "s3://models/v1/", "MODEL_VERSION": "v1", "S3_ENDPOINT": "http://x:8333",
                  "MAX_NEW_TOKENS": "33", "FAULT_INJECT": "1", "POD_NAME": "p"})
    assert (s.model_uri, s.model_version, s.s3_endpoint, s.max_new_tokens, s.fault_inject, s.served_by) == (
        "s3://models/v1/", "v1", "http://x:8333", 33, True, "p")


def test_loop_guard_bans_repeated_ngram():
    from service.app.model import banned_next_tokens
    assert banned_next_tokens([1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5], 6) == {6}
    assert banned_next_tokens([7, 7, 7, 7, 7, 7], 6) == {7}
    assert banned_next_tokens([1, 2, 3, 4, 5, 6], 6) == set()      # no earlier match
    assert banned_next_tokens([1, 1, 1, 1, 1, 1], 0) == set()      # disabled


def test_word_repeat_guard():
    from service.app.model import banned_word_repeats
    st = {1, 2}                                   # structural ids
    assert banned_word_repeats([5, 6, 5], st) == {5, 6}  # last=5 seen before followed by 6; no immediate repeat
    assert banned_word_repeats([5, 6, 1], st) == set()   # last token is structural
    assert banned_word_repeats([], st) == set()


def test_inside_string():
    from service.app.model import inside_string
    assert inside_string('{"intent": "alarm_set", "place": "zach')
    assert not inside_string('{"intent": "alarm_set", "place": null')
    assert not inside_string('{"intent": "a"}')
    assert inside_string('{"place": "say \\"hi')
