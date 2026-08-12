#include <Arduino.h>
#include "FlightController.h"

static FlightController flightController;

void setup() {
    flightController.begin("drone_b");
}

void loop() {
    flightController.loop();
}
