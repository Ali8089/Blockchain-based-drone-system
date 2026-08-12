"""
Signing-key helpers for the PoA blockchain nodes.

Each node (gs_node_1, gs_node_2, coordinator_node) has its own Ed25519
keypair. Nodes sign a block's hash; other nodes verify that signature
against the signer's *public* key, which is the only thing that needs to
be shared/known by everyone (see keys/known_nodes.json).

Deliberate separation of key storage:
  keys/ground_station/   -> private keys for gs_node_1, gs_node_2
                             (these live on the ground station laptop)
  keys/coordinator/      -> private key for coordinator_node
                             (this lives in the coordinator's own cloud
                             environment and must never be copied onto
                             the ground station laptop — see PRD Section 8)
  keys/known_nodes.json  -> PUBLIC keys only, for all 3 nodes; safe to
                             share everywhere, used for signature checks
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterator

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

def _default_keys_dir() -> Path:
    override = os.environ.get("DRONE_CHAIN_KEYS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "keys"


KEYS_DIR = _default_keys_dir()
KNOWN_NODES_PATH = KEYS_DIR / "known_nodes.json"

# Which subdirectory each node's PRIVATE key lives in. This mapping is
# the structural expression of "coordinator key never touches the
# ground station laptop" — the two locations are never merged.
NODE_HOME = {
    "gs_node_1": "ground_station",
    "gs_node_2": "ground_station",
    "coordinator_node": "coordinator",
}

ALL_NODE_IDS = tuple(NODE_HOME.keys())


def _private_key_path(node_id: str) -> Path:
    if node_id not in NODE_HOME:
        raise ValueError(f"Unknown node_id '{node_id}'")
    return KEYS_DIR / NODE_HOME[node_id] / f"{node_id}.pem"


@contextlib.contextmanager
def _known_nodes_lock() -> Iterator[None]:
    """Advisory file lock guarding known_nodes.json's read-modify-write.

    Node processes (potentially several, on different machines pointed at
    a shared registry) call generate_node_keypair() around the same time
    on startup. Without locking, two concurrent read-modify-writes race:
    node B can read the registry before node A's write lands, then save a
    copy that silently drops node A's just-registered key. The lock makes
    "read current registry, add my key, write it back" atomic across
    processes.
    """
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = KEYS_DIR / ".known_nodes.lock"
    with open(lock_path, "w") as lock_file:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def generate_node_keypair(node_id: str, overwrite: bool = False) -> None:
    """Generate (and persist) a fresh Ed25519 keypair for a node, and
    register its public key in known_nodes.json."""
    priv_path = _private_key_path(node_id)
    priv_path.parent.mkdir(parents=True, exist_ok=True)

    if priv_path.exists() and not overwrite:
        pass  # keep existing key
    else:
        private_key = Ed25519PrivateKey.generate()
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        priv_path.write_bytes(pem)

    # (Re)register the public key. Locked so concurrent node startups
    # (see _known_nodes_lock docstring) can't clobber each other.
    private_key = load_private_key(node_id)
    public_key = private_key.public_key()
    pub_hex = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    with _known_nodes_lock():
        known = load_known_nodes()
        known[node_id] = pub_hex
        save_known_nodes(known)


def load_private_key(node_id: str) -> Ed25519PrivateKey:
    priv_path = _private_key_path(node_id)
    if not priv_path.exists():
        raise FileNotFoundError(
            f"No private key for '{node_id}' at {priv_path}. "
            f"Call generate_node_keypair('{node_id}') first."
        )
    pem = priv_path.read_bytes()
    return serialization.load_pem_private_key(pem, password=None)


def load_known_nodes() -> Dict[str, str]:
    if not KNOWN_NODES_PATH.exists():
        return {}
    return json.loads(KNOWN_NODES_PATH.read_text())


def save_known_nodes(known: Dict[str, str]) -> None:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    KNOWN_NODES_PATH.write_text(json.dumps(known, indent=2, sort_keys=True))


def sign(node_id: str, message: bytes) -> str:
    private_key = load_private_key(node_id)
    signature = private_key.sign(message)
    return signature.hex()


def verify(node_id: str, message: bytes, signature_hex: str) -> bool:
    known = load_known_nodes()
    if node_id not in known:
        return False
    try:
        pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(known[node_id]))
        pub_key.verify(bytes.fromhex(signature_hex), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def ensure_all_node_keys_exist() -> None:
    for node_id in ALL_NODE_IDS:
        generate_node_keypair(node_id, overwrite=False)
