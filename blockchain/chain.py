"""
In-memory (optionally disk-persisted) chain of Blocks, owned by a single
node. Enforces consensus rules on every append.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from .block import Block
from . import consensus


class ChainError(Exception):
    pass


class Chain:
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path
        self.blocks: List[Block] = [Block.genesis()]
        if storage_path and storage_path.exists():
            self._load()

    @property
    def tip(self) -> Block:
        return self.blocks[-1]

    def try_append(self, block: Block) -> Tuple[bool, str]:
        """Validate `block` against consensus rules and the current tip.
        Appends and persists only if valid. Returns (ok, reason)."""
        ok, reason = consensus.check_block_acceptable(block, self.tip.hash)
        if not ok:
            return False, reason
        if block.index != self.tip.index + 1:
            return False, (
                f"index_mismatch: expected index {self.tip.index + 1}, got {block.index}"
            )
        self.blocks.append(block)
        self._persist()
        return True, "ok"

    def verify_full_chain(self) -> Tuple[bool, str]:
        """Walk the whole chain and confirm every block's hash is
        internally consistent and correctly links to its predecessor.
        Used to detect tampering with historical blocks."""
        for i in range(1, len(self.blocks)):
            blk = self.blocks[i]
            prev = self.blocks[i - 1]
            if not blk.hash_is_valid():
                return False, f"block {i} hash_mismatch (data tampered post-hoc)"
            if blk.previous_hash != prev.hash:
                return False, f"block {i} previous_hash does not match block {i - 1}.hash"
            if not consensus.has_majority(blk):
                return False, f"block {i} lacks majority signatures"
        return True, "ok"

    def to_list(self) -> List[dict]:
        return [b.to_dict() for b in self.blocks]

    def _persist(self) -> None:
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(self.to_list(), indent=2, sort_keys=True))

    def _load(self) -> None:
        raw = json.loads(self.storage_path.read_text())
        self.blocks = [Block.from_dict(d) for d in raw]
