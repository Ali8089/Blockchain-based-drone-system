"""
Shared logic for a single drone's negotiating agent (PRD Section 3 / 6a).

Each drone gets its OWN DroneAgent instance (see agent_a.py / agent_b.py):
same underlying model, distinct system prompt, distinct local state — each
agent primarily sees its own drone's telemetry plus the other agent's
proposals, never the other drone's raw internal state.

The agent's job each round is narrow: given its own state, the other
drone's state, and (if round 2) what the other agent proposed in round 1,
output ONE structured proposal:

    {"action": "<one of ACTIONS>", "reasoning": "<short string>"}

Action vocabulary is fixed and small on purpose — the negotiation
coordinator needs to mechanically detect conflicts (PRD 6a), which only
works if proposals are structured, not free text.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

ACTIONS = (
    "continue_path",     # proceed on the current planned path, no change
    "reduce_speed",      # keep path, slow down
    "yield_and_pause",   # stop and hold position until the other clears
    "reroute_left",      # deviate left of planned path
    "reroute_right",     # deviate right of planned path
)

MODEL = "claude-sonnet-4-6"


class AgentError(RuntimeError):
    pass


@dataclass
class Proposal:
    action: str
    reasoning: str

    def to_dict(self) -> Dict[str, str]:
        return {"action": self.action, "reasoning": self.reasoning}


class DroneAgent:
    """One drone's negotiating agent. Distinct instance per drone —
    distinct drone_id, distinct system_prompt, distinct call history."""

    def __init__(self, drone_id: str, system_prompt: str, client: Optional[Any] = None):
        self.drone_id = drone_id
        self.system_prompt = system_prompt
        # Injectable client so tests can supply a fake without an API key.
        # Real client is constructed lazily (only when actually calling
        # the API) so importing/instantiating an agent never requires
        # ANTHROPIC_API_KEY to be set.
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AgentError(
                f"[{self.drone_id}] No ANTHROPIC_API_KEY set and no client "
                f"injected. Set the env var to run this agent live, or pass "
                f"a fake client for testing."
            )
        import anthropic  # deferred import: keeps the package importable
        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _call_model(self, user_message: str) -> str:
        client = self._get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

    def propose(
        self,
        own_state: Dict[str, Any],
        other_state: Dict[str, Any],
        estimated_distance: float,
        round_number: int,
        other_agent_proposal: Optional[Dict[str, str]] = None,
        own_prior_proposal: Optional[Dict[str, str]] = None,
    ) -> Proposal:
        """Ask the model for one structured proposal this round.

        round_number 1: no other_agent_proposal yet (agents propose in
        sequence within round 1 per PRD 6a — A first, then B sees A's).
        round_number 2 (counter round): both other_agent_proposal and
        own_prior_proposal are set, since this is a revision.
        """
        context = {
            "your_drone_id": self.drone_id,
            "your_state": own_state,
            "other_drone_state": other_state,
            "estimated_distance_between_drones_m": estimated_distance,
            "round_number": round_number,
            "other_agent_proposal_this_cycle": other_agent_proposal,
            "your_own_prior_proposal_this_cycle": own_prior_proposal,
            "allowed_actions": list(ACTIONS),
        }
        user_message = (
            "Propose your drone's next action for this negotiation round. "
            "Reply with ONLY a JSON object: "
            '{"action": "<one of allowed_actions>", "reasoning": "<short, one sentence>"}. '
            "No other text.\n\n"
            f"Context:\n{json.dumps(context, indent=2)}"
        )
        raw = self._call_model(user_message)
        return self._parse_proposal(raw)

    def _parse_proposal(self, raw: str) -> Proposal:
        raw = raw.strip()
        # Tolerate accidental code-fencing even though the prompt asks
        # for bare JSON — cheap robustness, cost nothing.
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise AgentError(f"[{self.drone_id}] model did not return valid JSON: {raw!r}") from e

        action = parsed.get("action")
        reasoning = parsed.get("reasoning", "")
        if action not in ACTIONS:
            raise AgentError(
                f"[{self.drone_id}] model proposed unknown action {action!r}; "
                f"must be one of {ACTIONS}"
            )
        return Proposal(action=action, reasoning=str(reasoning))
