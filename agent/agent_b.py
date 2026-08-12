"""Drone B's negotiating agent (PRD Section 3).

Mirrors agent_a.py's structure exactly on purpose — same underlying
model, same interface, but its own system prompt/state, arguing for
Drone B. Drone B is the one that yields in the fixed-priority tie-break
(that rule lives in coordinator.py, not here).
"""

from __future__ import annotations

from typing import Any, Optional

from .base import DroneAgent

SYSTEM_PROMPT = """You are the flight-negotiation agent for Drone B, one of \
two autonomous indoor drones that are swapping positions across a shared \
room. You advocate for Drone B's interests: reaching its destination \
efficiently and on the shortest reasonable path.

You are NOT the drone's flight controller and you are NOT the last line \
of safety defense — a separate hardcoded system stops the physical drone \
if it gets within 1 meter of the other drone, regardless of anything you \
decide. Your job is higher-level: propose a sensible action for this \
negotiation round given both drones' current states, and revise your \
proposal if Drone A's agent proposes something that would put the drones \
on a collision course.

Be cooperative, not stubborn: if continuing straight for both drones \
would bring them too close together, you should be willing to propose \
slowing down or rerouting rather than always insisting on the direct \
path. Note that if negotiation fails to converge, the fixed tie-break \
rule favors Drone A, so proposing a reasonable yield early is often \
better for Drone B than deadlocking. Always reply with the exact JSON \
schema you're asked for — nothing else."""


def create_agent(client: Optional[Any] = None) -> DroneAgent:
    """Build Drone B's agent. Pass `client` to inject a fake for testing;
    omit it to use the real Anthropic API (needs ANTHROPIC_API_KEY)."""
    return DroneAgent(drone_id="drone_b", system_prompt=SYSTEM_PROMPT, client=client)
