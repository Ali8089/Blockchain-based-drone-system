"""
Client-side helper for proposing a block to the 3-node PoA network.

Used by: tests, and (in Phase 3) the negotiation coordinator, which is
itself one of the 3 signing nodes but still needs to gather the *other*
two nodes' signatures over HTTP before a block can be committed anywhere.

This module only speaks HTTP to node.py processes — it has no special
access to any node's private key beyond whichever single node_id the
caller says "I am" (used only to also self-sign locally, mirroring what
that node's own /validate would produce).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import requests

from .block import Block
from . import consensus


class ProposalFailed(Exception):
    pass


def get_tip(node_url: str) -> dict:
    resp = requests.get(f"{node_url}/chain/tip", timeout=5)
    resp.raise_for_status()
    return resp.json()


def request_signature(node_url: str, block: Block) -> Optional[Tuple[str, str]]:
    """Ask one node to validate+sign `block`. Returns (node_id, signature)
    or None if that node declined."""
    resp = requests.post(f"{node_url}/validate", json=block.to_dict(), timeout=5)
    body = resp.json()
    if body.get("accepted"):
        return body["node_id"], body["signature"]
    return None


def commit_to_all(node_urls: List[str], block: Block) -> Dict[str, dict]:
    results = {}
    for url in node_urls:
        try:
            resp = requests.post(f"{url}/commit", json=block.to_dict(), timeout=5)
            results[url] = resp.json()
        except requests.RequestException as e:
            results[url] = {"committed": False, "reason": f"request_failed: {e}"}
    return results


def propose_and_commit(
    node_urls: List[str],
    block_type: str,
    data: dict,
) -> Tuple[Block, Dict[str, dict]]:
    """End-to-end: fetch tip, build block, collect signatures from all
    reachable nodes, and — once >=2 valid signatures are gathered —
    commit the signed block to every node. Raises ProposalFailed if
    majority signatures can't be gathered."""
    if not node_urls:
        raise ProposalFailed("no node_urls provided")

    tip = get_tip(node_urls[0])
    candidate = Block(
        index=tip["index"] + 1,
        block_type=block_type,
        data=data,
        previous_hash=tip["hash"],
    )

    for url in node_urls:
        sig = request_signature(url, candidate)
        if sig:
            node_id, signature_hex = sig
            candidate.add_signature(node_id, signature_hex)

    if not consensus.has_majority(candidate):
        raise ProposalFailed(
            f"could not gather majority signatures; got {list(candidate.signatures.keys())}"
        )

    commit_results = commit_to_all(node_urls, candidate)
    return candidate, commit_results
