"""Host-side startup and verification when the agent cannot bind ports or access Docker."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from aristotle_backend.config import PROJECT_ROOT
from aristotle_backend.migrations import schema_head


def run(command, cwd=PROJECT_ROOT, env=None):
    print("Running: " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def wait_http(url, process, json_response=False):
    opener = build_opener(ProxyHandler({}))
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError("Service stopped during startup; inspect its .local log")
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read()) if json_response else True
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Service did not become ready: " + url)


def main():
    parser = argparse.ArgumentParser(
        description="Start the PostgreSQL learning map; Ctrl-C stops only these child services"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Run PostgreSQL, frontend and Chrome E2E checks before startup"
    )
    parser.add_argument("--e2e", action="store_true", help="Resume only Chrome E2E validation before startup")
    parser.add_argument(
        "--probe-models",
        action="store_true",
        help="Make four small real model calls using authored data in an isolated test schema",
    )
    parser.add_argument("--api-port", type=int, default=8020)
    parser.add_argument("--frontend-port", type=int, default=5180)
    args = parser.parse_args()
    for port in (args.api_port, args.frontend_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(
                    f"Port {port} is already in use; stop its terminal or choose another port. No process was killed."
                )
    run(["docker", "compose", "up", "-d", "--wait", "postgres"])
    run([sys.executable, "-m", "aristotle_backend.migrations"])
    frontend = PROJECT_ROOT / "code" / "frontend"
    # Never pass model/database secrets into the frontend process environment.
    front_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ARISTOTLE_LLM_", "ARISTOTLE_EMBEDDING_", "ARISTOTLE_MODEL_"))
        and key != "ARISTOTLE_DATABASE_URL"
        and not key.endswith("_API_KEY")
    }
    if args.verify:
        run([sys.executable, "scripts/verify_postgresql.py"])
        run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], frontend, front_env)
        run(["npm", "test"], frontend, front_env)
        run(["npm", "run", "build"], frontend, front_env)
    if args.verify or args.e2e:
        run(["npm", "run", "test:e2e"], frontend, {**front_env, "PLAYWRIGHT_CHANNEL": "chrome"})
    if args.probe_models:
        run([sys.executable, "scripts/probe_learning_services.py"])
    output = PROJECT_ROOT / ".local"
    output.mkdir(exist_ok=True)
    children, handles = [], []
    try:

        def start(command, name, cwd, env=None):
            path = output / (name + ".log")
            path.touch(mode=0o600, exist_ok=True)
            path.chmod(0o600)
            log = path.open("w")
            handles.append(log)
            child = subprocess.Popen(
                command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            children.append(child)
            return child

        api = start(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "aristotle_backend.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ],
            "backend",
            PROJECT_ROOT,
        )
        api_url = f"http://127.0.0.1:{args.api_port}"
        health = wait_http(api_url + "/health", api, True)
        if health.get("database") != "postgresql" or health.get("schema_revision") != schema_head():
            raise RuntimeError("The running backend did not report PostgreSQL and the current schema")
        web = start(
            [
                "npm",
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.frontend_port),
                "--strictPort",
            ],
            "frontend",
            frontend,
            {**front_env, "ARISTOTLE_BACKEND_URL": api_url},
        )
        web_url = f"http://127.0.0.1:{args.frontend_port}"
        wait_http(web_url + "/", web)
        try:
            build_opener(ProxyHandler({})).open(web_url + "/api/v1/knowledge", timeout=3)
        except HTTPError as exc:
            if exc.code != 401:
                raise RuntimeError(
                    "Frontend proxy did not reach the backend authentication boundary"
                ) from None
        else:
            raise RuntimeError("Frontend proxy unexpectedly bypassed authentication")
        path = output / "learning-space-status.json"
        path.write_text(
            json.dumps(
                {
                    "running": True,
                    "frontend": web_url,
                    "backend": api_url,
                    "health": health,
                    "proxy_verified": True,
                    "backend_pid": api.pid,
                    "frontend_pid": web.pid,
                },
                indent=2,
            )
            + "\n"
        )
        print(
            "\nLearning space is ready: "
            + web_url
            + "\nKeep this terminal open; Ctrl-C stops these two services and preserves the database.",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(1)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
        for handle in handles:
            handle.close()
        status = output / "learning-space-status.json"
        if status.exists():
            data = json.loads(status.read_text())
            data["running"] = False
            status.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
