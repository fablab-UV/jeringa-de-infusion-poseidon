// =============================================================
//  POSEIDON SINGLE PUMP - Firmware limpio para 1 jeringa
// -------------------------------------------------------------
//  Hardware : Arduino Uno + driver A4988 (1/16 microstepping)
//             STEP -> pin 2
//             DIR  -> pin 5
//             EN   -> pin 8 (opcional; si ENABLE del driver va
//                     directo a GND, el pin 8 queda sin uso)
//  Protocolo : identico al Poseidon original (pachterlab), asi
//             que tambien funciona con la GUI antigua si hace
//             falta. Comandos entre '<' y '>', separados por ',':
//
//   <SETTING,SPEED,1,<pasos/s>,F,0,0,0>
//   <SETTING,ACCEL,1,<pasos/s^2>,F,0,0,0>
//   <RUN,DIST,1,0,F,<pasos>,0,0>     F = infundir, B = retirar
//   <PAUSE,X,1,X,F,0,0,0>
//   <RESUME,X,1,X,F,0,0,0>
//   <STOP,X,X,X,F,0,0,0>
//
//  Reportes hacia el PC:
//   <Arduino is ready>            al arrancar
//   <OK>                          cada vez que recibe un comando
//   <DISP1|<pasos restantes>>     progreso mientras se mueve
//   <DONE>                        cuando termina el movimiento
// =============================================================

#include <Arduino.h>
#include <AccelStepper.h>

// ---------------- Pines ----------------
#define PIN_STEP   2
#define PIN_DIR    5
#define PIN_ENABLE 8      // activo en LOW (si no lo usas, igual no estorba)

// ---------------- Comunicacion ---------
#define BAUD_RATE 115200
const byte BUFF_SIZE = 64;
char inputBuffer[BUFF_SIZE];
byte bytesRecvd = 0;
bool readInProgress = false;
const char START_MARKER = '<';
const char END_MARKER   = '>';

// ---------------- Motor ----------------
AccelStepper stepper(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);

// Defaults razonables (se sobreescriben desde la GUI)
float motorSpeed = 1000.0;   // pasos/s
float motorAccel = 5000.0;   // pasos/s^2

// ---------------- Estado ---------------
bool isRunning = false;
bool isPaused  = false;

// Reporte de progreso
unsigned long lastReportMillis = 0;
const unsigned long REPORT_INTERVAL = 200;  // ms
long lastReportedDist = -1;

// =============================================================
//  Utilidades de parseo
// =============================================================

// Copia el campo n-esimo (0-based) del buffer en 'out'
void getField(byte index, char* out, size_t outSize) {
  byte field = 0;
  size_t j = 0;
  for (byte i = 0; i < bytesRecvd; i++) {
    char c = inputBuffer[i];
    if (c == ',') { field++; continue; }
    if (field == index && j < outSize - 1) {
      out[j++] = c;
    }
  }
  out[j] = '\0';
}

// =============================================================
//  Acciones
// =============================================================

void doRun() {
  char distBuf[20];
  char dirBuf[8];
  getField(5, distBuf, sizeof(distBuf));   // pasos (bomba 1 = campo 5)
  getField(4, dirBuf, sizeof(dirBuf));     // 'F' o 'B'

  long steps = atol(distBuf);
  if (dirBuf[0] == 'B') steps = -steps;

  if (steps == 0) return;

  stepper.enableOutputs();
  stepper.move(steps);
  isRunning = true;
  isPaused  = false;
  lastReportedDist = -1;
}

void doPause() {
  if (isRunning) isPaused = true;
}

void doResume() {
  if (isRunning) isPaused = false;
}

void doStop() {
  stepper.stop();            // desacelera y queda en posicion
  isRunning = false;
  isPaused  = false;
  Serial.println(F("<DONE>"));
}

void doSetting() {
  char settingBuf[16];
  char valueBuf[20];
  getField(1, settingBuf, sizeof(settingBuf));
  getField(3, valueBuf, sizeof(valueBuf));
  float value = atof(valueBuf);

  if (strcmp(settingBuf, "SPEED") == 0 && value > 0) {
    motorSpeed = value;
    stepper.setMaxSpeed(motorSpeed);
  } else if (strcmp(settingBuf, "ACCEL") == 0 && value > 0) {
    motorAccel = value;
    stepper.setAcceleration(motorAccel);
  }
  // DELTA y otros se ignoran: la GUI calcula los pasos del jog
  // y los manda como un RUN normal.
}

void parseCommand() {
  char modeBuf[16];
  getField(0, modeBuf, sizeof(modeBuf));

  if      (strcmp(modeBuf, "RUN") == 0)     doRun();
  else if (strcmp(modeBuf, "SETTING") == 0) doSetting();
  else if (strcmp(modeBuf, "STOP") == 0)    doStop();
  else if (strcmp(modeBuf, "PAUSE") == 0)   doPause();
  else if (strcmp(modeBuf, "RESUME") == 0)  doResume();

  Serial.println(F("<OK>"));
}

// =============================================================
//  Lectura serial (no bloqueante, byte a byte)
// =============================================================

void getDataFromPC() {
  while (Serial.available() > 0) {
    char x = (char)Serial.read();

    if (x == START_MARKER) {
      bytesRecvd = 0;
      readInProgress = true;
    } else if (x == END_MARKER && readInProgress) {
      readInProgress = false;
      inputBuffer[bytesRecvd] = '\0';
      parseCommand();
    } else if (readInProgress) {
      inputBuffer[bytesRecvd++] = x;
      if (bytesRecvd >= BUFF_SIZE - 1) bytesRecvd = BUFF_SIZE - 2;
    }
  }
}

// =============================================================
//  Setup / Loop
// =============================================================

void setup() {
  Serial.begin(BAUD_RATE);

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH); delay(300);
  digitalWrite(LED_BUILTIN, LOW);

  // Pin enable por si se cablea al pin 8 (LOW = driver activo)
  stepper.setEnablePin(PIN_ENABLE);
  stepper.setPinsInverted(false, false, true);  // enable activo en LOW
  stepper.enableOutputs();

  stepper.setMaxSpeed(motorSpeed);
  stepper.setAcceleration(motorAccel);

  Serial.println(F("<Arduino is ready>"));
}

void loop() {
  getDataFromPC();

  if (isRunning && !isPaused) {
    stepper.run();          // avanza con aceleracion, no bloquea
  }

  // Reporte de progreso
  if (isRunning) {
    long dist = stepper.distanceToGo();
    unsigned long now = millis();
    if (dist != lastReportedDist && now - lastReportMillis >= REPORT_INTERVAL) {
      Serial.print(F("<DISP1|"));
      Serial.print(dist);
      Serial.println(F(">"));
      lastReportedDist = dist;
      lastReportMillis = now;
    }
    if (dist == 0) {
      isRunning = false;
      Serial.println(F("<DONE>"));
    }
  }
}
