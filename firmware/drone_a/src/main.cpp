#include <Arduino.h>
#include "FlightController.h"

static FlightController flightController;

void setup() {
    flightController.begin("drone_a");
}

void loop() {
    flightController.loop();
}
