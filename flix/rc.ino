// Copyright (c) 2023 Oleg Kalachev <okalachev@gmail.com>
// Repository: https://github.com/okalachev/flix
// Modified: no physical SBUS RC receiver on this build.
// Control input comes entirely from MAVLink over Wi-Fi (see wifi.ino / mavlink.ino),
// which writes directly into the shared `controls[]` array. These are no-op stubs
// kept only so flix.ino, cli.ino, and parameters.ino still compile without changes.

// Kept only because parameters.ino references these as tunable parameters (RC_NEUTRAL_*, RC_MAX_*).
// They're unused with no physical receiver connected.
float channelNeutral[RC_CHANNELS] = {0};
float channelMax[RC_CHANNELS] = {0};

void setupRC() {
	Serial.println("RC: no physical receiver configured, using Wi-Fi/MAVLink control only");
}

void readRC() {
	// no-op: controls[] is populated by receiveMavlink() in mavlink.ino instead
}

void calibrateRC() {
	Serial.println("RC: no physical receiver to calibrate (Wi-Fi/MAVLink control in use)");
}
