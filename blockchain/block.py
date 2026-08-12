"""
Block definition for the drone flight-recorder blockchain.

A Block wraps one of three payload types (see PRD Section 5):
  - "pre_flight"  : one per drone, written before takeoff
  - "in_flight"   : one per negotiation cycle, covering both drones
  - "post_flight" : one per drone, written after landing

Chain-level fields (index, previous_hash, hash, signatures) are separate
from the payload's own fields (which may include an "agent_signature" —
that is the *agent's* signature on the content it proposed, not a PoA
consensus signature; it is carried as ordinary payload data and is not
interpreted by the consensus layer).

Hashing is deterministic: the hash covers index, block_type, payload data,
timestamp and previous_hash. It deliberately excludes the `signatures`
dict, so that signatures can be collected incrementally (by different
nodes, possibly arriving out of order) without changing block identity.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

VALID_BLOCK_TYPES = {"genesis", "pre_flight", "in_flight", "post_flight"}


@dataclass
class Block:
    index: int
    block_type: str
    data: Dict[str, Any]
    previous_hash: str
    timestamp: float = field(default_factory=time.time)
    # node_id -> signature (base64/hex string). Populated as nodes sign.
    signatures: Dict[str, str] = field(default_factory=dict)
    hash: str = ""

    def __post_init__(self):
        if self.block_type not in VALID_BLOCK_TYPES:
            raise ValueError(
                f"Invalid block_type '{self.block_type}'. "
                f"Must be one of {sorted(VALID_BLOCK_TYPES)}"
            )
        if not self.hash:
            self.hash = self.compute_hash()

    def _hash_payload(self) -> Dict[str, Any]:
        """Fields that determine block identity. Signatures are excluded
        on purpose: they are collected after the fact and must not change
        what block they're signing."""
        return {
            "index": self.index,
            "block_type": self.block_type,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
        }

    def compute_hash(self) -> str:
        canonical = json.dumps(self._hash_payload(), sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def hash_is_valid(self) -> bool:
        """True if the stored hash matches a fresh recomputation — i.e.
        nothing in the identity-bearing fields has been tampered with."""
        return self.hash == self.compute_hash()

    def signable_bytes(self) -> bytes:
        """The exact bytes a node signs. Signing the hash (not the raw
        payload) keeps signature verification cheap and unambiguous."""
        return self.hash.encode("utf-8")

    def add_signature(self, node_id: str, signature_hex: str) -> None:
        self.signatures[node_id] = signature_hex

    def signature_count(self) -> int:
        return len(self.signatures)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        # Reconstruct without re-deriving the hash, so a tampered dict
        # (hash left stale relative to mutated data) can still be loaded
        # and then checked with hash_is_valid().
        blk = cls.__new__(cls)
        blk.index = d["index"]
        blk.block_type = d["block_type"]
        blk.data = d["data"]
        blk.previous_hash = d["previous_hash"]
        blk.timestamp = d["timestamp"]
        blk.signatures = dict(d.get("signatures", {}))
        blk.hash = d["hash"]
        return blk

    @staticmethod
    def genesis() -> "Block":
        blk = Block(
            index=0,
            block_type="genesis",
            data={"note": "genesis block"},
            previous_hash="0" * 64,
            timestamp=0.0,
        )
        return blk
