import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worker import clean, teacher, worker  # noqa: E402

INTENTS = clean.load_intents()


def rec(i, text, raw):
    return {"id": i, "text": text, "teacher_raw": raw}


def good(intent="alarm_set", date=None, time=None, place=None):
    return json.dumps({"intent": intent, "date": date, "time": time, "place": place})


def test_sharding_partitions_pool_exactly_once():
    pool = [json.loads(line) for line in open(ROOT / "data" / "commands_pool.jsonl")]
    for count in (2, 7, 15):
        seen = []
        for idx in range(count):
            seen += [r["id"] for r in worker.shard_records(pool, idx, count)]
        assert sorted(seen) == sorted(r["id"] for r in pool)
        assert len(seen) == len(set(seen))


def test_sharding_uses_line_number_mod_count():
    pool = [{"id": f"C{n}", "text": "x"} for n in range(10)]
    assert [r["id"] for r in worker.shard_records(pool, 1, 3)] == ["C1", "C4", "C7"]


def test_each_rejection_rule():
    assert clean.classify(rec("1", "hi", "not json"), INTENTS) == "a"
    assert clean.classify(rec("1", "hi", good() + " trailing"), INTENTS) == "a"
    assert clean.classify(rec("1", "hi", '["x"]'), INTENTS) == "b"
    assert clean.classify(rec("1", "hi", '{"intent": "alarm_set", "date": null, "time": null}'), INTENTS) == "b"
    assert clean.classify(rec("1", "hi", '{"intent":"alarm_set","date":null,"time":null,"place":null,"x":1}'), INTENTS) == "b"
    assert clean.classify(rec("1", "hi", good(intent="play_music")), INTENTS) == "c"
    assert clean.classify(rec("1", "wake me at seven am", good(time="07:00")), INTENTS) == "d"
    assert clean.classify(rec("1", "wake me at seven am", good(time=7)), INTENTS) == "d"
    assert clean.classify(rec("1", "wake me at seven am", good(time="")), INTENTS) == "d"
    assert clean.classify(rec("1", "wake me at seven am", good(time="seven am")), INTENTS) is None


def test_clean_counts_add_up_and_dedupe_keeps_smallest_id():
    records = [
        rec("C0003", "wake me at seven am", good(time="seven am")),
        rec("C0001", "wake me at seven am", good(time="seven am")),
        rec("C0002", "what is the weather in london", good("weather_query", place="london")),
        rec("C0004", "bad", "oops"),
        rec("C0005", "bad2", good("nope")),
    ]
    kept, counts = clean.clean(records, INTENTS)
    assert [r["id"] for r in kept] == ["C0001", "C0002"]
    assert counts == {"input": 5, "rejected_a_invalid_json": 1, "rejected_b_keys": 0, "rejected_c_intent": 1,
                      "rejected_d_slot": 0, "duplicates": 1, "kept": 2}


def test_clean_output_is_deterministic(tmp_path):
    shards = tmp_path / "teacher"
    shards.mkdir()
    pool = tmp_path / "pool.jsonl"
    rows = [{"id": f"C{n:04d}", "text": f"what is the weather in city{n}"} for n in range(6)]
    pool.write_text("".join(json.dumps(r) + "\n" for r in rows))
    for s in range(2):
        out = [dict(r, teacher_raw=good("weather_query", place=f"city{n}"))
               for n, r in enumerate(rows) if n % 2 == s]
        (shards / f"shard-{s}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in out))
    digests = []
    for run in range(2):
        out_dir = tmp_path / f"o{run}"
        clean.main(["--shards", str(shards), "--out", str(out_dir), "--pool", str(pool)])
        digests.append((out_dir / "train.sha256").read_text())
        assert (out_dir / "train.sha256").read_text().split()[0] == clean.sha256_text((out_dir / "train.jsonl").read_text())
    assert digests[0] == digests[1]


def test_clean_rejects_gaps_and_repeats():
    pool = ["C1", "C2", "C3"]
    assert clean.check_coverage(pool, [{"id": "C1"}, {"id": "C2"}, {"id": "C3"}]) == []
    assert clean.check_coverage(pool, [{"id": "C1"}, {"id": "C2"}])
    assert clean.check_coverage(pool, [{"id": "C1"}, {"id": "C1"}, {"id": "C2"}, {"id": "C3"}])


def test_teacher_prompt_contract():
    text = (ROOT / "prompts" / "teacher_prompt.txt").read_text()
    assert text.rstrip().endswith("{command}")
    for needle in ("intent", "date", "time", "place", "null", *INTENTS):
        assert needle in text
    rendered = teacher.render(text, "set an alarm")
    assert "{command}" not in rendered and rendered.rstrip().endswith("set an alarm")
    assert teacher.OPTIONS["temperature"] == 0 and teacher.OPTIONS["seed"] == 42
