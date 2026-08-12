"""
A single blockchain node, runnable as its own OS process:

    python -m blockchain.node --node-id gs_node_1 --port 5001
    python -m blockchain.node --node-id gs_node_2 --port 5002
    python -m blockchain.node --node-id coordinator_node --port 5003

Each node is fully independent: it has its own chain, its own signing
key, and its own HTTP server. Killing one node's process does not affect
the others (Phase 1 DoD: "3 node processes run independently and can be
started/stopped individually").

Endpoints
---------
GET  /health            -> {"node_id":..., "status":"ok", "chain_length":N}
GET  /chain              -> full chain as JSON list of blocks
GET  /chain/tip          -> current tip block
POST /validate           -> body: a candidate block (no signatures needed
                             yet). If it's internally consistent and
                             correctly extends this node's chain, the
                             node signs its hash and returns the
                             signature. Does NOT mutate the chain.
POST /commit              -> body: a candidate block WITH >=2 valid
                             signatures attached. Node independently
                             re-verifies everything and, only if it
                             passes, appends it to its own chain.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from flask import Flask, jsonify, request

from . import keys
from .block import Block
from .chain import Chain
from . import consensus


def _default_data_dir() -> Path:
    override = os.environ.get("DRONE_CHAIN_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "chain_data"


DATA_DIR = _default_data_dir()


def create_app(node_id: str, storage_path: Path | None = None) -> Flask:
    if node_id not in keys.ALL_NODE_IDS:
        raise ValueError(f"Unknown node_id '{node_id}'. Must be one of {keys.ALL_NODE_IDS}")

    keys.generate_node_keypair(node_id, overwrite=False)

    app = Flask(node_id)
    app.chain = Chain(storage_path=storage_path)
    app.node_id = node_id

    @app.get("/health")
    def health():
        return jsonify({
            "node_id": node_id,
            "status": "ok",
            "chain_length": len(app.chain.blocks),
            "tip_hash": app.chain.tip.hash,
        })

    @app.get("/chain")
    def get_chain():
        return jsonify(app.chain.to_list())

    @app.get("/chain/tip")
    def get_tip():
        return jsonify(app.chain.tip.to_dict())

    @app.post("/validate")
    def validate():
        payload = request.get_json(force=True)
        try:
            candidate = Block.from_dict(payload)
        except (KeyError, ValueError) as e:
            return jsonify({"accepted": False, "reason": f"malformed_block: {e}"}), 400

        if not candidate.hash_is_valid():
            return jsonify({"accepted": False, "reason": "hash_mismatch"}), 200

        if candidate.previous_hash != app.chain.tip.hash:
            return jsonify({
                "accepted": False,
                "reason": "previous_hash_mismatch",
                "our_tip_hash": app.chain.tip.hash,
            }), 200

        if candidate.index != app.chain.tip.index + 1:
            return jsonify({"accepted": False, "reason": "index_mismatch"}), 200

        signature_hex = keys.sign(node_id, candidate.signable_bytes())
        return jsonify({
            "accepted": True,
            "node_id": node_id,
            "block_hash": candidate.hash,
            "signature": signature_hex,
        })

    @app.post("/commit")
    def commit():
        payload = request.get_json(force=True)
        try:
            candidate = Block.from_dict(payload)
        except (KeyError, ValueError) as e:
            return jsonify({"committed": False, "reason": f"malformed_block: {e}"}), 400

        ok, reason = app.chain.try_append(candidate)
        status = 200 if ok else 409
        return jsonify({
            "committed": ok,
            "reason": reason,
            "node_id": node_id,
            "chain_length": len(app.chain.blocks),
        }), status

    @app.get("/verify_integrity")
    def verify_integrity():
        ok, reason = app.chain.verify_full_chain()
        return jsonify({"valid": ok, "reason": reason})

    return app


def main():
    parser = argparse.ArgumentParser(description="Run a single PoA blockchain node.")
    parser.add_argument("--node-id", required=True, choices=list(keys.ALL_NODE_IDS))
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Keep the chain in memory only (default: persist to chain_data/<node_id>.json)",
    )
    args = parser.parse_args()

    storage_path = None
    if not args.no_persist:
        storage_path = DATA_DIR / f"{args.node_id}.json"

    app = create_app(args.node_id, storage_path=storage_path)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
