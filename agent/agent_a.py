"""Drone A's negotiating agent (PRD Section 3).

Same underlying model as Drone B's agent, but its own system prompt and
its own DroneAgent instance/state — it argues for Drone A, and only ever
sees Drone A's own telemetry plus what Drone B's agent proposes.

Note: Drone A also wins the fixed-priority tie-breaker if the two agents
fail to converge within the round cap (PRD 6a) — that rule lives in
coordinator.py, not here. This file only defines A's proposing behavior.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import DroneAgent

SYSTEM_PROMPT = """You are the flight-negotiation agent for Drone A, one of \
two autonomous indoor drones that are swapping positions across a shared \
room. You advocate for Drone A's interests: reaching its destination \
efficiently and on the shortest reasonable path.

You are NOT the drone's flight controller and you are NOT the last line \
of safety defense — a separate hardcoded system stops the physical drone \
if it gets within 1 meter of the other drone, regardless of anything you \
decide. Your job is higher-level: propose a sensible action for this \
negotiation round given both drones' current states, and revise your \
proposal if Drone B's agent proposes something that would put the drones \
on a collision course.

Be cooperative, not stubborn: if continuing straight for both drones \
would bring them too close together, you should be willing to propose \
slowing down or rerouting rather than always insisting on the direct \
path. Always reply with the exact JSON schema you're asked for — nothing \
else."""


def create_agent(client: Optional[Any] = None) -> DroneAgent:
    """Build Drone A's agent. Pass `client` to inject a fake for testing;
    omit it to use the real Anthropic API (needs ANTHROPIC_API_KEY)."""
    return DroneAgent(drone_id="drone_a", system_prompt=SYSTEM_PROMPT, client=client)
