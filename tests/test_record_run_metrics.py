import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from record_run_metrics import append_record  # noqa: E402


def test_append_creates_file_and_parent_dir(tmp_path):
    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps({"run_id": "1", "pass_rate": 1.0}))
    history_path = tmp_path / "nested" / "history.jsonl"

    append_record(str(record_path), str(history_path))

    lines = history_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["run_id"] == "1"


def test_append_adds_to_existing_history(tmp_path):
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(json.dumps({"run_id": "0"}) + "\n")

    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps({"run_id": "1"}))
    append_record(str(record_path), str(history_path))

    lines = history_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["run_id"] == "0"
    assert json.loads(lines[1])["run_id"] == "1"


def test_append_returns_the_record_it_wrote(tmp_path):
    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps({"run_id": "7"}))
    history_path = tmp_path / "history.jsonl"

    result = append_record(str(record_path), str(history_path))

    assert result == {"run_id": "7"}
