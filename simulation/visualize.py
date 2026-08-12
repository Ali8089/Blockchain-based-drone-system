"""
matplotlib visualization for the simulation harness (PRD Phase 2).

This runs headless (no display attached), so "shows both drones' positions
updating" is delivered as a saved animated GIF (a real frame-by-frame
record of positions changing over time — not just a single static plot),
plus a static path-summary image useful for quick inspection and for the
Phase 10 analysis report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # headless: no display in this environment
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 (registers the '3d' projection)

from .sim_drones import Simulation

COLORS = {"drone_a": "tab:blue", "drone_b": "tab:orange"}


def _setup_3d_axes(ax, sim: Simulation, title: str) -> None:
    b = sim.bounds
    ax.set_xlim(b.x_min, b.x_max)
    ax.set_ylim(b.y_min, b.y_max)
    ax.set_zlim(b.z_min, b.z_max)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_zlabel("z (m)")
    ax.set_title(title)


def animate_simulation(
    sim: Simulation,
    out_path: Path,
    fps: int = 20,
    run_to_completion: bool = True,
    max_steps: int = 10_000,
) -> Path:
    """Run `sim` (if not already finished) while positions accumulate in
    each drone's path_history, then render an animated GIF of both
    drones moving through 3D space, frame by frame."""
    if run_to_completion:
        sim.run(max_steps=max_steps)

    n_frames = max(len(d.path_history) for d in sim.drones)

    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, projection="3d")
    _setup_3d_axes(ax, sim, "Two-drone flight simulation")

    lines, points = {}, {}
    for d in sim.drones:
        color = COLORS.get(d.drone_id)
        (line,) = ax.plot([], [], [], color=color, alpha=0.5, label=d.drone_id)
        (point,) = ax.plot([], [], [], "o", color=color, markersize=8)
        lines[d.drone_id] = line
        points[d.drone_id] = point
    ax.legend()

    def update(frame_idx):
        for d in sim.drones:
            hist = d.path_history
            idx = min(frame_idx, len(hist) - 1)
            xs = [p[0] for p in hist[: idx + 1]]
            ys = [p[1] for p in hist[: idx + 1]]
            zs = [p[2] for p in hist[: idx + 1]]
            lines[d.drone_id].set_data(xs, ys)
            lines[d.drone_id].set_3d_properties(zs)
            points[d.drone_id].set_data([xs[-1]], [ys[-1]])
            points[d.drone_id].set_3d_properties([zs[-1]])
        return list(lines.values()) + list(points.values())

    anim = FuncAnimation(fig, update, frames=n_frames, interval=1000 / fps, blit=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    anim.save(str(out_path), writer=PillowWriter(fps=fps))
    plt.close(fig)
    return out_path


def plot_static_paths(sim: Simulation, out_path: Path) -> Path:
    """A single static image of the full paths flown — quick to generate,
    used by the Phase 10 analysis report."""
    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, projection="3d")
    _setup_3d_axes(ax, sim, "Flight paths")

    for d in sim.drones:
        color = COLORS.get(d.drone_id)
        xs = [p[0] for p in d.path_history]
        ys = [p[1] for p in d.path_history]
        zs = [p[2] for p in d.path_history]
        ax.plot(xs, ys, zs, color=color, label=d.drone_id)
        ax.scatter([xs[0]], [ys[0]], [zs[0]], color=color, marker="^", s=80)   # start
        ax.scatter([xs[-1]], [ys[-1]], [zs[-1]], color=color, marker="s", s=80)  # end
    ax.legend()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path), dpi=120)
    plt.close(fig)
    return out_path
