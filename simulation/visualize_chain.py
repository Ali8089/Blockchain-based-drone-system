"""
Visual representation of the blockchain itself: a horizontal diagram of
blocks linked by hash, color-coded by what happened in each one. Distinct
from simulation/visualize.py, which shows the drones' physical paths —
this shows the *ledger*.

Reads plain block dicts (e.g. from GET /chain on a live node, or from
Block.to_dict()) so it has no dependency on any particular blockchain
node being alive at render time.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrow

# Color by what the block represents, so the shape of a flight is visible
# at a glance without reading every label.
COLOR_BY_KIND = {
    "genesis": "#888888",
    "pre_flight": "#4a86e8",
    "post_flight": "#4a86e8",
    "normal": "#44b984",              # in_flight, converged, no drama
    "replanned": "#ffad47",           # in_flight, converged after a counter-round
    "tie_breaker_fixed_priority": "#e66550",  # in_flight, agents deadlocked
    "safety_stop_triggered": "#cc3a21",       # in_flight, Tier 2 override fired
}


def _block_kind(block: dict) -> str:
    bt = block.get("block_type")
    if bt in ("genesis", "pre_flight", "post_flight"):
        return bt
    # in_flight: color by what actually happened, not just the fact that
    # it's an in_flight block, since that's the interesting part.
    data = block.get("data", {})
    if data.get("event_type") == "safety_stop_triggered":
        return "safety_stop_triggered"
    if data.get("resolution_method") == "tie_breaker_fixed_priority":
        return "tie_breaker_fixed_priority"
    if data.get("event_type") == "replanned":
        return "replanned"
    return "normal"


def _block_label(block: dict) -> List[str]:
    """Short multi-line label for one block's box."""
    bt = block.get("block_type")
    idx = block.get("index")
    h = block.get("hash", "")[:8]
    n_sigs = len(block.get("signatures", {}) or {})
    lines = [f"#{idx} {bt}", h]
    data = block.get("data", {})
    if bt == "in_flight":
        fd = data.get("final_decision") or {}
        if data.get("event_type") == "safety_stop_triggered":
            lines.append("SAFETY STOP")
        elif fd:
            lines.append(f"A:{fd.get('drone_a_action','?')}")
            lines.append(f"B:{fd.get('drone_b_action','?')}")
    elif bt in ("pre_flight", "post_flight"):
        lines.append(str(data.get("drone_id", "")))
    lines.append(f"{n_sigs} sigs")
    return lines


def plot_blockchain(chain: List[dict], out_path: Path, title: str = "Flight blockchain") -> Path:
    """Render `chain` (a list of block dicts, in order) as a horizontal
    sequence of boxes linked by arrows, each colored by what happened in
    that block. Saves a PNG (wide, since flights can have many blocks)."""
    n = len(chain)
    box_w, box_h, gap = 1.6, 1.3, 0.55
    fig_w = max(8, n * (box_w + gap) * 0.55)
    fig, ax = plt.subplots(figsize=(fig_w, 3.4))

    for i, block in enumerate(chain):
        x = i * (box_w + gap)
        kind = _block_kind(block)
        color = COLOR_BY_KIND.get(kind, "#999999")

        box = FancyBboxPatch(
            (x, 0), box_w, box_h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=1.2, edgecolor="black", facecolor=color, alpha=0.85,
        )
        ax.add_patch(box)

        label = "\n".join(_block_label(block))
        ax.text(x + box_w / 2, box_h / 2, label, ha="center", va="center",
                 fontsize=6.5, color="white", fontweight="bold")

        if i > 0:
            prev_x = (i - 1) * (box_w + gap) + box_w
            ax.add_patch(FancyArrow(
                prev_x, box_h / 2, gap - 0.1, 0,
                width=0.02, head_width=0.15, head_length=0.08,
                length_includes_head=True, color="black",
            ))

    ax.set_xlim(-0.3, n * (box_w + gap))
    ax.set_ylim(-0.3, box_h + 0.3)
    ax.axis("off")
    ax.set_title(title, fontsize=11)

    # Legend
    handles = [
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor=c, markersize=12, label=k)
        for k, c in COLOR_BY_KIND.items()
        if k in {_block_kind(b) for b in chain}
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.05),
              ncol=min(len(handles), 5), fontsize=7, frameon=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out_path
