#include "FlightController.h"
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <ESP32Servo.h>
#include <VL53L0X.h>

// ===== Pin map — adjust to your actual wiring =====
static constexpr int PIN_MOTOR_FL = 13;
static constexpr int PIN_MOTOR_FR = 12;
static constexpr int PIN_MOTOR_RL = 14;
static constexpr int PIN_MOTOR_RR = 27;
static constexpr int PIN_I2C_SDA = 21;
static constexpr int PIN_I2C_SCL = 22;
// VL53L0X default I2C address is 0x29. If you add a second I2C device at
// the same address later, you'll need an XSHUT-pin address reassignment
// sequence at boot — not included here since this build has just the one.

static Adafruit_MPU6050 mpu;
static VL53L0X proximitySensor;
static Servo motorFL, motorFR, motorRL, motorRR;

float FlightController::PID::update(float setpoint, float measured, float dt) {
    float error = setpoint - measured;
    integral += error * dt;
    float derivative = (dt > 0) ? (error - prevError) / dt : 0;
    prevError = error;
    return kp * error + ki * integral + kd * derivative;
}

void FlightController::begin(const char* droneId) {
    _droneId = droneId;
    Serial.begin(115200);
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    Wire.setClock(400000);

    _imuOk = mpu.begin();
    if (_imuOk) {
        mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
        mpu.setGyroRange(MPU6050_RANGE_500_DEG);
        mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    } else {
        Serial.println("[FATAL] MPU6050 not found. Check wiring/address.");
    }

    proximitySensor.setTimeout(50);
    if (!proximitySensor.init()) {
        Serial.println("[WARN] VL53L0X not found. Safety net will fail-safe to STOP.");
    }
    proximitySensor.startContinuous();

    motorFL.attach(PIN_MOTOR_FL, 1000, 2000);
    motorFR.attach(PIN_MOTOR_FR, 1000, 2000);
    motorRL.attach(PIN_MOTOR_RL, 1000, 2000);
    motorRR.attach(PIN_MOTOR_RR, 1000, 2000);
    // Arm ESCs at minimum throttle. KEEP PROPS OFF for first power-up.
    motorFL.writeMicroseconds(1000);
    motorFR.writeMicroseconds(1000);
    motorRL.writeMicroseconds(1000);
    motorRR.writeMicroseconds(1000);
    delay(3000); // ESC arming window — adjust to your ESC's spec

    _lastLoopMicros = micros();
    Serial.printf("[%s] FlightController ready.\n", _droneId);
}

void FlightController::readIMU(float dt) {
    if (!_imuOk) return;
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    // Complementary filter: gyro integration for short-term response,
    // accelerometer for long-term drift correction. No magnetometer, so
    // yaw is gyro-integration only and WILL drift — fine for a short
    // indoor hop, not for anything needing absolute heading.
    float accelRoll  = atan2(a.acceleration.y, a.acceleration.z) * 180.0f / PI;
    float accelPitch = atan2(-a.acceleration.x, a.acceleration.z) * 180.0f / PI;
    _gyroRollRateDps  = g.gyro.x * 180.0f / PI;
    _gyroPitchRateDps = g.gyro.y * 180.0f / PI;
    _yawRateDps       = g.gyro.z * 180.0f / PI;

    constexpr float ALPHA = 0.98f;
    _roll  = ALPHA * (_roll  + _gyroRollRateDps  * dt) + (1 - ALPHA) * accelRoll;
    _pitch = ALPHA * (_pitch + _gyroPitchRateDps * dt) + (1 - ALPHA) * accelPitch;
}

float FlightController::readProximityMeters() {
    uint16_t mm = proximitySensor.readRangeContinuousMillimeters();
    if (proximitySensor.timeoutOccurred()) {
        // Fail-SAFE, not fail-open: a broken/unreadable safety sensor
        // must not be interpreted as "clear to fly". Treat it as if
        // something is dangerously close, so the stop still fires.
        return 0.0f;
    }
    return mm / 1000.0f;
}

void FlightController::triggerSafetyStop() {
    // Tier 2. Reacts ONLY to the physical proximity sensor — never to
    // negotiation state, network status, or blockchain writes.
    //
    // Cutting all motors is the simplest, most conservative failsafe for
    // a light indoor prototype. Decide with your actual airframe/test
    // area (netting? padded floor? over people?) whether a controlled-
    // descent behavior would be safer than a hard cut before flying near
    // anything you don't want it landing on.
    motorFL.writeMicroseconds(1000);
    motorFR.writeMicroseconds(1000);
    motorRL.writeMicroseconds(1000);
    motorRR.writeMicroseconds(1000);
    _safetyTriggered = true;
    Serial.printf("[%s] SAFETY STOP: proximity < %.2fm\n", _droneId, SAFETY_TRIGGER_M);
}

void FlightController::writeMotors(float rollCmd, float pitchCmd, float yawCmd) {
    // Standard X-quad mixing. Verify each motor's actual position/spin
    // direction matches this before arming with props on.
    float fl = _throttleUs + rollCmd - pitchCmd - yawCmd;
    float fr = _throttleUs - rollCmd - pitchCmd + yawCmd;
    float rl = _throttleUs + rollCmd + pitchCmd + yawCmd;
    float rr = _throttleUs - rollCmd + pitchCmd - yawCmd;

    auto clampUs = [](float v) { return (uint16_t)constrain(v, 1000, 2000); };
    _motorUs[0] = clampUs(fl);
    _motorUs[1] = clampUs(fr);
    _motorUs[2] = clampUs(rl);
    _motorUs[3] = clampUs(rr);

    motorFL.writeMicroseconds(_motorUs[0]);
    motorFR.writeMicroseconds(_motorUs[1]);
    motorRL.writeMicroseconds(_motorUs[2]);
    motorRR.writeMicroseconds(_motorUs[3]);
}

void FlightController::loop() {
    uint32_t now = micros();
    uint32_t elapsed = now - _lastLoopMicros;
    if (elapsed < LOOP_INTERVAL_US) return; // fixed-rate loop
    float dt = elapsed / 1e6f;
    _lastLoopMicros = now;

    // ---- Tier 2 safety check runs FIRST, unconditionally ----
    float distM = readProximityMeters();
    if (distM < SAFETY_TRIGGER_M) {
        triggerSafetyStop();
        return; // motors already cut this cycle — skip stabilization
    }
    _safetyTriggered = false;

    // ---- Tier 1 stabilization ----
    readIMU(dt);

    float rollRateSetpoint  = _rollAnglePID.update(_targetRollDeg, _roll, dt);
    float pitchRateSetpoint = _pitchAnglePID.update(_targetPitchDeg, _pitch, dt);

    float rollCmd  = _rollRatePID.update(rollRateSetpoint, _gyroRollRateDps, dt);
    float pitchCmd = _pitchRatePID.update(pitchRateSetpoint, _gyroPitchRateDps, dt);
    float yawCmd   = _yawRatePID.update(_targetYawRateDps, _yawRateDps, dt);

    writeMotors(rollCmd, pitchCmd, yawCmd);
}
