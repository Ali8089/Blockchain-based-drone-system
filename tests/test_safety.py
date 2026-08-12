"""
Phase 4 DoD tests (PRD Section 9):
  - hardcoded rule triggers reliably when proximity < 1m
  - safety net overrides/interrupts an in-progress or unresolved
    negotiation, provably
  - safety trigger is proven independent of optical-flow position data
    (deliberately-wrong optical-flow test case)
"""

from __future__ import annotations

import json

from agent.agent_a import create_agent as create_agent_a
from agent.agent_b import create_agent as create_agent_b
from simulation.flight_cycle import run_flight_cycle
from simulation.safety import TRIGGER_DISTANCE_M, evaluate_safety_net


STATE_A = {"current_position": {"x": 0, "y": 0, "z": 1.5}, "current_waypoint_target": {"x": 5, "y": 0, "z": 1.5}}
STATE_B = {"current_position": {"x": 0.5, "y": 0, "z": 1.5}, "current_waypoint_target": {"x": 0, "y": 0, "z": 1.5}}


# ---- pure evaluate_safety_net() tests: no blockchain/agents needed ----

def test_triggers_below_threshold():
    decision = evaluate_safety_net(0.5)
    assert decision.triggered is True


def test_does_not_trigger_at_or_above_threshold():
    assert evaluate_safety_net(TRIGGER_DISTANCE_M).triggered is False
    assert evaluate_safety_net(TRIGGER_DISTANCE_M + 0.01).triggered is False


def test_reliable_across_a_range_of_close_distances():
    for d in (0.99, 0.5, 0.2, 0.0, 0.01):
        assert evaluate_safety_net(d).triggered is True, f"should trigger at {d}m"
    for d in (1.0, 1.5, 3.0, 10.0):
        assert evaluate_safety_net(d).triggered is False, f"should not trigger at {d}m"


def test_fails_safe_on_invalid_sensor_reading():
    """A broken/unreadable sensor must be treated as danger, not as clear."""
    assert evaluate_safety_net(-1.0).triggered is True
    assert evaluate_safety_net(float("nan")).triggered is True


# ---- run_flight_cycle() tests: real blockchain, need three_live_nodes ----

class ScriptedTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class ScriptedResponse:
    def __init__(self, text):
        self.content = [ScriptedTextBlock(text)]


class NeverCalledClient:
    """Agent client that fails the test if the model is ever actually
    called — used to prove the safety override skips the agents
    entirely, rather than calling them and then discarding the result."""

    class _Messages:
        def create(self, **kwargs):
            raise AssertionError(
                "Agent was called during a safety-override cycle — Tier 2 "
                "must never wait on or invoke the negotiation layer."
            )

    def __init__(self):
        self.messages = self._Messages()


def test_safety_override_bypasses_negotiation_entirely(three_live_nodes):
    """Proximity below 1m -> safety fires -> agents are never called, and
    the committed block records a safety_stop_triggered override, not a
    negotiated decision. This is the 'overrides an unresolved negotiation'
    DoD item: negotiation doesn't even get the chance to conclude."""
    node_urls = [n.url for n in three_live_nodes]
    agent_a = create_agent_a(client=NeverCalledClient())
    agent_b = create_agent_b(client=NeverCalledClient())

    block, kind = run_flight_cycle(
        agent_a, agent_b, STATE_A, STATE_B,
        ground_truth_distance_m=0.4,
        node_urls=node_urls,
    )

    assert kind == "safety_override"
    assert block.data["event_type"] == "safety_stop_triggered"
    assert block.data["resolution_method"] == "safety_override"
    assert block.data["final_decision"] == {
        "drone_a_action": "yield_and_pause",
        "drone_b_action": "yield_and_pause",
    }
    assert block.data["negotiation_log"] == []  # negotiation never ran


def test_clear_proximity_proceeds_to_normal_negotiation(three_live_nodes):
    """Sanity check the other branch: when proximity is fine, agents ARE
    called and a negotiated (not override) block is committed."""
    node_urls = [n.url for n in three_live_nodes]

    def _reply(action):
        return ScriptedResponse(json.dumps({"action": action, "reasoning": "clear"}))

    class OneShotClient:
        def __init__(self, action):
            class _Messages:
                def create(self, **kwargs):
                    return _reply(action)
            self.messages = _Messages()

    agent_a = create_agent_a(client=OneShotClient("continue_path"))
    agent_b = create_agent_b(client=OneShotClient("continue_path"))

    block, kind = run_flight_cycle(
        agent_a, agent_b, STATE_A, STATE_B,
        ground_truth_distance_m=4.0,
        node_urls=node_urls,
    )

    assert kind == "negotiated"
    assert block.data["event_type"] == "normal"
    assert len(block.data["negotiation_log"]) == 1


def test_safety_trigger_independent_of_wrong_optical_flow_data(three_live_nodes):
    """Deliberately-wrong optical-flow test case (Phase 4 DoD #3): the
    negotiation-facing 'optical flow' distance claims the drones are far
    apart (10m, would never trigger anything), but the ground-truth
    proximity-sensor reading says 0.3m. The safety net must still fire,
    because it never looks at the optical-flow value at all."""
    node_urls = [n.url for n in three_live_nodes]
    agent_a = create_agent_a(client=NeverCalledClient())
    agent_b = create_agent_b(client=NeverCalledClient())

    block, kind = run_flight_cycle(
        agent_a, agent_b, STATE_A, STATE_B,
        ground_truth_distance_m=0.3,  # what the physical sensor reports
        node_urls=node_urls,
        optical_flow_estimated_distance_m=10.0,  # deliberately wrong/misleading
    )

    assert kind == "safety_override"
    assert block.data["event_type"] == "safety_stop_triggered"
    # the wrong optical-flow number never even appears in this block,
    # since negotiation (the only consumer of that value) never ran
    assert block.data["estimated_distance_between_drones"] == 0.3
