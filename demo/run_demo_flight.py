"""
Runnable end-to-end demo of the whole pipeline: spins up 3 REAL
blockchain node subprocesses, flies a simulated swap scenario with
scripted (fake) agent replies — no ANTHROPIC_API_KEY needed — and saves:

  demo/output/flight.gif             animated 3D flight path
  demo/output/flight_paths.png       static version of the same
  demo/output/blockchain_diagram.png visual chain of every block written
  demo/output/flight_report.md       plain-English narration, block by block

Run from the repo root:
    pip install -r requirements.txt
    python demo/run_demo_flight.py

To use the REAL Claude API instead of scripted replies, set
ANTHROPIC_API_KEY and pass --live.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "demo" / "output"

# Isolate this demo's keys/chain from any other run (tests, a real
# deployment, etc.) — must be set BEFORE blockchain.keys is imported
# anywhere, since it reads this env var once at import time and this
# script's own process also verifies signatures locally.
DEMO_STATE_DIR = ROOT / "demo" / ".demo_state"
os.environ["DRONE_CHAIN_KEYS_DIR"] = str(DEMO_STATE_DIR / "keys")
os.environ["DRONE_CHAIN_DATA_DIR"] = str(DEMO_STATE_DIR / "chain_data")

sys.path.insert(0, str(ROOT))

from agent.agent_a import create_agent as create_agent_a  # noqa: E402
from agent.agent_b import create_agent as create_agent_b  # noqa: E402
from simulation.flight_runner import run_full_flight  # noqa: E402
from simulation.sim_drones import RoomBounds, make_swap_scenario  # noqa: E402
from simulation.visualize import animate_simulation, plot_static_paths  # noqa: E402
from simulation.visualize_chain import plot_blockchain  # noqa: E402


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_health(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=1).status_code == 200:
                return
        except requests.RequestException as e:
            last_err = e
        time.sleep(0.1)
    raise TimeoutError(f"{url} never became healthy: {last_err}")


def start_nodes() -> tuple[list[subprocess.Popen], list[str]]:
    (DEMO_STATE_DIR / "keys").mkdir(parents=True, exist_ok=True)
    (DEMO_STATE_DIR / "chain_data").mkdir(parents=True, exist_ok=True)
    env = {**os.environ}
    procs, urls = [], []
    for node_id in ("gs_node_1", "gs_node_2", "coordinator_node"):
        port = free_port()
        p = subprocess.Popen(
            [sys.executable, "-m", "blockchain.node", "--node-id", node_id,
             "--port", str(port), "--no-persist"],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        procs.append(p)
        urls.append(f"http://127.0.0.1:{port}")
    for u in urls:
        wait_health(u)
    return procs, urls


# ---- scripted (fake) model client, so this runs with no API key ----
class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class ScriptedClient:
    """Cycles through a script of actions; repeats the last one once the
    script runs out (a flight's cycle count isn't known ahead of time)."""

    def __init__(self, replies: list[str]):
        self._replies = replies
        self.calls = 0
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls += 1
                idx = min(outer.calls - 1, len(outer._replies) - 1)
                return _FakeResponse(json.dumps({"action": outer._replies[idx], "reasoning": "demo"}))

        self.messages = _Messages()


def build_agents(live: bool):
    if live:
        # Real Claude API — needs ANTHROPIC_API_KEY set.
        return create_agent_a(), create_agent_b()
    agent_a = create_agent_a(client=ScriptedClient(
        ["continue_path", "continue_path", "reduce_speed", "continue_path",
         "continue_path", "continue_path"]))
    agent_b = create_agent_b(client=ScriptedClient(
        ["continue_path", "continue_path", "yield_and_pause", "continue_path",
         "continue_path", "continue_path"]))
    return agent_a, agent_b


def narrate(result, sim, bounds, node_urls) -> str:
    lines = ["# Demo Flight Report\n"]
    lines.append(
        f"Room: {bounds.x_max}x{bounds.y_max}x{bounds.z_max}m. "
        f"drone_a: {sim.get_drone('drone_a').path_history[0]} -> "
        f"{result.pre_flight_blocks['drone_a'].data['destination_position']}"
    )
    lines.append(
        f"drone_b: {sim.get_drone('drone_b').path_history[0]} -> "
        f"{result.pre_flight_blocks['drone_b'].data['destination_position']}\n"
    )

    lines.append("## Pre-flight (notarized before takeoff)\n")
    for drone_id, block in result.pre_flight_blocks.items():
        lines.append(
            f"- **{drone_id}**: block #{block.index}, {len(block.signatures)} node "
            f"signatures, max_speed={block.data['max_speed']}m/s, "
            f"safety trigger={block.data['safety_trigger_distance_m']}m"
        )

    lines.append(f"\n## In-flight ({len(result.cycle_blocks)} negotiation cycles)\n")
    for i, (block, kind) in enumerate(zip(result.cycle_blocks, result.cycle_kinds), start=1):
        d = block.data
        dist = d["estimated_distance_between_drones"]
        if kind == "safety_override":
            lines.append(
                f"- Cycle {i}: **SAFETY NET FIRED** — proximity {dist:.2f}m < 1.0m. "
                f"Agents were NOT called. Both drones forced to yield_and_pause. "
                f"({len(block.signatures)} signatures)"
            )
        else:
            fd = d["final_decision"]
            rounds = len(d["negotiation_log"])
            lines.append(
                f"- Cycle {i}: distance={dist:.2f}m, {rounds} negotiation round(s), "
                f"resolution={d['resolution_method']}: drone_a→{fd['drone_a_action']}, "
                f"drone_b→{fd['drone_b_action']} ({len(block.signatures)} signatures)"
            )

    lines.append("\n## Post-flight (summary, written after landing)\n")
    for drone_id, block in result.post_flight_blocks.items():
        lines.append(f"- **{drone_id}**: {block.data['summary']}")

    lines.append("\n## Chain verification\n")
    chain = requests.get(f"{node_urls[0]}/chain", timeout=5).json()
    lines.append(
        f"- Total blocks: {len(chain)} (genesis + 2 pre-flight + "
        f"{len(result.cycle_blocks)} in-flight + 2 post-flight)"
    )
    ok = all(chain[i]["previous_hash"] == chain[i - 1]["hash"] for i in range(1, len(chain)))
    lines.append(f"- Hash chain intact: {ok}")
    other_chain = requests.get(f"{node_urls[1]}/chain", timeout=5).json()
    lines.append(
        f"- All 3 nodes agree on identical history: "
        f"{[b['hash'] for b in chain] == [b['hash'] for b in other_chain]}"
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                         help="Use the real Claude API instead of scripted replies (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--room", type=float, default=5.0, help="Square room size in meters")
    parser.add_argument("--speed", type=float, default=1.0, help="Drone max speed, m/s")
    args = parser.parse_args()

    procs, node_urls = start_nodes()
    try:
        print(f"3 blockchain nodes running: {node_urls}\n")

        agent_a, agent_b = build_agents(args.live)

        bounds = RoomBounds(x_min=0, x_max=args.room, y_min=0, y_max=args.room, z_min=0, z_max=3)
        sim = make_swap_scenario(bounds=bounds, max_speed=args.speed, dt=0.3)

        print("Starting flight: drone_a bottom-left -> top-right, drone_b bottom-right -> top-left\n")
        result = run_full_flight(sim, agent_a, agent_b, node_urls, steps_per_cycle=1, max_cycles=200)

        report = narrate(result, sim, bounds, node_urls)
        print(report)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "flight_report.md").write_text(report)

        animate_simulation(sim, OUTPUT_DIR / "flight.gif", fps=15, run_to_completion=False)
        plot_static_paths(sim, OUTPUT_DIR / "flight_paths.png")

        chain = requests.get(f"{node_urls[0]}/chain", timeout=5).json()
        plot_blockchain(chain, OUTPUT_DIR / "blockchain_diagram.png",
                         title="Flight blockchain — every block written this flight")

        print(f"\nSaved output to {OUTPUT_DIR}/")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
