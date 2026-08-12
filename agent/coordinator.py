"""
Negotiation coordinator (PRD Section 3 / 6a).

Runs the bounded propose -> counter -> resolve loop between Drone A's and
Drone B's agents, applies the fixed-priority tie-breaker if they don't
converge, and writes the resulting joint decision as a signed in_flight
block (PRD Section 5).

Split into two layers on purpose:
  - negotiate_cycle()       pure negotiation logic, no network/blockchain.
                             Cheap to unit-test exhaustively.
  - run_and_record_cycle()  wraps negotiate_cycle(), builds the in_flight
                             block payload, and commits it to the 3-node
                             chain via blockchain.client (reuses the
                             already-tested Phase 1 commit path — the
                             coordinator's own node process, wherever it
                             runs, holds the coordinator_node key and
                             signs there; see PRD Section 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .base import DroneAgent, Proposal

ROUND_CAP = 2
COLLISION_DISTANCE_THRESHOLD_M = 1.5
TIE_BREAK_WINNER = "drone_a"  # PRD 6a: fixed priority, Drone A wins ties
TIE_BREAK_LOSER_ACTION = "yield_and_pause"  # forced safe fallback for the loser


@dataclass
class NegotiationResult:
    negotiation_log: List[Dict[str, Any]]
    resolution_method: str  # "converged" | "tie_breaker_fixed_priority"
    final_decision: Dict[str, str]  # {"drone_a_action":..., "drone_b_action":...}
    event_type: str  # "normal" | "replanned" | "safety_stop_triggered"


def _conflicts(prop_a: Proposal, prop_b: Proposal, distance_m: float) -> bool:
    """Conflict rule: both drones insist on continuing straight while
    already within the collision-risk distance. Anything else (either
    side slowing, yielding, or rerouting) is treated as resolved, even
    if the two proposals aren't identical — they don't need to match,
    they just need to not both barrel straight through the same space."""
    both_holding_course = prop_a.action == "continue_path" and prop_b.action == "continue_path"
    return both_holding_course and distance_m < COLLISION_DISTANCE_THRESHOLD_M


def _round_entry(round_number: int, prop_a: Proposal, prop_b: Proposal) -> Dict[str, Any]:
    return {
        "round": round_number,
        "drone_a_proposal": prop_a.action,
        "drone_a_reasoning": prop_a.reasoning,
        "drone_b_proposal": prop_b.action,
        "drone_b_reasoning": prop_b.reasoning,
    }


def negotiate_cycle(
    agent_a: DroneAgent,
    agent_b: DroneAgent,
    drone_a_state: Dict[str, Any],
    drone_b_state: Dict[str, Any],
    estimated_distance_m: float,
) -> NegotiationResult:
    """One full negotiation cycle, bounded to ROUND_CAP rounds (PRD 6a).

    Round 1: A proposes first, then B proposes seeing A's round-1 proposal.
    Round 2 (only if round 1 conflicted): both agents revise, each seeing
    the other's round-1 proposal.
    If still conflicting after ROUND_CAP rounds, the fixed-priority
    tie-breaker resolves it: Drone A's last proposal stands, Drone B is
    forced to yield_and_pause.
    """
    log: List[Dict[str, Any]] = []

    prop_a1 = agent_a.propose(
        own_state=drone_a_state,
        other_state=drone_b_state,
        estimated_distance=estimated_distance_m,
        round_number=1,
    )
    prop_b1 = agent_b.propose(
        own_state=drone_b_state,
        other_state=drone_a_state,
        estimated_distance=estimated_distance_m,
        round_number=1,
        other_agent_proposal=prop_a1.to_dict(),
    )
    log.append(_round_entry(1, prop_a1, prop_b1))

    if not _conflicts(prop_a1, prop_b1, estimated_distance_m):
        return NegotiationResult(
            negotiation_log=log,
            resolution_method="converged",
            final_decision={"drone_a_action": prop_a1.action, "drone_b_action": prop_b1.action},
            event_type="normal",
        )

    # Round 2 (counter round) — capped, per PRD 8: "negotiation rounds are
    # capped at 2 per cycle; the fixed-priority tie-breaker must always
    # produce a resolved decision within that bound."
    prop_a2 = agent_a.propose(
        own_state=drone_a_state,
        other_state=drone_b_state,
        estimated_distance=estimated_distance_m,
        round_number=2,
        other_agent_proposal=prop_b1.to_dict(),
        own_prior_proposal=prop_a1.to_dict(),
    )
    prop_b2 = agent_b.propose(
        own_state=drone_b_state,
        other_state=drone_a_state,
        estimated_distance=estimated_distance_m,
        round_number=2,
        other_agent_proposal=prop_a2.to_dict(),
        own_prior_proposal=prop_b1.to_dict(),
    )
    log.append(_round_entry(2, prop_a2, prop_b2))

    if not _conflicts(prop_a2, prop_b2, estimated_distance_m):
        return NegotiationResult(
            negotiation_log=log,
            resolution_method="converged",
            final_decision={"drone_a_action": prop_a2.action, "drone_b_action": prop_b2.action},
            event_type="replanned",
        )

    # Did not converge within ROUND_CAP rounds -> fixed-priority tie-break.
    return NegotiationResult(
        negotiation_log=log,
        resolution_method="tie_breaker_fixed_priority",
        final_decision={
            "drone_a_action": prop_a2.action,
            "drone_b_action": TIE_BREAK_LOSER_ACTION,
        },
        event_type="replanned",
    )


def build_in_flight_block_data(
    drone_a_state: Dict[str, Any],
    drone_b_state: Dict[str, Any],
    estimated_distance_m: float,
    result: NegotiationResult,
) -> Dict[str, Any]:
    """Assemble the in_flight block payload exactly per PRD Section 5's
    schema. `agent_signature` is left for the caller (run_and_record_cycle)
    to fill in once the coordinator has actually signed the block hash —
    it is ordinary payload data, not the chain-level PoA signature."""
    return {
        "drone_a_state": drone_a_state,
        "drone_b_state": drone_b_state,
        "estimated_distance_between_drones": estimated_distance_m,
        "negotiation_log": result.negotiation_log,
        "resolution_method": result.resolution_method,
        "final_decision": result.final_decision,
        "event_type": result.event_type,
    }


def run_and_record_cycle(
    agent_a: DroneAgent,
    agent_b: DroneAgent,
    drone_a_state: Dict[str, Any],
    drone_b_state: Dict[str, Any],
    estimated_distance_m: float,
    node_urls: List[str],
):
    """Full Phase-3 cycle: negotiate, build the in_flight block, and
    commit it to the 3-node chain (majority sign, including the
    coordinator's own node — PRD Section 8). Returns (Block, NegotiationResult).

    Deferred import of blockchain.client so this module stays importable
    (and unit-testable via negotiate_cycle directly) without Flask/requests
    installed, matching how agent/base.py defers importing `anthropic`.
    """
    from blockchain import client as chain_client

    result = negotiate_cycle(
        agent_a, agent_b, drone_a_state, drone_b_state, estimated_distance_m
    )
    data = build_in_flight_block_data(drone_a_state, drone_b_state, estimated_distance_m, result)

    block, commit_results = chain_client.propose_and_commit(
        node_urls, block_type="in_flight", data=data
    )
    return block, result, commit_results
