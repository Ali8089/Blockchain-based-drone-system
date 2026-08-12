# Arduino IDE version of the firmware

This is the same code as `firmware/drone_a` and `firmware/drone_b`
(PlatformIO versions), just laid out the way Arduino IDE expects:
- one `.ino` file whose name matches its folder name
- `FlightController.h` / `FlightController.cpp` copied alongside it in
  the same folder (Arduino IDE compiles every file in a sketch folder
  together, so no special include path is needed)

## Board: ESP32 only

This firmware needs an ESP32, not an Arduino Uno — the Uno has no WiFi
and not enough RAM/flash for this. See the top comment in each `.ino`
file for the full one-time setup (board URL, libraries to install).

## Folders

- `drone_a/drone_a.ino` — flash this to Drone A's ESP32
- `drone_b/drone_b.ino` — flash this to Drone B's ESP32

Only difference between them is the drone ID string passed to
`begin()` — the flight logic is identical.

## Before flying

This code has never been compiled or run (built without a toolchain
available). Compile it first with propellers OFF, verify Serial output
looks sane, and read the warnings in `FlightController.h`/`.cpp` about
pin mapping, motor mixing direction, and PID tuning before attaching
props.
