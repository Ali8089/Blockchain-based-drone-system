// Copyright (c) 2023 Oleg Kalachev <okalachev@gmail.com>
// Repository: https://github.com/okalachev/flix
// Modified for MPU6050 (GY-521, I2C) instead of MPU9250 (SPI)

// Work with the IMU sensor

#include <Wire.h>
#include <MPU6050.h> // "MPU6050" by Electronic Cats (or Jeff Rowberg's I2Cdevlib) via Library Manager

MPU6050 IMU;

Vector accBias;
Vector gyroBias;
Vector accScale(1, 1, 1);

// MPU6050 raw-to-physical-units conversion factors (default library ranges: +-2g accel, +-250dps gyro)
#define ACCEL_SCALE_FACTOR (16384.0f) // LSB per g at +-2g range
#define GYRO_SCALE_FACTOR (131.0f)    // LSB per deg/s at +-250dps range
#define DEG2RAD (PI / 180.0f)

void setupIMU() {
	Serial.println("Setup IMU");
	Wire.begin();
	Wire.setClock(400000); // 400kHz I2C

	IMU.initialize();
	bool status = IMU.testConnection();
	if (!status) {
		while (true) {
			Serial.println("IMU begin error");
			delay(1000);
		}
	}
	configureIMU();
	calibrateGyro();
}

void configureIMU() {
	IMU.setFullScaleAccelRange(MPU6050_ACCEL_FS_2);
	IMU.setFullScaleGyroRange(MPU6050_GYRO_FS_250);
	IMU.setDLPFMode(MPU6050_DLPF_BW_42); // ~42Hz low-pass filter, reasonable default for a small frame
}

void readIMU() {
	int16_t ax, ay, az, gx, gy, gz;
	IMU.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);

	// convert raw values to physical units (m/s/s and rad/s)
	acc = Vector(ax, ay, az) / ACCEL_SCALE_FACTOR * ONE_G;
	gyro = Vector(gx, gy, gz) / GYRO_SCALE_FACTOR * DEG2RAD;

	// apply scale and bias
	acc = (acc - accBias) / accScale;
	gyro = gyro - gyroBias;

	// rotate
	rotateIMU(acc);
	rotateIMU(gyro);
}

void rotateIMU(Vector& data) {
	// Rotate to FLU (Forward-Left-Up) to match the rest of the firmware
	// NOTE: This depends on how your GY-521 is physically mounted on the frame.
	// Start with this identity mapping and adjust axes/signs if roll/pitch/yaw
	// directions don't match stick input once you test on the bench (props off).
	data = Vector(data.x, data.y, data.z);
}

void calibrateGyro() {
	const int samples = 1000;
	Serial.println("Calibrating gyro, stand still");

	gyroBias = Vector(0, 0, 0);
	for (int i = 0; i < samples; i++) {
		int16_t ax, ay, az, gx, gy, gz;
		IMU.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
		Vector g = Vector(gx, gy, gz) / GYRO_SCALE_FACTOR * DEG2RAD;
		gyroBias = gyroBias + g;
		delay(2);
	}
	gyroBias = gyroBias / samples;

	printIMUCal();
	configureIMU();
}

void calibrateAccel() {
	Serial.println("Calibrating accelerometer");

	Serial.setTimeout(60000);
	Serial.print("Place level [enter] "); Serial.readStringUntil('\n');
	calibrateAccelOnce();
	Serial.print("Place nose up [enter] "); Serial.readStringUntil('\n');
	calibrateAccelOnce();
	Serial.print("Place nose down [enter] "); Serial.readStringUntil('\n');
	calibrateAccelOnce();
	Serial.print("Place on right side [enter] "); Serial.readStringUntil('\n');
	calibrateAccelOnce();
	Serial.print("Place on left side [enter] "); Serial.readStringUntil('\n');
	calibrateAccelOnce();
	Serial.print("Place upside down [enter] "); Serial.readStringUntil('\n');
	calibrateAccelOnce();

	printIMUCal();
	configureIMU();
}

void calibrateAccelOnce() {
	const int samples = 1000;
	static Vector accMax(-INFINITY, -INFINITY, -INFINITY);
	static Vector accMin(INFINITY, INFINITY, INFINITY);

	// Compute the average of the accelerometer readings
	acc = Vector(0, 0, 0);
	for (int i = 0; i < samples; i++) {
		int16_t ax, ay, az, gx, gy, gz;
		IMU.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
		Vector sample = Vector(ax, ay, az) / ACCEL_SCALE_FACTOR * ONE_G;
		acc = acc + sample;
		delay(2);
	}
	acc = acc / samples;

	// Update the maximum and minimum values
	if (acc.x > accMax.x) accMax.x = acc.x;
	if (acc.y > accMax.y) accMax.y = acc.y;
	if (acc.z > accMax.z) accMax.z = acc.z;
	if (acc.x < accMin.x) accMin.x = acc.x;
	if (acc.y < accMin.y) accMin.y = acc.y;
	if (acc.z < accMin.z) accMin.z = acc.z;
	Serial.printf("acc %f %f %f\n", acc.x, acc.y, acc.z);
	Serial.printf("max %f %f %f\n", accMax.x, accMax.y, accMax.z);
	Serial.printf("min %f %f %f\n", accMin.x, accMin.y, accMin.z);
	// Compute scale and bias
	accScale = (accMax - accMin) / 2 / ONE_G;
	accBias = (accMax + accMin) / 2;
}

void printIMUCal() {
	Serial.printf("gyro bias: %f %f %f\n", gyroBias.x, gyroBias.y, gyroBias.z);
	Serial.printf("accel bias: %f %f %f\n", accBias.x, accBias.y, accBias.z);
	Serial.printf("accel scale: %f %f %f\n", accScale.x, accScale.y, accScale.z);
}

void printIMUInfo() {
	Serial.printf("device ID: 0x%02X\n", IMU.getDeviceID());
}
