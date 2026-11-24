#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================
 BOMBA DE JERINGA - Software de control (1 jeringa)  v2.1
-------------------------------------------------------------
 Basado en el sistema Poseidon (Pachter Lab). Compatible con el
 firmware de src/main.cpp (Arduino Uno + A4988), sin cambios.

 Requisitos:  pip install PyQt5 pyserial
=============================================================
"""

import sys
import os
import json
import math
import time
from datetime import datetime

import serial
import serial.tools.list_ports

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

APP_NAME = "Bomba de Jeringa"
APP_VERSION = "2.1"
BAUD_RATE = 115200

MAX_STEPS_PER_S = 4000.0       # limite practico de AccelStepper en un Uno
CONTINUOUS_LIMIT_MM = 100.0    # tope de seguridad del movimiento continuo
WATER_DENSITY = 0.998          # g/mL a ~20 °C
FAST_ACCEL_MM_S2 = 20.0        # aceleracion de los movimientos rapidos

BUILTIN_SYRINGES = [
    ("BD Plastipak 1 mL", 1.0, 17.34206347),
    ("BD Plastipak 3 mL", 3.0, 57.88559215),
    ("BD Plastipak 5 mL", 5.0, 112.9089185),
    ("BD Plastipak 10 mL", 10.0, 163.539454),
    ("BD Plastipak 20 mL", 20.0, 285.022957),
    ("BD Plastipak 30 mL", 30.0, 366.0961536),
    ("BD Plastipak 60 mL", 60.0, 554.0462538),
]

METHOD_LABELS = {
    "factory": "De fábrica",
    "diameter": "Por diámetro",
    "pump_scale": "Con la bomba (escala)",
    "pump_weight": "Con la bomba (balanza)",
}

FLOW_UNITS = {                 # factor -> mL/s
    "mL/min": 1.0 / 60.0,
    "mL/h": 1.0 / 3600.0,
    "µL/min": 1.0 / 60000.0,
    "µL/h": 1.0 / 3600000.0,
    "mL/s": 1.0,
}
VOLUME_UNITS = {"mL": 1.0, "µL": 0.001}

MANUAL_STEPS_ML = [0.01, 0.1, 1.0]   # el 4.º modo es "Mantener"

DEFAULT_MACHINE = {
    "steps_per_rev": 200,
    "microsteps": 16,
    "mm_per_rev": 2.0,        # tornillo T8 de 1 entrada (2 mm por vuelta)
    "invert": False,
    "accel_mm_s2": 2.0,
    "jog_speed_mm_s": 0.7,
    "fast_speed_mm_s": 2.5,   # Mantener y Retroceder todo
    "retract_mm": 60.0,       # recorrido de Retroceder todo
}

SCREW_PRESETS = [
    ("T8 paso 2 · 2 mm por vuelta", 2.0),
    ("T8 4 entradas · 8 mm por vuelta", 8.0),
    ("M5 · 0,8 mm por vuelta", 0.8),
    ("M6 · 1 mm por vuelta", 1.0),
    ("M8 · 1,25 mm por vuelta", 1.25),
    ("Otro / calibrado", None),
]

BLUE = "#2563eb"
GREEN = "#16a34a"
AMBER = "#f59e0b"
RED = "#dc2626"


# =============================================================
#  Utilidades
# =============================================================
def area_from_diameter(d):
    return math.pi * (d / 2.0) ** 2


def diameter_from_area(a):
    return 2.0 * math.sqrt(a / math.pi)


def fmt(value, decimals=2):
    """Numero con el separador decimal del sistema."""
    return QtCore.QLocale().toString(float(value), "f", decimals)


def fmt_smart(value):
    v = abs(value)
    if v == 0:
        return "0"
    if v >= 100:
        return fmt(value, 1)
    if v >= 10:
        return fmt(value, 2)
    return fmt(value, 3)


def fmt_duration(seconds):
    if seconds is None or not math.isfinite(seconds):
        return "—"
    s = int(round(max(0.0, seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return "%d h %02d min" % (h, m)
    if m:
        return "%d min %02d s" % (m, sec)
    return "%d s" % sec


def today_str():
    return datetime.now().strftime("%d/%m/%Y")


# =============================================================
#  Configuracion persistente
# =============================================================
def config_dir():
    base = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), ".config")
    path = os.path.join(base, "BombaJeringa")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


CONFIG_FILE = os.path.join(config_dir(), "config.json")


def builtin_syringes():
    return [{"name": n, "capacity_ml": c, "area_mm2": a,
             "method": "factory", "date": ""}
            for n, c, a in BUILTIN_SYRINGES]


def default_config():
    return {
        "machine": dict(DEFAULT_MACHINE),
        "syringes": builtin_syringes(),
        "selected": "BD Plastipak 10 mL",
        "volume": 1.0,
        "volume_unit": "mL",
        "flow": 1.0,
        "flow_unit": "mL/min",
        "infuse": True,
        "manual_step": 1,
        "last_port": "",
    }


def load_config():
    cfg = default_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in cfg:
            if key not in data:
                continue
            if key == "machine" and isinstance(data[key], dict):
                cfg["machine"].update(data[key])
            else:
                cfg[key] = data[key]
    except (OSError, ValueError):
        pass
    clean = []
    for s in cfg.get("syringes", []):
        try:
            if s["name"] and float(s["area_mm2"]) > 0:
                s.setdefault("capacity_ml", 0.0)
                s.setdefault("method", "factory")
                s.setdefault("date", "")
                clean.append(s)
        except (KeyError, TypeError, ValueError):
            pass
    cfg["syringes"] = clean or builtin_syringes()
    if cfg["volume_unit"] not in VOLUME_UNITS:
        cfg["volume_unit"] = "mL"
    if cfg["flow_unit"] not in FLOW_UNITS:
        cfg["flow_unit"] = "mL/min"
    return cfg


def save_config(cfg):
    tmp = CONFIG_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_FILE)
    except OSError:
        pass


# =============================================================
#  Comunicacion con el Arduino
# =============================================================
class SerialReader(QtCore.QThread):
    message = QtCore.pyqtSignal(str)
    lost = QtCore.pyqtSignal()

    def __init__(self, ser):
        super().__init__()
        self.ser = ser
        self._running = True

    def run(self):
        buffer = ""
        while self._running:
            try:
                waiting = self.ser.in_waiting
                if waiting:
                    buffer += self.ser.read(waiting).decode(
                        "ascii", errors="ignore")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            self.message.emit(line)
                else:
                    self.msleep(15)
            except (serial.SerialException, OSError, TypeError,
                    AttributeError):
                if self._running:
                    self.lost.emit()
                break

    def stop(self):
        self._running = False
        self.wait(1000)


class PumpController(QtCore.QObject):
    """Habla con el firmware y lleva el estado de la bomba."""

    log = QtCore.pyqtSignal(str)
    state_changed = QtCore.pyqtSignal()
    progress = QtCore.pyqtSignal(int, int)          # pasos hechos, total
    finished = QtCore.pyqtSignal(bool, str)         # completado, dueno

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self.ser = None
        self.reader = None
        self.port = ""
        self.connected = False
        self.ready = False
        self.busy = False
        self.paused = False
        self.owner = None
        self.total_steps = 0
        self.done_steps = 0
        self.speed_steps = 0.0
        self._stop_requested = False

        self._ready_timer = QtCore.QTimer(self)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.setInterval(4000)
        self._ready_timer.timeout.connect(self._on_ready_timeout)

    def steps_per_mm(self):
        m = self.machine
        return m["steps_per_rev"] * m["microsteps"] / m["mm_per_rev"]

    def max_speed_mm_s(self):
        return MAX_STEPS_PER_S / self.steps_per_mm()

    @property
    def operational(self):
        return self.connected and self.ready

    def connect_port(self, port):
        try:
            self.ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
        except (OSError, serial.SerialException) as e:
            self.ser = None
            self.log.emit("ERROR al abrir %s: %s" % (port, e))
            return False, str(e)
        self.reader = SerialReader(self.ser)
        self.reader.message.connect(self._on_line)
        self.reader.lost.connect(self._on_lost)
        self.reader.start()
        self.port = port
        self.connected = True
        self.ready = False
        self.busy = False
        self.paused = False
        self.owner = None
        self.log.emit("Conectando a %s @ %d baud..." % (port, BAUD_RATE))
        self._ready_timer.start()
        self.state_changed.emit()
        return True, ""

    def disconnect_port(self):
        self._ready_timer.stop()
        if self.reader:
            self.reader.stop()
            self.reader = None
        if self.ser:
            try:
                self.ser.close()
            except (serial.SerialException, OSError):
                pass
            self.ser = None
        was = self.connected
        self.connected = self.ready = self.busy = self.paused = False
        self.owner = None
        if was:
            self.log.emit("Desconectado")
        self.state_changed.emit()

    def _on_lost(self):
        self.log.emit("Se perdió la conexión con la bomba (¿cable USB?)")
        self.disconnect_port()

    def _on_ready_timeout(self):
        if self.connected and not self.ready:
            self.ready = True
            self.log.emit("Aviso: el Arduino no envió el mensaje de inicio; "
                          "se continúa igual.")
            self.state_changed.emit()

    def _on_line(self, line):
        self.log.emit("← " + line)
        if "Arduino is ready" in line:
            self._ready_timer.stop()
            if not self.ready:
                self.ready = True
                self.state_changed.emit()
        elif line.startswith("<DISP1|"):
            try:
                remaining = abs(int(float(line.split("|")[1].rstrip(">"))))
            except (ValueError, IndexError):
                return
            if self.busy:
                self.done_steps = max(0, self.total_steps - remaining)
                self.progress.emit(self.done_steps, self.total_steps)
        elif line.startswith("<DONE>"):
            if not self.busy:
                return
            owner = self.owner
            completed = not self._stop_requested
            if completed:
                self.done_steps = self.total_steps
            self.progress.emit(self.done_steps, self.total_steps)
            self.busy = False
            self.paused = False
            self.owner = None
            self._stop_requested = False
            self.finished.emit(completed, owner or "")
            self.state_changed.emit()

    def _send(self, cmd):
        if not self.ser:
            return
        try:
            self.ser.write(cmd.encode("ascii"))
            self.log.emit("→ " + cmd)
        except (serial.SerialException, OSError) as e:
            self.log.emit("ERROR al enviar: %s" % e)
            self._on_lost()

    def move_mm(self, mm, infuse, speed_mm_s, owner, accel_mm_s2=None):
        """Mueve el carro 'mm' milimetros. Devuelve True si se envio."""
        if not self.operational or self.busy:
            return False
        spm = self.steps_per_mm()
        steps = int(round(abs(mm) * spm))
        if steps < 1:
            return False
        speed = min(speed_mm_s * spm, MAX_STEPS_PER_S)
        if speed < 1e-4:
            return False
        accel = max(1.0, (accel_mm_s2 or self.machine["accel_mm_s2"]) * spm)
        # En esta bomba (cableado actual) empujar el embolo = "F" del firmware.
        # Infundir, Avanzar y la calibracion usan todos infuse=True.
        direction = "F" if infuse else "B"
        if self.machine["invert"]:
            direction = "B" if direction == "F" else "F"

        self._send("<SETTING,SPEED,1,%.6f,F,0,0,0>" % speed)
        self._send("<SETTING,ACCEL,1,%.3f,F,0,0,0>" % accel)
        self._send("<RUN,DIST,1,0,%s,%d,0,0>" % (direction, steps))

        self.busy = True
        self.paused = False
        self.owner = owner
        self.total_steps = steps
        self.done_steps = 0
        self.speed_steps = speed
        self._stop_requested = False
        self.progress.emit(0, steps)
        self.state_changed.emit()
        return True

    def pause(self):
        if self.busy and not self.paused:
            self._send("<PAUSE,X,1,X,F,0,0,0>")
            self.paused = True
            self.state_changed.emit()

    def resume(self):
        if self.busy and self.paused:
            self._send("<RESUME,X,1,X,F,0,0,0>")
            self.paused = False
            self.state_changed.emit()

    def stop(self):
        if self.busy:
            self._stop_requested = True
            self._send("<STOP,X,X,X,F,0,0,0>")


# =============================================================
#  Widgets de apoyo
# =============================================================
def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def set_prop(w, name, value):
    if w.property(name) != value:
        w.setProperty(name, value)
        repolish(w)


def label(text, role=None, wrap=False, align=None):
    lbl = QtWidgets.QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        lbl.setWordWrap(True)
    if align is not None:
        lbl.setAlignment(align)
    return lbl


def button(text, kind=None, tooltip=None):
    b = QtWidgets.QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def make_card(title=None):
    frame = QtWidgets.QFrame()
    frame.setProperty("card", True)
    lay = QtWidgets.QVBoxLayout(frame)
    lay.setContentsMargins(22, 18, 22, 20)
    lay.setSpacing(14)
    if title:
        lay.addWidget(label(title, "cardTitle"))
    shadow = QtWidgets.QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(24)
    shadow.setOffset(0, 2)
    shadow.setColor(QtGui.QColor(15, 23, 42, 20))
    frame.setGraphicsEffect(shadow)
    return frame, lay


def scroll_page(page):
    """Envuelve una pagina con scroll: el contenido nunca se aplasta."""
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(page)
    return scroll


class NoWheelSpin(QtWidgets.QDoubleSpinBox):
    """Spinbox que no cambia el valor al hacer scroll por encima."""

    def __init__(self, decimals=2, minimum=0.0, maximum=1e6, value=0.0,
                 suffix="", big=False):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.setDecimals(decimals)
        self.setRange(minimum, maximum)
        self.setValue(value)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if suffix:
            self.setSuffix(suffix)
        if big:
            self.setProperty("big", True)
        self.setMinimumWidth(100)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoWheelCombo(QtWidgets.QComboBox):
    def __init__(self, big=False):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        if big:
            self.setProperty("big", True)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class Segmented(QtWidgets.QWidget):
    """Grupo de botones con una sola opcion activa."""
    changed = QtCore.pyqtSignal(int)

    def __init__(self, labels, tall=False):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        n = len(labels)
        for i, text in enumerate(labels):
            b = QtWidgets.QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("seg", "first" if i == 0 else
                          ("last" if i == n - 1 else "mid"))
            if tall:
                b.setProperty("tall", True)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)
        self.group.buttonClicked.connect(
            lambda b: self.changed.emit(self.group.id(b)))

    def index(self):
        return self.group.checkedId()

    def set_index(self, i):
        if 0 <= i < len(self.buttons):
            self.buttons[i].setChecked(True)


class RingProgress(QtWidgets.QWidget):
    """Anillo de progreso con el volumen en el centro."""

    def __init__(self):
        super().__init__()
        self._frac = 0.0
        self._value = "0"
        self._unit = "mL"
        self._sub = ""
        self._color = QtGui.QColor(BLUE)
        self.setMinimumSize(190, 190)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)

    def sizeHint(self):
        return QtCore.QSize(230, 230)

    def set_state(self, frac, value, unit, sub, color):
        self._frac = max(0.0, min(1.0, frac))
        self._value, self._unit, self._sub = value, unit, sub
        self._color = QtGui.QColor(color)
        self.update()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 8
        thick = max(10.0, side * 0.065)
        r = QtCore.QRectF((self.width() - side) / 2 + thick / 2,
                          (self.height() - side) / 2 + thick / 2,
                          side - thick, side - thick)
        pen = QtGui.QPen(QtGui.QColor("#e5e7eb"), thick, Qt.SolidLine,
                         Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(r)
        if self._frac > 0:
            pen.setColor(self._color)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, int(-self._frac * 360 * 16))

        f = QtGui.QFont(self.font())
        f.setBold(True)
        f.setPixelSize(max(14, int(side * 0.17)))
        p.setFont(f)
        p.setPen(QtGui.QColor("#0f172a"))
        top = QtCore.QRectF(r.left(), r.center().y() - side * 0.16,
                            r.width(), side * 0.2)
        p.drawText(top, Qt.AlignCenter, self._value)
        f.setBold(False)
        f.setPixelSize(max(10, int(side * 0.065)))
        p.setFont(f)
        p.setPen(QtGui.QColor("#6b7280"))
        unit_r = QtCore.QRectF(r.left(), r.center().y() + side * 0.05,
                               r.width(), side * 0.09)
        p.drawText(unit_r, Qt.AlignCenter, self._unit)
        sub_r = QtCore.QRectF(r.left(), r.center().y() + side * 0.14,
                              r.width(), side * 0.09)
        p.drawText(sub_r, Qt.AlignCenter, self._sub)
        p.end()


def make_icon_pixmap(size=256):
    """Icono de la aplicacion dibujado en codigo."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    s = size / 256.0
    grad = QtGui.QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, QtGui.QColor("#3b82f6"))
    grad.setColorAt(1, QtGui.QColor("#1d4ed8"))
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QBrush(grad))
    p.drawRoundedRect(QtCore.QRectF(8 * s, 8 * s, 240 * s, 240 * s),
                      56 * s, 56 * s)
    p.translate(size / 2.0, size / 2.0)
    p.rotate(-45)
    white = QtGui.QColor("#ffffff")
    p.setBrush(white)
    p.drawRoundedRect(QtCore.QRectF(-58 * s, -24 * s, 100 * s, 48 * s),
                      7 * s, 7 * s)
    p.setBrush(QtGui.QColor("#93c5fd"))
    p.drawRect(QtCore.QRectF(-6 * s, -16 * s, 42 * s, 32 * s))
    p.setBrush(white)
    p.drawRoundedRect(QtCore.QRectF(-68 * s, -36 * s, 10 * s, 72 * s),
                      3 * s, 3 * s)
    p.drawRect(QtCore.QRectF(-104 * s, -7 * s, 48 * s, 14 * s))
    p.drawRoundedRect(QtCore.QRectF(-112 * s, -26 * s, 11 * s, 52 * s),
                      3 * s, 3 * s)
    path = QtGui.QPainterPath()
    path.moveTo(42 * s, -13 * s)
    path.lineTo(58 * s, -5 * s)
    path.lineTo(58 * s, 5 * s)
    path.lineTo(42 * s, 13 * s)
    path.closeSubpath()
    p.drawPath(path)
    p.drawRect(QtCore.QRectF(58 * s, -2.5 * s, 50 * s, 5 * s))
    p.end()
    return pm


# =============================================================
#  Asistente: nueva jeringa / calibrar jeringa
# =============================================================
class SyringeDialog(QtWidgets.QDialog):
    P_INFO, P_METHOD, P_ALIGN, P_MOVE, P_RESULT, P_DIAM = range(6)

    def __init__(self, parent, pump, jog_speed, existing_names,
                 syringe=None):
        super().__init__(parent)
        self.pump = pump
        self.jog_speed = jog_speed
        self.orig = syringe
        self.existing = {n.lower() for n in existing_names
                         if not syringe or n != syringe["name"]}
        self.result_syringe = None
        self._cmd_mm = None
        self._moved_mm = None
        self._history = []

        self.setWindowTitle("Calibrar jeringa" if syringe else
                            "Nueva jeringa")
        self.setMinimumWidth(560)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(16)

        self.step_lbl = label("", "small")
        root.addWidget(self.step_lbl)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._page_info())
        self.stack.addWidget(self._page_method())
        self.stack.addWidget(self._page_align())
        self.stack.addWidget(self._page_move())
        self.stack.addWidget(self._page_result())
        self.stack.addWidget(self._page_diam())
        root.addWidget(self.stack, 1)

        nav = QtWidgets.QHBoxLayout()
        self.back_btn = button("Atrás", "ghost")
        self.cancel_btn = button("Cancelar", "ghost")
        self.next_btn = button("Siguiente", "primary")
        self.next_btn.setMinimumWidth(150)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        nav.addWidget(self.cancel_btn)
        nav.addWidget(self.next_btn)
        root.addLayout(nav)

        if syringe:
            self.name_edit.setText(syringe["name"])
            if syringe.get("capacity_ml"):
                self.cap_spin.setValue(float(syringe["capacity_ml"]))
            self.diam_spin.setValue(diameter_from_area(syringe["area_mm2"]))

        self.back_btn.clicked.connect(self._back)
        self.cancel_btn.clicked.connect(self.reject)
        self.next_btn.clicked.connect(self._next)
        self.name_edit.textChanged.connect(self._update)
        self.cap_spin.valueChanged.connect(self._update)
        for w in (self.diam_spin, self.init_spin, self.final_spin,
                  self.grams_spin, self.dist_spin):
            w.valueChanged.connect(self._update)
        self.measure_seg.changed.connect(self._update)
        self.move_btn.clicked.connect(self._do_test_move)

        self.pump.state_changed.connect(self._update)
        self.pump.finished.connect(self._on_pump_finished)
        self.finished.connect(self._cleanup)

        self._go(self.P_INFO, remember=False)

    # ---------- Paginas ----------
    def _page(self, title, text=None):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        v.addWidget(label(title, "dlgTitle"))
        if text:
            v.addWidget(label(text, "muted", wrap=True))
        return w, v

    def _field(self, text, widget):
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(label(text, "small"))
        box.addWidget(widget)
        return box

    def _page_info(self):
        w, v = self._page("¿Qué jeringa es?")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setProperty("big", True)
        self.name_edit.setPlaceholderText("Ej.: Cranberry 10 mL")
        self.cap_spin = NoWheelSpin(1, 0.1, 1000, 10.0, " mL", big=True)
        row.addLayout(self._field("Nombre", self.name_edit), 3)
        row.addLayout(self._field("Capacidad", self.cap_spin), 1)
        v.addLayout(row)
        self.name_err = label("", "errText")
        v.addWidget(self.name_err)
        v.addStretch(1)
        return w

    def _page_method(self):
        w, v = self._page("¿Cómo quieres calibrarla?")
        self.choice_pump = button(
            "Con la bomba\nRecomendado · usa agua", "choice")
        self.choice_diam = button(
            "Por diámetro\nSi conoces el diámetro interior", "choice")
        self.choice_pump.clicked.connect(lambda: self._go(self.P_ALIGN))
        self.choice_diam.clicked.connect(lambda: self._go(self.P_DIAM))
        v.addWidget(self.choice_pump)
        v.addWidget(self.choice_diam)
        v.addStretch(1)
        return w

    def _page_align(self):
        w, v = self._page("Alinea el émbolo",
                          "Jeringa llena de agua, sin burbujas. Deja el borde "
                          "del émbolo justo sobre una marca.")
        self.pump_warn = label("Conecta la bomba para continuar.", "warn")
        v.addWidget(self.pump_warn)
        jog = QtWidgets.QHBoxLayout()
        jog.setSpacing(8)
        self.jog_btns = []
        for text, mm, infuse in (("−1 mm", 1.0, False), ("−0,1 mm", 0.1, False),
                                 ("+0,1 mm", 0.1, True), ("+1 mm", 1.0, True)):
            b = button(text.replace("0,1", fmt(0.1, 1)), None,
                       "Avanzar" if infuse else "Retroceder")
            b.setProperty("jog", True)
            b.clicked.connect(
                lambda _=False, mm=mm, inf=infuse: self._jog(mm, inf))
            jog.addWidget(b)
            self.jog_btns.append(b)
        jog.addStretch(1)
        v.addLayout(jog)

        v.addSpacing(6)
        v.addWidget(label("Voy a medir con…", "small"))
        self.measure_seg = Segmented(["Escala de la jeringa",
                                      "Balanza (más preciso)"])
        v.addWidget(self.measure_seg)
        self.init_box = QtWidgets.QWidget()
        b = QtWidgets.QHBoxLayout(self.init_box)
        b.setContentsMargins(0, 0, 0, 0)
        self.init_spin = NoWheelSpin(2, 0, 1000, 0.0, " mL", big=True)
        self.init_spin.setMaximumWidth(180)
        b.addWidget(label("Lectura actual", "field"))
        b.addWidget(self.init_spin)
        b.addStretch(1)
        v.addWidget(self.init_box)
        self.tare_lbl = label("Pon un vaso bajo la punta y tara la balanza "
                              "a cero.", "muted", wrap=True)
        v.addWidget(self.tare_lbl)
        v.addStretch(1)
        return w

    def _page_move(self):
        w, v = self._page("Mueve el émbolo",
                          "Más distancia = más precisión.")
        row = QtWidgets.QHBoxLayout()
        self.dist_spin = NoWheelSpin(1, 1, 150, 20.0, " mm", big=True)
        self.dist_spin.setMaximumWidth(160)
        self.est_lbl = label("", "muted")
        row.addWidget(self.dist_spin)
        row.addWidget(self.est_lbl)
        row.addStretch(1)
        v.addLayout(row)
        self.move_btn = button("Mover ahora", "go")
        v.addWidget(self.move_btn)
        self.move_status = label("", "muted", wrap=True)
        v.addWidget(self.move_status)
        v.addStretch(1)
        return w

    def _page_result(self):
        w, v = self._page("Anota el resultado")
        self.final_box = QtWidgets.QWidget()
        b = QtWidgets.QHBoxLayout(self.final_box)
        b.setContentsMargins(0, 0, 0, 0)
        self.final_spin = NoWheelSpin(2, 0, 1000, 0.0, " mL", big=True)
        self.final_spin.setMaximumWidth(180)
        b.addWidget(label("Nueva lectura", "field"))
        b.addWidget(self.final_spin)
        b.addStretch(1)
        v.addWidget(self.final_box)
        self.grams_box = QtWidgets.QWidget()
        b = QtWidgets.QHBoxLayout(self.grams_box)
        b.setContentsMargins(0, 0, 0, 0)
        self.grams_spin = NoWheelSpin(3, 0, 1000, 0.0, " g", big=True)
        self.grams_spin.setMaximumWidth(180)
        b.addWidget(label("Peso del agua", "field"))
        b.addWidget(self.grams_spin)
        b.addStretch(1)
        v.addWidget(self.grams_box)
        self.result_lbl = label("", "result", wrap=True)
        v.addWidget(self.result_lbl)
        v.addStretch(1)
        return w

    def _page_diam(self):
        w, v = self._page("Diámetro interior",
                          "Medido con calibre o de la ficha del fabricante.")
        self.diam_spin = NoWheelSpin(2, 0, 60, 0.0, " mm", big=True)
        self.diam_spin.setMaximumWidth(180)
        v.addWidget(self.diam_spin)
        self.diam_result = label("", "result", wrap=True)
        v.addWidget(self.diam_result)
        v.addStretch(1)
        return w

    # ---------- Navegacion ----------
    def _go(self, page, remember=True):
        if remember:
            self._history.append(self.stack.currentIndex())
        if page == self.P_MOVE and self._moved_mm is None:
            self._suggest_distance()
        self.stack.setCurrentIndex(page)
        self._update()

    def _back(self):
        if self._history:
            self._go(self._history.pop(), remember=False)

    def _next(self):
        page = self.stack.currentIndex()
        if page == self.P_INFO:
            self._go(self.P_METHOD)
        elif page == self.P_ALIGN:
            self._go(self.P_MOVE)
        elif page == self.P_MOVE:
            self._go(self.P_RESULT)
        elif page in (self.P_RESULT, self.P_DIAM):
            self._save()

    # ---------- Logica ----------
    def _estimate_area(self):
        if self.diam_spin.value() > 0:
            return area_from_diameter(self.diam_spin.value())
        if self.orig:
            return self.orig["area_mm2"]
        return self.cap_spin.value() * 1000.0 / 60.0

    def _safe_ml(self):
        """Volumen de prueba que no vacia la jeringa (deja 1 mL de margen)."""
        ml = 0.4 * self.cap_spin.value()
        if not self._weight_mode():
            ml = min(ml, self.init_spin.value() - 1.0)
        return max(0.1, ml)

    def _suggest_distance(self):
        area = self._estimate_area()
        dist = self._safe_ml() * 1000.0 / area
        self.dist_spin.setValue(max(1.0, min(60.0, round(dist, 1))))

    def _weight_mode(self):
        return self.measure_seg.index() == 1

    def _name_problem(self):
        name = self.name_edit.text().strip()
        if not name:
            return "Escribe un nombre."
        if name.lower() in self.existing:
            return "Ya existe una jeringa con ese nombre."
        return None

    def _compute(self):
        """Devuelve (area, metodo)."""
        if self.stack.currentIndex() == self.P_DIAM:
            d = self.diam_spin.value()
            if d <= 0:
                return None, None
            return area_from_diameter(d), "diameter"
        if self._moved_mm is None:
            return None, None
        if self._weight_mode():
            dv = self.grams_spin.value() / WATER_DENSITY
            method = "pump_weight"
        else:
            dv = abs(self.init_spin.value() - self.final_spin.value())
            method = "pump_scale"
        if dv <= 0:
            return None, None
        return dv * 1000.0 / self._moved_mm, method

    def _result_text(self, area):
        if not area:
            return "", "result"
        text = "1 mL = %s mm" % fmt(1000.0 / area, 2)
        d = diameter_from_area(area)
        cap = self.cap_spin.value()
        length = cap * 1000.0 / area
        plausible = 1.0 <= d <= 45.0 and 15 <= length <= 160
        pump = self.stack.currentIndex() == self.P_RESULT
        if pump and self._moved_mm:
            dv = area * self._moved_mm / 1000.0
            if self._weight_mode():
                how = "%s g de agua" % fmt(self.grams_spin.value(), 2)
            else:
                how = "de %s a %s mL" % (fmt(self.init_spin.value(), 2),
                                         fmt(self.final_spin.value(), 2))
            detail = ("La bomba empujó %s mm y anotaste %s = %s mL."
                      % (fmt(self._moved_mm, 1), how, fmt(dv, 2)))
        else:
            detail = ""
        if plausible:
            return (text + "   ·   Ø %s mm" % fmt(d, 2)
                    + ("\n" + detail if detail else "")), "result"
        msg = text + "\nValor poco probable."
        if detail:
            # Volumen tipico para esa distancia (la escala de una
            # jeringa suele medir ~60 mm de largo)
            expected = self._moved_mm * (cap * 1000.0 / 60.0) / 1000.0
            msg += ("\n%s\nEn una jeringa de %s mL deberían salir unos "
                    "%s mL." % (detail, fmt(cap, 0), fmt(expected, 1)))
            if dv < expected:
                msg += ("\nRevisa que la «Lectura actual» sea donde estaba "
                        "el émbolo y que el carro tocara el émbolo.")
            else:
                msg += "\nRevisa las lecturas de la escala."
        else:
            msg += " Revisa el diámetro."
        return msg, "warn"

    def _update(self, *_):
        page = self.stack.currentIndex()
        if page in (self.P_ALIGN, self.P_MOVE, self.P_RESULT):
            num = {self.P_ALIGN: 3, self.P_MOVE: 4, self.P_RESULT: 5}[page]
            total = 5
        else:
            num = {self.P_INFO: 1, self.P_METHOD: 2, self.P_DIAM: 3}[page]
            total = 3 if page == self.P_DIAM else 5
        self.step_lbl.setText("PASO %d DE %d" % (num, total))

        self.back_btn.setVisible(bool(self._history))
        self.next_btn.setVisible(page != self.P_METHOD)
        final = page in (self.P_RESULT, self.P_DIAM)
        self.next_btn.setText("Guardar" if final else "Siguiente")

        ok = self.pump.operational
        idle = ok and not self.pump.busy
        weight = self._weight_mode()

        if page == self.P_INFO:
            prob = self._name_problem()
            self.name_err.setText(prob if self.name_edit.text().strip()
                                  else "")
            self.next_btn.setEnabled(prob is None)
        elif page == self.P_ALIGN:
            self.pump_warn.setVisible(not ok)
            for b in self.jog_btns:
                b.setEnabled(idle)
            self.init_box.setVisible(not weight)
            self.tare_lbl.setVisible(weight)
            self.next_btn.setEnabled(ok and (weight or
                                             self.init_spin.value() > 0))
        elif page == self.P_MOVE:
            ml = self.dist_spin.value() * self._estimate_area() / 1000.0
            self.est_lbl.setText("≈ %s mL" % fmt(ml, 1))
            risky = (not weight and
                     ml > self.init_spin.value() - 0.5)
            set_prop(self.est_lbl, "role", "errText" if risky else "muted")
            if risky:
                self.est_lbl.setText("≈ %s mL: vaciaría la jeringa, usa menos "
                                     "distancia" % fmt(ml, 1))
            self.move_btn.setEnabled(idle and not risky)
            self.next_btn.setEnabled(self._moved_mm is not None
                                     and not self.pump.busy)
        elif page == self.P_RESULT:
            self.final_box.setVisible(not weight)
            self.grams_box.setVisible(weight)
            area, _m = self._compute()
            text, role = self._result_text(area)
            self.result_lbl.setText(text)
            set_prop(self.result_lbl, "role", role)
            self.result_lbl.setVisible(bool(text))
            self.next_btn.setEnabled(bool(area))
        elif page == self.P_DIAM:
            area, _m = self._compute()
            text, role = self._result_text(area)
            self.diam_result.setText(text)
            set_prop(self.diam_result, "role", role)
            self.diam_result.setVisible(bool(text))
            self.next_btn.setEnabled(bool(area))

    def _jog(self, mm, infuse):
        self.pump.move_mm(mm, infuse, self.jog_speed(), "syr_jog")

    def _do_test_move(self):
        dist = self.dist_spin.value()
        if self.pump.move_mm(dist, True, self.jog_speed(), "syr_test"):
            self._cmd_mm = dist
            self._moved_mm = None
            self.move_status.setText("Moviendo…")
            set_prop(self.move_status, "role", "muted")
            self._update()

    def _on_pump_finished(self, completed, owner):
        if owner != "syr_test" or self._cmd_mm is None:
            return
        if completed:
            self._moved_mm = self._cmd_mm
            self.move_status.setText("Listo, avanzó %s mm"
                                     % fmt(self._moved_mm, 1))
            set_prop(self.move_status, "role", "ok")
        else:
            self._moved_mm = None
            self.move_status.setText("Interrumpido. Vuelve a alinear y "
                                     "repite.")
            set_prop(self.move_status, "role", "warn")
        self._update()

    def _save(self):
        area, method = self._compute()
        if not area:
            return
        self.result_syringe = {
            "name": self.name_edit.text().strip(),
            "capacity_ml": self.cap_spin.value(),
            "area_mm2": area,
            "method": method,
            "date": today_str(),
        }
        self.accept()

    def _cleanup(self, _result=None):
        if self.pump.busy and self.pump.owner in ("syr_jog", "syr_test"):
            self.pump.stop()
        for sig, slot in ((self.pump.state_changed, self._update),
                          (self.pump.finished, self._on_pump_finished)):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass


# =============================================================
#  Ventana principal
# =============================================================
class MainWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.pump = PumpController(self.cfg["machine"], self)

        self._dose = None
        self._dose_result = None      # "done" / "stopped"
        self._run_elapsed = 0.0
        self._run_t0 = None
        self._continuous = False
        self._screw_cmd = None
        self._port_sig = None
        self._loading = True

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QtGui.QIcon(make_icon_pixmap()))
        self.setMinimumSize(820, 560)

        self._build_ui()
        self._restore_from_config()
        self._loading = False

        self.pump.log.connect(self._log)
        self.pump.state_changed.connect(self._refresh_state)
        self.pump.progress.connect(self._on_progress)
        self.pump.finished.connect(self._on_finished)

        self.port_timer = QtCore.QTimer(self)
        self.port_timer.setInterval(2000)
        self.port_timer.timeout.connect(self._poll_ports)
        self.port_timer.start()

        self.tick = QtCore.QTimer(self)
        self.tick.setInterval(500)
        self.tick.timeout.connect(self._update_status_card)

        QtWidgets.QApplication.instance().applicationStateChanged.connect(
            self._on_app_state)

        self.refresh_ports(force=True)
        self._refresh_all()

    # ---------------------------------------------------------
    #  Construccion de la interfaz
    # ---------------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(scroll_page(self._build_dose_page()), "Dosificar")
        self.tabs.addTab(scroll_page(self._build_syringe_page()), "Jeringas")
        self.tabs.addTab(scroll_page(self._build_settings_page()), "Ajustes")
        style_tabbar(self.tabs)
        root.addWidget(self.tabs, 1)
        self.statusBar().hide()

    def _build_header(self):
        header = QtWidgets.QFrame()
        header.setObjectName("header")
        h = QtWidgets.QHBoxLayout(header)
        h.setContentsMargins(20, 10, 20, 10)
        h.setSpacing(10)

        logo = QtWidgets.QLabel()
        logo.setPixmap(QtGui.QIcon(make_icon_pixmap()).pixmap(34, 34))
        t = QtWidgets.QLabel(APP_NAME)
        t.setObjectName("appTitle")
        h.addWidget(logo)
        h.addWidget(t)
        h.addStretch(1)

        self.conn_pill = QtWidgets.QLabel()
        self.conn_pill.setProperty("pill", "off")
        self.port_combo = NoWheelCombo()
        self.port_combo.setMinimumWidth(200)
        self.port_combo.setToolTip("Puerto USB de la bomba (se detecta solo)")
        self.connect_btn = button("Conectar", "primary")
        self.connect_btn.setMinimumWidth(115)
        self.help_btn = button("?", None, "Ayuda")
        self.help_btn.setObjectName("helpBtn")

        h.addWidget(self.conn_pill)
        h.addWidget(self.port_combo)
        h.addWidget(self.connect_btn)
        h.addWidget(self.help_btn)

        self.connect_btn.clicked.connect(self.toggle_connection)
        self.help_btn.clicked.connect(self.show_help)
        return header

    def _page(self):
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        return page

    def _field(self, text, *widgets):
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(label(text, "small"))
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        for i, w in enumerate(widgets):
            row.addWidget(w, 1 if i == 0 else 0)
        box.addLayout(row)
        return box

    # ---------- Pagina: Dosificar ----------
    def _build_dose_page(self):
        page = self._page()
        g = QtWidgets.QGridLayout(page)
        g.setContentsMargins(20, 18, 20, 20)
        g.setSpacing(16)

        prog, pl = make_card()
        self.syr_combo = NoWheelCombo(big=True)
        self.syr_combo.setToolTip("Jeringa montada en la bomba")
        self.goto_syr_btn = button("Jeringas", "ghost", "Administrar jeringas")
        pl.addLayout(self._field("Jeringa", self.syr_combo,
                                 self.goto_syr_btn))

        self.action_seg = Segmented(["Infundir", "Retirar"], tall=True)
        self.action_seg.buttons[0].setToolTip("Empujar: saca líquido")
        self.action_seg.buttons[1].setToolTip("Aspirar: carga líquido")
        pl.addWidget(self.action_seg)

        self.vol_spin = NoWheelSpin(3, 0, 100000, 1.0, big=True)
        self.vol_unit = NoWheelCombo(big=True)
        self.vol_unit.addItems(VOLUME_UNITS.keys())
        self.flow_spin = NoWheelSpin(3, 0, 100000, 1.0, big=True)
        self.flow_unit = NoWheelCombo(big=True)
        self.flow_unit.addItems(FLOW_UNITS.keys())
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(self._field("Volumen", self.vol_spin, self.vol_unit), 1)
        row.addLayout(self._field("Caudal", self.flow_spin, self.flow_unit),
                      1)
        pl.addLayout(row)

        self.dose_hint = label("", "hintLine", wrap=True)
        pl.addWidget(self.dose_hint)
        pl.addStretch(1)

        btns = QtWidgets.QHBoxLayout()
        btns.setSpacing(10)
        self.start_btn = button("▶   Iniciar", "go")
        self.pause_btn = button("❚❚", "warn", "Pausar")
        self.stop_btn = button("■", "danger", "Detener")
        self.pause_btn.setMinimumWidth(80)
        self.stop_btn.setMinimumWidth(80)
        btns.addWidget(self.start_btn, 1)
        btns.addWidget(self.pause_btn)
        btns.addWidget(self.stop_btn)
        pl.addLayout(btns)

        stat, sl = make_card()
        self.state_pill = QtWidgets.QLabel()
        self.state_pill.setProperty("state", "offline")
        self.state_pill.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.state_pill, 0, Qt.AlignHCenter)
        self.ring = RingProgress()
        sl.addWidget(self.ring, 1)
        stats = QtWidgets.QHBoxLayout()
        self.eta_lbl = label("—", "statValue", align=Qt.AlignCenter)
        self.rate_lbl = label("—", "statValue", align=Qt.AlignCenter)
        for title, w in (("Restante", self.eta_lbl), ("Caudal", self.rate_lbl)):
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(w)
            box.addWidget(label(title, "small", align=Qt.AlignCenter))
            stats.addLayout(box, 1)
        sl.addLayout(stats)

        man, ml = make_card()
        top = QtWidgets.QHBoxLayout()
        top.addWidget(label("Mover émbolo", "cardTitle"))
        top.addStretch(1)
        self.retract_btn = button("Retroceder todo", "ghost")
        top.addWidget(self.retract_btn)
        ml.addLayout(top)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        self.step_seg = Segmented(
            ["%s mL" % fmt(v, 2 if v < 0.1 else 1) for v in MANUAL_STEPS_ML]
            + ["Mantener"])
        self.step_seg.buttons[-1].setToolTip(
            "Mantén presionado Avanzar o Retroceder; se detiene al soltar")
        row.addWidget(self.step_seg)
        row.addStretch(1)
        self.back_btn = button("Retroceder", "jogBig", "Retroceder (aspirar)")
        self.fwd_btn = button("Avanzar", "jogBig", "Avanzar (empujar)")
        row.addWidget(self.back_btn)
        row.addWidget(self.fwd_btn)
        ml.addLayout(row)

        g.addWidget(prog, 0, 0)
        g.addWidget(stat, 0, 1)
        g.addWidget(man, 1, 0, 1, 2)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 2)
        g.setRowStretch(0, 1)

        self.goto_syr_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        self.syr_combo.currentIndexChanged.connect(self._on_syr_combo)
        self.action_seg.changed.connect(self._on_program_changed)
        self.vol_spin.valueChanged.connect(self._on_program_changed)
        self.flow_spin.valueChanged.connect(self._on_program_changed)
        self.vol_unit.currentIndexChanged.connect(self._on_program_changed)
        self.flow_unit.currentIndexChanged.connect(self._on_program_changed)
        self.start_btn.clicked.connect(self.start_dose)
        self.pause_btn.clicked.connect(self.pause_resume)
        self.stop_btn.clicked.connect(self.stop_all)
        self.retract_btn.clicked.connect(self.retract_all)
        self.step_seg.changed.connect(self._on_step_mode)
        for b, infuse in ((self.fwd_btn, True), (self.back_btn, False)):
            b.pressed.connect(lambda inf=infuse: self._manual_pressed(inf))
            b.released.connect(self._manual_released)
            b.clicked.connect(lambda _=False, inf=infuse:
                              self._manual_clicked(inf))
        return page

    # ---------- Pagina: Jeringas ----------
    def _build_syringe_page(self):
        page = self._page()
        g = QtWidgets.QGridLayout(page)
        g.setContentsMargins(20, 18, 20, 20)
        g.setSpacing(16)

        lib, ll = make_card()
        self.syr_list = QtWidgets.QListWidget()
        self.syr_list.setObjectName("syrList")
        self.syr_list.setMinimumHeight(260)
        ll.addWidget(self.syr_list, 1)
        self.new_syr_btn = button("+   Nueva jeringa", "primary")
        ll.addWidget(self.new_syr_btn)

        det, dl = make_card()
        self.det_name = label("", "detailTitle", wrap=True)
        self.det_tag = QtWidgets.QLabel()
        self.det_tag.setProperty("tag", "factory")
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.det_name, 1)
        top.addWidget(self.det_tag, 0, Qt.AlignTop)
        dl.addLayout(top)

        stats = QtWidgets.QHBoxLayout()
        stats.setSpacing(12)
        self.det = {}
        for key, title in (("cap", "Capacidad"), ("ml_mm", "1 mL ="),
                           ("diam", "Diámetro")):
            tile = QtWidgets.QFrame()
            tile.setProperty("tile", True)
            tv = QtWidgets.QVBoxLayout(tile)
            tv.setContentsMargins(14, 12, 14, 12)
            tv.setSpacing(2)
            tv.addWidget(label(title, "small"))
            self.det[key] = label("", "tileValue")
            tv.addWidget(self.det[key])
            stats.addWidget(tile, 1)
        dl.addLayout(stats)
        self.det_date = label("", "small")
        dl.addWidget(self.det_date)

        row = QtWidgets.QHBoxLayout()
        self.use_btn = button("Usar esta jeringa", "primary")
        self.calib_btn = button("Calibrar")
        self.del_syr_btn = button("Eliminar", "ghost")
        row.addWidget(self.use_btn)
        row.addWidget(self.calib_btn)
        row.addStretch(1)
        row.addWidget(self.del_syr_btn)
        dl.addLayout(row)
        dl.addStretch(1)

        g.addWidget(lib, 0, 0)
        g.addWidget(det, 0, 1)
        g.setColumnStretch(0, 2)
        g.setColumnStretch(1, 3)

        self.syr_list.currentRowChanged.connect(self._on_syr_list)
        self.new_syr_btn.clicked.connect(lambda: self.edit_syringe(None))
        self.calib_btn.clicked.connect(
            lambda: self.edit_syringe(self._list_syringe()))
        self.syr_list.itemDoubleClicked.connect(
            lambda _i: self._use_list_syringe())
        self.del_syr_btn.clicked.connect(self.delete_syringe)
        self.use_btn.clicked.connect(self._use_list_syringe)
        return page

    # ---------- Pagina: Ajustes ----------
    def _build_settings_page(self):
        page = self._page()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 20)
        v.setSpacing(16)

        mech, ml = make_card("Mecánica")
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)
        self.spr_combo = NoWheelCombo()
        self.spr_combo.addItem("200 (1,8°)", 200)
        self.spr_combo.addItem("400 (0,9°)", 400)
        self.spr_combo.setToolTip("Pasos por vuelta del motor")
        self.micro_combo = NoWheelCombo()
        for m in (1, 2, 4, 8, 16, 32):
            self.micro_combo.addItem(str(m), m)
        self.micro_combo.setToolTip("A4988 con MS1–MS3 a 5 V = 16")
        self.screw_combo = NoWheelCombo()
        for text, val in SCREW_PRESETS:
            self.screw_combo.addItem(text, val)
        self.screw_combo.setToolTip("Tipo de tornillo / varilla del carro")
        self.mmrev_spin = NoWheelSpin(4, 0.05, 50, 2.0, " mm")
        self.mmrev_spin.setToolTip("Cuánto avanza el carro por cada vuelta "
                                   "del motor")
        self.accel_spin = NoWheelSpin(2, 0.05, 100, 2.0, " mm/s²")
        self.jog_spin = NoWheelSpin(2, 0.01, 10, 0.7, " mm/s")
        self.jog_spin.setToolTip("Velocidad de Avanzar / Retroceder")
        self.fast_spin = NoWheelSpin(1, 0.5, 10, 2.5, " mm/s")
        self.fast_spin.setToolTip("Velocidad de Mantener y Retroceder todo")
        self.retract_spin = NoWheelSpin(0, 5, 300, 60.0, " mm")
        self.retract_spin.setToolTip("Cuánto retrocede el carro con "
                                     "«Retroceder todo»")
        self.invert_chk = QtWidgets.QCheckBox("Invertir sentido del motor")
        self.invert_chk.setToolTip(
            "Márcalo si al avanzar el carro se aleja de la jeringa")
        fields = [("Tornillo", self.screw_combo),
                  ("Avance por vuelta", self.mmrev_spin),
                  ("Microstepping", self.micro_combo),
                  ("Pasos por vuelta", self.spr_combo),
                  ("Aceleración", self.accel_spin),
                  ("Velocidad manual", self.jog_spin),
                  ("Velocidad rápida", self.fast_spin),
                  ("Recorrido «Retroceder todo»", self.retract_spin)]
        for i, (k, w) in enumerate(fields):
            r, c = divmod(i, 3)
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(6)
            box.addWidget(label(k, "small"))
            box.addWidget(w)
            grid.addLayout(box, r, c)
        grid.addWidget(self.invert_chk, 3, 0, 1, 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        ml.addLayout(grid)
        self.mech_info = label("", "hintLine", wrap=True)
        ml.addWidget(self.mech_info)
        v.addWidget(mech)

        screw, sl = make_card("Calibrar tornillo")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        self.screw_dist = NoWheelSpin(1, 1, 150, 5.0, " mm")
        self.screw_move_btn = button("1 · Mover", "primary")
        self.screw_meas = NoWheelSpin(2, 0, 300, 0.0, " mm")
        self.screw_meas.setToolTip("Distancia que avanzó realmente el carro "
                                   "(medida con calibre)")
        self.screw_apply_btn = button("2 · Aplicar")
        row.addWidget(self.screw_dist)
        row.addWidget(self.screw_move_btn)
        row.addSpacing(14)
        row.addWidget(label("Medido:", "field"))
        row.addWidget(self.screw_meas)
        row.addWidget(self.screw_apply_btn)
        row.addStretch(1)
        sl.addLayout(row)
        self.screw_status = label("", "small", wrap=True)
        sl.addWidget(self.screw_status)
        v.addWidget(screw)

        logc, lgl = make_card()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(label("Registro técnico", "cardTitle"))
        row.addStretch(1)
        reset_btn = button("Valores de fábrica", "ghost")
        self.log_toggle = button("Mostrar", "ghost")
        row.addWidget(reset_btn)
        row.addWidget(self.log_toggle)
        lgl.addLayout(row)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        self.log_view.setMinimumHeight(180)
        self.log_view.setVisible(False)
        lgl.addWidget(self.log_view)
        v.addWidget(logc)
        v.addStretch(1)

        self.spr_combo.currentIndexChanged.connect(self._on_machine_changed)
        self.micro_combo.currentIndexChanged.connect(self._on_machine_changed)
        self.mmrev_spin.valueChanged.connect(self._on_machine_changed)
        self.screw_combo.currentIndexChanged.connect(self._on_screw_preset)
        self.invert_chk.toggled.connect(self._on_machine_changed)
        self.accel_spin.valueChanged.connect(self._on_machine_changed)
        self.jog_spin.valueChanged.connect(self._on_machine_changed)
        self.fast_spin.valueChanged.connect(self._on_machine_changed)
        self.retract_spin.valueChanged.connect(self._on_machine_changed)
        self.screw_move_btn.clicked.connect(self._screw_move)
        self.screw_apply_btn.clicked.connect(self._screw_apply)
        self.log_toggle.clicked.connect(self._toggle_log)
        reset_btn.clicked.connect(self.reset_machine)
        return page

    def _on_screw_preset(self, _idx):
        val = self.screw_combo.currentData()
        if val is not None and abs(val - self.mmrev_spin.value()) > 1e-6:
            self.mmrev_spin.setValue(val)

    def _sync_screw_combo(self):
        v = self.mmrev_spin.value()
        idx = self.screw_combo.count() - 1
        for i in range(self.screw_combo.count()):
            d = self.screw_combo.itemData(i)
            if d is not None and abs(d - v) < 1e-6:
                idx = i
                break
        self.screw_combo.blockSignals(True)
        self.screw_combo.setCurrentIndex(idx)
        self.screw_combo.blockSignals(False)

    def _toggle_log(self):
        vis = not self.log_view.isVisible()
        self.log_view.setVisible(vis)
        self.log_toggle.setText("Ocultar" if vis else "Mostrar")

    # ---------------------------------------------------------
    #  Configuracion <-> interfaz
    # ---------------------------------------------------------
    def _restore_from_config(self):
        c = self.cfg
        m = c["machine"]
        self._set_combo_data(self.spr_combo, m["steps_per_rev"])
        self._set_combo_data(self.micro_combo, m["microsteps"])
        self.mmrev_spin.setValue(m["mm_per_rev"])
        self._sync_screw_combo()
        self.invert_chk.setChecked(bool(m["invert"]))
        self.accel_spin.setValue(m["accel_mm_s2"])
        self.jog_spin.setValue(m["jog_speed_mm_s"])
        self.fast_spin.setValue(m["fast_speed_mm_s"])
        self.retract_spin.setValue(m["retract_mm"])
        self.vol_unit.setCurrentText(c["volume_unit"])
        self.flow_unit.setCurrentText(c["flow_unit"])
        self.vol_spin.setValue(float(c["volume"]))
        self.flow_spin.setValue(float(c["flow"]))
        self.action_seg.set_index(0 if c["infuse"] else 1)
        self.step_seg.set_index(int(c.get("manual_step", 1)))
        self._reload_syringes()

    @staticmethod
    def _set_combo_data(combo, value):
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _save(self):
        if not self._loading:
            save_config(self.cfg)

    def _on_machine_changed(self, *_):
        if self._loading:
            return
        m = self.cfg["machine"]
        m["steps_per_rev"] = self.spr_combo.currentData()
        m["microsteps"] = self.micro_combo.currentData()
        m["mm_per_rev"] = self.mmrev_spin.value()
        m["invert"] = self.invert_chk.isChecked()
        m["accel_mm_s2"] = self.accel_spin.value()
        m["jog_speed_mm_s"] = self.jog_spin.value()
        m["fast_speed_mm_s"] = self.fast_spin.value()
        m["retract_mm"] = self.retract_spin.value()
        self._sync_screw_combo()
        self._save()
        self._refresh_all()

    def _on_program_changed(self, *_):
        if self._loading:
            return
        c = self.cfg
        c["volume"] = self.vol_spin.value()
        c["volume_unit"] = self.vol_unit.currentText()
        c["flow"] = self.flow_spin.value()
        c["flow_unit"] = self.flow_unit.currentText()
        c["infuse"] = self.action_seg.index() == 0
        if not self.pump.busy:
            self._dose_result = None
        self._save()
        self._refresh_all()

    def fast_speed(self):
        return min(self.cfg["machine"]["fast_speed_mm_s"],
                   self.pump.max_speed_mm_s())

    def jog_speed(self):
        return min(self.cfg["machine"]["jog_speed_mm_s"],
                   self.pump.max_speed_mm_s())

    # ---------------------------------------------------------
    #  Jeringas
    # ---------------------------------------------------------
    def current_syringe(self):
        for s in self.cfg["syringes"]:
            if s["name"] == self.cfg["selected"]:
                return s
        return self.cfg["syringes"][0]

    def _list_syringe(self):
        row = self.syr_list.currentRow()
        if 0 <= row < len(self.cfg["syringes"]):
            return self.cfg["syringes"][row]
        return None

    def _reload_syringes(self, select=None, list_row=None):
        names = [s["name"] for s in self.cfg["syringes"]]
        sel = select or self.cfg["selected"]
        if sel not in names:
            sel = names[0]
        self.cfg["selected"] = sel
        idx = names.index(sel)
        for w in (self.syr_combo, self.syr_list):
            w.blockSignals(True)
            w.clear()
        self.syr_combo.addItems(names)
        for s in self.cfg["syringes"]:
            self.syr_list.addItem(s["name"] + ("   (en uso)" if s["name"] == sel else ""))
        self.syr_combo.setCurrentIndex(idx)
        self.syr_list.setCurrentRow(idx if list_row is None else list_row)
        for w in (self.syr_combo, self.syr_list):
            w.blockSignals(False)
        self._update_syr_detail()

    def _on_syr_combo(self, idx):
        if idx < 0:
            return
        self.cfg["selected"] = self.syr_combo.currentText()
        if not self.pump.busy:
            self._dose_result = None
        self._save()
        self._reload_syringes()
        self._refresh_all()

    def _on_syr_list(self, _row):
        self._update_syr_detail()

    def _use_list_syringe(self):
        s = self._list_syringe()
        if s and not (self.pump.busy and self.pump.owner == "dose"):
            self.syr_combo.setCurrentText(s["name"])
            self.tabs.setCurrentIndex(0)

    def _update_syr_detail(self):
        s = self._list_syringe()
        if not s:
            return
        a = s["area_mm2"]
        in_use = s["name"] == self.cfg["selected"]
        self.det_name.setText(s["name"])
        method = s.get("method", "factory")
        self.det_tag.setText(METHOD_LABELS.get(method, ""))
        set_prop(self.det_tag, "tag",
                 "factory" if method == "factory" else "calibrated")
        cap = s.get("capacity_ml") or 0
        self.det["cap"].setText("%s mL" % fmt(cap, 1) if cap else "—")
        self.det["ml_mm"].setText("%s mm" % fmt(1000.0 / a, 2))
        self.det["diam"].setText("%s mm" % fmt(diameter_from_area(a), 2))
        self.det_date.setText("Calibrada el " + s["date"] if s.get("date")
                              else "")
        self.use_btn.setText("En uso" if in_use else "Usar esta jeringa")
        self.use_btn.setEnabled(not in_use)

    def edit_syringe(self, syringe):
        if self.pump.busy:
            return
        names = [s["name"] for s in self.cfg["syringes"]]
        dlg = SyringeDialog(self, self.pump, self.jog_speed, names, syringe)
        if dlg.exec_() != QtWidgets.QDialog.Accepted or not dlg.result_syringe:
            return
        new = dlg.result_syringe
        if syringe is not None:
            i = self.cfg["syringes"].index(syringe)
            if syringe["name"] == self.cfg["selected"]:
                self.cfg["selected"] = new["name"]
            self.cfg["syringes"][i] = new
        else:
            self.cfg["syringes"].append(new)
        self._save()
        row = [s["name"] for s in self.cfg["syringes"]].index(new["name"])
        self._reload_syringes(list_row=row)
        self._refresh_all()

    def delete_syringe(self):
        s = self._list_syringe()
        if not s:
            return
        if len(self.cfg["syringes"]) <= 1:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Debe quedar al menos una jeringa.")
            return
        r = QtWidgets.QMessageBox.question(
            self, "Eliminar", "¿Eliminar «%s»?" % s["name"])
        if r != QtWidgets.QMessageBox.Yes:
            return
        self.cfg["syringes"].remove(s)
        self._save()
        self._reload_syringes()
        self._refresh_all()

    # ---------------------------------------------------------
    #  Conexion
    # ---------------------------------------------------------
    @staticmethod
    def _list_ports():
        out = []
        for p in sorted(serial.tools.list_ports.comports(),
                        key=lambda p: p.device):
            desc = (p.description or "").replace("(%s)" % p.device, "")
            desc = desc.strip()
            if desc.lower() in ("n/a", p.device.lower()):
                desc = ""
            likely = (p.vid in (0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4)
                      or "arduino" in desc.lower()
                      or "ch340" in desc.lower())
            out.append((p.device, desc, likely))
        return out

    def refresh_ports(self, force=False):
        ports = self._list_ports()
        sig = [p[0] for p in ports]
        if sig == self._port_sig and not force:
            return
        self._port_sig = sig
        current = self.port_combo.currentData() or self.cfg.get("last_port")
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for dev, desc, _likely in ports:
            self.port_combo.addItem("%s · %s" % (dev, desc) if desc else dev,
                                    dev)
        if not ports:
            self.port_combo.addItem("Sin bomba USB", None)
        idx = self.port_combo.findData(current) if current else -1
        if idx < 0:
            for i, (_dev, _desc, likely) in enumerate(ports):
                if likely:
                    idx = i
                    break
        self.port_combo.setCurrentIndex(max(0, idx))
        self.port_combo.blockSignals(False)
        self._refresh_state()

    def _poll_ports(self):
        if not self.pump.connected and not self.port_combo.view().isVisible():
            self.refresh_ports()

    def toggle_connection(self):
        if self.pump.connected:
            if self.pump.busy:
                r = QtWidgets.QMessageBox.question(
                    self, APP_NAME, "La bomba se está moviendo. ¿Detener y "
                    "desconectar?")
                if r != QtWidgets.QMessageBox.Yes:
                    return
                self.pump.stop()
            self.pump.disconnect_port()
            self.refresh_ports(force=True)
            return
        dev = self.port_combo.currentData()
        if not dev:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "No se detecta la bomba.\n\nConecta el cable "
                "USB y espera unos segundos.")
            return
        ok, err = self.pump.connect_port(dev)
        if not ok:
            QtWidgets.QMessageBox.critical(
                self, "No se pudo conectar",
                "No se pudo abrir %s.\n\nRevisa el cable y cierra otros "
                "programas que usen el puerto (por ejemplo el Monitor Serie "
                "de Arduino).\n\n%s" % (dev, err))
            return
        self.cfg["last_port"] = dev
        self._save()

    def _on_app_state(self, state):
        if state != Qt.ApplicationActive and self._continuous:
            self._manual_released()

    # ---------------------------------------------------------
    #  Dosificacion
    # ---------------------------------------------------------
    def _compute_dose(self):
        s = self.current_syringe()
        area = s["area_mm2"]
        vu = self.vol_unit.currentText()
        fu = self.flow_unit.currentText()
        vol_ml = self.vol_spin.value() * VOLUME_UNITS[vu]
        flow_ml_s = self.flow_spin.value() * FLOW_UNITS[fu]
        d = {"infuse": self.action_seg.index() == 0, "vol_ml": vol_ml,
             "vol_unit": vu, "flow_unit": fu, "flow": self.flow_spin.value(),
             "error": None, "warning": None}
        if vol_ml <= 0:
            d["error"] = "Indica un volumen"
            return d
        if flow_ml_s <= 0:
            d["error"] = "Indica un caudal"
            return d
        d["mm"] = vol_ml * 1000.0 / area
        d["speed_mm_s"] = flow_ml_s * 1000.0 / area
        d["duration"] = vol_ml / flow_ml_s
        max_mm_s = self.pump.max_speed_mm_s()
        if d["speed_mm_s"] > max_mm_s * 1.0001:
            max_flow = max_mm_s * area / 1000.0 / FLOW_UNITS[fu]
            d["error"] = "Caudal máximo con esta jeringa: %s %s" % (
                fmt_smart(max_flow), fu)
            return d
        if d["speed_mm_s"] * self.pump.steps_per_mm() < 1e-4:
            d["error"] = "Caudal demasiado bajo"
            return d
        cap = float(s.get("capacity_ml") or 0)
        if cap and vol_ml > cap * 1.0001:
            d["warning"] = "Supera la capacidad (%s mL)" % fmt(cap, 1)
        return d

    def start_dose(self):
        d = self._compute_dose()
        if d["error"]:
            QtWidgets.QMessageBox.warning(self, APP_NAME, d["error"])
            return
        if d["warning"]:
            r = QtWidgets.QMessageBox.question(
                self, APP_NAME, "El volumen supera la capacidad de la "
                "jeringa.\n¿Iniciar de todos modos?")
            if r != QtWidgets.QMessageBox.Yes:
                return
        prev = self._dose
        self._dose = d
        self._dose_result = None
        self._run_elapsed = 0.0
        self._run_t0 = time.monotonic()
        if self.pump.move_mm(d["mm"], d["infuse"], d["speed_mm_s"], "dose"):
            self.tick.start()
        else:
            self._dose = prev
            self._run_t0 = None
        self._refresh_all()

    def pause_resume(self):
        if not (self.pump.busy and self.pump.owner == "dose"):
            return
        if self.pump.paused:
            self.pump.resume()
            self._run_t0 = time.monotonic()
        else:
            self.pump.pause()
            if self._run_t0 is not None:
                self._run_elapsed += time.monotonic() - self._run_t0
                self._run_t0 = None

    def stop_all(self):
        self.pump.stop()

    def _active_elapsed(self):
        e = self._run_elapsed
        if self._run_t0 is not None:
            e += time.monotonic() - self._run_t0
        return e

    def _on_progress(self, done, total):
        if self.pump.owner == "dose":
            self._update_status_card()

    def _on_finished(self, completed, owner):
        if owner == "dose":
            self.tick.stop()
            if self._run_t0 is not None:
                self._run_elapsed += time.monotonic() - self._run_t0
                self._run_t0 = None
            self._dose_result = "done" if completed else "stopped"
            if completed:
                QtWidgets.QApplication.beep()
        elif owner == "screw":
            if completed:
                self.screw_status.setText(
                    "Mide cuánto avanzó el carro, escríbelo y pulsa Aplicar.")
                self.screw_meas.setValue(self._screw_cmd or 0)
            else:
                self._screw_cmd = None
                self.screw_status.setText("Interrumpido.")
        self._refresh_all()

    # ---------------------------------------------------------
    #  Movimiento manual
    # ---------------------------------------------------------
    def _is_continuous(self):
        return self.step_seg.index() == len(MANUAL_STEPS_ML)

    def _on_step_mode(self, idx):
        self.cfg["manual_step"] = idx
        self._save()
        self._refresh_all()

    def _manual_pressed(self, infuse):
        if self._is_continuous():
            if self.pump.move_mm(CONTINUOUS_LIMIT_MM, infuse,
                                 self.fast_speed(), "manual",
                                 FAST_ACCEL_MM_S2):
                self._continuous = True

    def retract_all(self):
        if self.pump.busy and self.pump.owner == "retract":
            self.pump.stop()
            return
        self.pump.move_mm(self.cfg["machine"]["retract_mm"], False,
                          self.fast_speed(), "retract", FAST_ACCEL_MM_S2)

    def _manual_released(self):
        if self._continuous:
            self._continuous = False
            if self.pump.busy and self.pump.owner == "manual":
                self.pump.stop()

    def _manual_clicked(self, infuse):
        if self._is_continuous():
            return
        ml = MANUAL_STEPS_ML[self.step_seg.index()]
        mm = ml * 1000.0 / self.current_syringe()["area_mm2"]
        self.pump.move_mm(mm, infuse, self.jog_speed(), "manual")

    # ---------------------------------------------------------
    #  Calibracion del tornillo
    # ---------------------------------------------------------
    def _screw_move(self):
        d = self.screw_dist.value()
        if self.pump.move_mm(d, True, self.jog_speed(), "screw"):
            self._screw_cmd = d
            self.screw_status.setText("Moviendo %s mm…" % fmt(d, 1))

    def _screw_apply(self):
        if not self._screw_cmd:
            return
        meas = self.screw_meas.value()
        if meas <= 0:
            return
        k = meas / self._screw_cmd
        m = self.cfg["machine"]
        old = m["mm_per_rev"]
        new = old * k
        r = QtWidgets.QMessageBox.question(
            self, "Calibrar tornillo",
            "Avance por vuelta: %s → %s mm (%+.2f %%).\n\n¿Aplicar?"
            % (fmt(old, 4), fmt(new, 4), (k - 1) * 100))
        if r != QtWidgets.QMessageBox.Yes:
            return
        pump_cal = [s for s in self.cfg["syringes"]
                    if s.get("method", "").startswith("pump")]
        if pump_cal:
            r = QtWidgets.QMessageBox.question(
                self, "Jeringas calibradas",
                "¿Corregir también las %d jeringa(s) calibradas con la "
                "bomba? (recomendado)" % len(pump_cal))
            if r == QtWidgets.QMessageBox.Yes:
                for s in pump_cal:
                    s["area_mm2"] = s["area_mm2"] / k
        self.mmrev_spin.setValue(round(new, 4))
        self._screw_cmd = None
        self.screw_meas.setValue(0)
        self.screw_status.setText("Aplicado: %s mm por vuelta"
                                  % fmt(new, 4))
        self._save()
        self._update_syr_detail()
        self._refresh_all()

    def reset_machine(self):
        r = QtWidgets.QMessageBox.question(
            self, APP_NAME, "¿Restaurar la mecánica a los valores de "
            "fábrica (tornillo T8 de 2 mm por vuelta, microstepping 16)? Las "
            "jeringas no se "
            "borran.")
        if r != QtWidgets.QMessageBox.Yes:
            return
        self._loading = True
        self.cfg["machine"].update(DEFAULT_MACHINE)
        self._restore_from_config()
        self._loading = False
        self._save()
        self._refresh_all()

    # ---------------------------------------------------------
    #  Refresco de la interfaz
    # ---------------------------------------------------------
    def _refresh_all(self):
        self._refresh_program()
        self._refresh_state()
        self._refresh_manual_tips()
        self._refresh_mech_info()

    def _refresh_program(self):
        d = self._compute_dose()
        if d["error"]:
            self.dose_hint.setText(d["error"])
            set_prop(self.dose_hint, "role", "errText")
        elif d["warning"]:
            self.dose_hint.setText(d["warning"])
            set_prop(self.dose_hint, "role", "warnText")
        else:
            self.dose_hint.setText("Duración: %s"
                                   % fmt_duration(d["duration"]))
            set_prop(self.dose_hint, "role", "hintLine")
        self._update_status_card()

    def _refresh_state(self):
        p = self.pump
        if not p.connected:
            txt, st = "Desconectado", "off"
        elif not p.ready:
            txt, st = "Conectando…", "wait"
        else:
            txt, st = "Conectado", "on"
        self.conn_pill.setText(txt)
        set_prop(self.conn_pill, "pill", st)
        self.connect_btn.setText("Desconectar" if p.connected else "Conectar")
        set_prop(self.connect_btn, "kind",
                 "ghost" if p.connected else "primary")
        self.port_combo.setVisible(not p.connected)

        op = p.operational
        busy = p.busy
        dosing = busy and p.owner == "dose"
        d = self._compute_dose()

        self.start_btn.setEnabled(op and not busy and not d["error"])
        self.pause_btn.setEnabled(dosing)
        self.pause_btn.setText("▶" if p.paused else "❚❚")
        self.pause_btn.setToolTip("Reanudar" if p.paused else "Pausar")
        self.stop_btn.setEnabled(busy)
        manual_ok = op and (not busy or p.owner == "manual")
        retracting = busy and p.owner == "retract"
        self.retract_btn.setEnabled(op and (not busy or retracting))
        self.retract_btn.setText("Detener" if retracting
                                 else "Retroceder todo")
        self.retract_btn.setToolTip(
            "Lleva el carro %s mm hacia atrás, rápido, para cargar o cambiar "
            "la jeringa" % fmt(self.cfg["machine"]["retract_mm"], 0))
        self.fwd_btn.setEnabled(manual_ok)
        self.back_btn.setEnabled(manual_ok)
        self.step_seg.setEnabled(not busy)
        for w in (self.syr_combo, self.action_seg, self.vol_spin,
                  self.vol_unit, self.flow_spin, self.flow_unit,
                  self.goto_syr_btn):
            w.setEnabled(not dosing)
        for w in (self.spr_combo, self.micro_combo, self.mmrev_spin,
                  self.screw_combo,
                  self.invert_chk, self.accel_spin, self.jog_spin,
                  self.fast_spin, self.retract_spin):
            w.setEnabled(not busy)
        self.screw_move_btn.setEnabled(op and not busy)
        self.screw_apply_btn.setEnabled(bool(self._screw_cmd) and not busy)
        self.calib_btn.setEnabled(not busy)
        self.new_syr_btn.setEnabled(not busy)
        self.del_syr_btn.setEnabled(not busy)
        self._update_status_card()

    def _update_status_card(self):
        p = self.pump
        d = self._dose if (self._dose and (p.owner == "dose" or
                                            self._dose_result)) else None
        color = BLUE
        if not p.connected:
            txt, st = "Sin conexión", "offline"
        elif not p.ready:
            txt, st = "Conectando…", "offline"
        elif p.busy and p.owner == "dose" and self._dose:
            if p.paused:
                txt, st, color = "En pausa", "paused", AMBER
            else:
                txt = "Infundiendo" if self._dose["infuse"] else "Retirando"
                st = "running"
        elif p.busy and p.owner == "manual":
            txt, st = "Moviendo", "running"
        elif p.busy and p.owner == "retract":
            txt, st = "Retrocediendo", "running"
        elif p.busy:
            txt, st = "Calibrando", "running"
        elif self._dose_result == "done":
            txt, st, color = "Completado", "done", GREEN
        elif self._dose_result == "stopped":
            txt, st, color = "Detenido", "stopped", RED
        else:
            txt, st = "Listo", "idle"
        self.state_pill.setText(txt)
        set_prop(self.state_pill, "state", st)

        if d is None:
            prev = self._compute_dose()
            unit = self.vol_unit.currentText()
            self.ring.set_state(0, fmt_smart(self.vol_spin.value()), unit,
                                "programado", BLUE)
            self.eta_lbl.setText(fmt_duration(prev.get("duration"))
                                 if not prev["error"] else "—")
            self.rate_lbl.setText("%s %s" % (fmt_smart(self.flow_spin.value()),
                                             self.flow_unit.currentText()))
            return

        unit = d["vol_unit"]
        factor = VOLUME_UNITS[unit]
        frac = (p.done_steps / p.total_steps) if p.total_steps else 0.0
        if self._dose_result == "done":
            frac = 1.0
        done_val = frac * d["vol_ml"] / factor
        total_val = d["vol_ml"] / factor
        self.ring.set_state(frac, fmt_smart(done_val), unit,
                            "de %s" % fmt_smart(total_val), color)
        if self._dose_result:
            self.eta_lbl.setText("—")
        else:
            self.eta_lbl.setText(fmt_duration(
                max(0.0, d["duration"] - self._active_elapsed())))
        self.rate_lbl.setText("%s %s" % (fmt_smart(d["flow"]), d["flow_unit"]))

    def _refresh_manual_tips(self):
        if self._is_continuous():
            tip = "Mantén presionado; se detiene al soltar"
        else:
            ml = MANUAL_STEPS_ML[self.step_seg.index()]
            mm = ml * 1000.0 / self.current_syringe()["area_mm2"]
            tip = "Cada clic: %s mL (%s mm)" % (fmt(ml, 2), fmt(mm, 2))
        self.fwd_btn.setToolTip("Avanzar (empujar)\n" + tip)
        self.back_btn.setToolTip("Retroceder (aspirar)\n" + tip)

    def _refresh_mech_info(self):
        p = self.pump
        s = self.current_syringe()
        qmax = p.max_speed_mm_s() * s["area_mm2"] / 1000.0 * 60.0
        self.mech_info.setText(
            "Caudal máximo con %s: %s mL/min" % (s["name"], fmt_smart(qmax)))

    # ---------------------------------------------------------
    #  Otros
    # ---------------------------------------------------------
    def show_help(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Ayuda")
        box.setIconPixmap(QtGui.QIcon(make_icon_pixmap()).pixmap(48, 48))
        box.setTextFormat(Qt.RichText)
        box.setText(
            "<b>1.</b> Conecta el USB y pulsa <b>Conectar</b>.<br>"
            "<b>2.</b> Elige la jeringa (nueva → pestaña <b>Jeringas</b>).<br>"
            "<b>3.</b> Acerca el carro con <b>Avanzar</b> / <b>Retroceder</b>.<br>"
            "<b>4.</b> Elige volumen y caudal, y pulsa <b>Iniciar</b>.")
        box.exec_()

    def _log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText("[%s] %s" % (stamp, text))

    def closeEvent(self, event):
        if self.pump.busy:
            r = QtWidgets.QMessageBox.question(
                self, APP_NAME, "La bomba se está moviendo. ¿Detener y salir?")
            if r != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
            self.pump.stop()
        self.pump.disconnect_port()
        save_config(self.cfg)
        event.accept()


# =============================================================
#  Tema visual
# =============================================================
STYLE = """
* {
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: #1f2937;
}
QMainWindow, QWidget#root, QWidget#page, QScrollArea { background: #f3f5f9; }
QDialog { background: #ffffff; }
QFrame#header { background: #ffffff; }
QLabel#appTitle { font-size: 14pt; font-weight: 700; color: #0f172a; }
QLabel, QCheckBox { background: transparent; }

QFrame[card="true"] {
    background: #ffffff; border: 1px solid #e3e7ee; border-radius: 16px;
}
QFrame[tile="true"] {
    background: #f8fafc; border: 1px solid #eef1f5; border-radius: 12px;
}

QLabel[role="cardTitle"]   { font-size: 11.5pt; font-weight: 700; color: #0f172a; }
QLabel[role="detailTitle"] { font-size: 16pt; font-weight: 700; color: #0f172a; }
QLabel[role="dlgTitle"]    { font-size: 16pt; font-weight: 700; color: #0f172a; }
QLabel[role="field"]  { color: #374151; font-weight: 600; }
QLabel[role="small"]  { color: #6b7280; font-size: 9pt; font-weight: 600; }
QLabel[role="muted"]  { color: #6b7280; }
QLabel[role="statValue"] { font-size: 13pt; font-weight: 700; color: #0f172a; }
QLabel[role="tileValue"] { font-size: 13pt; font-weight: 700; color: #0f172a; }
QLabel[role="hintLine"] { color: #4b5563; font-size: 10.5pt; }
QLabel[role="errText"]  { color: #dc2626; font-weight: 600; }
QLabel[role="warnText"] { color: #b45309; font-weight: 600; }
QLabel[role="result"] {
    color: #1e3a8a; background: #eff6ff; border-radius: 12px;
    padding: 14px 16px; font-size: 13pt; font-weight: 700;
}
QLabel[role="warn"] {
    color: #92400e; background: #fffbeb; border-radius: 12px;
    padding: 12px 14px; font-weight: 600;
}
QLabel[role="ok"] {
    color: #166534; background: #f0fdf4; border-radius: 10px;
    padding: 10px 12px; font-weight: 600;
}

QLabel[pill] { border-radius: 13px; padding: 5px 12px; font-weight: 700; }
QLabel[pill="off"]  { color: #b91c1c; background: #fef2f2; }
QLabel[pill="wait"] { color: #b45309; background: #fffbeb; }
QLabel[pill="on"]   { color: #15803d; background: #f0fdf4; }

QLabel[tag] { border-radius: 11px; padding: 4px 10px; font-size: 9pt; font-weight: 700; }
QLabel[tag="factory"]    { color: #4b5563; background: #f3f4f6; }
QLabel[tag="calibrated"] { color: #15803d; background: #dcfce7; }

QLabel[state] { border-radius: 13px; padding: 5px 16px; font-weight: 700; }
QLabel[state="offline"] { color: #6b7280; background: #f3f4f6; }
QLabel[state="idle"]    { color: #1d4ed8; background: #eff6ff; }
QLabel[state="running"] { color: #1d4ed8; background: #dbeafe; }
QLabel[state="paused"]  { color: #b45309; background: #fef3c7; }
QLabel[state="done"]    { color: #15803d; background: #dcfce7; }
QLabel[state="stopped"] { color: #b91c1c; background: #fee2e2; }

QTabWidget::pane { border: none; }
QTabWidget > QTabBar { qproperty-drawBase: 0; }
QTabBar { background: #ffffff; }
QTabBar::tab {
    background: #ffffff; color: #6b7280;
    padding: 10px 22px; border: none; border-bottom: 3px solid transparent;
}
QTabBar::tab:hover    { color: #111827; }
QTabBar::tab:selected { color: #2563eb; border-bottom: 3px solid #2563eb; }

QPushButton {
    background: #ffffff; border: 1px solid #d1d5db; border-radius: 10px;
    padding: 9px 16px; font-weight: 600; color: #1f2937; min-height: 18px;
}
QPushButton:hover    { background: #f3f4f6; }
QPushButton:pressed  { background: #e5e7eb; }
QPushButton:disabled { color: #9ca3af; background: #f9fafb; border-color: #e5e7eb; }

QPushButton[kind="primary"] { background: #2563eb; border-color: #2563eb; color: #ffffff; }
QPushButton[kind="primary"]:hover   { background: #1d4ed8; }
QPushButton[kind="primary"]:disabled { background: #bfdbfe; border-color: #bfdbfe; color: #ffffff; }
QPushButton[kind="go"] {
    background: #16a34a; border-color: #16a34a; color: #ffffff;
    font-size: 12.5pt; padding: 14px 18px;
}
QPushButton[kind="go"]:hover    { background: #15803d; }
QPushButton[kind="go"]:disabled { background: #bbf7d0; border-color: #bbf7d0; color: #ffffff; }
QPushButton[kind="warn"] {
    background: #f59e0b; border-color: #f59e0b; color: #ffffff;
    font-size: 12.5pt; padding: 14px 14px;
}
QPushButton[kind="warn"]:hover    { background: #d97706; }
QPushButton[kind="warn"]:disabled { background: #fde68a; border-color: #fde68a; color: #ffffff; }
QPushButton[kind="danger"] {
    background: #dc2626; border-color: #dc2626; color: #ffffff;
    font-size: 12.5pt; padding: 14px 14px;
}
QPushButton[kind="danger"]:hover    { background: #b91c1c; }
QPushButton[kind="danger"]:disabled { background: #fecaca; border-color: #fecaca; color: #ffffff; }
QPushButton[kind="ghost"] { background: #ffffff; color: #374151; }
QPushButton[kind="icon"] { padding: 8px 12px; font-size: 13pt; min-width: 22px; }
QPushButton[kind="jogBig"] {
    min-width: 110px; padding: 9px 16px; color: #2563eb;
}
QPushButton[kind="jogBig"]:pressed { background: #2563eb; color: #ffffff; }
QPushButton[kind="jogBig"]:disabled { color: #bfdbfe; }
QPushButton[jog="true"] { min-width: 70px; color: #2563eb; }
QPushButton[kind="choice"] {
    text-align: left; padding: 18px 20px; font-size: 11pt; border-radius: 14px;
}
QPushButton[kind="choice"]:hover { border-color: #2563eb; background: #eff6ff; }
QPushButton#helpBtn {
    border-radius: 17px; min-width: 34px; max-width: 34px;
    min-height: 34px; max-height: 34px; padding: 0; font-size: 12pt;
}

QPushButton[seg] { border-radius: 0; padding: 8px 14px; }
QPushButton[tall="true"] { padding: 12px 14px; font-size: 11pt; }
QPushButton[seg="first"] { border-top-left-radius: 10px; border-bottom-left-radius: 10px; }
QPushButton[seg="last"]  { border-top-right-radius: 10px; border-bottom-right-radius: 10px; }
QPushButton[seg="mid"], QPushButton[seg="last"] { border-left: none; }
QPushButton:checked { background: #2563eb; border-color: #2563eb; color: #ffffff; }
QPushButton:checked:disabled { background: #93c5fd; border-color: #93c5fd; }

QLineEdit, QDoubleSpinBox, QComboBox {
    background: #ffffff; border: 1px solid #d1d5db; border-radius: 10px;
    padding: 7px 11px; min-height: 20px; selection-background-color: #2563eb;
}
QLineEdit[big="true"], QDoubleSpinBox[big="true"], QComboBox[big="true"] {
    font-size: 13pt; padding: 8px 12px; min-height: 26px;
}
QDoubleSpinBox[big="true"] { font-weight: 700; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #2563eb; }
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: #9ca3af; background: #f9fafb;
}
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #d1d5db; outline: none; padding: 4px;
    selection-background-color: #eff6ff; selection-color: #1d4ed8;
}

QCheckBox { spacing: 9px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 2px solid #9ca3af; background: #ffffff;
    border-radius: 5px;
}
QCheckBox::indicator:hover { border-color: #2563eb; }
QCheckBox::indicator:checked {
    border-color: #2563eb; background: #2563eb; image: url(%CHECK%);
}

QListWidget#syrList { background: #ffffff; border: none; outline: none; }
QListWidget#syrList::item {
    padding: 11px 10px; border-radius: 10px; color: #1f2937; margin: 1px 0;
}
QListWidget#syrList::item:hover    { background: #f3f4f6; }
QListWidget#syrList::item:selected { background: #eff6ff; color: #1d4ed8; font-weight: 600; }

QPlainTextEdit {
    background: #0f172a; color: #cbd5e1; border: none; border-radius: 10px;
    padding: 8px; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt;
}
QToolTip { background: #111827; color: #f9fafb; border: none; padding: 6px 8px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def build_stylesheet():
    """Genera la marca de verificacion (PNG) y la inserta en el estilo."""
    path = os.path.join(config_dir(), "check.png")
    pm = QtGui.QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 4.5, Qt.SolidLine,
                        Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(7, 17),
                                    QtCore.QPointF(13, 23),
                                    QtCore.QPointF(25, 9)]))
    p.end()
    if not pm.save(path, "PNG"):
        return STYLE.replace("image: url(%CHECK%);", "")
    return STYLE.replace("%CHECK%", path.replace("\\", "/"))


def style_tabbar(tabs):
    """Negrita en el widget (asi Qt calcula bien el ancho de cada pestana)."""
    bar = tabs.tabBar()
    f = bar.font()
    f.setBold(True)
    f.setPointSizeF(10.5)
    bar.setFont(f)


def setup_high_dpi():
    """Escalado exacto en pantallas al 125 %, 150 %, etc.

    Sin esto, Qt5 redondea 1,25 a 1: las letras crecen pero el resto no,
    y en modo ventana el contenido queda apretado y cortado.
    """
    QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    try:
        QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass


def fit_to_screen(window):
    scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
    w = min(1060, int(scr.width() * 0.92))
    h = min(720, int(scr.height() * 0.90))
    window.resize(w, h)
    window.move(scr.x() + (scr.width() - w) // 2,
                scr.y() + (scr.height() - h) // 2)


def main():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "BombaJeringa.Control.2")
        except (AttributeError, OSError):
            pass

    setup_high_dpi()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())
    app.setWindowIcon(QtGui.QIcon(make_icon_pixmap()))

    if "--export-icon" in sys.argv:
        path = sys.argv[sys.argv.index("--export-icon") + 1]
        ok = make_icon_pixmap(256).save(path)
        print("Icono exportado:" if ok else "ERROR exportando icono:", path)
        return

    window = MainWindow()
    fit_to_screen(window)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
