"""
One flight cycle = safety check, then (only if clear) a negotiation
cycle. This mirrors the firmware's `FlightController::loop()`, which
checks the proximity sensor FIRST, unconditionally, and returns
immediately (skipping stabilization) if it trips — see
firmware/common/src/FlightController.cpp. Same shape here: safety first,
negotiation second, never the other way around.

Used by both:
  - Phase 4 tests (call run_flight_cycle directly, assert override
    behavior in isolation)
  - Phase 5 end-to-end test (call it in a loop via flight_runner.py)
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from agent.base import DroneAgent
from agent.coordinator import build_in_flight_block_data, negotiate_cycle
from simulation.safety import build_safety_override_block_data, evaluate_safety_net

ProximityReader = Callable[[float], float]  # (ground_truth_distance_m) -> sensor reading


def run_flight_cycle(
    agent_a: DroneAgent,
    agent_b: DroneAgent,
    drone_a_state: Dict[str, Any],
    drone_b_state: Dict[str, Any],
    ground_truth_distance_m: float,
    node_urls: List[str],
    proximity_reader: Optional[ProximityReader] = None,
    optical_flow_estimated_distance_m: Optional[float] = None,
):
    """Run exactly one flight cycle and commit exactly one in_flight block.

    `ground_truth_distance_m` stands in for the dedicated physical
    proximity sensor (Tier 2's only allowed input).
    `proximity_reader`, if given, transforms it (e.g. to inject a sensor
    fault) — defaults to identity.
    `optical_flow_estimated_distance_m`, if given, is what negotiation
    sees for `estimated_distance_between_drones` instead of the ground
    truth. It is used ONLY if the safety net does not trigger, and is
    NEVER passed to evaluate_safety_net — this is the structural proof
    for Phase 4 DoD #3 (safety trigger is independent of optical-flow
    data, even deliberately wrong optical-flow data).

    Returns (block, cycle_kind) where cycle_kind is "safety_override" or
    "negotiated".
    """
    from blockchain import client as chain_client

    reader = proximity_reader or (lambda d: d)
    proximity_reading = reader(ground_truth_distance_m)

    decision = evaluate_safety_net(proximity_reading)
    if decision.triggered:
        # Tier 2 fires. Agents are never called this cycle — the whole
        # point is not waiting on them (PRD Section 6).
        data = build_safety_override_block_data(drone_a_state, drone_b_state, decision)
        block, _commit_results = chain_client.propose_and_commit(
            node_urls, block_type="in_flight", data=data
        )
        return block, "safety_override"

    # Tier 2 clear -> proceed to Tier 3 negotiation, same as Phase 3.
    negotiation_distance = (
        optical_flow_estimated_distance_m
        if optical_flow_estimated_distance_m is not None
        else ground_truth_distance_m
    )
    result = negotiate_cycle(
        agent_a, agent_b, drone_a_state, drone_b_state, negotiation_distance
    )
    data = build_in_flight_block_data(drone_a_state, drone_b_state, negotiation_distance, result)
    block, _commit_results = chain_client.propose_and_commit(
        node_urls, block_type="in_flight", data=data
    )
    return block, "negotiated"
