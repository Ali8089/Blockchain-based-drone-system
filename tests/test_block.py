from blockchain.block import Block


def make_block(index=1, prev="0" * 64):
    return Block(
        index=index,
        block_type="pre_flight",
        data={"drone_id": "drone_a", "start_position": {"x": 0, "y": 0, "z": 0}},
        previous_hash=prev,
    )


def test_hash_is_deterministic_for_same_content():
    b1 = make_block()
    b2 = Block(
        index=b1.index,
        block_type=b1.block_type,
        data=b1.data,
        previous_hash=b1.previous_hash,
        timestamp=b1.timestamp,
    )
    assert b1.hash == b2.hash


def test_hash_changes_if_data_changes():
    b1 = make_block()
    b2 = make_block()
    b2.data = {"drone_id": "drone_b", "start_position": {"x": 1, "y": 0, "z": 0}}
    b2.hash = b2.compute_hash()
    assert b1.hash != b2.hash


def test_hash_is_valid_on_untampered_block():
    b = make_block()
    assert b.hash_is_valid()


def test_tampering_with_data_is_detected():
    b = make_block()
    original_hash = b.hash
    # Simulate tampering: mutate payload data WITHOUT recomputing the hash
    b.data["drone_id"] = "drone_b_forged"
    assert b.hash == original_hash  # hash field untouched
    assert not b.hash_is_valid()  # but recomputation reveals the mismatch


def test_tampering_with_previous_hash_is_detected():
    b = make_block()
    b.previous_hash = "f" * 64
    assert not b.hash_is_valid()


def test_round_trip_dict_serialization():
    b = make_block()
    b.add_signature("gs_node_1", "deadbeef")
    d = b.to_dict()
    b2 = Block.from_dict(d)
    assert b2.hash == b.hash
    assert b2.signatures == {"gs_node_1": "deadbeef"}
    assert b2.hash_is_valid()


def test_invalid_block_type_rejected():
    import pytest
    with pytest.raises(ValueError):
        Block(index=1, block_type="not_a_real_type", data={}, previous_hash="0" * 64)


def test_genesis_block():
    g = Block.genesis()
    assert g.index == 0
    assert g.previous_hash == "0" * 64
    assert g.hash_is_valid()
