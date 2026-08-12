# Decentralized Blockchain-Coordinated Autonomous Drone System

Two ESP32 drones swap positions indoors. A 3-node Proof-of-Authority
blockchain (run as 3 independent HTTP processes) is a tamper-evident flight
recorder — pre-flight plan, every negotiation cycle between the two drones'
LLM agents, and a post-flight summary all get written as signed blocks.
Real-time flight safety never depends on the blockchain or the agents; see
`PRD.md` for the full design rationale (honesty note on trust model,
tiered safety architecture, negotiation protocol).

## Status against the PRD's Definition of Done (Section 9)

Built and passing so far, with real automated tests behind every checkbox
(no hand-waving — `pytest -v` shows each one):

- **Phase 0 — Scaffolding**: repo structure, dependencies, `.gitignore`. Done.
- **Phase 1 — Blockchain core**: DONE, all 5 DoD items verified.
  - 3 node processes run independently, start/stop individually — proven
    with real OS subprocesses in `tests/test_node_integration.py`, not
    just in-process mocks.
  - Any node can be the entry point for a block proposal.
  - A block is only accepted once 2-of-3 nodes produce a valid Ed25519
    signature over its hash (see `blockchain/consensus.py`).
  - Tampering with historical block data is detected via hash mismatch.
  - 23 automated tests pass (`tests/test_block.py`, `test_consensus.py`,
    `test_node_integration.py`).
- **Phase 2 — Simulation harness**: DONE, all 3 DoD items verified.
  - Two simulated drones move through 3D space, positions update over
    time (`simulation/sim_drones.py`).
  - matplotlib visualization renders both drones moving — saved as an
    animated GIF (headless-safe) plus a static path plot.
  - Room bounds are a constructor parameter (`RoomBounds`), not a
    hardcoded constant — tested with a 1×1×1 room and a −10..10 room.
  - 7 automated tests pass (`tests/test_simulation.py`).
- **Phase 3 — LLM agent negotiation**: DONE, all 5 DoD items verified —
  logic only, not yet run live (see "Needs your API key" below).
  - `agent/agent_a.py` / `agent/agent_b.py`: distinct DroneAgent
    instances, distinct system prompts, each sees only its own drone's
    state plus the other agent's proposals.
  - `agent/coordinator.py`: `negotiate_cycle()` runs the bounded
    propose → counter → resolve loop (round cap = 2), detects conflicts
    (both drones holding course within 1.5m), and converges as soon as
    either side yields/slows/reroutes.
  - Fixed-priority tie-breaker (Drone A wins, Drone B forced to
    `yield_and_pause`) fires correctly when both agents refuse to budge
    for the full 2 rounds — tested.
  - Full transcript (both proposals + reasoning, every round) is
    captured in `negotiation_log`, matching the PRD's in_flight block
    schema exactly (`build_in_flight_block_data()`).
  - `run_and_record_cycle()` wires the negotiated result into the
    existing Phase 1 blockchain client (`blockchain.client.propose_and_commit`)
    so the coordinator's signature comes from whichever node process is
    running as `coordinator_node` — its key is never touched by this code.
  - 8 automated tests pass (`tests/test_agent_negotiation.py`), all
    against a scripted fake model client — **no API key needed to
    verify the negotiation logic itself.**
- **Phase 4 — Safety net**: DONE, all 3 DoD items verified.
  - `simulation/safety.py`: `evaluate_safety_net()` is a pure function of
    one number (the proximity reading) — no access to negotiation state,
    optical-flow data, or the blockchain, so it structurally can't be
    gated by any of them.
  - `simulation/flight_cycle.py`: `run_flight_cycle()` checks safety
    FIRST, unconditionally, mirroring `FlightController::loop()` in
    firmware — same shape on both sides. If it trips, the agents are
    never called at all (proven with a client that fails the test if
    invoked) and a `safety_stop_triggered` block is written directly.
  - Tie-in to "overrides an unresolved negotiation": since the safety
    check runs before negotiation even starts, there's no window where a
    negotiation is "in progress" when the override fires — tested.
  - Independence from optical-flow data: tested with a deliberately
    wrong optical-flow distance (10m) alongside a real close-proximity
    reading (0.3m) — safety net still fires, because it never receives
    the optical-flow value in the first place.
  - 7 automated tests pass (`tests/test_safety.py`).
- **Phase 5 — End-to-end simulation**: DONE, all 4 DoD items verified.
  - `simulation/flight_runner.py`: `run_full_flight()` writes pre-flight
    blocks for both drones, runs flight cycles (safety-checked, then
    negotiated) until both drones arrive, then writes post-flight summary
    blocks with replan/safety-stop/tie-break counts.
  - Full swap scenario (small room, X-crossing paths) runs to completion
    without crashing.
  - Pre-flight (x2), in-flight (xN, each with a transcript or an
    explicit empty-transcript override), and post-flight (x2) blocks are
    all present, well-formed, and correctly hash-chained.
  - At least one collision-avoidance event (a non-`continue_path`
    decision) is observed as the paths cross.
  - Chain read back from a live node afterward: genesis → 2 pre-flight →
    N in-flight → 2 post-flight, in order, hashes linked, and every one
    of the 3 nodes agrees on the identical history.
  - 1 automated test passes end-to-end (`tests/test_end_to_end.py`),
    against real node subprocesses and scripted agents (no API key
    needed).

**Needs your `ANTHROPIC_API_KEY` to actually run live:** all of Phases 3-5
are built and fully unit/integration-tested against a fake model client.
Nobody has run them against the real Claude API yet.

**Not started yet:** Phases 6-9 (real hardware — can't be done in this
sandbox at all, needs the physical ESP32s, sensors, and a PlatformIO
toolchain on your machine — firmware skeleton exists but is UNVERIFIED,
see `firmware/common/include/FlightController.h`), Phase 10 (analysis
tooling).

## Try it yourself

`demo/run_demo_flight.py` runs one complete flight end-to-end — real
blockchain nodes, real negotiation/safety logic, simulated drone
positions — and saves a flight animation, a blockchain diagram, and a
plain-English report. See `demo/README.md`.

## Repo layout

```
blockchain/     3-node PoA chain: block.py, consensus.py, chain.py, node.py, keys.py, client.py
simulation/     sim_drones.py (kinematics), visualize.py (flight animation),
                visualize_chain.py (blockchain diagram), safety.py (Phase 4 safety net),
                flight_cycle.py (safety+negotiation per cycle),
                flight_runner.py (Phase 5 full flight orchestration)
agent/          Phase 3: base.py (DroneAgent), agent_a.py, agent_b.py, coordinator.py
demo/           runnable end-to-end demo — see demo/README.md
gateway/        (Phase 7 — not started, hardware telemetry relay)
firmware/       (Phase 6 — skeleton only, unverified, needs real ESP32 + PlatformIO)
analysis/       (Phase 10 — not started)
tests/          pytest suite, one file per module/phase, conftest.py holds shared
                live-blockchain-node fixtures used by Phase 3/4/5 tests
PRD.md          the full product requirements doc this build follows
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Running the tests

```bash
pytest tests/ -v
```

## Running the blockchain manually (3 terminals)

```bash
python -m blockchain.node --node-id gs_node_1 --port 5001
python -m blockchain.node --node-id gs_node_2 --port 5002
python -m blockchain.node --node-id coordinator_node --port 5003
```

Then, from a Python shell or script:

```python
from blockchain import client
block, results = client.propose_and_commit(
    ["http://127.0.0.1:5001", "http://127.0.0.1:5002", "http://127.0.0.1:5003"],
    block_type="pre_flight",
    data={"drone_id": "drone_a", "start_position": {"x": 0, "y": 0, "z": 1.5}},
)
```

Node keys are generated on first run:
`keys/ground_station/gs_node_{1,2}.pem` and `keys/coordinator/coordinator_node.pem`
(private — gitignored), with public keys registered in `keys/known_nodes.json`
(safe to share/commit). This directory split is the structural expression of
the PRD's requirement that the coordinator's signing key never touches the
ground station laptop.

## Running the simulation

```python
from pathlib import Path
from simulation.sim_drones import make_swap_scenario
from simulation.visualize import animate_simulation

sim = make_swap_scenario()  # default 5m x 5m x 3m room
animate_simulation(sim, Path("swap_scenario.gif"))
```

## Running Phase 3 (needs ANTHROPIC_API_KEY)

```bash
export ANTHROPIC_API_KEY=your_key_here
```

```python
from agent.agent_a import create_agent as create_agent_a
from agent.agent_b import create_agent as create_agent_b
from agent.coordinator import negotiate_cycle, run_and_record_cycle

agent_a = create_agent_a()  # real Claude API client, built lazily
agent_b = create_agent_b()

drone_a_state = {"current_position": {"x": 0, "y": 0, "z": 1.5},
                  "current_waypoint_target": {"x": 5, "y": 0, "z": 1.5}}
drone_b_state = {"current_position": {"x": 4.2, "y": 0, "z": 1.5},
                  "current_waypoint_target": {"x": 0, "y": 0, "z": 1.5}}

# Negotiation only, no blockchain (quick way to sanity-check live behavior):
result = negotiate_cycle(agent_a, agent_b, drone_a_state, drone_b_state, estimated_distance_m=0.8)
print(result.resolution_method, result.final_decision)

# Full cycle: negotiate AND write the signed in_flight block (needs the
# 3 node processes running — see "Running the blockchain manually" above):
block, result, commit_results = run_and_record_cycle(
    agent_a, agent_b, drone_a_state, drone_b_state,
    estimated_distance_m=0.8,
    node_urls=["http://127.0.0.1:5001", "http://127.0.0.1:5002", "http://127.0.0.1:5003"],
)
```

## Next step

Phases 1-5 are done in simulation. Everything from here needs real
hardware: Phase 6 (assemble the ESP32 drones, bench-test the firmware in
`firmware/`, tune PID gains), which this sandbox can't do — needs the
physical drones and a PlatformIO toolchain on your machine.
