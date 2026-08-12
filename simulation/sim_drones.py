"""
Fake drones with simulated positions moving through 3D space (PRD Phase 2).

No real hardware, no UWB yet — this is purely a kinematic stand-in used to
build and test the blockchain/negotiation/safety pipeline before any
firmware exists. Room bounds are a constructor parameter, not a constant,
so scenarios can target whatever real room gets used later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

Position = Tuple[float, float, float]


@dataclass
class RoomBounds:
    """Configurable room dimensions. PRD Section 10 gives 5m x 5m x 3m as
    a placeholder default, explicitly meant to be adjusted later."""
    x_min: float = 0.0
    x_max: float = 5.0
    y_min: float = 0.0
    y_max: float = 5.0
    z_min: float = 0.0
    z_max: float = 3.0

    def clamp(self, pos: Position) -> Position:
        x, y, z = pos
        return (
            min(max(x, self.x_min), self.x_max),
            min(max(y, self.y_min), self.y_max),
            min(max(z, self.z_min), self.z_max),
        )

    def contains(self, pos: Position, eps: float = 1e-6) -> bool:
        x, y, z = pos
        return (
            self.x_min - eps <= x <= self.x_max + eps
            and self.y_min - eps <= y <= self.y_max + eps
            and self.z_min - eps <= z <= self.z_max + eps
        )


def _dist(a: Position, b: Position) -> float:
    return float(np.linalg.norm(np.array(a, dtype=float) - np.array(b, dtype=float)))


@dataclass
class SimDrone:
    drone_id: str
    position: Position
    destination: Position
    max_speed: float = 1.0  # m/s
    path_history: List[Position] = field(default_factory=list)

    def __post_init__(self):
        if not self.path_history:
            self.path_history.append(self.position)

    def distance_to_destination(self) -> float:
        return _dist(self.position, self.destination)

    def has_arrived(self, tol: float = 0.05) -> bool:
        return self.distance_to_destination() <= tol

    def step(self, dt: float, bounds: RoomBounds) -> None:
        if self.has_arrived():
            return
        direction = np.array(self.destination, dtype=float) - np.array(self.position, dtype=float)
        dist = np.linalg.norm(direction)
        if dist < 1e-9:
            return
        unit_dir = direction / dist
        step_dist = min(self.max_speed * dt, dist)
        new_pos = np.array(self.position, dtype=float) + unit_dir * step_dist
        self.position = bounds.clamp(tuple(new_pos.tolist()))
        self.path_history.append(self.position)


class Simulation:
    def __init__(self, drones: List[SimDrone], bounds: RoomBounds, dt: float = 0.1):
        self.drones = drones
        self.bounds = bounds
        self.dt = dt
        self.time_elapsed = 0.0

    def step(self) -> None:
        for d in self.drones:
            d.step(self.dt, self.bounds)
        self.time_elapsed += self.dt

    def all_arrived(self, tol: float = 0.05) -> bool:
        return all(d.has_arrived(tol) for d in self.drones)

    def get_drone(self, drone_id: str) -> SimDrone:
        return next(d for d in self.drones if d.drone_id == drone_id)

    def distance_between(self, id_a: str, id_b: str) -> float:
        return _dist(self.get_drone(id_a).position, self.get_drone(id_b).position)

    def run(self, max_steps: int = 10_000, tol: float = 0.05) -> int:
        """Step until every drone has arrived (or max_steps is hit).
        Returns the number of steps actually taken."""
        steps = 0
        while not self.all_arrived(tol) and steps < max_steps:
            self.step()
            steps += 1
        return steps


def make_swap_scenario(
    bounds: RoomBounds | None = None,
    max_speed: float = 1.0,
    dt: float = 0.1,
    flight_height: float | None = None,
) -> Simulation:
    """The scenario described in the PRD: two drones swap positions so
    their flight paths cross in the middle of the room.

    Uses opposite (not identical-diagonal) corner pairs — A goes
    bottom-left -> top-right, B goes bottom-right -> top-left — so the
    two straight-line paths form a genuine X crossing near room center,
    rather than perfectly overlapping on the same line. That's both a
    clearer visual and a more representative case for later negotiation/
    collision-avoidance work (an angled conflict, not just a symmetric
    head-on one).
    """
    bounds = bounds or RoomBounds()
    z = flight_height if flight_height is not None else (bounds.z_min + bounds.z_max) / 2

    margin = 0.5
    a_start = (bounds.x_min + margin, bounds.y_min + margin, z)
    a_dest = (bounds.x_max - margin, bounds.y_max - margin, z)
    b_start = (bounds.x_max - margin, bounds.y_min + margin, z)
    b_dest = (bounds.x_min + margin, bounds.y_max - margin, z)

    drone_a = SimDrone("drone_a", position=a_start, destination=a_dest, max_speed=max_speed)
    drone_b = SimDrone("drone_b", position=b_start, destination=b_dest, max_speed=max_speed)
    return Simulation([drone_a, drone_b], bounds, dt=dt)
