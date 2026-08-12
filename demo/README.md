# End-to-end demo

Runs one complete flight against 3 real blockchain node subprocesses,
using scripted (fake) agent replies by default — no API key needed.

## Run it

From the repo root:

```bash
pip install -r requirements.txt
python demo/run_demo_flight.py
```

Output lands in `demo/output/`:

- `flight.gif` — animated 3D view of both drones flying and crossing
- `flight_paths.png` — static version of the same paths
- `blockchain_diagram.png` — every block written this flight, as a
  horizontal chain diagram, color-coded by what happened (normal
  negotiation, a replan, a tie-break, or the safety net firing)
- `flight_report.md` — plain-English, cycle-by-cycle narration of the
  whole flight and a final chain-integrity check

## Options

```bash
python demo/run_demo_flight.py --room 8 --speed 1.5   # bigger room, faster drones
python demo/run_demo_flight.py --live                 # use the real Claude API
                                                        # (needs ANTHROPIC_API_KEY set)
```

## What's genuinely real here vs. scripted

- The 3 blockchain nodes, their signatures, hash-chaining, and the
  negotiation/safety logic are all the real code, run for real — nothing
  here is faked or mocked.
- The drone *positions* are a kinematic simulation (straight-line motion
  toward each destination), not real flight — there's no hardware yet.
- By default the two agents' proposals come from a short scripted list
  instead of the Claude API, so this runs offline with no key. Because
  the room geometry is real, the drones' actual simulated distance can
  (and often does) drop under the 1m safety threshold as their paths
  cross — when that happens the safety net fires for real, independent
  of anything scripted.
