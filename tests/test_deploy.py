import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from deploy import deploy, health_check  # noqa: E402


class FakeStarter:
    """Records every (image, tag) it was asked to start."""

    def __init__(self):
        self.calls = []

    def __call__(self, image, tag, name, port, docker_bin="docker"):
        self.calls.append((image, tag))


def make_checker(results):
    """Returns a checker that yields True/False per call, in order given."""
    results_iter = iter(results)

    def checker(url, retries, delay_seconds):
        return next(results_iter)

    return checker


def test_health_check_retries_then_succeeds():
    calls = {"n": 0}

    def fetch_fn(url):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("not up yet")

        class Resp:
            status = 200

        return Resp()

    slept = []
    result = health_check(
        "http://x/health", retries=5, delay_seconds=1, sleep_fn=slept.append, fetch_fn=fetch_fn
    )
    assert result is True
    assert calls["n"] == 3
    assert slept == [1, 1]  # slept between attempts 1->2 and 2->3, not after success


def test_health_check_exhausts_retries_and_fails():
    def fetch_fn(url):
        raise ConnectionError("never up")

    slept = []
    result = health_check(
        "http://x/health", retries=3, delay_seconds=2, sleep_fn=slept.append, fetch_fn=fetch_fn
    )
    assert result is False
    assert slept == [2, 2]  # slept between 1->2 and 2->3, not after final failed attempt


def test_deploy_success_records_state(tmp_path):
    state_path = tmp_path / "deployment_state.json"
    starter = FakeStarter()
    checker = make_checker([True])

    code = deploy(
        "ghcr.io/org/app",
        "sha123",
        state_path=str(state_path),
        starter=starter,
        checker=checker,
    )

    assert code == 0
    assert starter.calls == [("ghcr.io/org/app", "sha123")]
    state = json.loads(state_path.read_text())
    assert state["last_known_good_tag"] == "sha123"
    assert state["last_deploy_status"] == "success"


def test_deploy_failure_rolls_back_to_last_good(tmp_path):
    state_path = tmp_path / "deployment_state.json"
    state_path.write_text(json.dumps({"last_known_good_tag": "sha-good"}))
    starter = FakeStarter()
    # First call (new tag) fails health check, second call (rollback) succeeds.
    checker = make_checker([False, True])

    code = deploy(
        "ghcr.io/org/app",
        "sha-bad",
        state_path=str(state_path),
        starter=starter,
        checker=checker,
    )

    assert code == 1
    assert starter.calls == [
        ("ghcr.io/org/app", "sha-bad"),
        ("ghcr.io/org/app", "sha-good"),
    ]
    state = json.loads(state_path.read_text())
    assert state["last_deploy_status"] == "rolled_back"
    assert state["failed_tag"] == "sha-bad"
    assert state["last_known_good_tag"] == "sha-good"  # unchanged


def test_deploy_failure_rollback_also_fails(tmp_path):
    state_path = tmp_path / "deployment_state.json"
    state_path.write_text(json.dumps({"last_known_good_tag": "sha-good"}))
    starter = FakeStarter()
    checker = make_checker([False, False])

    code = deploy(
        "ghcr.io/org/app",
        "sha-bad",
        state_path=str(state_path),
        starter=starter,
        checker=checker,
    )

    assert code == 1
    state = json.loads(state_path.read_text())
    assert state["last_deploy_status"] == "rollback_failed"


def test_deploy_failure_no_rollback_target(tmp_path):
    state_path = tmp_path / "deployment_state.json"  # no prior state file at all
    starter = FakeStarter()
    checker = make_checker([False])

    code = deploy(
        "ghcr.io/org/app",
        "sha-first-ever",
        state_path=str(state_path),
        starter=starter,
        checker=checker,
    )

    assert code == 1
    assert starter.calls == [("ghcr.io/org/app", "sha-first-ever")]
    state = json.loads(state_path.read_text())
    assert state["last_deploy_status"] == "failed_no_rollback_target"
    assert "last_known_good_tag" not in state


def test_deploy_same_tag_as_last_good_does_not_rollback_loop(tmp_path):
    # If the tag we're deploying IS the last known-good tag and it fails,
    # rolling back to itself would be pointless — must not loop.
    state_path = tmp_path / "deployment_state.json"
    state_path.write_text(json.dumps({"last_known_good_tag": "sha-same"}))
    starter = FakeStarter()
    checker = make_checker([False])

    code = deploy(
        "ghcr.io/org/app",
        "sha-same",
        state_path=str(state_path),
        starter=starter,
        checker=checker,
    )

    assert code == 1
    assert starter.calls == [("ghcr.io/org/app", "sha-same")]  # only one attempt, no rollback
    state = json.loads(state_path.read_text())
    assert state["last_deploy_status"] == "failed_no_rollback_target"
