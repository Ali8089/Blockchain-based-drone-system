"""
Phase 5 DoD tests (PRD Section 9):
  - full swap-position scenario runs start to finish without crashing
  - pre-flight, in-flight (with negotiation transcripts), and post-flight
    blocks are all present and well-formed by the end of a run
  - paths cross in the middle and a collision-avoidance event is
    observed in the block log
  - the full flight's blockchain history can be replayed/read back and
    makes narrative sense, including negotiation transcripts

Uses scripted (fake) agent clients, same approach as Phase 3/4 tests, so
this runs with no ANTHROPIC_API_KEY. Uses three real blockchain node
subprocesses (tests/conftest.py's three_live_nodes) so the "committed to
an actual chain, read back over HTTP" claim is genuine, not mocked.
"""

from __future__ import annotations

import json

import requests

from agent.agent_a import create_agent as create_agent_a
from agent.agent_b import create_agent as create_agent_b
from simulation.flight_runner import run_full_flight
from simulation.sim_drones import RoomBounds, make_swap_scenario


def _reply(action, reasoning="ok"):
    return json.dumps({"action": action, "reasoning": reasoning})


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeTextBlock(text)]


class ScriptedClient:
    """Cycles through a script of replies; once exhausted, keeps
    repeating the last one (a full flight's cycle count depends on when
    distance crosses thresholds, which we don't want to hand-count)."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                outer = self._outer
                outer.calls += 1
                reply = outer._replies[min(outer.calls - 1, len(outer._replies) - 1)]
                return FakeResponse(reply)

        self.messages = _Messages(self)


def test_full_swap_scenario_runs_start_to_finish(three_live_nodes):
    node_urls = [n.url for n in three_live_nodes]

    # Small room + coarse steps so the crossing happens within a handful
    # of cycles: deterministic and fast, without hand-tuning exact counts.
    bounds = RoomBounds(x_min=0, x_max=3, y_min=0, y_max=3, z_min=0, z_max=2)
    sim = make_swap_scenario(bounds=bounds, max_speed=1.0, dt=0.4)

    # Both agents cooperative: continue while far apart, yield when close.
    # This produces at least one 'continue_path' cycle and at least one
    # 'yield_and_pause' cycle as the drones cross near the middle.
    agent_a = create_agent_a(client=ScriptedClient([
        _reply("continue_path"), _reply("continue_path"), _reply("continue_path"),
        _reply("reduce_speed"), _reply("continue_path"),
    ]))
    agent_b = create_agent_b(client=ScriptedClient([
        _reply("continue_path"), _reply("continue_path"), _reply("yield_and_pause"),
        _reply("continue_path"), _reply("continue_path"),
    ]))

    result = run_full_flight(sim, agent_a, agent_b, node_urls, steps_per_cycle=1, max_cycles=100)

    # --- ran to completion without crashing ---
    assert sim.all_arrived()
    assert result.steps_taken > 0
    assert result.steps_taken < 100  # didn't hit the safety cap

    # --- pre-flight blocks present, one per drone, well-formed ---
    assert set(result.pre_flight_blocks.keys()) == {"drone_a", "drone_b"}
    for drone_id, block in result.pre_flight_blocks.items():
        assert block.block_type == "pre_flight"
        assert block.data["drone_id"] == drone_id
        assert block.hash_is_valid()
        assert len(block.signatures) >= 2

    # --- in-flight blocks present, with transcripts, well-formed ---
    assert len(result.cycle_blocks) == result.steps_taken
    for block in result.cycle_blocks:
        assert block.block_type == "in_flight"
        assert block.hash_is_valid()
        assert len(block.signatures) >= 2
        assert "final_decision" in block.data
        assert "negotiation_log" in block.data  # present even if empty (safety-override cycles)

    # --- post-flight blocks present, one per drone, well-formed ---
    assert set(result.post_flight_blocks.keys()) == {"drone_a", "drone_b"}
    for drone_id, block in result.post_flight_blocks.items():
        assert block.block_type == "post_flight"
        assert block.data["drone_id"] == drone_id
        assert block.data["total_flight_time_s"] > 0
        assert len(block.data["path_actually_flown"]) >= 2
        assert block.hash_is_valid()

    # --- paths actually crossed near the middle (genuine swap, not a
    #     no-op) — final positions are near each other's start ---
    drone_a = sim.get_drone("drone_a")
    drone_b = sim.get_drone("drone_b")
    assert drone_a.has_arrived()
    assert drone_b.has_arrived()

    # --- collision-avoidance event observed: at least one cycle where
    #     the drones didn't both just blindly continue (either a
    #     negotiated non-continue action, or a safety override) ---
    non_continue_cycles = [
        b for b in result.cycle_blocks
        if b.data["final_decision"]["drone_a_action"] != "continue_path"
        or b.data["final_decision"]["drone_b_action"] != "continue_path"
    ]
    assert len(non_continue_cycles) >= 1, "expected at least one collision-avoidance event"

    # --- full history can be read back from a live node and makes
    #     narrative sense: genesis, then pre-flight x2, in-flight xN,
    #     post-flight x2, in that order, hash-chained correctly ---
    chain = requests.get(f"{node_urls[0]}/chain", timeout=5).json()
    block_types_in_order = [b["block_type"] for b in chain]
    assert block_types_in_order[0] == "genesis"
    assert block_types_in_order.count("pre_flight") == 2
    assert block_types_in_order.count("in_flight") == result.steps_taken
    assert block_types_in_order.count("post_flight") == 2
    assert block_types_in_order[-2:] == ["post_flight", "post_flight"]

    for i in range(1, len(chain)):
        assert chain[i]["previous_hash"] == chain[i - 1]["hash"], (
            f"chain broken between block {i - 1} and {i}"
        )

    # every other live node agrees on the exact same history
    for n in three_live_nodes[1:]:
        other_chain = requests.get(f"{n.url}/chain", timeout=5).json()
        assert [b["hash"] for b in other_chain] == [b["hash"] for b in chain]
