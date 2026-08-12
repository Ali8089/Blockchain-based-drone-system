// Drone B — Arduino IDE version. Identical setup steps as drone_a.ino —
// see that file's header comment for the full Boards Manager / library
// install walkthrough.
//
// This sketch is UNVERIFIED — never compiled, never flown. Read the
// warnings in FlightController.h/.cpp before powering on with props on.

#include "FlightController.h"

static FlightController flightController;

void setup() {
    flightController.begin("drone_b");
}

void loop() {
    flightController.loop();
}
