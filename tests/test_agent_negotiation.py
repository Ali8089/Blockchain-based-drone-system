"""
Phase 3 DoD tests (PRD Section 9):
  - each agent has its own prompt/state, sees its own drone's data
  - agents exchange proposals and resolve within the 2-round cap
  - fixed-priority tie-breaker fires and resolves correctly on deadlock
  - full transcript (all rounds, both proposals + reasoning) is captured

No ANTHROPIC_API_KEY needed: DroneAgent accepts an injected fake client,
so these test the negotiation *logic* end-to-end against scripted model
responses, per the README's stated Phase 3 plan.
"""

import json

import pytest

from agent.agent_a import create_agent as create_agent_a
from agent.agent_b import create_agent as create_agent_b
from agent.base import AgentError
from agent.coordinator import (
    ROUND_CAP,
    TIE_BREAK_LOSER_ACTION,
    negotiate_cycle,
)


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeTextBlock(text)]


class ScriptedClient:
    """Fake Anthropic client: returns one scripted JSON reply per call,
    in order. Raises if the script runs out (catches missing-call bugs)."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                outer = self._outer
                if not outer._replies:
                    raise AssertionError("ScriptedClient ran out of replies")
                outer.calls += 1
                return FakeResponse(outer._replies.pop(0))

        self.messages = _Messages(self)


def _reply(action, reasoning="because"):
    return json.dumps({"action": action, "reasoning": reasoning})


STATE_A = {"current_position": {"x": 0, "y": 0, "z": 1.5}, "current_waypoint_target": {"x": 5, "y": 0, "z": 1.5}}
STATE_B = {"current_position": {"x": 5, "y": 0, "z": 1.5}, "current_waypoint_target": {"x": 0, "y": 0, "z": 1.5}}


def test_converges_round_1_when_no_collision_risk():
    """Far apart, both want to continue -> no conflict, resolved in round 1."""
    client_a = ScriptedClient([_reply("continue_path")])
    client_b = ScriptedClient([_reply("continue_path")])
    agent_a = create_agent_a(client=client_a)
    agent_b = create_agent_b(client=client_b)

    result = negotiate_cycle(agent_a, agent_b, STATE_A, STATE_B, estimated_distance_m=4.0)

    assert result.resolution_method == "converged"
    assert result.event_type == "normal"
    assert len(result.negotiation_log) == 1
    assert result.final_decision == {"drone_a_action": "continue_path", "drone_b_action": "continue_path"}
    assert client_a.calls == 1 and client_b.calls == 1


def test_converges_round_2_when_one_side_yields_on_counter():
    """Round 1: both continue, close distance -> conflict. Round 2: B yields -> resolved."""
    client_a = ScriptedClient([_reply("continue_path"), _reply("continue_path")])
    client_b = ScriptedClient([_reply("continue_path"), _reply("yield_and_pause")])
    agent_a = create_agent_a(client=client_a)
    agent_b = create_agent_b(client=client_b)

    result = negotiate_cycle(agent_a, agent_b, STATE_A, STATE_B, estimated_distance_m=1.0)

    assert result.resolution_method == "converged"
    assert result.event_type == "replanned"
    assert len(result.negotiation_log) == 2
    assert result.final_decision == {"drone_a_action": "continue_path", "drone_b_action": "yield_and_pause"}
    # both agents actually called twice -> genuine round 2, not skipped
    assert client_a.calls == 2 and client_b.calls == 2


def test_tie_breaker_fires_when_agents_never_converge():
    """Both sides stubbornly continue for both rounds -> deadlock ->
    fixed-priority tie-break: Drone A's proposal stands, B forced to yield."""
    client_a = ScriptedClient([_reply("continue_path"), _reply("continue_path")])
    client_b = ScriptedClient([_reply("continue_path"), _reply("continue_path")])
    agent_a = create_agent_a(client=client_a)
    agent_b = create_agent_b(client=client_b)

    result = negotiate_cycle(agent_a, agent_b, STATE_A, STATE_B, estimated_distance_m=0.8)

    assert result.resolution_method == "tie_breaker_fixed_priority"
    assert result.final_decision["drone_a_action"] == "continue_path"
    assert result.final_decision["drone_b_action"] == TIE_BREAK_LOSER_ACTION
    # exactly ROUND_CAP rounds happened, never more
    assert len(result.negotiation_log) == ROUND_CAP


def test_transcript_captures_both_proposals_and_reasoning_every_round():
    client_a = ScriptedClient([_reply("continue_path", "shortest path"), _reply("continue_path", "still shortest")])
    client_b = ScriptedClient([_reply("continue_path", "shortest path"), _reply("continue_path", "still shortest")])
    agent_a = create_agent_a(client=client_a)
    agent_b = create_agent_b(client=client_b)

    result = negotiate_cycle(agent_a, agent_b, STATE_A, STATE_B, estimated_distance_m=0.5)

    for round_entry in result.negotiation_log:
        assert set(round_entry.keys()) == {
            "round", "drone_a_proposal", "drone_a_reasoning",
            "drone_b_proposal", "drone_b_reasoning",
        }
        assert round_entry["drone_a_reasoning"]
        assert round_entry["drone_b_reasoning"]


def test_agents_have_distinct_state_and_prompts():
    """Each agent only gets told its OWN state as 'your_state' — sanity
    check they're genuinely separate instances, not shared state."""
    agent_a = create_agent_a(client=ScriptedClient([_reply("continue_path")]))
    agent_b = create_agent_b(client=ScriptedClient([_reply("continue_path")]))

    assert agent_a.drone_id == "drone_a"
    assert agent_b.drone_id == "drone_b"
    assert agent_a.system_prompt != agent_b.system_prompt
    assert agent_a is not agent_b


def test_no_api_key_needed_to_construct_agents():
    """Constructing an agent (no API call yet) must never require
    ANTHROPIC_API_KEY — only actually calling the model does."""
    agent_a = create_agent_a()
    agent_b = create_agent_b()
    assert agent_a.drone_id == "drone_a"
    assert agent_b.drone_id == "drone_b"


def test_missing_api_key_raises_clear_error_when_actually_calling(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent_a = create_agent_a()
    with pytest.raises(AgentError):
        agent_a.propose(STATE_A, STATE_B, estimated_distance=4.0, round_number=1)


def test_rejects_action_outside_allowed_vocabulary():
    bad_client = ScriptedClient([_reply("fly_into_wall")])
    agent_a = create_agent_a(client=bad_client)
    with pytest.raises(AgentError):
        agent_a.propose(own_state=STATE_A, other_state=STATE_B, estimated_distance=4.0, round_number=1)
