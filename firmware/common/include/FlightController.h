#pragma once
#include <Arduino.h>

// Tier 1 (stabilization) + Tier 2 (hardcoded proximity safety net) for one
// drone, per PRD Section 6. Both tiers run here, locally, at loop rate —
// neither depends on Wi-Fi, the blockchain, or the LLM agents.
//
// ASSUMED HARDWARE (change together with the .cpp if yours differs):
//   IMU:       MPU6050 (I2C)
//   Proximity: VL53L0X time-of-flight sensor (I2C), facing the other
//              drone's approach direction — this is the ONLY input
//              allowed to trigger the safety stop.
//   Motors:    4x ESC via standard 1000-2000us PWM (X-quad layout)
//
// UNVERIFIED: written without a PlatformIO toolchain available to
// compile against, and never flown. Bench-test with propellers OFF,
// confirm motor mixing directions and IMU sign conventions, then tune
// PID gains gradually before any real flight.
class FlightController {
public:
    void begin(const char* droneId);
    void loop(); // call every iteration of the Arduino loop(); self rate-limits

private:
    const char* _droneId = "unknown";

    // ---- timing ----
    uint32_t _lastLoopMicros = 0;
    static constexpr uint32_t LOOP_INTERVAL_US = 4000; // ~250 Hz stabilization loop

    // ---- IMU state ----
    bool _imuOk = false;
    float _roll = 0, _pitch = 0;                                  // degrees, complementary-filtered
    float _gyroRollRateDps = 0, _gyroPitchRateDps = 0, _yawRateDps = 0;
    void readIMU(float dt);

    // ---- cascaded PID (angle -> rate -> motor mix) ----
    struct PID {
        float kp, ki, kd;
        float integral = 0;
        float prevError = 0;
        float update(float setpoint, float measured, float dt);
    };
    PID _rollRatePID{0.9f, 0.6f, 0.01f};
    PID _pitchRatePID{0.9f, 0.6f, 0.01f};
    PID _yawRatePID{1.2f, 0.3f, 0.0f};
    PID _rollAnglePID{4.0f, 0.0f, 0.0f};
    PID _pitchAnglePID{4.0f, 0.0f, 0.0f};

    // ---- setpoints — replace with real RC/telemetry input later ----
    // Defaulted to "hold level, no yaw" so the loop is well-defined even
    // before any command source is wired in.
    float _targetRollDeg = 0, _targetPitchDeg = 0, _targetYawRateDps = 0;
    uint16_t _throttleUs = 1000; // 1000-2000us; starts at disarmed-low

    void writeMotors(float rollCmd, float pitchCmd, float yawCmd);
    uint16_t _motorUs[4] = {1000, 1000, 1000, 1000}; // FL, FR, RL, RR

    // ---- Tier 2: hardcoded safety net (PRD Section 6, non-negotiable) ----
    // Triggered ONLY by the physical proximity sensor reading below 1m.
    // Never gated by negotiation state, network, or blockchain writes.
    static constexpr float SAFETY_TRIGGER_M = 1.0f;
    bool _safetyTriggered = false;
    float readProximityMeters(); // fail-safe: returns 0.0 (= "danger") on sensor read failure
    void triggerSafetyStop();
};
