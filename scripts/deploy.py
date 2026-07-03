"""Deploy a container, retry the health check with backoff, and roll back to
the last known-good tag if it never comes up healthy.

Runs against the CI runner itself - no real host needed for the demo. Swap
start_container()'s docker run for kubectl/ecs/ssh+compose/whatever to point
this at an actual target; the retry/rollback logic doesn't need to change.
Last known-good tag lives in deployment_state.json.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

CONTAINER_NAME = "app-deploy"
STATE_FILE_DEFAULT = "deployment_state.json"


def run(cmd, check=True):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def container_exists(name, docker_bin="docker"):
    result = run([docker_bin, "ps", "-a", "-q", "-f", f"name=^{name}$"], check=False)
    return bool(result.stdout.strip())


def stop_and_remove(name, docker_bin="docker"):
    if container_exists(name, docker_bin):
        run([docker_bin, "rm", "-f", name], check=False)


def start_container(image, tag, name, port, docker_bin="docker"):
    stop_and_remove(name, docker_bin)
    run([docker_bin, "run", "-d", "--name", name, "-p", f"{port}:8000", f"{image}:{tag}"])


def health_check(url, retries, delay_seconds, sleep_fn=time.sleep, fetch_fn=None):
    fetch_fn = fetch_fn or (lambda u: urllib.request.urlopen(u, timeout=3))
    for attempt in range(1, retries + 1):
        try:
            resp = fetch_fn(url)
            status = getattr(resp, "status", 200)
            if status == 200:
                return True
        except Exception:
            pass
        if attempt < retries:
            sleep_fn(delay_seconds)
    return False


def load_state(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def deploy(
    image,
    tag,
    port=8000,
    retries=5,
    delay_seconds=3,
    state_path=STATE_FILE_DEFAULT,
    docker_bin="docker",
    health_url=None,
    starter=start_container,
    checker=health_check,
):
    health_url = health_url or f"http://localhost:{port}/health"
    state = load_state(state_path)
    last_good = state.get("last_known_good_tag")

    print(f"Deploying {image}:{tag} ...")
    starter(image, tag, CONTAINER_NAME, port, docker_bin)
    healthy = checker(health_url, retries, delay_seconds)

    if healthy:
        state["last_known_good_tag"] = tag
        state["last_deploy_status"] = "success"
        state.pop("failed_tag", None)
        save_state(state_path, state)
        print(f"Deploy healthy: {image}:{tag}")
        return 0

    print(f"Deploy of {tag} failed health check after {retries} attempts.", file=sys.stderr)

    if last_good and last_good != tag:
        print(f"Rolling back to last known-good tag: {last_good}", file=sys.stderr)
        starter(image, last_good, CONTAINER_NAME, port, docker_bin)
        rollback_healthy = checker(health_url, retries, delay_seconds)
        state["failed_tag"] = tag
        state["last_deploy_status"] = "rolled_back" if rollback_healthy else "rollback_failed"
        save_state(state_path, state)
        if rollback_healthy:
            print(f"Rollback to {last_good} succeeded.", file=sys.stderr)
        else:
            print(f"Rollback to {last_good} ALSO failed health check.", file=sys.stderr)
        return 1

    state["last_deploy_status"] = "failed_no_rollback_target"
    state["failed_tag"] = tag
    save_state(state_path, state)
    print("No known-good tag available to roll back to.", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Image repo, e.g. ghcr.io/org/repo")
    parser.add_argument("--tag", required=True, help="Tag to deploy, e.g. the commit SHA")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--delay-seconds", type=float, default=3)
    parser.add_argument("--state-file", default=STATE_FILE_DEFAULT)
    args = parser.parse_args()

    return deploy(
        args.image,
        args.tag,
        port=args.port,
        retries=args.retries,
        delay_seconds=args.delay_seconds,
        state_path=args.state_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
