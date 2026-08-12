"""
Shared fixtures for tests that need a real 3-node blockchain running.

Mirrors the fixtures originally written in test_node_integration.py
(Phase 1) so Phase 4/5 tests can spin up the same kind of live node
subprocesses without duplicating the setup code.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from blockchain import keys

ROOT = Path(__file__).resolve().parent.parent
NODE_IDS = ("gs_node_1", "gs_node_2", "coordinator_node")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_health(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/health", timeout=1)
            if r.status_code == 200:
                return
        except requests.RequestException as e:
            last_err = e
        time.sleep(0.1)
    raise TimeoutError(f"{url} never became healthy: {last_err}")


class LiveNode:
    def __init__(self, node_id: str, port: int, proc: subprocess.Popen, url: str):
        self.node_id = node_id
        self.port = port
        self.proc = proc
        self.url = url

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def is_running(self) -> bool:
        return self.proc.poll() is None


@pytest.fixture()
def isolated_test_env(tmp_path, monkeypatch):
    """Fresh keys + fresh chain_data dir per test, isolated from any real
    developer state (same rationale as Phase 1's version of this fixture)."""
    fake_keys_dir = tmp_path / "keys"
    fake_chain_dir = tmp_path / "chain_data"
    monkeypatch.setenv("DRONE_CHAIN_KEYS_DIR", str(fake_keys_dir))
    monkeypatch.setenv("DRONE_CHAIN_DATA_DIR", str(fake_chain_dir))
    monkeypatch.setattr(keys, "KEYS_DIR", fake_keys_dir)
    monkeypatch.setattr(keys, "KNOWN_NODES_PATH", fake_keys_dir / "known_nodes.json")
    return {"keys_dir": fake_keys_dir, "chain_dir": fake_chain_dir}


@pytest.fixture()
def three_live_nodes(isolated_test_env):
    nodes = []
    env = {
        **os.environ,
        "DRONE_CHAIN_KEYS_DIR": str(isolated_test_env["keys_dir"]),
        "DRONE_CHAIN_DATA_DIR": str(isolated_test_env["chain_dir"]),
    }
    for node_id in NODE_IDS:
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "blockchain.node", "--node-id", node_id,
             "--port", str(port), "--no-persist"],
            cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        nodes.append(LiveNode(node_id, port, proc, f"http://127.0.0.1:{port}"))

    try:
        for n in nodes:
            _wait_for_health(n.url)
        yield nodes
    finally:
        for n in nodes:
            n.stop()
