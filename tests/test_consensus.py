import shutil
from pathlib import Path

import pytest

from blockchain.block import Block
from blockchain import keys, consensus

TEST_KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"


@pytest.fixture(autouse=True)
def isolated_keys(monkeypatch, tmp_path):
    """Point the keys module at a throwaway directory for every test, so
    test runs never depend on / clobber real node keys."""
    fake_dir = tmp_path / "keys"
    monkeypatch.setattr(keys, "KEYS_DIR", fake_dir)
    monkeypatch.setattr(keys, "KNOWN_NODES_PATH", fake_dir / "known_nodes.json")
    keys.ensure_all_node_keys_exist()
    yield


def make_block():
    return Block(
        index=1,
        block_type="pre_flight",
        data={"drone_id": "drone_a"},
        previous_hash="0" * 64,
    )


def test_no_signatures_no_majority():
    b = make_block()
    assert not consensus.has_majority(b)


def test_one_valid_signature_not_enough():
    b = make_block()
    sig = keys.sign("gs_node_1", b.signable_bytes())
    b.add_signature("gs_node_1", sig)
    assert not consensus.has_majority(b)


def test_two_valid_signatures_is_majority():
    b = make_block()
    for node_id in ["gs_node_1", "gs_node_2"]:
        sig = keys.sign(node_id, b.signable_bytes())
        b.add_signature(node_id, sig)
    assert consensus.has_majority(b)


def test_three_valid_signatures_is_majority():
    b = make_block()
    for node_id in keys.ALL_NODE_IDS:
        sig = keys.sign(node_id, b.signable_bytes())
        b.add_signature(node_id, sig)
    assert consensus.has_majority(b)


def test_forged_signature_does_not_count():
    b = make_block()
    # Sign with gs_node_1's key but CLAIM it's coordinator_node's signature
    forged_sig = keys.sign("gs_node_1", b.signable_bytes())
    b.add_signature("coordinator_node", forged_sig)
    real_sig = keys.sign("gs_node_2", b.signable_bytes())
    b.add_signature("gs_node_2", real_sig)
    # Only 1 of these 2 entries is actually valid -> no majority
    assert not consensus.has_majority(b)
    assert set(consensus.valid_signatures(b).keys()) == {"gs_node_2"}


def test_signature_over_wrong_block_does_not_count():
    b1 = make_block()
    b2 = make_block()
    b2.data = {"drone_id": "drone_b"}
    b2.hash = b2.compute_hash()

    # Sign b1's hash, but attach the signature to b2
    sig_for_b1 = keys.sign("gs_node_1", b1.signable_bytes())
    b2.add_signature("gs_node_1", sig_for_b1)
    sig_for_b2 = keys.sign("gs_node_2", b2.signable_bytes())
    b2.add_signature("gs_node_2", sig_for_b2)

    assert set(consensus.valid_signatures(b2).keys()) == {"gs_node_2"}
    assert not consensus.has_majority(b2)


def test_check_block_acceptable_full_flow():
    b = make_block()
    for node_id in ["gs_node_1", "gs_node_2"]:
        sig = keys.sign(node_id, b.signable_bytes())
        b.add_signature(node_id, sig)
    ok, reason = consensus.check_block_acceptable(b, expected_previous_hash="0" * 64)
    assert ok, reason


def test_check_block_acceptable_rejects_wrong_previous_hash():
    b = make_block()
    for node_id in ["gs_node_1", "gs_node_2"]:
        sig = keys.sign(node_id, b.signable_bytes())
        b.add_signature(node_id, sig)
    ok, reason = consensus.check_block_acceptable(b, expected_previous_hash="f" * 64)
    assert not ok
    assert "previous_hash_mismatch" in reason


def test_check_block_acceptable_rejects_tampered_block():
    b = make_block()
    for node_id in ["gs_node_1", "gs_node_2"]:
        sig = keys.sign(node_id, b.signable_bytes())
        b.add_signature(node_id, sig)
    b.data["drone_id"] = "forged"  # tamper AFTER signing
    ok, reason = consensus.check_block_acceptable(b, expected_previous_hash="0" * 64)
    assert not ok
    assert "hash_mismatch" in reason
