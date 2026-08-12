# PRD: Decentralized Blockchain-Coordinated Autonomous Drone System

## Document purpose

This document is a complete Product Requirements Document (PRD) for building a two-drone, blockchain-coordinated, AI-agent-controlled flight system. It is written so that an AI coding agent (or a human developer) can pick it up and build the entire project end-to-end without further clarification, using the objectives checklist in Section 9 to know when work is actually complete.

**Instruction to the executing AI**: Do not stop after completing one phase or one file. Work through the phases in order. After each phase, verify it against its "Definition of Done" in Section 9 before moving to the next. If a phase's DoD is not met, keep iterating on that phase — do not proceed to the next phase with a broken or incomplete previous phase. Only consider the project complete when every checkbox in Section 9 is checked.

## 1. Executive summary

Two autonomous drones (built from scratch on ESP32) fly indoors and swap positions, with their flight paths crossing in the middle of the room. Each drone has its own cloud-hosted LLM agent, and the two agents communicate with each other to negotiate a joint path-planning and collision-avoidance decision each cycle — there is no single overseeing "controller" agent. All flight data — before, during, and after each flight, including the full negotiation transcript between the two agents — is recorded on a small, locally-run blockchain (3 nodes, Proof of Authority) running on a ground station laptop. The blockchain is a tamper-evident audit record of what happened and why, not a real-time control channel, and not a claim of genuine multi-party trust (see Section 2). Real-time flight safety (stabilization and last-resort collision avoidance) never depends on the blockchain or the LLM agents — it is fast, local, and hardware-based.

## 2. Core concept, explained simply

Think of the blockchain as a black box flight recorder that multiple processes watch at once.

- Before takeoff, each drone's flight plan gets written down and "notarized" (a block).
- During flight, each negotiation cycle between the two drones' agents — both proposals, any back-and-forth, and the resolved decision — gets written down as it happens.
- After landing, a full summary gets written down for each drone (a final block).

Because 3 separate node processes all have to agree before anything gets written, no single node can quietly add an invalid block. Important honesty note: since the ground station laptop runs 2 of the 3 nodes, it already holds majority signing power on its own — so this system provides tamper-evidence (you can prove the log wasn't edited after the fact) rather than genuine multi-party trust (it does not protect against the ground station operator rewriting history, since they control the deciding votes). This is an intentional, honestly-stated scope choice, not an oversight.

The two LLM agents are each a "voice" for one drone — Drone A's agent argues for Drone A, Drone B's agent argues for Drone B — and they negotiate to a joint decision each cycle. Neither agent is the thing keeping its drone stable in the air (that's the ESP32's own fast control loop), and neither is the last line of defense against a collision (that's a simple hardcoded safety rule driven by a physical sensor, not by the agents' negotiated positions).

## 3. System components

**Drone A and Drone B (ESP32-based, built from scratch)**
- Local flight stabilization (IMU + PID + motor control) — fast loop, no network dependency
- Optical flow sensor + rangefinder (future hardware phase) for indoor position estimation (used for planning, not for the hard safety trigger)
- A separate, dedicated physical proximity sensor (e.g. ToF/ultrasonic) facing the other drone's approach direction — this is the sole trigger for the Tier 2 hardcoded safety stop (see Section 6)
- ESP-NOW radio link to the other drone (fast, direct, no router needed)
- Wi-Fi/UDP link to the ground station laptop
- Local hardcoded safety net: if the physical proximity sensor reads below 1 meter, stop/divert immediately, regardless of what either agent, the negotiation outcome, or the blockchain says

**Ground station laptop**
- Runs 2 of the 3 blockchain node processes (Proof of Authority, majority vote = 2 of 3)
- Runs the gateway service that relays data between drones and the blockchain/agents
- Runs the simulation environment (Phase 1, before real hardware)
- Runs the negotiation coordinator process (see below)

**Two cloud LLM agents (one per drone)**
- Drone A's agent and Drone B's agent — same underlying model, distinct system prompts, distinct local state (each primarily sees its own drone's telemetry plus messages from the other agent)
- Communicate through a bounded negotiation protocol (max 2 rounds: propose → counter → forced resolution) to reach a joint decision each cycle — see Section 6a
- Called roughly once per negotiation cycle each; block writes happen when a negotiation concludes, not on a strict external clock (see Section 6a)

**Negotiation coordinator (cloud, separate from the ground station)**
- Runs the propose/counter/resolve loop between the two agents
- Applies the fixed-priority tie-breaker (Drone A wins ties) if the agents don't converge within the round cap
- Acts as the 3rd blockchain node, signing the negotiated result — its signing key lives in its own cloud environment and is never stored on the ground station laptop, so its signature is a genuine independent check on what the ground station later claims happened

**Optical flow positioning system (hardware phase only — not needed for simulation)**
- Downward-facing optical flow sensor on each drone (velocity/motion tracking)
- Downward-facing rangefinder (e.g. ToF/ultrasonic) for height reference — required alongside optical flow, since optical flow alone gives velocity, not absolute position
- No fixed anchors needed (unlike UWB) — positioning is self-contained on the drone, but drifts over time without periodic correction
- Used for path planning and negotiation input only — never used as the trigger for the Tier 2 hardcoded safety stop, since it can drift with no external correction

## 4. Technology stack

- Language: Python for all backend components (blockchain nodes, gateway, agents, negotiation coordinator, simulation)
- Blockchain node communication: HTTP (simple REST endpoints between the 3 nodes)
- Drone-to-drone: ESP-NOW (hardware phase)
- Drone-to-ground: Wi-Fi / UDP (hardware phase)
- Drone firmware: Arduino framework via PlatformIO
- Simulation visualization: matplotlib
- LLM: Claude API (via Anthropic API) — two separate agent calls per negotiation cycle, plus the coordinator
- Consensus: Proof of Authority, 3 nodes, majority vote (2 of 3 must sign a block for it to be accepted)

## 5. Block data schema

**Pre-flight block** (one per drone, written before takeoff)

```json
{
  "block_type": "pre_flight",
  "drone_id": "drone_a" | "drone_b",
  "timestamp": "<unix time>",
  "start_position": {"x": "float", "y": "float", "z": "float"},
  "destination_position": {"x": "float", "y": "float", "z": "float"},
  "planned_path": [{"x": "..", "y": "..", "z": ".."}],
  "max_speed": "float",
  "safety_trigger_distance_m": 1.0,
  "agent_signature": "<node signature>"
}
```

**In-flight block** (one per negotiation cycle, covering both drones)

Changed from the original per-drone schema: since decisions now come from a negotiation between two agents, each cycle produces one joint block rather than two independent ones.

```json
{
  "block_type": "in_flight",
  "timestamp": "<unix time>",
  "drone_a_state": {
    "current_position": {"x": "float", "y": "float", "z": "float"},
    "current_waypoint_target": {"x": "float", "y": "float", "z": "float"}
  },
  "drone_b_state": {
    "current_position": {"x": "float", "y": "float", "z": "float"},
    "current_waypoint_target": {"x": "float", "y": "float", "z": "float"}
  },
  "estimated_distance_between_drones": "float",
  "negotiation_log": [
    {
      "round": 1,
      "drone_a_proposal": "<short string>",
      "drone_a_reasoning": "<short LLM explanation>",
      "drone_b_proposal": "<short string>",
      "drone_b_reasoning": "<short LLM explanation>"
    }
  ],
  "resolution_method": "converged" | "tie_breaker_fixed_priority",
  "final_decision": {
    "drone_a_action": "<short string>",
    "drone_b_action": "<short string>"
  },
  "event_type": "normal" | "replanned" | "safety_stop_triggered",
  "agent_signature": "<coordinator node signature>"
}
```

**Post-flight block** (one per drone, written after landing)

```json
{
  "block_type": "post_flight",
  "drone_id": "drone_a" | "drone_b",
  "total_flight_time_s": "float",
  "final_position": {"x": "float", "y": "float", "z": "float"},
  "path_actually_flown": [{"x": "..", "y": "..", "z": ".."}],
  "number_of_replans": "int",
  "number_of_safety_stops": "int",
  "number_of_tie_breaker_resolutions": "int",
  "summary": "<short LLM-generated debrief>"
}
```

Every block also carries standard chain fields: `index`, `previous_hash`, `hash`, and the list of node signatures that approved it (for PoA majority vote verification).

## 6. Safety architecture (non-negotiable)

This is a tiered safety design and must never be collapsed into a single tier:

- **Tier 1 — Local flight stabilization** (ESP32, always running): IMU + PID + motor control. Never depends on network, blockchain, or LLM agents.
- **Tier 2 — Hardcoded safety net** (ESP32, always running): Triggered only by the dedicated physical proximity sensor reading below 1 meter — never by optical-flow-derived position estimates, since those can drift with no external correction. This rule runs locally on the drone and does not wait for either agent, the negotiation coordinator, or the blockchain.
- **Tier 3 — LLM negotiation layer** (cloud, two agents + coordinator, bounded to 2 rounds per cycle): Handles path planning and right-of-way decisions through negotiation. This is "smart" but slow (multiple LLM calls per cycle), so it is never the only thing standing between the drones and a collision.

Any implementation that makes Tier 2 dependent on Tier 3 (the agents or negotiation outcome) responding in time, or that uses optical-flow position estimates as the Tier 2 trigger, is a bug.

### 6a. Negotiation protocol

- Each cycle: Drone A's agent proposes an action → Drone B's agent proposes an action, seeing A's proposal → if they conflict, one counter-round is allowed → if still unresolved after 2 rounds, the fixed-priority tie-breaker applies (Drone A's proposal is taken; this is a rare fallback, not a core mechanic).
- Block writes happen when a negotiation cycle concludes, not on a strict external clock — since rounds are capped, this keeps worst-case latency bounded without forcing an artificial deadline on the LLM calls.
- The full transcript of every round (both proposals and reasoning) is logged on-chain in the `negotiation_log` field, regardless of whether resolution came from convergence or the tie-breaker.

## 7. Development phases

- **Phase 0** — Project scaffolding: repo structure, Python environment, dependency management.
- **Phase 1** — Blockchain core: 3-node PoA blockchain — block creation, hashing, signature-based majority-vote validation, HTTP endpoints for nodes to propose/receive/sync blocks.
- **Phase 2** — Simulation harness: fake drones with simulated positions moving through 3D space (5m x 5m x 3m room, placeholder — adjustable later). matplotlib visualization showing both drones moving in real time (or step-by-step). No real hardware, no UWB yet.
- **Phase 3** — LLM agent negotiation integration: the two per-drone agents and the negotiation coordinator. Each cycle: agents exchange proposals (bounded to 2 rounds), coordinator resolves (convergence or tie-breaker), writes the joint in-flight block, and signs it as the 3rd blockchain node using its own cloud-held key.
- **Phase 4** — Safety net logic: implement the physical-proximity-sensor-triggered 1-meter hardcoded rule in the simulation first (as a stand-in for what will later run on the ESP32), prove it overrides the negotiation outcome when both are active simultaneously — including the case where the agents have not yet resolved a decision.
- **Phase 5** — End-to-end simulation test: full swap-position scenario runs start to finish in simulation — pre-flight blocks written, in-flight negotiation blocks accumulate with full transcripts, collision avoidance triggers correctly when paths cross, post-flight blocks summarize the run for both drones.
- **Phase 6** — Hardware: drone build: assemble the two ESP32 drones (motors, ESC, IMU, frame — hardware already available). Port the flight stabilization loop to real firmware (Arduino/PlatformIO). Mount the dedicated physical proximity sensor separately from the optical flow module.
- **Phase 7** — Hardware: communication: implement ESP-NOW (drone-to-drone) and Wi-Fi/UDP (drone-to-ground) on real hardware. Confirm the gateway on the laptop can relay real telemetry into the blockchain/negotiation pipeline built in Phases 1-3.
- **Phase 8** — Hardware: optical flow positioning: add optical flow + rangefinder modules to drones. Replace simulated positions with real optical-flow-derived positions (velocity integrated over time, height from rangefinder) for negotiation input. Confirm the physical proximity sensor remains fully independent of this data path.
- **Phase 9** — Full real-flight test: run the actual swap-position scenario with real drones indoors, blockchain recording the full flight and negotiation transcripts, agents negotiating live decisions, hardcoded physical-sensor safety net as the last line of defense.
- **Phase 10** — Analysis tooling: a simple tool/script to read back the full blockchain history of a flight and produce a human-readable report (path taken, negotiation transcripts, tie-breaker resolutions, any safety triggers).

## 8. Non-negotiable constraints

- Real-time flight stabilization must never depend on network, blockchain, or LLM availability.
- The 1-meter hardcoded safety net must be triggered only by the dedicated physical proximity sensor, never by optical-flow position estimates, and must never be bypassed or gated by the agents or negotiation coordinator.
- Negotiation rounds are capped at 2 per cycle; the fixed-priority tie-breaker must always produce a resolved decision within that bound.
- Blockchain writes happen after a decision/action, never before — the chain is a record, not a live command bus, for anything time-critical.
- All 3 blockchain nodes must independently verify a block before it's accepted (majority vote, 2 of 3) — no single node can unilaterally add a block.
- The negotiation coordinator's signing key must never be stored on the ground station laptop.

## 9. Objectives checklist (Definition of Done)

See `README.md` in this repo for current status against every item below.

**Phase 1 — Blockchain core**
- [ ] 3 node processes run independently and can be started/stopped individually
- [ ] A block can be proposed by any node
- [ ] A block is only accepted into the chain once 2 of 3 nodes sign off on it
- [ ] Tampering with a past block's data is detectable via hash mismatch
- [ ] Basic automated tests pass for block creation, validation, and majority-vote logic

**Phase 2 — Simulation harness**
- [ ] Two simulated drones move through 3D space with position updates over time
- [ ] matplotlib visualization shows both drones' positions updating
- [ ] Room bounds are configurable (not hardcoded to one value)

**Phase 3 — LLM agent negotiation**
- [ ] Each drone has its own agent with distinct prompt/state, receiving its own drone's data each cycle
- [ ] Agents exchange proposals and reach a resolution within the 2-round cap
- [ ] Fixed-priority tie-breaker fires and resolves correctly when the agents fail to converge (test case included)
- [ ] Full negotiation transcript (all rounds, both proposals + reasoning) is written into the in-flight block correctly
- [ ] The negotiation coordinator successfully acts as a signing blockchain node, using a key never stored on the ground station

**Phase 4 — Safety net**
- [ ] Hardcoded rule triggers reliably when the physical proximity sensor reads below 1 meter
- [ ] Safety net action overrides/interrupts an in-progress or unresolved negotiation, provably
- [ ] Safety net trigger is proven independent of optical-flow-derived position estimates

**Phase 5 — End-to-end simulation**
- [ ] Full swap-position scenario runs start to finish without crashing
- [ ] Pre-flight, in-flight (with negotiation transcripts), and post-flight blocks are all present and well-formed
- [ ] Paths cross in the middle and a collision-avoidance event is observed in the block log
- [ ] A full flight's blockchain history can be replayed/read back and makes narrative sense

**Phase 6 — Hardware drone build**
- [ ] Both ESP32 drones stabilize in a basic hover test
- [ ] PID tuning is stable enough for controlled manual flight
- [ ] Physical proximity sensor mounted separately from optical flow module and reading correctly

**Phase 7 — Hardware communication**
- [ ] ESP-NOW message round-trip confirmed between the two drones
- [ ] Wi-Fi/UDP telemetry from drone to laptop confirmed
- [ ] Real telemetry successfully flows into the same blockchain/negotiation pipeline used in simulation, with no changes needed to Phases 1-3 logic

**Phase 8 — Optical flow positioning**
- [ ] Optical flow + rangefinder mounted and reading correctly on both drones
- [ ] Drone-reported position matches known physical position within acceptable error margin
- [ ] Position drift over a typical flight duration measured and documented
- [ ] Confirmed the physical proximity sensor path remains fully independent of optical flow data

**Phase 9 — Full real-flight test**
- [ ] Real swap-position flight completes with blockchain recording the full journey and negotiation transcripts
- [ ] Safety net proven to work on real hardware

**Phase 10 — Analysis tooling**
- [ ] A script/tool exists that takes a flight's blockchain data and produces a readable report
- [ ] Report includes: path flown, full negotiation transcripts, tie-breaker resolutions, any safety triggers, total flight time

## 10. Open parameters (safe defaults given — revisit later)

- Room size: default 5m x 5m x 3m height (placeholder, adjust once real space is confirmed)
- Optical flow sensor model + rangefinder pairing: to be decided in Phase 8
- Physical proximity sensor model (ToF vs. ultrasonic) for the Tier 2 trigger: to be decided in Phase 6
- Drift-correction strategy for optical flow: to be decided in Phase 8
- Negotiation cycle target frequency: ~1Hz (soft target; actual write timing follows negotiation conclusion, not a strict clock)
- Safety-net trigger distance: 1 meter (adjustable after real-world testing)

Decided (no longer open):
- Negotiation round cap: 2 rounds
- Tie-breaker rule: fixed priority, Drone A wins ties
- On-chain negotiation logging: full transcript, every round

## 11. Repo structure

```
drone-blockchain-project/
├── blockchain/
│   ├── node.py          # single node process (HTTP server + chain logic)
│   ├── block.py         # block class, hashing
│   └── consensus.py     # PoA majority-vote logic
├── agent/
│   ├── agent_a.py        # Drone A's agent: prompt, state, proposal logic
│   ├── agent_b.py         # Drone B's agent: prompt, state, proposal logic
│   └── coordinator.py    # negotiation loop, tie-breaker, block signing
├── simulation/
│   ├── sim_drones.py     # fake drone position/movement logic
│   └── visualize.py      # matplotlib rendering
├── gateway/
│   └── gateway.py        # relays real drone telemetry <-> blockchain/agents (hardware phase)
├── firmware/
│   ├── drone_a/           # PlatformIO project for Drone A
│   └── drone_b/           # PlatformIO project for Drone B
├── analysis/
│   └── report.py          # reads blockchain, produces flight report
└── tests/
    └── ...
```
