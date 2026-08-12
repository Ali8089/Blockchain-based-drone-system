"""
Proof-of-Authority majority-vote consensus logic.

Rules (PRD Section 8):
  - There are exactly 3 known signing nodes.
  - A block is only accepted once at least 2 of the 3 have produced a
    VALID signature (verified against that node's known public key) over
    that exact block's hash.
  - A node cannot be counted twice, and a signature that doesn't verify
    (wrong key, wrong message, forged) does not count toward the total,
    even if it's present in the `signatures` dict.

This module is pure logic — no I/O, no Flask — so it's cheap to unit test.
"""

from __future__ import annotations

from typing import Dict, Tuple

from . import keys
from .block import Block

REQUIRED_SIGNATURES = 2  # majority of 3


def valid_signatures(block: Block) -> Dict[str, str]:
    """Return the subset of block.signatures that are (a) from a known
    node and (b) cryptographically valid over the block's hash."""
    good = {}
    message = block.signable_bytes()
    for node_id, sig_hex in block.signatures.items():
        if node_id not in keys.ALL_NODE_IDS:
            continue
        if keys.verify(node_id, message, sig_hex):
            good[node_id] = sig_hex
    return good


def has_majority(block: Block) -> bool:
    return len(valid_signatures(block)) >= REQUIRED_SIGNATURES


def check_block_acceptable(block: Block, expected_previous_hash: str) -> Tuple[bool, str]:
    """Full acceptance check for appending `block` onto a chain whose
    current tip hash is `expected_previous_hash`. Returns (ok, reason)."""
    if not block.hash_is_valid():
        return False, "hash_mismatch: block data does not match its stored hash (tampered)"

    if block.previous_hash != expected_previous_hash:
        return False, (
            f"previous_hash_mismatch: block points to {block.previous_hash[:12]}..., "
            f"chain tip is {expected_previous_hash[:12]}..."
        )

    good_sigs = valid_signatures(block)
    if len(good_sigs) < REQUIRED_SIGNATURES:
        return False, (
            f"insufficient_signatures: {len(good_sigs)}/{REQUIRED_SIGNATURES} valid "
            f"signatures (have {sorted(good_sigs.keys())})"
        )

    return True, "ok"
