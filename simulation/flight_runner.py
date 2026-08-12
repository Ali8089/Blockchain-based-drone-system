"""
Phase 5 — end-to-end flight: pre-flight blocks, a loop of flight cycles
(safety-checked first, negotiated second — see flight_cycle.py) driving
the simulated drones to their destinations, then post-flight summary
blocks. This is the PRD Section 7 "full swap-position scenario runs
start to finish" test target, wired together from Phases 1-4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from agent.base import DroneAgent
from simulation.flight_cycle import run_flight_cycle
from simulation.sim_drones import Simulation


def _state_of(sim: Simulation, drone_id: str) -> Dict[str, Any]:
    d = sim.get_drone(drone_id)
    return {
        "current_position": {"x": d.position[0], "y": d.position[1], "z": d.position[2]},
        "current_waypoint_target": {"x": d.destination[0], "y": d.destination[1], "z": d.destination[2]},
    }


def _write_pre_flight_blocks(sim: Simulation, node_urls: List[str]) -> Dict[str, Any]:
    from blockchain import client as chain_client

    blocks = {}
    for drone_id in ("drone_a", "drone_b"):
        d = sim.get_drone(drone_id)
        block, _ = chain_client.propose_and_commit(
            node_urls,
            block_type="pre_flight",
            data={
                "drone_id": drone_id,
                "start_position": {"x": d.position[0], "y": d.position[1], "z": d.position[2]},
                "destination_position": {"x": d.destination[0], "y": d.destination[1], "z": d.destination[2]},
                "planned_path": [{"x": p[0], "y": p[1], "z": p[2]} for p in [d.position, d.destination]],
                "max_speed": d.max_speed,
                "safety_trigger_distance_m": 1.0,
            },
        )
        blocks[drone_id] = block
    return blocks


def _write_post_flight_blocks(
    sim: Simulation, node_urls: List[str], flight_time_s: float, cycle_blocks: List[Any]
) -> Dict[str, Any]:
    from blockchain import client as chain_client

    number_of_replans = sum(1 for b in cycle_blocks if b.data.get("event_type") == "replanned")
    number_of_safety_stops = sum(
        1 for b in cycle_blocks if b.data.get("event_type") == "safety_stop_triggered"
    )
    number_of_tie_breaker_resolutions = sum(
        1 for b in cycle_blocks if b.data.get("resolution_method") == "tie_breaker_fixed_priority"
    )

    blocks = {}
    for drone_id in ("drone_a", "drone_b"):
        d = sim.get_drone(drone_id)
        block, _ = chain_client.propose_and_commit(
            node_urls,
            block_type="post_flight",
            data={
                "drone_id": drone_id,
                "total_flight_time_s": flight_time_s,
                "final_position": {"x": d.position[0], "y": d.position[1], "z": d.position[2]},
                "path_actually_flown": [{"x": p[0], "y": p[1], "z": p[2]} for p in d.path_history],
                "number_of_replans": number_of_replans,
                "number_of_safety_stops": number_of_safety_stops,
                "number_of_tie_breaker_resolutions": number_of_tie_breaker_resolutions,
                "summary": (
                    f"{drone_id} completed the swap in {flight_time_s:.1f}s across "
                    f"{len(cycle_blocks)} negotiation cycle(s); {number_of_replans} replan(s), "
                    f"{number_of_safety_stops} safety stop(s), "
                    f"{number_of_tie_breaker_resolutions} tie-break(s)."
                ),
            },
        )
        blocks[drone_id] = block
    return blocks


@dataclass
class FlightRunResult:
    pre_flight_blocks: Dict[str, Any]
    cycle_blocks: List[Any] = field(default_factory=list)
    cycle_kinds: List[str] = field(default_factory=list)
    post_flight_blocks: Dict[str, Any] = field(default_factory=dict)
    steps_taken: int = 0


def run_full_flight(
    sim: Simulation,
    agent_a: DroneAgent,
    agent_b: DroneAgent,
    node_urls: List[str],
    steps_per_cycle: int = 1,
    max_cycles: int = 200,
) -> FlightRunResult:
    """Drive `sim` to completion, writing the full pre/in-flight/post
    blockchain record as it goes. One flight cycle (safety check, then
    negotiation if clear) happens per iteration, followed by
    `steps_per_cycle` physical simulation steps.
    """
    pre_flight_blocks = _write_pre_flight_blocks(sim, node_urls)

    cycle_blocks: List[Any] = []
    cycle_kinds: List[str] = []
    cycles = 0
    while not sim.all_arrived() and cycles < max_cycles:
        distance = sim.distance_between("drone_a", "drone_b")
        block, kind = run_flight_cycle(
            agent_a,
            agent_b,
            _state_of(sim, "drone_a"),
            _state_of(sim, "drone_b"),
            ground_truth_distance_m=distance,
            node_urls=node_urls,
        )
        cycle_blocks.append(block)
        cycle_kinds.append(kind)
        cycles += 1

        for _ in range(steps_per_cycle):
            if sim.all_arrived():
                break
            sim.step()

    post_flight_blocks = _write_post_flight_blocks(
        sim, node_urls, sim.time_elapsed, cycle_blocks
    )

    return FlightRunResult(
        pre_flight_blocks=pre_flight_blocks,
        cycle_blocks=cycle_blocks,
        cycle_kinds=cycle_kinds,
        post_flight_blocks=post_flight_blocks,
        steps_taken=cycles,
    )
