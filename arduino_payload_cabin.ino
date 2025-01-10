#include "BNO055_support.h"
#include <Wire.h>

#define INPUT_PIN 5
#define OUTPUT_PIN 6

bool temp = false;
struct bno055_t myBNO;
struct bno055_euler myEulerData;

void setup() {
  delay(2000);
  Serial.begin(115200);
  Serial1.begin(115200);
  pinMode(INPUT_PIN, INPUT_PULLUP);
  pinMode(OUTPUT_PIN, OUTPUT);
  digitalWrite(OUTPUT_PIN, HIGH);
  Wire.begin();
  BNO_Init(&myBNO);
  bno055_set_operation_mode(OPERATION_MODE_NDOF);
  delay(100);
  Serial.println("System Ready");
}

void loop() {
  if (digitalRead(INPUT_PIN) == LOW && temp == false) {
    digitalWrite(OUTPUT_PIN, LOW);
    bno055_read_euler_hrp(&myEulerData);
    unsigned long timestamp = millis();
    float yaw = float(myEulerData.h) / 16.0;
    float roll = float(myEulerData.r) / 16.0;
    float pitch = float(myEulerData.p) / 16.0;
    delay(8);
    digitalWrite(OUTPUT_PIN, HIGH);
    String message = "Timestamp:" + String(timestamp) +
                     ",Yaw:" + String(yaw) +
                     ",Roll:" + String(roll) +
                     ",Pitch:" + String(pitch);
    Serial1.println(message);
    Serial.println(message);
    temp = true;
  }
  else if (digitalRead(INPUT_PIN) == HIGH && temp == true) {
    temp = false;
  }
}



//#include "BNO055_support.h"
//#include <Wire.h>
//#include <ESP32Servo.h>
//
//#define PULSE_INPUT_PIN 19     // Interrupt pin for input pulse
//#define PULSE_OUTPUT_PIN 18    // Output pulse pin
//#define CAMERA_STATUS_PIN 25  // Reads camera status (3.3V = ON, GND = OFF)
//#define CAMERA_TOGGLE_PIN 26   // Toggles camera state with a ground pulse
//#define TX_PIN 17              // SoftwareSerial TX
//#define RX_PIN 16              // SoftwareSerial RX
//#define DEBOUNCE_DELAY 50     // Debounce delay in ms
// 
//struct bno055_t myBNO;
//struct bno055_euler myEulerData;
//
//volatile bool triggerEvent = false;  // Flag for interrupt
//unsigned long lastInterruptTime = 0; // Timestamp for debouncing
//
//const int servoPin = 23;     // Pin for servo PWM signal
//Servo myServo;
//const int servoOpenValue = 2400;  // Pulse width for open position (in microseconds)
//const int servoCloseValue = 400;  // Pulse width for close position (in microseconds)
//
//void IRAM_ATTR handlePulseInterrupt() {
//  unsigned long currentTime = millis();
//  if ((currentTime - lastInterruptTime) > DEBOUNCE_DELAY) {
//    lastInterruptTime = currentTime;
//    triggerEvent = true;
//  }
//}
//
//void setup() {
//  delay(3000);
//  Serial.begin(115200);
//  Serial2.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN); // Initialize Serial2 (RX=GPIO16, TX=GPIO17)
//  Serial.println("hello");
//
//  myServo.attach(servoPin);
//  myServo.writeMicroseconds(servoOpenValue);
//  // Pin configurations
//  pinMode(PULSE_INPUT_PIN, INPUT_PULLUP);
//  pinMode(PULSE_OUTPUT_PIN, OUTPUT);
//  digitalWrite(PULSE_OUTPUT_PIN, HIGH);  // Default state
//  pinMode(CAMERA_STATUS_PIN, INPUT);
//  pinMode(CAMERA_TOGGLE_PIN, OUTPUT);
//  digitalWrite(CAMERA_TOGGLE_PIN, HIGH); // Default state
//  //pinMode(servoPin, OUTPUT);
//
//  // Attach interrupt for input pulse
//  attachInterrupt(digitalPinToInterrupt(PULSE_INPUT_PIN), handlePulseInterrupt, FALLING);
//
//  // BNO055 setup
//  Wire.begin();
//  BNO_Init(&myBNO);
//  bno055_set_operation_mode(OPERATION_MODE_NDOF);
//  delay(10);
//
//  // Set default servo position (OPEN)
//
//  Serial.println("System Ready");
//}
//
//void loop() {
//  // Handle trigger event
//  if (triggerEvent) {
//    Serial.println("Event");
//    triggerEvent = false;
//
//    digitalWrite(PULSE_OUTPUT_PIN, LOW);
//
//    // Read BNO055 sensor data
//    bno055_read_euler_hrp(&myEulerData);
//    unsigned long timestamp = micros();
//    float yaw = float(myEulerData.h) / 16.0;
//    float roll = float(myEulerData.r) / 16.0;
//    float pitch = float(myEulerData.p) / 16.0;
//
//    // 5 ms delay for processing
//    delayMicroseconds(5000);
//    digitalWrite(PULSE_OUTPUT_PIN, HIGH);
//
//    // Send data via SoftwareSerial
//    String message = "Timestamp:" + String(timestamp) +
//                     ",Yaw:" + String(yaw) +
//                     ",Roll:" + String(roll) +
//                     ",Pitch:" + String(pitch);
//
//    // Send the message via Serial2 in one call
//    Serial2.println(message);
//    Serial.println(message);
//  }
//
//  // Handle serial commands
//  if (Serial2.available()) {
//    String command = Serial2.readStringUntil('\n');
//    Serial.println(command);
//    command.trim();
//
//    if (command == "SERVO:OPEN") {
//      myServo.writeMicroseconds(servoOpenValue);
//      Serial.println("Servo set to OPEN");
//    } else if (command == "SERVO:CLOSE") {
//      myServo.writeMicroseconds(servoCloseValue);
//      Serial.println("Servo set to CLOSE");
//    } else if (command == "CAMERA:ON") {
//      int cameraState = digitalRead(CAMERA_STATUS_PIN);
//      if (cameraState == HIGH) {
//        Serial.println("Camera is already ON");
//      } else {
//        digitalWrite(CAMERA_TOGGLE_PIN, LOW);
//        delay(50);  // Short ground pulse
//        digitalWrite(CAMERA_TOGGLE_PIN, HIGH);
//        Serial.println("Camera is ON");
//      }
//    } else if (command == "CAMERA:OFF") {
//      int cameraState = digitalRead(CAMERA_STATUS_PIN);
//      if (cameraState == HIGH) {
//        digitalWrite(CAMERA_TOGGLE_PIN, LOW);
//        delay(50);  // Short ground pulse
//        digitalWrite(CAMERA_TOGGLE_PIN, HIGH);
//        Serial.println("Camera is OFF");
//      } else {
//        Serial.println("Camera is already OFF");
//      }
//    } else if (command == "CAMERA:STATUS") {
//      int cameraState = digitalRead(CAMERA_STATUS_PIN);
//      if (cameraState == HIGH) {
//        Serial.println("Camera is ON");
//      } else {
//        Serial.println("Camera is OFF");
//      }
//    } else {
//      Serial.println("Unknown command");
//    }
//  }
//}
