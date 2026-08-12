// Drone A — Arduino IDE version.
//
// SETUP (one-time, in Arduino IDE):
//   1. File > Preferences > "Additional Board Manager URLs", paste:
//      https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
//   2. Tools > Board > Boards Manager > search "esp32" > Install
//   3. Tools > Manage Libraries > install:
//        - "ESP32Servo" (by Kevin Harrington / madhephaestus)
//        - "VL53L0X" (by Pololu)
//        - "Adafruit MPU6050" (installing this will also prompt to
//          install "Adafruit Unified Sensor" and "Adafruit BusIO" —
//          accept those too, FlightController.cpp needs all three)
//   4. Tools > Board: pick your exact ESP32 dev board model
//   5. Tools > Port: pick the port it shows up as when plugged in
//   6. Upload — WITH PROPELLERS OFF for the first several tests
//
// This sketch is UNVERIFIED — never compiled (no toolchain access where
// it was written) and never flown. Read the warnings in
// FlightController.h/.cpp before powering on with props attached.

#include "FlightController.h"

static FlightController flightController;

void setup() {
    flightController.begin("drone_a");
}

void loop() {
    flightController.loop();
}
