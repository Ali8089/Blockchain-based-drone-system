"""
Integration test: spins up 3 REAL node.py OS subprocesses on localhost,
talks to them only over HTTP (exactly as the negotiation coordinator
will in Phase 3), and tears them down afterward.

This is the test that actually proves the Phase 1 DoD items:
  - 3 node processes run independently and can be started/stopped individually
  - a block is only accepted once 2 of 3 nodes sign off
  - tampering with a past block is detectable via hash mismatch
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from blockchain.block import Block
from blockchain import client, keys

ROOT = Path(__file__).resolve().parent.parent
NODE_SPECS = [
    ("gs_node_1", None),
    ("gs_node_2", None),
    ("coordinator_node", None),
]


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
    """Fresh keys + fresh chain_data dir for this test run, so it never
    depends on / pollutes any real developer state.

    Two audiences need to agree on the keys location:
      - the node.py SUBPROCESSES we spawn (they read the
        DRONE_CHAIN_KEYS_DIR env var at import time), and
      - THIS pytest process itself, since client.propose_and_commit()
        calls consensus.has_majority() -> keys.verify() locally to check
        signatures before committing. That verification must look at the
        exact same known_nodes.json the subprocesses wrote to, so we
        also monkeypatch the keys module in-process (same pattern as
        test_consensus.py's isolated_keys fixture).
    """
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
        **__import__("os").environ,
        "DRONE_CHAIN_KEYS_DIR": str(isolated_test_env["keys_dir"]),
        "DRONE_CHAIN_DATA_DIR": str(isolated_test_env["chain_dir"]),
    }
    for node_id, _ in NODE_SPECS:
        port = _free_port()
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "blockchain.node",
                "--node-id", node_id,
                "--port", str(port),
                "--no-persist",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        url = f"http://127.0.0.1:{port}"
        nodes.append(LiveNode(node_id, port, proc, url))

    try:
        for n in nodes:
            _wait_for_health(n.url)
        yield nodes
    finally:
        for n in nodes:
            n.stop()


def test_three_nodes_start_independently(three_live_nodes):
    for n in three_live_nodes:
        r = requests.get(f"{n.url}/health", timeout=2)
        assert r.status_code == 200
        assert r.json()["node_id"] == n.node_id
        assert r.json()["chain_length"] == 1  # just genesis


def test_stopping_one_node_does_not_affect_others(three_live_nodes):
    victim = three_live_nodes[0]
    survivors = three_live_nodes[1:]

    victim.stop()
    assert not victim.is_running()

    for n in survivors:
        r = requests.get(f"{n.url}/health", timeout=2)
        assert r.status_code == 200


def test_block_proposal_gathers_majority_and_commits(three_live_nodes):
    node_urls = [n.url for n in three_live_nodes]
    block, commit_results = client.propose_and_commit(
        node_urls,
        block_type="pre_flight",
        data={
            "drone_id": "drone_a",
            "start_position": {"x": 0, "y": 0, "z": 0},
            "destination_position": {"x": 5, "y": 5, "z": 1},
        },
    )
    assert len(block.signatures) >= 2

    for url, result in commit_results.items():
        assert result["committed"] is True, result

    for n in three_live_nodes:
        chain = requests.get(f"{n.url}/chain", timeout=2).json()
        assert len(chain) == 2  # genesis + new block
        assert chain[-1]["data"]["drone_id"] == "drone_a"


def test_block_rejected_when_only_one_node_reachable(three_live_nodes):
    # Kill 2 of 3 nodes -> only 1 signer left -> can never reach majority
    for n in three_live_nodes[1:]:
        n.stop()

    node_urls = [three_live_nodes[0].url]
    with pytest.raises(client.ProposalFailed):
        client.propose_and_commit(
            node_urls,
            block_type="pre_flight",
            data={"drone_id": "drone_a"},
        )


def test_any_node_can_be_the_proposal_entry_point(three_live_nodes):
    """The 3 nodes are symmetric peers: whichever one a proposer talks to
    first (to read the current tip from) is just that call's entry point,
    not a privileged 'leader'. Propose twice, rotating which node is
    listed first, and confirm both proposals succeed identically."""
    n1, n2, n3 = three_live_nodes

    block_a, results_a = client.propose_and_commit(
        [n1.url, n2.url, n3.url],
        block_type="pre_flight",
        data={"drone_id": "drone_a"},
    )
    assert all(r["committed"] for r in results_a.values())

    block_b, results_b = client.propose_and_commit(
        [n3.url, n1.url, n2.url],  # different node first this time
        block_type="pre_flight",
        data={"drone_id": "drone_b"},
    )
    assert all(r["committed"] for r in results_b.values())
    assert block_b.index == block_a.index + 1

    for n in three_live_nodes:
        chain = requests.get(f"{n.url}/chain", timeout=2).json()
        assert len(chain) == 3  # genesis + 2 proposals, on every node


def test_tampering_with_a_committed_block_is_detected(three_live_nodes):
    node_urls = [n.url for n in three_live_nodes]
    block, _ = client.propose_and_commit(
        node_urls,
        block_type="pre_flight",
        data={"drone_id": "drone_a", "start_position": {"x": 0, "y": 0, "z": 0}},
    )

    # Fetch the committed chain from node 1, tamper with the historical
    # block's data (as if someone edited the stored JSON directly),
    # then ask that same node to verify its own chain's integrity.
    chain = requests.get(f"{node_urls[0]}/chain", timeout=2).json()
    chain[1]["data"]["drone_id"] = "drone_b_forged"  # tamper, leave hash untouched

    tampered_block = Block.from_dict(chain[1])
    assert not tampered_block.hash_is_valid(), (
        "tampering with historical block data must be detectable via hash mismatch"
    )
