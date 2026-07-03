import json

import pytest

import app.main as main_module
from app.main import add, app as flask_app


@pytest.fixture
def client():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_version(client):
    resp = client.get("/version")
    assert resp.status_code == 200
    assert resp.get_json() == {"version": "0.1.0"}


def test_pipeline_status_no_history_file(client, monkeypatch):
    monkeypatch.setattr(main_module, "HISTORY_PATH", "/does/not/exist.jsonl")
    resp = client.get("/pipeline/status")
    assert resp.status_code == 200
    assert resp.get_json()["available"] is False


def test_pipeline_status_empty_history_file(client, monkeypatch, tmp_path):
    empty = tmp_path / "history.jsonl"
    empty.write_text("")
    monkeypatch.setattr(main_module, "HISTORY_PATH", str(empty))
    resp = client.get("/pipeline/status")
    assert resp.get_json()["available"] is False


def test_pipeline_status_reports_latest_run(client, monkeypatch, tmp_path):
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps({"commit_sha": "abc111", "pass_rate": 0.9}) + "\n"
        + json.dumps(
            {
                "commit_sha": "abc222",
                "pass_rate": 0.95,
                "test_duration_seconds": 5.0,
                "pipeline_duration_seconds": 40.0,
            }
        )
        + "\n"
    )
    monkeypatch.setattr(main_module, "HISTORY_PATH", str(history))

    resp = client.get("/pipeline/status")
    data = resp.get_json()
    assert data["available"] is True
    assert data["runs_recorded"] == 2
    assert data["latest_run"]["commit_sha"] == "abc222"
    assert data["latest_run"]["pass_rate"] == 0.95


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (1, 2, 3),
        (-1, 1, 0),
        (0, 0, 0),
        (100, 250, 350),
    ],
)
def test_add(a, b, expected):
    assert add(a, b) == expected
