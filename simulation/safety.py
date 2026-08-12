"""
Phase 4 — hardcoded safety net (PRD Section 6, Tier 2), simulation version.

This is a stand-in for what later runs directly on the ESP32: a simple,
non-negotiable rule that stops both drones the instant a proximity
reading drops below 1 meter. Nothing here calls an LLM, waits on a
negotiation, or reads the blockchain — that's the whole point (PRD
Section 8: "must never be bypassed or gated by the agents or negotiation
coordinator").

Independence from optical-flow position estimates (PRD Section 6):
`evaluate_safety_net()` takes a single `proximity_reading_m` float and
nothing else. It has no idea what the agents proposed, what the
negotiation's `estimated_distance_between_drones` said, or what either
drone's optical-flow-derived position claims. That's a structural
guarantee, not just a convention — there's no shared state for a bug to
accidentally leak through.
"""

from __future__ import annotations

from dataclasses import dataclass

TRIGGER_DISTANCE_M = 1.0

# Action forced on both drones the moment the safety net fires. Reusing
# "yield_and_pause" from agent.base.ACTIONS rather than inventing a new
# action keeps the in-flight block's final_decision field validating
# against the same vocabulary everywhere.
SAFETY_OVERRIDE_ACTION = "yield_and_pause"


@dataclass
class SafetyDecision:
    triggered: bool
    proximity_reading_m: float
    trigger_distance_m: float
    reason: str


def evaluate_safety_net(
    proximity_reading_m: float, trigger_distance_m: float = TRIGGER_DISTANCE_M
) -> SafetyDecision:
    """The Tier 2 rule itself: trigger if the (sole) proximity reading is
    below the trigger distance. Fail-safe on a bad reading, mirroring
    FlightController::readProximityMeters() in firmware — a NaN or
    negative reading (sensor fault stand-in) is treated as "dangerously
    close", never as "clear to fly"."""
    if proximity_reading_m != proximity_reading_m or proximity_reading_m < 0:  # NaN or negative
        return SafetyDecision(
            triggered=True,
            proximity_reading_m=proximity_reading_m,
            trigger_distance_m=trigger_distance_m,
            reason=f"invalid_sensor_reading({proximity_reading_m!r}) -> fail-safe stop",
        )
    triggered = proximity_reading_m < trigger_distance_m
    reason = (
        f"proximity {proximity_reading_m:.2f}m < trigger {trigger_distance_m:.2f}m"
        if triggered
        else f"proximity {proximity_reading_m:.2f}m clear (trigger {trigger_distance_m:.2f}m)"
    )
    return SafetyDecision(
        triggered=triggered,
        proximity_reading_m=proximity_reading_m,
        trigger_distance_m=trigger_distance_m,
        reason=reason,
    )


def build_safety_override_block_data(
    drone_a_state: dict, drone_b_state: dict, decision: SafetyDecision
) -> dict:
    """In-flight block payload for a cycle where the safety net fired.
    negotiation_log is deliberately empty: the whole point of Tier 2 is
    that it does not wait for a negotiation to run or conclude (PRD
    Section 6) — a real trigger short-circuits the cycle before the
    agents are ever called."""
    return {
        "drone_a_state": drone_a_state,
        "drone_b_state": drone_b_state,
        "estimated_distance_between_drones": decision.proximity_reading_m,
        "negotiation_log": [],
        "resolution_method": "safety_override",
        "final_decision": {
            "drone_a_action": SAFETY_OVERRIDE_ACTION,
            "drone_b_action": SAFETY_OVERRIDE_ACTION,
        },
        "event_type": "safety_stop_triggered",
        "safety_override_reason": decision.reason,
    }
